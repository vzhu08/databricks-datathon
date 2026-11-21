import { afterEach, describe, expect, it, vi } from 'vitest';
import { mkdir, mkdtemp, rm, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { Coordinator } from '../../tools/agents/coordinator';
import { StateStore } from '../../tools/agents/state';
import {
  ConfigSchema,
  PlanSchema,
  TaskSchema,
  type Config,
  type QueueTransport,
  type RunState,
  type Task,
  type WorkerReport,
} from '../../tools/agents/contracts';
import {
  CheckpointSchema,
  TAKEOVER_SAFETY_MS,
  coordinatorActors,
  type HandoffMethods,
  type LeadershipMode,
  type LeadershipStatus,
  type PortableCheckpoint,
} from '../../tools/agents/handoff-contracts';
import {
  assertSharedSafe,
  buildCheckpoint,
  redactTeamText,
  validateCheckpoint,
} from '../../tools/agents/checkpoint';

const start = Date.parse('2026-10-24T12:00:00Z');
const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'handoff-run',
  repo: 'team/project',
  coordinator: 'alice',
  authorizedActors: ['alice'],
  workers: [
    { name: 'agent-a', githubLogin: 'alice' },
    { name: 'agent-b', githubLogin: 'bob' },
    { name: 'agent-c', githubLogin: 'carol' },
  ],
  startedAt: new Date(start).toISOString(),
  deadline: new Date(start + 86_400_000).toISOString(),
  checks: [{ id: 'unit', command: 'node', args: ['--test'] }],
});
type Trace = {
  kind: 'checkpoint' | 'offer' | 'assignment';
  actor: string;
  checkpoint?: PortableCheckpoint;
  task?: Task;
};
class Authority {
  now = start;
  revision = 0;
  leadership?: LeadershipStatus;
  checkpoint?: PortableCheckpoint;
  issues = new Map<string, Task>();
  reports: WorkerReport[] = [];
  trace: Trace[] = [];
  failSave?: (checkpoint: PortableCheckpoint) => boolean;
  acquisitionGate?: () => Promise<void>;
}

