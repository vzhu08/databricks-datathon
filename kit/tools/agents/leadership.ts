import { createHash, randomUUID } from 'node:crypto';
import { hostname } from 'node:os';
import { z } from 'zod';
import { ConfigSchema, type Config } from './contracts';
import { validateCheckpoint } from './checkpoint';
import {
  LeadershipStatusSchema,
  MAX_CHECKPOINT_BYTES,
  TAKEOVER_SAFETY_MS,
  coordinatorActors,
  type LeadershipMode,
  type LeadershipStatus,
  type PortableCheckpoint,
} from './handoff-contracts';
import type { GitHubApi } from './github';

const V2 = 'hackathon-kit/leadership/v2\n';
const V1 = 'hackathon-kit/leadership/v1\n';
const lower = (value: string) => value.toLowerCase();
const LegacySchema = z
  .object({
    schemaVersion: z.literal(1),
    runId: z.string(),
    owner: z.string().uuid(),
    coordinator: z.string(),
    expiresAt: z.number().int(),
    released: z.boolean(),
  })
  .strict();
type Snapshot = { sha: string; tree: string; data: LeadershipStatus; legacy: boolean };
export type ControlOptions = {
  api: GitHubApi;
  now?: () => number;
  ownerId?: string;
  host?: string;
  leadershipMode?: LeadershipMode;
  recoverExpiredLeadership?: boolean;
};

