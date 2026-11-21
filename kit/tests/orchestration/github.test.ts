import { afterEach, describe, expect, it } from 'vitest';
import { randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import {
  ConfigSchema,
  TaskSchema,
  type Task,
  type WorkerReport,
} from '../../tools/agents/contracts';
import { GitHubTransport, type GitHubApi, type GitHubOptions } from '../../tools/agents/github';
import { buildCheckpoint } from '../../tools/agents/checkpoint';
import { TAKEOVER_SAFETY_MS, type PortableCheckpoint } from '../../tools/agents/handoff-contracts';

const temporaryRoots: string[] = [];
afterEach(async () => {
  for (const root of temporaryRoots.splice(0)) {
    if (!path.basename(root).startsWith('kit-github-ledger-'))
      throw new Error('Unsafe test cleanup');
    await rm(root, { recursive: true, force: true });
  }
});
async function temporaryRoot() {
  const directory = path.join(process.cwd(), '.kit', 'github-tests');
  await mkdir(directory, { recursive: true });
  const root = await mkdtemp(path.join(directory, 'kit-github-ledger-'));
  temporaryRoots.push(root);
  return root;
}

const instant = Date.parse('2026-10-24T12:00:00Z');
const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'demo',
  repo: 'team/project',
  coordinator: 'lead',
  authorizedActors: ['lead'],
  workers: [{ name: 'agent-a', githubLogin: 'alice' }],
  startedAt: '2026-10-24T12:00:00Z',
  deadline: '2026-10-25T12:00:00Z',
  checks: [{ id: 'test', command: 'npm', args: ['test'] }],
});
function task(): Task {
  return TaskSchema.parse({
    id: 'UI-1',
    runId: 'demo',
    version: 1,
    planVersion: 1,
    title: 'Implement UI',
    description: 'Only the authorized UI.',
    state: 'Assigned',
    dependencies: [],
    baseSha: 'a'.repeat(40),
    allowedPaths: ['app/ui'],
    acceptance: ['Pass UI test'],
    checkIds: ['test'],
    assignedWorker: 'agent-a',
    branch: 'codex/demo/UI-1',
    lease: {
      token: randomUUID(),
      epoch: 1,
      expiresAt: new Date(instant + config.leaseMs).toISOString(),
    },
    updatedAt: new Date(instant).toISOString(),
  });
}
function report(t: Task): WorkerReport {
  return {
    reportId: randomUUID(),
    runId: t.runId,
    taskId: t.id,
    version: t.version,
    leaseToken: t.lease!.token,
    worker: 'agent-a',
    at: new Date(instant).toISOString(),
    kind: 'started',
    evidence: [],
  };
}
type Content = {
  id: string;
  node_id: string;
  number?: number;
  body: string;
  author: { login: string };
  user: { login: string };
  editor: { login: string } | null;
  lastEditedAt: string | null;
};
class FakeGitHub {
  actor = 'lead';
  time = instant;
  control?: string;
  commits = new Map<string, { message: string; tree: { sha: string }; parents: string[] }>([
    ['base', { message: 'initial', tree: { sha: 'tree' }, parents: [] }],
  ]);
  issues: Content[] = [];
  comments = new Map<number, Content[]>();
  blobs = new Map<string, { content: string; encoding: 'base64'; size: number }>();
  calls: { endpoint: string; method: string; input?: any }[] = [];
  next = 1;
  failCreateAfterApply = false;
  failCreateBeforeApply = false;
  failIssuePatchAfterApply = false;
  failNextPatch = false;
  onIssuePatch?: () => Promise<void>;
  fullPages = false;
  api: GitHubApi = async (endpoint, method, input?: any) => {
    this.calls.push({ endpoint, method, input });
    if (endpoint === 'user') return { login: this.actor };
    if (endpoint === 'repos/team/project')
      return { default_branch: 'main', permissions: { push: true } };
    if (endpoint.endsWith('/git/ref/heads/main')) return { object: { sha: 'base' } };
    if (endpoint.includes('/git/ref/heads/codex/')) {
      if (!this.control) throw Object.assign(new Error('not found'), { status: 404 });
      return { object: { sha: this.control } };
    }
    if (endpoint.includes('/git/commits/') && method === 'GET')
      return this.commits.get(endpoint.split('/').at(-1)!);
    if (endpoint.endsWith('/git/blobs') && method === 'POST') {
      const sha = `blob-${this.next++}`;
      this.blobs.set(sha, { ...input, size: Buffer.from(input.content, 'base64').length });
      return { sha };
    }
    if (endpoint.includes('/git/blobs/') && method === 'GET')
      return this.blobs.get(endpoint.split('/').at(-1)!);
    if (endpoint.endsWith('/git/commits') && method === 'POST') {
      const sha = `commit-${this.next++}`;
      this.commits.set(sha, { ...input, tree: { sha: input.tree } });
      return { sha };
    }
    if (endpoint.endsWith('/git/refs') && method === 'POST') {
      if (this.control) throw Object.assign(new Error('exists'), { status: 422 });
      this.control = input.sha;
      return { object: { sha: this.control } };
    }
    if (endpoint.includes('/git/refs/heads/codex/') && method === 'PATCH') {
      if (this.failNextPatch || this.commits.get(input.sha)!.parents[0] !== this.control) {
        this.failNextPatch = false;
        throw Object.assign(new Error('non-fast-forward'), { status: 422 });
      }
      expect(input.force).toBe(false);
      this.control = input.sha;
      return { object: { sha: this.control } };
    }
    if (endpoint.includes('/issues?'))
      return this.fullPages
        ? Array.from({ length: 100 }, () => ({ body: 'unrelated' }))
        : this.issues;
    if (endpoint === 'graphql') {
      const all = [...this.issues, ...[...this.comments.values()].flat()];
      return {
        data: {
          nodes: input.variables.ids.map((id: string) => all.find((item) => item.id === id)),
        },
      };
    }
    if (endpoint.endsWith('/issues') && method === 'POST') {
      if (this.failCreateBeforeApply) {
        this.failCreateBeforeApply = false;
        throw new Error('connection lost before outcome known');
      }
      const number = this.issues.length + 1;
      this.issues.push(this.content(`issue-${number}`, input.body, number));
      if (this.failCreateAfterApply) {
        this.failCreateAfterApply = false;
        throw new Error('connection lost');
      }
      return { number };
    }
    const issuePatch = endpoint.match(/\/issues\/(\d+)$/);
    if (issuePatch && method === 'PATCH') {
      if (this.onIssuePatch) {
        const hook = this.onIssuePatch;
        this.onIssuePatch = undefined;
        await hook();
      }
      const issue = this.issues.find((i) => i.number === Number(issuePatch[1]))!;
      issue.body = input.body;
      issue.editor = { login: this.actor };
      issue.lastEditedAt = new Date(this.time).toISOString();
      if (this.failIssuePatchAfterApply) {
        this.failIssuePatchAfterApply = false;
        throw new Error('connection lost after PATCH');
      }
      return issue;
    }
    const comment = endpoint.match(/\/issues\/(\d+)\/comments/);
    if (comment) {
      const number = Number(comment[1]),
        items = this.comments.get(number) ?? [];
      if (method === 'POST') {
        const content = this.content(`comment-${this.next++}`, input.body);
        items.push(content);
        this.comments.set(number, items);
        return content;
      }
      return items;
    }
    throw new Error(`Unexpected fake API request: ${method} ${endpoint}`);
  };
  content(id: string, body: string, number?: number): Content {
    return {
      id,
      node_id: id,
      number,
      body,
      author: { login: this.actor },
      user: { login: this.actor },
      editor: null,
      lastEditedAt: null,
    };
  }
  transport(options: Pick<GitHubOptions, 'recoverExpiredLeadership' | 'cwd'> = {}, raw = false) {
    const transport = new GitHubTransport(config, {
      api: this.api,
      now: () => this.time,
      ...options,
    });
    if (raw) return transport;
    const publish = transport.publishTask.bind(transport);
    transport.publishTask = async (input) => {
      const status = await transport.getLeadership();
      const actor = status?.coordinator ?? config.coordinator;
      let cp = await transport.loadCheckpoint();
      if (!cp) {
        cp = buildCheckpoint(
          {
            schemaVersion: 1,
            runId: config.runId,
            tasks: [],
            paused: false,
            events: [],
            seenReports: [],
            notices: [],
            lastStatusAt: this.time,
          },
          config,
          actor,
          new Date(this.time).toISOString(),
        );
        await transport.saveCheckpoint(cp);
      }
      const update = async (value: PortableCheckpoint) => {
        value.sequence++;
        value.at = new Date(this.time).toISOString();
        await transport.saveCheckpoint(value);
        cp = value;
      };
      const prior = cp.state.tasks.find((task) => task.id === input.id);
      if (input.lease && (!prior || prior.lease?.token !== input.lease.token)) {
        input.assignmentDecisionId ??= `dispatch-${randomUUID()}`;
        const decision = {
          id: input.assignmentDecisionId,
          at: new Date(this.time).toISOString(),
          actor,
          kind: 'dispatch' as const,
          summary: 'Authored fixture dispatch',
          rationale: 'Fixture scope is independent and approved',
          taskId: input.id,
          planVersion: input.planVersion,
        };
        await update({
          ...structuredClone(cp),
          context: { ...cp.context, decisions: [...cp.context.decisions, decision] },
        });
      }
      if (prior) {
        const comparable = (item: Task) => {
          const { version: _v, issue: _i, ...rest } = item;
          return JSON.stringify(rest);
        };
        if (comparable(prior) === comparable(input)) input.version = prior.version;
      }
      const desired = structuredClone(cp);
      const index = desired.state.tasks.findIndex((task) => task.id === input.id);
      if (index === -1) desired.state.tasks.push(structuredClone(input));
      else desired.state.tasks[index] = structuredClone(input);
      await update(desired);
      const result = await publish(input);
      const acknowledged = structuredClone(cp);
      acknowledged.state.tasks[acknowledged.state.tasks.findIndex((task) => task.id === input.id)] =
        result;
      await update(acknowledged);
      return result;
    };
    return transport;
  }
}

