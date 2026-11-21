import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { lstat, mkdir, open, readFile, rename, unlink } from 'node:fs/promises';
import path from 'node:path';
import { GitHubControl } from './leadership';
import { assertSharedSafe } from './checkpoint';
import {
  coordinatorActors,
  type LeadershipMode,
  type PortableCheckpoint,
} from './handoff-contracts';
import { z } from 'zod';
import {
  ConfigSchema,
  Id,
  TaskSchema,
  WorkerReportSchema,
  type Config,
  type QueueTransport,
  type Task,
  type WorkerReport,
} from './contracts';

const TASK = '<!-- hackathon-kit/task/v1 -->';
const REPORT = '<!-- hackathon-kit/report/v1 -->';
const MAX_BODY = 60_000;
const PAGE_LIMIT = 10;
const login = (value: string) => value.toLowerCase();
type Method = 'GET' | 'POST' | 'PATCH';
export type GitHubApi = (endpoint: string, method: Method, input?: unknown) => Promise<unknown>;
export type GitHubOptions = {
  cwd?: string;
  api?: GitHubApi;
  now?: () => number;
  ownerId?: string;
  recoverExpiredLeadership?: boolean;
  leadershipMode?: LeadershipMode;
  host?: string;
};
const ActorSchema = z.object({ login: z.string() }).nullable();
const ContentSchema = z.object({
  id: z.string(),
  body: z.string().max(MAX_BODY),
  author: ActorSchema,
  editor: ActorSchema,
  lastEditedAt: z.string().nullable(),
});
const IssueSchema = ContentSchema.extend({ number: z.number().int().positive() });
const UncertainSchema = z
  .object({ schemaVersion: z.literal(1), runId: Id, uncertain: z.array(Id).max(100) })
  .strict();

function encode(marker: string, value: unknown): string {
  const body = `${marker}\n\`\`\`json\n${JSON.stringify(value)}\n\`\`\``;
  if (Buffer.byteLength(body) > MAX_BODY)
    throw new Error('GitHub record exceeds 60 KB; archive evidence first');
  return body;
}
function decode(marker: string, body: string): unknown {
  const prefix = `${marker}\n\`\`\`json\n`,
    suffix = '\n```';
  if (Buffer.byteLength(body) > MAX_BODY || !body.startsWith(prefix) || !body.endsWith(suffix))
    throw new Error('Malformed orchestration record; no issue text is executable');
  return JSON.parse(body.slice(prefix.length, -suffix.length));
}
function intent(task: Task): string {
  const { version: _version, issue: _issue, ...body } = task;
  return JSON.stringify(body);
}
function trusted(content: z.infer<typeof ContentSchema>, expected: string): boolean {
  return (
    !!content.author &&
    login(content.author.login) === login(expected) &&
    (!content.lastEditedAt || (!!content.editor && login(content.editor.login) === login(expected)))
  );
}

/** Bounded gh API adapter. JSON is sent on stdin, never interpolated into a shell. */
export function ghApi(cwd = process.cwd()): GitHubApi {
  return (endpoint, method, input) =>
    new Promise((resolve, reject) => {
      const args = ['api', '--hostname', 'github.com', '--method', method, endpoint];
      if (input !== undefined) args.push('--input', '-');
      const child = spawn(process.platform === 'win32' ? 'gh.exe' : 'gh', args, {
        cwd,
        shell: false,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      let output = '',
        stderr = '',
        bytes = 0,
        settled = false;
      const fail = (error: Error) => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(error);
        }
      };
      const timer = setTimeout(() => {
        child.kill();
        fail(new Error('GitHub request timed out; mutation outcome may be unknown'));
      }, 30_000);
      for (const [stream, isError] of [
        [child.stdout, false],
        [child.stderr, true],
      ] as const) {
        stream.on('data', (chunk: Buffer) => {
          bytes += chunk.length;
          if (bytes > 2_000_000) {
            child.kill();
            fail(new Error('GitHub response exceeds 2 MB'));
            return;
          }
          if (isError) stderr += chunk.toString();
          else output += chunk.toString();
        });
      }
      child.on('error', fail);
      child.stdin.on('error', () => {});
      child.on('close', (code) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (code !== 0) {
          // Only retain the HTTP status; gh stderr may contain private URLs or account details.
          const status = stderr.match(/HTTP (\d{3})/)?.[1];
          reject(
            Object.assign(
              new Error(`GitHub ${method} failed${status ? ` (HTTP ${status})` : ''}`),
              { status: Number(status) || undefined },
            ),
          );
        } else {
          try {
            resolve(output.trim() ? JSON.parse(output) : null);
          } catch {
            reject(new Error('GitHub returned invalid JSON'));
          }
        }
      });
      child.stdin.end(input === undefined ? undefined : JSON.stringify(input));
    });
}