/** The atomic register is independent of Issues, just as the control ref is in GitHub. */
class HandoffQueue implements QueueTransport, HandoffMethods {
  private owner = randomUUID();
  private expectedRevision?: number;
  private held = false;
  constructor(
    readonly shared: Authority,
    readonly actor: string,
    readonly mode: LeadershipMode = 'normal',
    readonly policy: Config = config,
  ) {}
  private assertOwned() {
    const current = this.shared.leadership;
    if (
      !this.held ||
      !current ||
      current.owner !== this.owner ||
      current.coordinator !== this.actor ||
      current.phase !== 'active' ||
      current.expiresAt <= this.shared.now ||
      this.expectedRevision !== this.shared.revision
    )
      throw new Error('Stale or expired leadership fence');
    return current;
  }
  private commit(previous: number, leadership: LeadershipStatus, checkpoint?: PortableCheckpoint) {
    if (previous !== this.shared.revision) throw new Error('Leadership CAS lost');
    this.shared.revision++;
    this.shared.leadership = structuredClone(leadership);
    if (checkpoint) this.shared.checkpoint = structuredClone(checkpoint);
    this.expectedRevision = this.shared.revision;
  }
  async acquireLeadership() {
    if (!coordinatorActors(this.policy).includes(this.actor))
      throw new Error('Unauthorized coordinator');
    const previous = this.shared.revision,
      current = structuredClone(this.shared.leadership);
    if (!current) {
      if (this.mode !== 'normal' || this.actor !== this.policy.coordinator)
        throw new Error('Bootstrap coordinator required');
    } else if (this.mode === 'resume') {
      if (current.phase !== 'handoff' || current.successor !== this.actor)
        throw new Error('Not the designated successor');
    } else if (this.mode === 'takeover') {
      if (current.phase !== 'released' && this.shared.now < current.expiresAt + TAKEOVER_SAFETY_MS)
        throw new Error('Healthy lease or takeover safety margin');
    } else if (current.phase !== 'released' || current.coordinator !== this.actor)
      throw new Error('Coordinator already active; use handoff or takeover');
    // Both contenders can observe the same revision, but only one CAS can commit.
    await this.shared.acquisitionGate?.();
    await Promise.resolve();
    this.commit(previous, {
      schemaVersion: 2,
      runId: this.policy.runId,
      epoch: (current?.epoch ?? 0) + 1,
      owner: this.owner,
      coordinator: this.actor,
      host: `computer-${this.actor}`,
      phase: 'active',
      expiresAt: this.shared.now + this.policy.leaseMs,
      checkpoint: current?.checkpoint,
    });
    this.held = true;
  }
  async renewLeadership() {
    const current = this.assertOwned();
    this.commit(this.shared.revision, {
      ...current,
      expiresAt: this.shared.now + this.policy.leaseMs,
    });
  }
  async releaseLeadership() {
    if (!this.held) return;
    const current = this.assertOwned();
    this.commit(this.shared.revision, { ...current, phase: 'released' });
    this.held = false;
  }
  async getLeadership() {
    return structuredClone(this.shared.leadership);
  }
  async loadCheckpoint() {
    return structuredClone(this.shared.checkpoint);
  }
  private checkedCheckpoint(input: PortableCheckpoint) {
    this.assertOwned();
    const checkpoint = validateCheckpoint(input, this.policy);
    if (
      checkpoint.actor !== this.actor ||
      checkpoint.sequence !== (this.shared.checkpoint?.sequence ?? 0) + 1
    )
      throw new Error('Checkpoint actor or sequence fence failed');
    if (this.shared.failSave?.(checkpoint))
      throw new Error('Injected checkpoint persistence failure');
    return checkpoint;
  }
  private withCheckpoint(
    leadership: LeadershipStatus,
    checkpoint: PortableCheckpoint,
  ): LeadershipStatus {
    const digest = createHash('sha256').update(JSON.stringify(checkpoint)).digest('hex');
    return {
      ...leadership,
      checkpoint: {
        blobSha: `blob-${checkpoint.sequence}`,
        digest,
        sequence: checkpoint.sequence,
        at: checkpoint.at,
      },
    };
  }
  async saveCheckpoint(input: PortableCheckpoint) {
    const checkpoint = this.checkedCheckpoint(input),
      current = this.assertOwned();
    this.commit(this.shared.revision, this.withCheckpoint(current, checkpoint), checkpoint);
    this.shared.trace.push({
      kind: 'checkpoint',
      actor: this.actor,
      checkpoint: structuredClone(checkpoint),
    });
    return (await this.getLeadership())!;
  }
  async prepareHandoff(successor: string, input: PortableCheckpoint) {
    const checkpoint = this.checkedCheckpoint(input),
      current = this.assertOwned();
    if (!coordinatorActors(this.policy).includes(successor) || successor === this.actor)
      throw new Error('Invalid successor');
    this.commit(
      this.shared.revision,
      this.withCheckpoint({ ...current, phase: 'handoff', successor }, checkpoint),
      checkpoint,
    );
    this.shared.trace.push({
      kind: 'offer',
      actor: this.actor,
      checkpoint: structuredClone(checkpoint),
    });
    this.held = false;
    return (await this.getLeadership())!;
  }
  async listTasks() {
    return (this.shared.checkpoint?.state.tasks ?? []).map((source) => {
      const task = structuredClone(source),
        mirror = this.shared.issues.get(task.id);
      if (mirror && mirror.lease?.token === task.lease?.token && mirror.issue)
        task.issue = mirror.issue;
      if (task.lease && ['Assigned', 'Running', 'Blocked'].includes(task.state)) {
        const reachable = this.shared.reports.filter(
          (r) =>
            r.taskId === task.id &&
            r.leaseToken === task.lease?.token &&
            r.worker === task.assignedWorker &&
            ['started', 'heartbeat', 'checkpoint'].includes(r.kind) &&
            Date.parse(r.at) <= this.shared.now + 30_000,
        );
        task.lease.expiresAt = new Date(
          Math.max(
            Date.parse(task.lease.expiresAt),
            ...reachable.map((r) => Date.parse(r.at) + this.policy.leaseMs),
          ),
        ).toISOString();
      }
      return task;
    });
  }
  async listReports() {
    return structuredClone(this.shared.reports);
  }
  async postReport(_task: Task, report: WorkerReport) {
    this.shared.reports.push(structuredClone(report));
  }
  async publishTask(input: Task) {
    this.assertOwned();
    const task = TaskSchema.parse(input),
      authority = this.shared.checkpoint?.state.tasks.find((t) => t.id === task.id);
    if (
      !authority ||
      authority.state !== task.state ||
      authority.lease?.token !== task.lease?.token ||
      JSON.stringify(authority.allowedPaths) !== JSON.stringify(task.allowedPaths)
    )
      throw new Error('Task mirror has no current checkpoint authority');
    if (task.state === 'Assigned') {
      const decision = this.shared.checkpoint!.context.decisions.find(
        (d) => d.id === task.assignmentDecisionId && d.kind === 'dispatch' && d.taskId === task.id,
      );
      if (!decision) throw new Error('Assignment has no durable rationale');
      const earlier = this.shared.trace.some(
        (step) =>
          step.kind === 'checkpoint' &&
          step.checkpoint?.context.decisions.some((d) => d.id === decision.id) &&
          step.checkpoint.state.tasks.find((t) => t.id === task.id)?.state === 'Planned',
      );
      if (!earlier) throw new Error('Decision did not precede assignment authorization');
    }
    const mirror = TaskSchema.parse({
      ...task,
      issue: this.shared.issues.get(task.id)?.issue ?? this.shared.issues.size + 1,
    });
    this.shared.issues.set(task.id, mirror);
    this.shared.trace.push({
      kind: 'assignment',
      actor: this.actor,
      task: structuredClone(mirror),
    });
    return structuredClone(mirror);
  }
}