describe('GitHub distributed queue', () => {
  it('creates a leadership ref atomically, refuses a second writer, and permits explicit release', async () => {
    const gh = new FakeGitHub(),
      first = gh.transport(),
      second = gh.transport();
    await first.acquireLeadership();
    await expect(second.acquireLeadership()).rejects.toThrow('Another coordinator');
    await first.renewLeadership();
    await first.releaseLeadership();
    await second.acquireLeadership();
    await expect(first.renewLeadership()).rejects.toThrow('leadership lost');
    expect(
      gh.calls.filter((c) => c.endpoint.endsWith('/git/refs') && c.method === 'POST'),
    ).toHaveLength(1);
  });
  it('requires operator recovery for expired leadership and fences an old coordinator', async () => {
    const gh = new FakeGitHub(),
      first = gh.transport();
    await first.acquireLeadership();
    gh.time += config.leaseMs + TAKEOVER_SAFETY_MS + 1;
    await expect(gh.transport().acquireLeadership()).rejects.toThrow('explicitly recover');
    await gh.transport({ recoverExpiredLeadership: true }).acquireLeadership();
    await expect(first.publishTask(task())).rejects.toThrow('leadership lost');
  });
  it('stops on a failed non-force leadership CAS without repeating the mutation', async () => {
    const gh = new FakeGitHub(),
      transport = gh.transport();
    await transport.acquireLeadership();
    gh.failNextPatch = true;
    await expect(transport.renewLeadership()).rejects.toThrow('CAS failed');
    expect(gh.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1);
    await expect(transport.publishTask(task())).rejects.toThrow('leadership lost');
  });
  it('rejects incorrect local accounts before any mutation', async () => {
    const gh = new FakeGitHub();
    gh.actor = 'alice';
    await expect(gh.transport().acquireLeadership()).rejects.toThrow(/bootstrap|leadership lost/);
    expect(gh.calls.every((c) => c.method === 'GET')).toBe(true);
  });
  it('publishes idempotently, recovers an ambiguous create, and enforces version increments', async () => {
    const gh = new FakeGitHub(),
      transport = gh.transport();
    await transport.acquireLeadership();
    gh.failCreateAfterApply = true;
    const published = await transport.publishTask(task());
    expect(published.issue).toBe(1);
    await transport.publishTask(published);
    expect(gh.issues).toHaveLength(1);
    const updated = await transport.publishTask({ ...published, state: 'Running' });
    expect(updated.version).toBe(2);
    await expect(
      transport.publishTask({ ...published, title: 'Changed from stale version' }),
    ).rejects.toThrow('version conflict');
    expect((await transport.listTasks())[0]).toEqual(updated);
  });
  it('persists uncertainty before POST and refuses another creation across coordinator restart', async () => {
    const gh = new FakeGitHub(),
      cwd = await temporaryRoot(),
      first = gh.transport({ cwd });
    await first.acquireLeadership();
    gh.failCreateBeforeApply = true;
    const proposed = task();
    await expect(first.publishTask(proposed)).rejects.toThrow('connection lost');
    const ledgerPath = path.join(
      cwd,
      '.kit',
      'orchestration',
      config.runId,
      'github-uncertain.json',
    );
    expect(JSON.parse(await readFile(ledgerPath, 'utf8')).uncertain).toEqual([proposed.id]);
    await expect(first.publishTask(proposed)).rejects.toThrow('no second POST');
    await first.releaseLeadership();
    const restarted = gh.transport({ cwd });
    await restarted.acquireLeadership();
    await expect(restarted.publishTask(proposed)).rejects.toThrow('Manual reconciliation');
    expect(
      gh.calls.filter((c) => c.method === 'POST' && c.endpoint.endsWith('/issues')),
    ).toHaveLength(1);
    // The original remote outcome becomes readable. Only this stable match clears the gate.
    gh.issues.push(
      gh.content(
        'issue-1',
        `<!-- hackathon-kit/task/v1 -->\n\`\`\`json\n${JSON.stringify(proposed)}\n\`\`\``,
        1,
      ),
    );
    expect((await restarted.publishTask(proposed)).issue).toBe(1);
    expect(JSON.parse(await readFile(ledgerPath, 'utf8')).uncertain).toEqual([]);
    expect(
      gh.calls.filter((c) => c.method === 'POST' && c.endpoint.endsWith('/issues')),
    ).toHaveLength(1);
  });
  it('rejects a ledger from another run before creating an issue', async () => {
    const gh = new FakeGitHub(),
      cwd = await temporaryRoot();
    const directory = path.join(cwd, '.kit', 'orchestration', config.runId);
    await mkdir(directory, { recursive: true });
    await writeFile(
      path.join(directory, 'github-uncertain.json'),
      JSON.stringify({ schemaVersion: 1, runId: 'elsewhere', uncertain: [] }),
    );
    const transport = gh.transport({ cwd });
    await transport.acquireLeadership();
    await expect(transport.publishTask(task())).rejects.toThrow('ledger run mismatch');
    expect(gh.calls.some((c) => c.method === 'POST' && c.endpoint.endsWith('/issues'))).toBe(false);
  });
  it('refuses a symlink/junction recovery directory before issue creation', async () => {
    const gh = new FakeGitHub(),
      cwd = await temporaryRoot(),
      outside = await temporaryRoot();
    await symlink(
      outside,
      path.join(cwd, '.kit'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );
    const transport = gh.transport({ cwd });
    await transport.acquireLeadership();
    await expect(transport.publishTask(task())).rejects.toThrow('symlinks');
    expect(gh.calls.some((c) => c.method === 'POST' && c.endpoint.endsWith('/issues'))).toBe(false);
  });
  it('returns an empty queue, ignores foreign authors and blocks unauthorized last editors', async () => {
    const gh = new FakeGitHub(),
      transport = gh.transport();
    expect(await transport.listTasks()).toEqual([]);
    await transport.acquireLeadership();
    await transport.publishTask(task());
    gh.issues[0].lastEditedAt = new Date(instant).toISOString();
    gh.issues[0].editor = { login: 'mallory' };
    expect((await transport.listTasks())[0].id).toBe('UI-1');
    gh.issues[0].lastEditedAt = null;
    gh.issues[0].author.login = 'mallory';
    expect((await transport.listTasks())[0].id).toBe('UI-1');
  });
  it('recovers an ambiguous update without repeating PATCH and returns the new version', async () => {
    const gh = new FakeGitHub(),
      transport = gh.transport();
    await transport.acquireLeadership();
    const assigned = await transport.publishTask(task());
    gh.failIssuePatchAfterApply = true;
    const intent = { ...assigned, state: 'Running' as const };
    const updated = await transport.publishTask(intent);
    expect(updated.version).toBe(2);
    expect(await transport.publishTask(intent)).toEqual(updated);
    expect(
      gh.calls.filter((c) => c.method === 'PATCH' && c.endpoint.includes('/issues/')),
    ).toHaveLength(1);
  });
  it('checks the local GitHub identity again after an account switch', async () => {
    const gh = new FakeGitHub(),
      transport = gh.transport();
    await transport.acquireLeadership();
    gh.actor = 'alice';
    await expect(transport.publishTask(task())).rejects.toThrow(/bootstrap|leadership lost/);
    expect(gh.issues).toHaveLength(0);
  });
  it('accepts a report from an earlier version after lease renewal, and refuses expiry', async () => {
    const gh = new FakeGitHub(),
      lead = gh.transport();
    await lead.acquireLeadership();
    const assigned = await lead.publishTask(task());
    gh.time += 60_000;
    await lead.publishTask({
      ...assigned,
      lease: { ...assigned.lease!, expiresAt: new Date(gh.time + config.leaseMs).toISOString() },
    });
    gh.actor = 'alice';
    const worker = gh.transport();
    await worker.postReport(assigned, report(assigned));
    gh.time += config.leaseMs + 1;
    await expect(worker.postReport(assigned, report(assigned))).rejects.toThrow(
      'Assignment changed',
    );
  });
  it('fails closed on duplicate task IDs and incomplete pagination', async () => {
    const gh = new FakeGitHub(),
      transport = gh.transport();
    await transport.acquireLeadership();
    await transport.publishTask(task());
    gh.issues.push({ ...gh.issues[0], id: 'duplicate', node_id: 'duplicate', number: 2 });
    await expect(transport.publishTask((await transport.listTasks())[0])).rejects.toThrow(
      'Duplicate task',
    );
    gh.fullPages = true;
    await expect(transport.publishTask((await transport.listTasks())[0])).rejects.toThrow(
      'pagination cap',
    );
  });
  it('accepts authenticated worker reports exactly once and fences stale leases', async () => {
    const gh = new FakeGitHub(),
      lead = gh.transport();
    await lead.acquireLeadership();
    const assigned = await lead.publishTask(task());
    gh.actor = 'alice';
    const worker = gh.transport(),
      started = report(assigned);
    await expect(
      worker.postReport(assigned, {
        ...started,
        evidence: [{ kind: 'checkpoint', at: started.at, summary: 'Bearer ' + 'x'.repeat(32) }],
      }),
    ).rejects.toThrow('Sensitive content');
    expect(gh.comments.get(assigned.issue!)).toBeUndefined();
    await worker.postReport(assigned, started);
    await worker.postReport(assigned, started);
    expect(gh.comments.get(assigned.issue!)).toHaveLength(1);
    expect(await lead.listReports()).toEqual([started]);
    await expect(
      worker.postReport(assigned, { ...started, leaseToken: randomUUID() }),
    ).rejects.toThrow('current task lease');
  });
  it('ignores forged, edited, malformed and cross-run report comments', async () => {
    const gh = new FakeGitHub(),
      lead = gh.transport();
    await lead.acquireLeadership();
    const assigned = await lead.publishTask(task());
    const started = report(assigned),
      body = (value: unknown) =>
        `<!-- hackathon-kit/report/v1 -->\n\`\`\`json\n${JSON.stringify(value)}\n\`\`\``;
    gh.actor = 'mallory';
    const forged = gh.content('forged', body(started));
    gh.actor = 'alice';
    const edited = gh.content('edited', body({ ...started, reportId: randomUUID() }));
    edited.lastEditedAt = new Date(instant).toISOString();
    edited.editor = { login: 'mallory' };
    const malformed = gh.content('bad', '<!-- hackathon-kit/report/v1 -->\nnot json');
    const foreign = gh.content('foreign', body({ ...started, runId: 'elsewhere' }));
    gh.comments.set(assigned.issue!, [forged, edited, malformed, foreign]);
    expect(await lead.listReports()).toEqual([]);
  });
  it('rejects stale assignments and suspended tasks before posting', async () => {
    const gh = new FakeGitHub(),
      lead = gh.transport();
    await lead.acquireLeadership();
    const assigned = await lead.publishTask(task());
    await lead.publishTask({ ...assigned, version: 2, state: 'Paused' });
    gh.actor = 'alice';
    await expect(gh.transport().postReport(assigned, report(assigned))).rejects.toThrow(
      'Assignment changed',
    );
    expect(gh.comments.size).toBe(0);
  });
  it('bounds read retries and does not retry unknown-outcome mutations', async () => {
    let reads = 0;
    const transient = new GitHubTransport(config, {
      api: async () => {
        reads++;
        throw Object.assign(new Error('network'), { status: 503 });
      },
    });
    await expect(transient.acquireLeadership()).rejects.toThrow('network');
    expect(reads).toBe(3);
  });
  it('keeps worker heartbeats and results valid while leadership is handed to another account', async () => {
    const gh = new FakeGitHub(),
      lead = gh.transport();
    await lead.acquireLeadership();
    const assigned = await lead.publishTask(task());
    const cp = (await lead.loadCheckpoint())!;
    await lead.prepareHandoff('agent-a', { ...cp, sequence: cp.sequence + 1 });
    gh.actor = 'alice';
    const worker = gh.transport({}, true);
    for (let i = 0; i < 6; i++) {
      gh.time += 60_000;
      await worker.postReport(assigned, {
        ...report(assigned),
        reportId: randomUUID(),
        at: new Date(gh.time).toISOString(),
        kind: 'heartbeat',
      });
      expect(Date.parse((await worker.listTasks())[0].lease!.expiresAt)).toBeGreaterThan(gh.time);
    }
    const incoming = new GitHubTransport(config, {
      api: gh.api,
      now: () => gh.time,
      leadershipMode: 'resume',
    });
    await incoming.acquireLeadership();
    const completed = {
      ...report(assigned),
      reportId: randomUUID(),
      at: new Date(gh.time).toISOString(),
      kind: 'result' as const,
      evidence: [
        {
          kind: 'check' as const,
          at: new Date(gh.time).toISOString(),
          summary: 'Configured check passed',
          exitCode: 0,
        },
      ],
    };
    await worker.postReport(assigned, completed);
    expect(
      (await incoming.listReports()).some((item) => item.reportId === completed.reportId),
    ).toBe(true);
    expect((await incoming.listTasks())[0].lease!.token).toBe(assigned.lease!.token);
    expect((await incoming.getLeadership())?.coordinator).toBe('alice');
  });
  it('ignores a stale mirror scope and rejects the old leader after a mirror-write race', async () => {
    const gh = new FakeGitHub(),
      lead = gh.transport();
    await lead.acquireLeadership();
    const assigned = await lead.publishTask(task());
    let incoming: GitHubTransport;
    gh.onIssuePatch = async () => {
      const cp = (await lead.loadCheckpoint())!;
      await lead.prepareHandoff('agent-a', { ...cp, sequence: cp.sequence + 1 });
      gh.actor = 'alice';
      incoming = new GitHubTransport(config, {
        api: gh.api,
        now: () => gh.time,
        leadershipMode: 'resume',
      });
      await incoming.acquireLeadership();
      const restored = (await incoming.loadCheckpoint())!;
      restored.sequence++;
      restored.actor = 'alice';
      restored.state.tasks[0].state = 'Cancelled';
      await incoming.saveCheckpoint(restored);
      gh.actor = 'lead';
    };
    await expect(lead.publishTask({ ...assigned, state: 'Running' })).rejects.toThrow(
      'leadership lost',
    );
    expect((await incoming!.listTasks())[0].state).toBe('Cancelled');
    const mirror = JSON.parse(gh.issues[0].body.split('```json\n')[1].split('\n```')[0]);
    expect(mirror.state).toBe('Running');
    mirror.allowedPaths = ['outside/authorized/scope'];
    gh.issues[0].body = `<!-- hackathon-kit/task/v1 -->\n\`\`\`json\n${JSON.stringify(mirror)}\n\`\`\``;
    expect((await incoming!.listTasks())[0].allowedPaths).toEqual(['app/ui']);
  });
});