/** One coordinator publishes task bodies; each worker only appends its own fenced reports. */
export class GitHubTransport implements QueueTransport {
  readonly config: Config;
  private readonly api: GitHubApi;
  private readonly now: () => number;
  private readonly control: GitHubControl;
  private readonly ledgerDirectory?: string;
  private memoryUncertain = new Set<string>();
  private reportCache?: { key: string; at: number; reports: WorkerReport[] };

  constructor(config: Config, options: GitHubOptions = {}) {
    this.config = ConfigSchema.parse(config);
    this.api = options.api ?? ghApi(options.cwd);
    this.now = options.now ?? Date.now;
    this.control = new GitHubControl(this.config, { ...options, api: this.api });
    // An injected API without cwd is a pure in-memory mock. Live adapters always persist.
    if (options.cwd || !options.api)
      this.ledgerDirectory = path.join(
        path.resolve(options.cwd ?? process.cwd()),
        '.kit',
        'orchestration',
        this.config.runId,
      );
  }
  private async ledgerBoundary() {
    if (!this.ledgerDirectory) return;
    let current = path.parse(this.ledgerDirectory).root;
    for (const part of path.relative(current, this.ledgerDirectory).split(path.sep)) {
      current = path.join(current, part);
      const info = await lstat(current).catch((error) => {
        if (error.code !== 'ENOENT') throw error;
      });
      if (info?.isSymbolicLink()) throw new Error('GitHub recovery ledger cannot follow symlinks');
    }
    const info = await lstat(path.join(this.ledgerDirectory, 'github-uncertain.json')).catch(
      (error) => {
        if (error.code !== 'ENOENT') throw error;
      },
    );
    if (info?.isSymbolicLink()) throw new Error('GitHub recovery ledger cannot be a symlink');
    if (info && info.size > 16_000) throw new Error('GitHub recovery ledger exceeds 16 KB');
  }
  private async uncertain(): Promise<Set<string>> {
    if (!this.ledgerDirectory) return new Set(this.memoryUncertain);
    await this.ledgerBoundary();
    const raw = await readFile(
      path.join(this.ledgerDirectory, 'github-uncertain.json'),
      'utf8',
    ).catch((error) => {
      if (error.code === 'ENOENT') return undefined;
      throw error;
    });
    if (raw === undefined) return new Set();
    const data = UncertainSchema.parse(JSON.parse(raw));
    if (data.runId !== this.config.runId) throw new Error('GitHub recovery ledger run mismatch');
    return new Set(data.uncertain);
  }
  private async markUncertain(taskId: string, uncertain: boolean) {
    const pending = await this.uncertain();
    if (uncertain) pending.add(taskId);
    else if (!pending.delete(taskId)) return;
    const record = UncertainSchema.parse({
      schemaVersion: 1,
      runId: this.config.runId,
      uncertain: [...pending],
    });
    if (!this.ledgerDirectory) {
      this.memoryUncertain = pending;
      return;
    }
    await this.ledgerBoundary();
    await mkdir(this.ledgerDirectory, { recursive: true, mode: 0o700 });
    await this.ledgerBoundary();
    const destination = path.join(this.ledgerDirectory, 'github-uncertain.json');
    const temporary = `${destination}.${randomUUID()}.tmp`;
    const handle = await open(temporary, 'wx', 0o600);
    try {
      await handle.writeFile(JSON.stringify(record) + '\n');
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await this.ledgerBoundary();
      await rename(temporary, destination);
    } finally {
      await unlink(temporary).catch(() => {});
    }
  }
  private get root() {
    return `repos/${this.config.repo}`;
  }
  private async read(endpoint: string): Promise<unknown> {
    for (let retry = 0; ; retry++) {
      try {
        return await this.api(endpoint, 'GET');
      } catch (error) {
        const status = (error as { status?: number }).status;
        if (retry >= 2 || (status !== undefined && status < 500 && status !== 429)) throw error;
        await new Promise((resolve) => setTimeout(resolve, 100 * 2 ** retry));
      }
    }
  }
  private async identity(expected?: string) {
    const actor = z.object({ login: z.string() }).parse(await this.read('user')).login;
    if (expected && login(actor) !== login(expected))
      throw new Error(`GitHub login must be ${expected}; authenticate locally with gh auth login`);
    return actor;
  }
  async acquireLeadership(): Promise<void> {
    await this.control.acquire();
  }
  async renewLeadership(): Promise<void> {
    await this.control.renew();
  }
  async releaseLeadership(): Promise<void> {
    await this.control.release();
  }
  async getLeadership() {
    return this.control.status();
  }
  async loadCheckpoint() {
    return this.control.loadCheckpoint();
  }
  async saveCheckpoint(checkpoint: PortableCheckpoint) {
    return this.control.saveCheckpoint(checkpoint);
  }
  async prepareHandoff(successor: string, checkpoint: PortableCheckpoint) {
    return this.control.prepareHandoff(successor, checkpoint);
  }
  private async assertLeadership() {
    return this.control.assertOwned();
  }
  private trustedCoordinator(content: z.infer<typeof ContentSchema>) {
    const actors = coordinatorActors(this.config);
    return (
      !!content.author &&
      actors.includes(login(content.author.login)) &&
      (!content.lastEditedAt || (!!content.editor && actors.includes(login(content.editor.login))))
    );
  }
  private async pages(endpoint: string): Promise<any[]> {
    const result: any[] = [];
    for (let page = 1; page <= PAGE_LIMIT; page++) {
      const next = z
        .array(z.unknown())
        .parse(
          await this.read(
            `${endpoint}${endpoint.includes('?') ? '&' : '?'}per_page=100&page=${page}`,
          ),
        );
      result.push(...next);
      if (next.length < 100) return result;
    }
    throw new Error(
      'GitHub pagination cap reached; archive or narrow the project before continuing',
    );
  }
  private async contents(ids: string[], kind: 'Issue' | 'IssueComment') {
    if (!ids.length) return [];
    const query = `query($ids:[ID!]!){nodes(ids:$ids){... on ${kind}{id body author{login} editor{login} lastEditedAt ${kind === 'Issue' ? 'number' : ''}}}}`;
    const result = await this.api('graphql', 'POST', { query, variables: { ids } });
    const parsed = z
      .object({
        data: z.object({ nodes: z.array(kind === 'Issue' ? IssueSchema : ContentSchema) }),
      })
      .parse(result);
    if (parsed.data.nodes.length !== ids.length)
      throw new Error('GitHub returned incomplete trust metadata');
    return parsed.data.nodes;
  }
  private async issueTasks(): Promise<Task[]> {
    const issues = await this.pages(`${this.root}/issues?state=all&sort=created&direction=desc`);
    const candidates = issues.filter(
      (i) => !i.pull_request && typeof i.body === 'string' && i.body.startsWith(TASK),
    );
    if (candidates.length > 100)
      throw new Error('More than 100 orchestration issues; archive old runs before continuing');
    const records = await this.contents(
      candidates.map((i) => z.string().parse(i.node_id)),
      'Issue',
    );
    const tasks: Task[] = [];
    for (const raw of records) {
      const issue = IssueSchema.parse(raw);
      if (!issue.author || !coordinatorActors(this.config).includes(login(issue.author.login)))
        continue;
      if (!this.trustedCoordinator(issue))
        throw new Error(
          `Task issue #${issue.number} was edited by an unauthorized actor; reconcile before continuing`,
        );
      const parsed = TaskSchema.safeParse(decode(TASK, issue.body));
      if (!parsed.success)
        throw new Error(`Invalid task issue #${issue.number}; reconciliation required`);
      if (parsed.data.runId !== this.config.runId) continue;
      if (parsed.data.issue !== undefined && parsed.data.issue !== issue.number)
        throw new Error('Task issue number mismatch');
      if (tasks.some((t) => t.id === parsed.data.id))
        throw new Error(`Duplicate task issue ${parsed.data.id}; reconciliation required`);
      tasks.push({ ...parsed.data, issue: issue.number });
    }
    return tasks;
  }
  private sameAssignment(a: Task, b: Task) {
    const fields = (task: Task) => ({
      id: task.id,
      runId: task.runId,
      baseSha: task.baseSha,
      allowedPaths: task.allowedPaths,
      reservedPaths: task.reservedPaths,
      dependencies: task.dependencies,
      checkIds: task.checkIds,
      assignedWorker: task.assignedWorker,
      branch: task.branch,
      assignmentDecisionId: task.assignmentDecisionId,
      token: task.lease?.token,
      epoch: task.lease?.epoch,
    });
    return JSON.stringify(fields(a)) === JSON.stringify(fields(b));
  }
  private async authoritativeTasks(): Promise<Task[]> {
    const checkpoint = await this.loadCheckpoint();
    if (!checkpoint) {
      const status = await this.getLeadership();
      // Task-only v1 runs remain visible for bootstrap migration, never new v2 assignments.
      return status?.host === 'legacy-v1' || this.control.isLegacyMigration()
        ? this.issueTasks()
        : [];
    }
    const mirrors = checkpoint.state.tasks.some((task) => task.lease && !task.issue)
      ? await this.issueTasks()
      : [];
    return checkpoint.state.tasks.map((task) => {
      const mirror = mirrors.find(
        (candidate) => candidate.id === task.id && this.sameAssignment(candidate, task),
      );
      if (task.issue && mirror && task.issue !== mirror.issue)
        throw new Error('Authoritative task issue number mismatch');
      return TaskSchema.parse({ ...task, issue: task.issue ?? mirror?.issue });
    });
  }
  async listTasks(): Promise<Task[]> {
    const tasks = await this.authoritativeTasks();
    const reports = await this.reportsFor(
      tasks.filter((task) => ['Assigned', 'Running', 'Blocked'].includes(task.state)),
    );
    return tasks.map((task) => {
      if (!task.lease || !['Assigned', 'Running', 'Blocked'].includes(task.state)) return task;
      const heartbeat = reports
        .filter(
          (report) =>
            ['started', 'heartbeat', 'checkpoint'].includes(report.kind) &&
            report.taskId === task.id &&
            Date.parse(report.at) <= this.now() + 30_000,
        )
        .reduce((latest, report) => Math.max(latest, Date.parse(report.at)), 0);
      const expiresAt = Math.max(
        Date.parse(task.lease.expiresAt),
        heartbeat ? heartbeat + this.config.leaseMs : 0,
      );
      return { ...task, lease: { ...task.lease, expiresAt: new Date(expiresAt).toISOString() } };
    });
  }
  private async authorizeTask(task: Task) {
    await this.assertLeadership();
    const checkpoint = await this.loadCheckpoint();
    if (!checkpoint)
      throw new Error('A durable shared checkpoint is required before task publication');
    const authority = checkpoint.state.tasks.find((candidate) => candidate.id === task.id);
    if (!authority || intent(authority) !== intent(task))
      throw new Error('Task intent is absent from the current authoritative checkpoint');
    if (
      task.lease &&
      task.assignmentDecisionId &&
      !checkpoint.context.decisions.some(
        (decision) =>
          decision.id === task.assignmentDecisionId &&
          decision.kind === 'dispatch' &&
          decision.taskId === task.id,
      )
    )
      throw new Error('Assigned task has no durable dispatch decision');
  }
  async publishTask(input: Task): Promise<Task> {
    const task = TaskSchema.parse(input);
    if (task.runId !== this.config.runId) throw new Error('Task run mismatch');
    await this.authorizeTask(task);
    const existing = (await this.issueTasks()).find((t) => t.id === task.id);
    const uncertain = (await this.uncertain()).has(task.id);
    if (existing) {
      if (uncertain) {
        if (intent(existing) !== intent(task))
          throw new Error(
            `Uncertain creation of ${task.id} has a different remote body; manual reconciliation required`,
          );
        await this.markUncertain(task.id, false);
      }
      if (task.issue !== undefined && task.issue !== existing.issue)
        throw new Error('Task issue number changed');
      if (intent(existing) === intent(task)) {
        await this.assertLeadership();
        return existing;
      }
      if (task.version !== existing.version && task.version !== existing.version + 1)
        throw new Error('Task version conflict; reconcile before publishing');
      const candidate = { ...task, issue: existing.issue, version: existing.version + 1 };
      // Leadership must still be current after remote enumeration.
      await this.assertLeadership();
      try {
        await this.api(`${this.root}/issues/${existing.issue}`, 'PATCH', {
          body: encode(TASK, candidate),
        });
        await this.assertLeadership();
      } catch (error) {
        const recovered = (await this.issueTasks()).find((t) => t.id === task.id);
        if (recovered && intent(recovered) === intent(candidate)) {
          await this.assertLeadership();
          return recovered;
        }
        throw error;
      }
      return candidate;
    }
    if (task.issue !== undefined)
      throw new Error('Task issue missing remotely; do not recreate automatically');
    if (uncertain)
      throw new Error(
        `Uncertain creation of ${task.id}: no matching issue found. Manual reconciliation required; no second POST is allowed. Inspect github-uncertain.json after verifying GitHub.`,
      );
    await this.assertLeadership();
    // Write ahead: a crash during POST must never turn a retry into another issue.
    await this.markUncertain(task.id, true);
    try {
      z.object({ number: z.number().int().positive() }).parse(
        await this.api(`${this.root}/issues`, 'POST', {
          title: `[kit-agents:${this.config.runId}:${task.id}] ${task.title}`,
          body: encode(TASK, task),
        }),
      );
      await this.assertLeadership();
    } catch (error) {
      // A timed out POST may have succeeded. Read once; never blindly repeat it.
      const recovered = (await this.issueTasks()).find((t) => t.id === task.id);
      if (recovered && intent(recovered) === intent(task)) {
        await this.assertLeadership();
        await this.markUncertain(task.id, false);
        return recovered;
      }
      throw error;
    }
    const confirmed = (await this.issueTasks()).find((t) => t.id === task.id);
    if (!confirmed || intent(confirmed) !== intent(task))
      throw new Error(
        `Uncertain creation of ${task.id}; POST returned but a matching issue is not yet readable. Manual reconciliation required; no second POST is allowed.`,
      );
    await this.markUncertain(task.id, false);
    return confirmed;
  }
  async listReports(): Promise<WorkerReport[]> {
    return this.reportsFor(
      (await this.authoritativeTasks()).filter((task) =>
        ['Assigned', 'Running', 'Blocked', 'Paused', 'Cancelled'].includes(task.state),
      ),
    );
  }
  private async reportsFor(tasks: Task[]): Promise<WorkerReport[]> {
    const key = JSON.stringify(
      tasks.map((task) => [
        task.id,
        task.issue,
        task.version,
        task.lease?.token,
        task.assignedWorker,
        task.state,
      ]),
    );
    if (this.reportCache?.key === key && this.now() - this.reportCache.at < 3000)
      return structuredClone(this.reportCache.reports);
    const result: WorkerReport[] = [];
    for (const task of tasks.filter((t) => t.issue && t.assignedWorker && t.lease)) {
      const comments = await this.pages(`${this.root}/issues/${task.issue}/comments`);
      const candidates = comments.filter(
        (c) => typeof c.body === 'string' && c.body.startsWith(REPORT),
      );
      // GraphQL batches have a 100-node limit.
      for (let start = 0; start < candidates.length; start += 100) {
        const records = await this.contents(
          candidates.slice(start, start + 100).map((c) => z.string().parse(c.node_id)),
          'IssueComment',
        );
        for (const record of records) {
          if (!this.config.workers.some((w) => trusted(record, w.githubLogin))) continue;
          let decoded: unknown;
          try {
            decoded = decode(REPORT, record.body);
          } catch {
            continue;
          }
          const parsed = WorkerReportSchema.safeParse(decoded);
          if (!parsed.success) continue;
          const report = parsed.data;
          const worker = this.config.workers.find((w) => w.name === report.worker);
          if (
            !worker ||
            !trusted(record, worker.githubLogin) ||
            report.worker !== task.assignedWorker ||
            report.runId !== this.config.runId ||
            report.taskId !== task.id ||
            report.leaseToken !== task.lease!.token ||
            report.version > task.version
          )
            continue;
          if (!result.some((r) => r.reportId === report.reportId)) result.push(report);
        }
      }
    }
    this.reportCache = { key, at: this.now(), reports: result };
    return structuredClone(result);
  }
  async postReport(input: Task, inputReport: WorkerReport): Promise<void> {
    const task = TaskSchema.parse(input),
      report = WorkerReportSchema.parse(inputReport);
    assertSharedSafe(report);
    const worker = this.config.workers.find((w) => w.name === report.worker);
    if (!worker) throw new Error('Unknown worker');
    await this.identity(worker.githubLogin);
    if (
      !task.issue ||
      !task.lease ||
      task.runId !== this.config.runId ||
      report.runId !== task.runId ||
      report.taskId !== task.id ||
      report.worker !== task.assignedWorker ||
      report.leaseToken !== task.lease.token
    )
      throw new Error('Report does not match a current task lease');
    const current = (await this.listTasks()).find((t) => t.id === task.id);
    if (
      !current ||
      current.issue !== task.issue ||
      current.version < report.version ||
      current.lease?.token !== report.leaseToken ||
      current.assignedWorker !== report.worker ||
      Date.parse(current.lease.expiresAt) <= this.now() ||
      !['Assigned', 'Running', 'Blocked'].includes(current.state)
    )
      throw new Error('Assignment changed; stop the worker');
    const previous = await this.pages(`${this.root}/issues/${task.issue}/comments`);
    const duplicates = previous.filter(
      (c) =>
        c.user?.login &&
        login(c.user.login) === login(worker.githubLogin) &&
        c.body === encode(REPORT, report),
    );
    if (duplicates.length) {
      const metadata = await this.contents(
        duplicates.map((c) => z.string().parse(c.node_id)),
        'IssueComment',
      );
      if (metadata.some((c) => trusted(c, worker.githubLogin) && c.body === encode(REPORT, report)))
        return;
    }
    await this.api(`${this.root}/issues/${task.issue}/comments`, 'POST', {
      body: encode(REPORT, report),
    });
    this.reportCache = undefined;
  }
}