const roots: string[] = [],
  coordinators: Coordinator[] = [];
afterEach(async () => {
  for (const coordinator of coordinators.splice(0)) await coordinator.close().catch(() => {});
  for (const root of roots.splice(0)) {
    if (!path.basename(root).startsWith('kit-handoff-test-'))
      throw new Error('Unsafe fixture cleanup');
    await rm(root, { recursive: true, force: true });
  }
});
async function fixture(
  shared = new Authority(),
  actor = 'alice',
  mode: LeadershipMode = 'normal',
  root?: string,
) {
  if (!root) {
    const base = path.join(process.cwd(), '.kit', 'handoff-tests');
    await mkdir(base, { recursive: true });
    root = await mkdtemp(path.join(base, 'kit-handoff-test-'));
    roots.push(root);
  }
  const transport = new HandoffQueue(shared, actor, mode);
  const coordinator = await Coordinator.open(config, root, {
    transport,
    now: () => shared.now,
    resume: mode === 'resume',
    takeover: mode === 'takeover',
  });
  coordinators.push(coordinator);
  return { coordinator, transport, shared, root };
}
function task(id: string, dependencies: string[] = []): Task {
  return TaskSchema.parse({
    id,
    runId: config.runId,
    version: 1,
    planVersion: 1,
    title: id,
    description: `Implement ${id}`,
    dependencies,
    baseSha: 'a'.repeat(40),
    allowedPaths: [`src/${id}`],
    acceptance: ['Authored checks pass'],
    checkIds: ['unit'],
    updatedAt: new Date(start).toISOString(),
  });
}
async function plan(
  coordinator: Coordinator,
  tasks = [task('one'), task('two'), task('three')],
  approve = true,
) {
  await coordinator.propose(
    PlanSchema.parse({
      version: 1,
      objective: 'A working judge demo',
      contract: 'Shared response {text:string}',
      rationale:
        'Prioritize one source-backed demo and independent scopes to preserve a short critical path.',
      tasks,
    }),
  );
  if (approve) await coordinator.approve(1);
}
function report(
  assigned: Task,
  shared: Authority,
  kind: WorkerReport['kind'] = 'result',
): WorkerReport {
  return {
    reportId: randomUUID(),
    runId: config.runId,
    taskId: assigned.id,
    version: assigned.version,
    leaseToken: assigned.lease!.token,
    worker: assigned.assignedWorker!,
    at: new Date(shared.now).toISOString(),
    kind,
    evidence:
      kind === 'result'
        ? [
            {
              kind: 'check',
              summary: 'Fixture checks passed',
              command: 'node --test',
              exitCode: 0,
              at: new Date(shared.now).toISOString(),
            },
            {
              kind: 'commit',
              summary: 'Scoped fixture commit',
              sha: 'b'.repeat(40),
              at: new Date(shared.now).toISOString(),
            },
          ]
        : [],
  };
}