/** The fast-forward ref is the only authority; uploaded blobs and Issues are not locks. */
export class GitHubControl {
  readonly config: Config;
  private readonly now: () => number;
  private readonly owner: string;
  private readonly host: string;
  private readonly mode: LeadershipMode;
  private heldSha?: string;
  private migratedLegacy = false;
  private commitCache = new Map<string, { message: string; tree: { sha: string } }>();
  private checkpointCache = new Map<string, { value: PortableCheckpoint; digest: string }>();
  constructor(
    config: Config,
    private readonly options: ControlOptions,
  ) {
    this.config = ConfigSchema.parse(config);
    this.now = options.now ?? Date.now;
    this.owner = z
      .string()
      .uuid()
      .parse(options.ownerId ?? randomUUID());
    this.host = (options.host ?? hostname()).slice(0, 100);
    this.mode =
      options.leadershipMode ?? (options.recoverExpiredLeadership ? 'takeover' : 'normal');
  }
  private get root() {
    return `repos/${this.config.repo}`;
  }
  private get ref() {
    return `heads/codex/orchestration-control/${this.config.runId}`;
  }
  private async read(endpoint: string): Promise<unknown> {
    for (let attempt = 0; ; attempt++) {
      try {
        return await this.options.api(endpoint, 'GET');
      } catch (error) {
        const status = (error as { status?: number }).status;
        if (attempt >= 2 || (status !== undefined && status < 500 && status !== 429)) throw error;
        await new Promise((resolve) => setTimeout(resolve, 100 * 2 ** attempt));
      }
    }
  }
  async identity(): Promise<string> {
    return z.object({ login: z.string() }).parse(await this.read('user')).login;
  }
  private allowed(actor: string) {
    if (!coordinatorActors(this.config).includes(lower(actor)))
      throw new Error('GitHub identity is not an eligible coordinator');
  }
  private async snapshot(): Promise<Snapshot | undefined> {
    let ref: unknown;
    try {
      ref = await this.read(`${this.root}/git/ref/${this.ref}`);
    } catch (error) {
      if ((error as { status?: number }).status === 404) return;
      throw error;
    }
    const sha = z.object({ object: z.object({ sha: z.string().min(1) }) }).parse(ref).object.sha;
    let commit = this.commitCache.get(sha);
    if (!commit) {
      commit = z
        .object({ message: z.string().max(16_000), tree: z.object({ sha: z.string() }) })
        .parse(await this.read(`${this.root}/git/commits/${sha}`));
      if (this.commitCache.size >= 1024)
        this.commitCache.delete(this.commitCache.keys().next().value!);
      this.commitCache.set(sha, commit);
    }
    let data: LeadershipStatus,
      legacy = false;
    if (commit.message.startsWith(V2))
      data = LeadershipStatusSchema.parse(JSON.parse(commit.message.slice(V2.length)));
    else if (commit.message.startsWith(V1)) {
      legacy = true;
      const old = LegacySchema.parse(JSON.parse(commit.message.slice(V1.length)));
      data = LeadershipStatusSchema.parse({
        schemaVersion: 2,
        runId: old.runId,
        epoch: 1,
        owner: old.owner,
        coordinator: old.coordinator,
        host: 'legacy-v1',
        expiresAt: old.expiresAt,
        phase: old.released ? 'released' : 'active',
      });
    } else
      throw new Error('Control branch changed outside coordinator; manual reconciliation required');
    if (data.runId !== this.config.runId)
      throw new Error('Control branch belongs to a different run');
    this.allowed(data.coordinator);
    return { sha, tree: commit.tree.sha, data, legacy };
  }
  async status(): Promise<LeadershipStatus | undefined> {
    return (await this.snapshot())?.data;
  }
  isLegacyMigration() {
    return this.migratedLegacy;
  }
  private async commit(previous: { sha: string; tree: string }, record: LeadershipStatus) {
    return z.object({ sha: z.string().min(1) }).parse(
      await this.options.api(`${this.root}/git/commits`, 'POST', {
        message: V2 + JSON.stringify(LeadershipStatusSchema.parse(record)),
        tree: previous.tree,
        parents: [previous.sha],
      }),
    ).sha;
  }
  private async cas(previous: Snapshot, record: LeadershipStatus) {
    const sha = await this.commit(previous, record);
    try {
      await this.options.api(`${this.root}/git/refs/${this.ref}`, 'PATCH', { sha, force: false });
    } catch (error) {
      // An accepted but disconnected PATCH is recoverable only by this exact commit.
      const recovered = await this.snapshot().catch(() => undefined);
      if (recovered?.sha !== sha) {
        this.heldSha = undefined;
        throw new Error(
          'Leadership CAS failed or outcome unknown; stale coordinator must stop dispatch',
          { cause: error },
        );
      }
    }
    this.heldSha = sha;
    return LeadershipStatusSchema.parse(record);
  }
  async acquire(): Promise<void> {
    const actor = await this.identity();
    this.allowed(actor);
    const current = await this.snapshot();
    if (!current) {
      if (lower(actor) !== lower(this.config.coordinator) || this.mode !== 'normal')
        throw new Error(
          'No shared run exists; bootstrap with the configured original coordinator first',
        );
      const repository = z
        .object({
          default_branch: z.string(),
          permissions: z.object({ push: z.boolean() }).optional(),
        })
        .parse(await this.read(this.root));
      if (repository.permissions && !repository.permissions.push)
        throw new Error('GitHub write permission required');
      const base = z
        .object({ object: z.object({ sha: z.string() }) })
        .parse(
          await this.read(
            `${this.root}/git/ref/heads/${encodeURIComponent(repository.default_branch)}`,
          ),
        );
      const tree = z
        .object({ tree: z.object({ sha: z.string() }) })
        .parse(await this.read(`${this.root}/git/commits/${base.object.sha}`)).tree.sha;
      const record = LeadershipStatusSchema.parse({
        schemaVersion: 2,
        runId: this.config.runId,
        epoch: 1,
        owner: this.owner,
        coordinator: actor,
        host: this.host,
        expiresAt: this.now() + this.config.leaseMs,
        phase: 'active',
      });
      const sha = await this.commit({ sha: base.object.sha, tree }, record);
      try {
        await this.options.api(`${this.root}/git/refs`, 'POST', { ref: `refs/${this.ref}`, sha });
      } catch (error) {
        const recovered = await this.snapshot().catch(() => undefined);
        if (recovered?.sha !== sha)
          throw new Error(
            'Leadership creation raced or outcome unknown; reconcile before retrying',
            { cause: error },
          );
      }
      this.heldSha = sha;
      return;
    }
    const healthy = current.data.expiresAt > this.now();
    const designated =
      current.data.phase === 'handoff' && lower(current.data.successor ?? '') === lower(actor);
    if (this.mode === 'resume' && designated) {
      /* The offer atomically surrendered dispatch authority. */
    } else if (current.data.phase === 'released') {
      if (this.mode === 'normal' && lower(actor) !== lower(current.data.coordinator))
        throw new Error('Use coordinate --resume to acquire a released shared run');
    } else {
      if (healthy)
        throw new Error(
          'Another coordinator owns this run; healthy leadership or designated handoff cannot be taken over',
        );
      if (this.mode !== 'takeover')
        throw new Error(
          'Coordinator lease expired; explicitly recover using takeover after the safety margin',
        );
      if (this.now() < current.data.expiresAt + TAKEOVER_SAFETY_MS)
        throw new Error('Coordinator lease expired but takeover safety margin has not elapsed');
    }
    if (current.legacy && lower(actor) !== lower(this.config.coordinator))
      throw new Error(
        'Legacy run has no portable checkpoint; original coordinator must upgrade and checkpoint before cross-account handoff',
      );
    this.migratedLegacy = current.legacy;
    const record: LeadershipStatus = {
      ...current.data,
      schemaVersion: 2,
      epoch: current.data.epoch + 1,
      owner: this.owner,
      coordinator: actor,
      host: this.host,
      expiresAt: this.now() + this.config.leaseMs,
      phase: 'active',
    };
    delete record.successor;
    await this.cas(current, record);
  }
  async assertOwned(): Promise<Snapshot> {
    const actor = await this.identity();
    const current = await this.snapshot();
    if (
      !current ||
      !this.heldSha ||
      current.sha !== this.heldSha ||
      current.data.owner !== this.owner ||
      lower(current.data.coordinator) !== lower(actor) ||
      current.data.phase !== 'active' ||
      current.data.expiresAt <= this.now()
    ) {
      this.heldSha = undefined;
      throw new Error('Coordinator leadership lost or expired; no task mutation is allowed');
    }
    return current;
  }
  async renew() {
    const current = await this.assertOwned();
    await this.cas(current, { ...current.data, expiresAt: this.now() + this.config.leaseMs });
  }
  async release() {
    if (!this.heldSha) return;
    const current = await this.assertOwned();
    await this.cas(current, { ...current.data, phase: 'released' });
    this.heldSha = undefined;
  }
  private async checkpointFor(status: LeadershipStatus): Promise<PortableCheckpoint | undefined> {
    if (!status.checkpoint) return;
    const cached = this.checkpointCache.get(status.checkpoint.blobSha);
    if (cached) {
      if (
        cached.digest !== status.checkpoint.digest ||
        cached.value.sequence !== status.checkpoint.sequence ||
        cached.value.at !== status.checkpoint.at
      )
        throw new Error('Checkpoint pointer digest or sequence mismatch');
      return structuredClone(cached.value);
    }
    const blob = z
      .object({
        content: z.string(),
        encoding: z.literal('base64'),
        size: z.number().int().nonnegative(),
      })
      .parse(await this.read(`${this.root}/git/blobs/${status.checkpoint.blobSha}`));
    if (
      blob.size > MAX_CHECKPOINT_BYTES ||
      blob.content.length > Math.ceil((MAX_CHECKPOINT_BYTES * 4) / 3) + 30_000
    )
      throw new Error('Checkpoint blob exceeds limit');
    const bytes = Buffer.from(blob.content.replace(/\s/g, ''), 'base64');
    if (
      bytes.length !== blob.size ||
      bytes.length > MAX_CHECKPOINT_BYTES ||
      createHash('sha256').update(bytes).digest('hex') !== status.checkpoint.digest
    )
      throw new Error('Checkpoint blob is incomplete or digest mismatch');
    const checkpoint = validateCheckpoint(JSON.parse(bytes.toString('utf8')), this.config);
    if (
      checkpoint.sequence !== status.checkpoint.sequence ||
      checkpoint.at !== status.checkpoint.at
    )
      throw new Error('Checkpoint pointer sequence mismatch');
    if (this.checkpointCache.size >= 50)
      this.checkpointCache.delete(this.checkpointCache.keys().next().value!);
    this.checkpointCache.set(status.checkpoint.blobSha, {
      value: checkpoint,
      digest: status.checkpoint.digest,
    });
    return structuredClone(checkpoint);
  }
  async loadCheckpoint() {
    const current = await this.snapshot();
    return current ? this.checkpointFor(current.data) : undefined;
  }
  private async upload(checkpoint: PortableCheckpoint, current: Snapshot) {
    const value = validateCheckpoint(checkpoint, this.config);
    if (lower(value.actor) !== lower(current.data.coordinator))
      throw new Error('Checkpoint author does not own leadership');
    const previous = await this.checkpointFor(current.data);
    if (value.sequence !== (previous?.sequence ?? 0) + 1)
      throw new Error('Checkpoint sequence must increase by one');
    for (const prior of previous?.state.tasks ?? []) {
      const next = value.state.tasks.find((task) => task.id === prior.id);
      if (
        prior.lease &&
        !['Verified', 'Failed'].includes(prior.state) &&
        (!next || (!next.lease && next.state !== 'Failed'))
      )
        throw new Error(
          'Checkpoint cannot discard a reserved worker scope without stopped-process recovery',
        );
      if (next && next.version < prior.version)
        throw new Error('Task version conflict; checkpoint cannot regress a task');
    }
    for (const task of value.state.tasks.filter((t) => t.lease)) {
      const prior = previous?.state.tasks.find((t) => t.id === task.id);
      if (prior?.lease?.token === task.lease!.token) {
        if (prior.issue !== undefined && prior.issue !== task.issue)
          throw new Error('A live task cannot change its report issue');
        const identity = (item: typeof task) =>
          JSON.stringify({
            worker: item.assignedWorker,
            base: item.baseSha,
            branch: item.branch,
            scopes: item.allowedPaths,
            reserved: item.reservedPaths,
            checks: item.checkIds,
            dependencies: item.dependencies,
            epoch: item.lease?.epoch,
            decision: item.assignmentDecisionId,
            planVersion: item.planVersion,
            description: item.description,
            contract: item.sharedContract,
            acceptance: item.acceptance,
          });
        if (identity(prior) !== identity(task))
          throw new Error(
            'A live task lease cannot change ownership, scope, base or contract version',
          );
        continue;
      }
      if (!previous && this.migratedLegacy && !task.assignmentDecisionId) continue;
      if (value.state.paused)
        throw new Error('Paused checkpoints cannot authorize a new worker lease');
      const decision = previous?.context.decisions.find(
        (d) =>
          d.id === task.assignmentDecisionId &&
          d.kind === 'dispatch' &&
          d.taskId === task.id &&
          d.planVersion === task.planVersion,
      );
      if (!decision)
        throw new Error(
          `Assignment ${task.id} requires a decision in a previously committed checkpoint`,
        );
    }
    const bytes = Buffer.from(JSON.stringify(value));
    const blobSha = z.object({ sha: z.string().min(1) }).parse(
      await this.options.api(`${this.root}/git/blobs`, 'POST', {
        content: bytes.toString('base64'),
        encoding: 'base64',
      }),
    ).sha;
    if (this.checkpointCache.size >= 50)
      this.checkpointCache.delete(this.checkpointCache.keys().next().value!);
    this.checkpointCache.set(blobSha, {
      value: structuredClone(value),
      digest: createHash('sha256').update(bytes).digest('hex'),
    });
    return {
      blobSha,
      digest: createHash('sha256').update(bytes).digest('hex'),
      sequence: value.sequence,
      at: value.at,
    };
  }
  async saveCheckpoint(checkpoint: PortableCheckpoint): Promise<LeadershipStatus> {
    const current = await this.assertOwned();
    const pointer = await this.upload(checkpoint, current);
    // Recheck after slow blob upload; the final non-force CAS still supplies exclusion.
    const fresh = await this.assertOwned();
    if (fresh.sha !== current.sha) throw new Error('Leadership changed during checkpoint upload');
    return this.cas(current, { ...current.data, checkpoint: pointer });
  }
  async prepareHandoff(
    successor: string,
    checkpoint: PortableCheckpoint,
  ): Promise<LeadershipStatus> {
    const current = await this.assertOwned();
    const worker = this.config.workers.find(
      (w) => lower(w.name) === lower(successor) || lower(w.githubLogin) === lower(successor),
    );
    const target = worker?.githubLogin ?? successor;
    this.allowed(target);
    if (lower(target) === lower(current.data.coordinator))
      throw new Error('Handoff successor must use a different coordinator identity');
    const pointer = await this.upload(checkpoint, current);
    const fresh = await this.assertOwned();
    if (fresh.sha !== current.sha) throw new Error('Leadership changed while preparing handoff');
    const status = await this.cas(current, {
      ...current.data,
      checkpoint: pointer,
      phase: 'handoff',
      successor: target,
    });
    this.heldSha = undefined;
    return status;
  }
}