describe('portable coordinator handoff with durable decision authority', () => {
  it('moves A→B→C→A with larger epochs and unchanged active worker ownership', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await a.coordinator.saveThread('LOCAL-A-NATIVE-THREAD');
    await plan(a.coordinator);
    await a.coordinator.tick();
    const assignments = a.coordinator
      .getState()
      .tasks.map((t) => ({ id: t.id, worker: t.assignedWorker, branch: t.branch, lease: t.lease }));
    const offered = await a.coordinator.handoff('agent-b');
    expect(offered).toMatchObject({
      status: 'offered',
      completed: false,
      successor: 'bob',
      epoch: 1,
    });
    await a.coordinator.close();
    const localDirectory = path.join(a.root, '.kit', 'orchestration', config.runId);
    const disk = JSON.parse(
      await readFile(path.join(localDirectory, 'state.json'), 'utf8'),
    ) as RunState;
    disk.context!.decisions.push({
      id: 'local-unshared-decision',
      actor: 'alice',
      at: new Date(start).toISOString(),
      kind: 'architecture',
      summary: 'Unpublished local draft',
      rationale: 'Retain this local why without silently publishing it on resume.',
    });
    await writeFile(path.join(localDirectory, 'state.json'), JSON.stringify(disk));
    await expect(a.coordinator.tick()).rejects.toThrow('must start');
    const b = await fixture(a.shared, 'bob', 'resume');
    await b.coordinator.start();
    await b.coordinator.tick();
    expect(a.shared.leadership).toMatchObject({ coordinator: 'bob', epoch: 2, phase: 'active' });
    await b.coordinator.handoff('agent-c');
    const c = await fixture(a.shared, 'carol', 'resume');
    await c.coordinator.start();
    await c.coordinator.tick();
    expect(a.shared.leadership?.epoch).toBe(3);
    await c.coordinator.handoff('agent-a');
    const returned = await fixture(a.shared, 'alice', 'resume', a.root);
    await returned.coordinator.start();
    await returned.coordinator.tick();
    expect(a.shared.leadership).toMatchObject({ coordinator: 'alice', epoch: 4 });
    expect(
      returned.coordinator.getState().tasks.map((t) => ({
        id: t.id,
        worker: t.assignedWorker,
        branch: t.branch,
        lease: t.lease,
      })),
    ).toEqual(assignments);
    expect(a.shared.trace.filter((entry) => entry.kind === 'assignment')).toHaveLength(3);
    const backups = (await readdir(localDirectory)).filter((name) =>
      name.startsWith('local-before-resume-'),
    );
    expect(backups.length).toBeGreaterThan(0);
    const retained = await readFile(path.join(localDirectory, backups[0]), 'utf8');
    expect(retained).toContain('local-unshared-decision');
    expect(retained).toContain('LOCAL-A-NATIVE-THREAD');
    expect(returned.coordinator.getState().threadId).toBeUndefined();
    expect(JSON.stringify(a.shared.checkpoint)).not.toContain('local-unshared-decision');
  });
  it('keeps a committed successor offer truthful if its final local journal write fails', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator, [task('one')]);
    const events: string[] = [];
    a.coordinator.onEvent((event) => events.push(event.type));
    const save = StateStore.prototype.save;
    const failure = vi.spyOn(StateStore.prototype, 'save').mockImplementation(function (
      this: StateStore,
      state,
    ) {
      if (
        a.shared.leadership?.phase === 'handoff' &&
        state.events.at(-1)?.type === 'handoff-offered'
      )
        return Promise.reject(new Error('Local disk full after CAS'));
      return save.call(this, state);
    });
    try {
      expect(await a.coordinator.handoff('agent-b')).toMatchObject({
        status: 'offered',
        completed: false,
      });
      expect(events).toContain('handoff-offered');
      expect(a.shared.leadership?.phase).toBe('handoff');
    } finally {
      failure.mockRestore();
    }
  });

  it('rejects healthy/early takeover and allows only one simultaneous contender after expiry plus safety margin', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator, [task('one')]);
    await a.coordinator.tick();
    const early = await fixture(a.shared, 'bob', 'takeover');
    await expect(early.coordinator.start()).rejects.toThrow('Healthy lease');
    const expiresAt = a.shared.leadership!.expiresAt;
    a.shared.now = expiresAt + TAKEOVER_SAFETY_MS - 1;
    const margin = await fixture(a.shared, 'carol', 'takeover');
    await expect(margin.coordinator.start()).rejects.toThrow('safety margin');
    a.shared.now++;
    const b = await fixture(a.shared, 'bob', 'takeover'),
      c = await fixture(a.shared, 'carol', 'takeover');
    let contenders = 0,
      release!: () => void;
    const simultaneous = new Promise<void>((resolve) => {
      release = resolve;
    });
    a.shared.acquisitionGate = async () => {
      if (++contenders === 2) release();
      await simultaneous;
    };
    const attempts = await Promise.allSettled([b.coordinator.start(), c.coordinator.start()]);
    expect(attempts.filter((attempt) => attempt.status === 'fulfilled')).toHaveLength(1);
    expect(attempts.filter((attempt) => attempt.status === 'rejected')).toHaveLength(1);
    expect(
      (attempts.find((attempt) => attempt.status === 'rejected') as PromiseRejectedResult).reason
        .message,
    ).toContain('CAS lost');
    expect(a.shared.leadership?.epoch).toBe(2);
    expect(a.shared.checkpoint?.state.tasks[0].lease?.token).toBe(
      a.coordinator.getState().tasks[0].lease?.token,
    );
  });

  it('fences stale decisions, polling and old-coordinator reconnect after takeover', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator, [task('one')]);
    await a.coordinator.tick();
    a.shared.now = a.shared.leadership!.expiresAt + TAKEOVER_SAFETY_MS;
    const b = await fixture(a.shared, 'bob', 'takeover');
    await b.coordinator.start();
    const authoritative = structuredClone(a.shared.checkpoint);
    await expect(
      a.coordinator.recordDecision({
        kind: 'scope',
        summary: 'Stale new scope',
        rationale: 'Old process must not write',
      }),
    ).rejects.toThrow('Stale');
    expect(a.shared.checkpoint).toEqual(authoritative);
    await expect(a.coordinator.tick()).rejects.toThrow('Stale');
    const reconnect = await fixture(a.shared, 'alice', 'normal');
    await expect(reconnect.coordinator.start()).rejects.toThrow('already active');
    expect(a.shared.leadership?.coordinator).toBe('bob');
  });

  it('preserves a completion arriving during handoff, dependencies, branch and original task token', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator, [task('core'), task('ui', ['core'])]);
    await a.coordinator.tick();
    const assigned = a.coordinator.getState().tasks[0];
    await a.coordinator.handoff('agent-b');
    const completed = report(assigned, a.shared);
    await a.transport.postReport(assigned, completed);
    const b = await fixture(a.shared, 'bob', 'resume');
    await b.coordinator.start();
    await b.coordinator.tick();
    const state = b.coordinator.getState();
    expect(state.tasks[0]).toMatchObject({
      state: 'Review',
      branch: assigned.branch,
      assignedWorker: assigned.assignedWorker,
      lease: assigned.lease,
    });
    expect(state.tasks[1]).toMatchObject({ state: 'Planned', dependencies: ['core'] });
    expect(state.seenReports).toContain(completed.reportId);
    const resultEvents = state.events.filter((e) => e.type === 'worker-result').length;
    await b.coordinator.tick();
    expect(b.coordinator.getState().events.filter((e) => e.type === 'worker-result')).toHaveLength(
      resultEvents,
    );
    expect(
      a.shared.trace.filter(
        (entry) => entry.kind === 'assignment' && entry.task?.state === 'Assigned',
      ),
    ).toHaveLength(1);
  });

  it('restores pending context, answered questions, plan rationale and approval without sharing native thread state', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await a.coordinator.saveThread('PRIVATE-NATIVE-THREAD');
    await a.coordinator.updateContext({
      summary: 'PDF first, authored fixture, no paid APIs.',
      requirements: ['Source-backed output'],
      priorities: ['Demo before exports'],
      answeredQuestions: [{ question: 'PDF or LaTeX first?', answer: 'PDF first' }],
    });
    await a.coordinator.recordDecision({
      kind: 'architecture',
      summary: 'Use authored fixtures',
      rationale: 'Redistributable fixtures avoid an unresolved licensing dependency.',
    });
    await a.coordinator.rememberMessage({
      id: 'request-1',
      role: 'user',
      text: 'Polish the upload flow',
      status: 'pending',
      at: new Date(start).toISOString(),
    });
    await plan(a.coordinator, [task('one')]);
    await a.coordinator.handoff('agent-b');
    expect(JSON.stringify(a.shared.checkpoint)).not.toContain('PRIVATE-NATIVE-THREAD');
    const b = await fixture(a.shared, 'bob', 'resume');
    await b.coordinator.start();
    const state = b.coordinator.getState();
    expect(state.threadId).toBeUndefined();
    expect(state.reconstructed).toBe(true);
    await b.coordinator.saveThread('LOCAL-B-RESUMABLE');
    expect(b.coordinator.getState().reconstructed).toBe(false);
    expect(state.approvedVersion).toBe(1);
    expect(state.plan?.rationale).toContain('source-backed demo');
    expect(state.context?.summary).toContain('PDF first');
    expect(state.context?.answeredQuestions).toEqual([
      { question: 'PDF or LaTeX first?', answer: 'PDF first' },
    ]);
    expect(state.context?.recentMessages[0]).toMatchObject({ id: 'request-1', status: 'pending' });
    expect(
      state.context?.decisions.some(
        (d) => d.kind === 'architecture' && d.rationale.includes('licensing'),
      ),
    ).toBe(true);
    await b.coordinator.tick();
    expect(b.coordinator.getState().tasks[0].state).toBe('Assigned');
  });

  it('keeps an unapproved plan and unresolved blocker visible after transfer', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator, [task('one')], false);
    await a.coordinator.handoff('agent-b');
    const b = await fixture(a.shared, 'bob', 'resume');
    await b.coordinator.start();
    await b.coordinator.tick();
    expect(b.coordinator.getState().approvedVersion).toBeUndefined();
    expect(b.coordinator.getState().tasks[0].state).toBe('Planned');
    expect(a.shared.trace.filter((entry) => entry.kind === 'assignment')).toHaveLength(0);
    await b.coordinator.approve(1);
    await b.coordinator.tick();
    const assigned = b.coordinator.getState().tasks[0];
    const blocked = report(assigned, a.shared, 'blocked');
    blocked.blocker = {
      id: 'sample',
      question: 'Which sample has permission?',
      recommendation: 'Use authored fixture',
      options: ['Authored fixture', 'Supply permitted sample'],
      attempted: [],
      impact: 'One task waits',
    };
    await b.transport.postReport(assigned, blocked);
    await b.coordinator.tick();
    await b.coordinator.handoff('agent-c');
    const c = await fixture(a.shared, 'carol', 'resume');
    await c.coordinator.start();
    expect(c.coordinator.getState().tasks[0].blockers).toEqual([blocked.blocker]);
    expect(c.coordinator.getState().tasks[0].state).toBe('Blocked');
  });

  it.each(['decision', 'authorization'] as const)(
    'does not issue an assignment if %s checkpoint persistence fails',
    async (stage) => {
      const a = await fixture();
      await a.coordinator.start();
      await plan(a.coordinator, [task('one')]);
      a.shared.failSave = (cp) =>
        cp.context.decisions.some((d) => d.kind === 'dispatch') &&
        (stage === 'decision'
          ? cp.state.tasks[0].state === 'Planned'
          : cp.state.tasks[0].state === 'Assigned');
      await expect(a.coordinator.tick()).rejects.toThrow('checkpoint persistence');
      expect(a.shared.issues.size).toBe(0);
      expect(a.shared.checkpoint?.state.tasks[0].state).toBe('Planned');
      expect(a.shared.trace.filter((entry) => entry.kind === 'assignment')).toHaveLength(0);
      expect(a.coordinator.getState().paused).toBe(true);
      expect(
        (a.coordinator.status() as { checkpoint: { error?: string } }).checkpoint.error,
      ).toContain('no new assignment');
      a.shared.failSave = undefined;
      // Connectivity recovery alone must not publish an uncommitted paused task.
      await a.coordinator.tick().catch(() => {});
      expect(a.shared.issues.size).toBe(0);
      expect(a.shared.checkpoint?.state.tasks[0].state).toBe('Planned');
      await a.coordinator.recordDecision({
        kind: 'control',
        summary: 'Connectivity restored',
        rationale: 'Keep dispatch paused until a human explicitly resumes.',
      });
      expect(a.shared.checkpoint?.state.tasks[0]).toMatchObject({ state: 'Planned' });
      expect(a.shared.checkpoint?.state.tasks[0].lease).toBeUndefined();
      await a.coordinator.handoff('agent-b');
      expect(a.shared.checkpoint?.state.tasks[0].lease).toBeUndefined();
      expect(a.shared.checkpoint?.state.pendingPublications).not.toContain('one');
      const b = await fixture(a.shared, 'bob', 'resume');
      await b.coordinator.start();
      await b.coordinator.tick();
      expect(a.shared.issues.size).toBe(0);
      await b.coordinator.action('resume');
      await b.coordinator.tick();
      expect(b.coordinator.getState().tasks[0].state).toBe('Assigned');
      expect(a.shared.issues.size).toBe(1);
    },
  );

  it('commits each decision before its assignment and retains the last complete checkpoint on a failed write', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator);
    await a.coordinator.tick();
    const assignments = a.shared.trace.filter((entry) => entry.kind === 'assignment');
    expect(assignments).toHaveLength(3);
    for (const assignment of assignments) {
      const publishedAt = a.shared.trace.indexOf(assignment),
        id = assignment.task!.assignmentDecisionId;
      expect(id).toBeTruthy();
      expect(
        a.shared.trace
          .slice(0, publishedAt)
          .some(
            (entry) =>
              entry.checkpoint?.context.decisions.some((d) => d.id === id) &&
              entry.checkpoint?.state.tasks.find((t) => t.id === assignment.task!.id)?.state ===
                'Planned',
          ),
      ).toBe(true);
    }
    const durable = structuredClone(a.shared.checkpoint);
    a.shared.failSave = () => true;
    await expect(
      a.coordinator.updateContext({ summary: 'This write never became durable' }),
    ).rejects.toThrow('persistence failure');
    expect(a.shared.checkpoint).toEqual(durable);
    a.shared.failSave = undefined;
    a.shared.now = a.shared.leadership!.expiresAt + TAKEOVER_SAFETY_MS;
    const b = await fixture(a.shared, 'bob', 'takeover');
    await b.coordinator.start();
    expect(b.coordinator.getState().context?.summary).not.toBe('This write never became durable');
    expect(b.coordinator.getState().tasks.map((t) => t.lease?.token)).toEqual(
      durable!.state.tasks.map((t) => t.lease?.token),
    );
  });

  it('blocks transfer while private pending input has no explicit portable summary', async () => {
    const a = await fixture();
    await a.coordinator.start();
    const remove = a.coordinator.setHandoffGuard(async () => {
      throw new Error('Private input still pending');
    });
    await expect(a.coordinator.handoff('agent-b')).rejects.toThrow('Private input still pending');
    expect(a.shared.leadership?.phase).toBe('active');
    expect(a.shared.checkpoint?.context.decisions.some((d) => d.kind === 'handoff')).toBe(false);
    remove();
    await a.coordinator.handoff('agent-b');
    expect(a.shared.leadership?.phase).toBe('handoff');
  });

  it('rejects corrupt/outdated/policy-mismatched checkpoints instead of resuming untrusted state', async () => {
    const a = await fixture();
    await a.coordinator.start();
    await plan(a.coordinator, [task('one')]);
    await a.coordinator.handoff('agent-b');
    const correct = structuredClone(a.shared.checkpoint!);
    for (const corrupt of [
      { ...correct, schemaVersion: 1 },
      { ...correct, policyDigest: '0'.repeat(64) },
      { ...correct, runId: 'different-run' },
      { ...correct, state: { ...correct.state, events: correct.state.events.slice(1) } },
    ])
      expect(() => validateCheckpoint(corrupt, config)).toThrow();
    a.shared.checkpoint = { ...correct, policyDigest: '0'.repeat(64) };
    const b = await fixture(a.shared, 'bob', 'resume');
    await expect(b.coordinator.start()).rejects.toThrow('policy mismatch');
    expect(a.shared.issues.size).toBe(0);
  });

  it('refuses a remote checkpoint older than the durable local cursor', async () => {
    const a = await fixture();
    await a.coordinator.start();
    const earlier = structuredClone(a.shared.checkpoint!);
    await a.coordinator.updateContext({ summary: 'A newer durable project decision' });
    await a.coordinator.close();
    a.shared.checkpoint = earlier;
    const restarted = await fixture(a.shared, 'alice', 'normal', a.root);
    await expect(restarted.coordinator.start()).rejects.toThrow('checkpoint regressed');
    expect(a.shared.issues.size).toBe(0);
  });

  it('keeps credentials, native IDs and full private transcript fields out of provider-independent checkpoints', async () => {
    const a = await fixture();
    await a.coordinator.start();
    const local = Object.assign(a.coordinator.getState(), {
      threadId: 'LOCAL-THREAD-SENTINEL',
      auth: { token: 'PRIVATE-AUTH-SENTINEL' },
      privateTranscript: 'PRIVATE-TRANSCRIPT-SENTINEL',
      environment: { OPENAI_API_KEY: 'PRIVATE-ENV-SENTINEL' },
    });
    const checkpoint = buildCheckpoint(
      local as RunState,
      config,
      'alice',
      new Date(start).toISOString(),
    );
    const wire = JSON.stringify(checkpoint);
    for (const marker of [
      'LOCAL-THREAD-SENTINEL',
      'PRIVATE-AUTH-SENTINEL',
      'PRIVATE-TRANSCRIPT-SENTINEL',
      'PRIVATE-ENV-SENTINEL',
    ])
      expect(wire).not.toContain(marker);
    expect(() => CheckpointSchema.parse({ ...checkpoint, threadId: 'unportable' })).toThrow();
    const secret = `ghp_${'a'.repeat(30)}`;
    expect(() => assertSharedSafe({ nested: { credential: secret } })).toThrow('Sensitive');
    await expect(
      a.coordinator.recordDecision({
        kind: 'architecture',
        summary: 'Unsafe secret',
        rationale: `Use ${secret}`,
      }),
    ).rejects.toThrow('Sensitive');
    const safe = redactTeamText(
      `Email person@example.test, Bearer ${'x'.repeat(30)} and GH_TOKEN=${secret}`,
    );
    expect(safe).not.toContain(secret);
    expect(safe).not.toContain('person@example.test');
    expect(safe).toContain('[redacted]');
    expect(() => assertSharedSafe(safe)).not.toThrow();
  });
});
