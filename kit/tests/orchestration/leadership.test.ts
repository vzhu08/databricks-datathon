import { describe, expect, it } from 'vitest';
import { randomUUID } from 'node:crypto';
import { ConfigSchema, TaskSchema, type Task } from '../../tools/agents/contracts';
import { buildCheckpoint } from '../../tools/agents/checkpoint';
import { GitHubControl } from '../../tools/agents/leadership';
import { GitHubTransport, type GitHubApi } from '../../tools/agents/github';
import {
  TAKEOVER_SAFETY_MS,
  type PortableCheckpoint,
  type LeadershipMode,
} from '../../tools/agents/handoff-contracts';

const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'portable',
  repo: 'team/project',
  coordinator: 'lead',
  authorizedActors: ['lead'],
  workers: [
    { name: 'agent-a', githubLogin: 'lead' },
    { name: 'agent-b', githubLogin: 'bob' },
    { name: 'agent-c', githubLogin: 'carol' },
  ],
  startedAt: '2026-10-24T12:00:00Z',
  deadline: '2026-10-25T12:00:00Z',
  checks: [{ id: 'test', command: 'node', args: ['--test'] }],
});
class FakeControl {
  now = Date.parse(config.startedAt);
  next = 1;
  ref?: string;
  failBlob = false;
  failPatchAfterApply = false;
  patchBarrier = false;
  private waiters: (() => void)[] = [];
  blobHook?: () => Promise<void>;
  commits = new Map<string, any>([
    ['base', { message: 'root', tree: { sha: 'tree' }, parents: [] }],
  ]);
  blobs = new Map<string, { content: string; encoding: 'base64'; size: number }>();
  writes: { endpoint: string; input: any }[] = [];
  api(actor: string): GitHubApi {
    return async (endpoint, method, input: any) => {
      if (method !== 'GET') this.writes.push({ endpoint, input });
      if (endpoint === 'user') return { login: actor };
      if (endpoint === 'repos/team/project')
        return { default_branch: 'main', permissions: { push: true } };
      if (endpoint.endsWith('/git/ref/heads/main')) return { object: { sha: 'base' } };
      if (endpoint.includes('/git/ref/heads/codex/')) {
        if (!this.ref) throw Object.assign(new Error('missing'), { status: 404 });
        return { object: { sha: this.ref } };
      }
      if (endpoint.includes('/git/commits/') && method === 'GET')
        return this.commits.get(endpoint.split('/').at(-1)!);
      if (endpoint.endsWith('/git/commits') && method === 'POST') {
        const sha = `commit-${this.next++}`;
        this.commits.set(sha, { ...input, tree: { sha: input.tree } });
        return { sha };
      }
      if (endpoint.endsWith('/git/blobs') && method === 'POST') {
        if (this.failBlob) throw new Error('blob upload disconnected');
        const sha = `blob-${this.next++}`;
        this.blobs.set(sha, { ...input, size: Buffer.from(input.content, 'base64').length });
        if (this.blobHook) {
          const hook = this.blobHook;
          this.blobHook = undefined;
          await hook();
        }
        return { sha };
      }
      if (endpoint.includes('/git/blobs/') && method === 'GET')
        return this.blobs.get(endpoint.split('/').at(-1)!);
      if (endpoint.endsWith('/git/refs') && method === 'POST') {
        if (this.ref) throw Object.assign(new Error('exists'), { status: 422 });
        this.ref = input.sha;
        return { object: { sha: this.ref } };
      }
      if (endpoint.includes('/git/refs/heads/codex/') && method === 'PATCH') {
        if (this.patchBarrier)
          await new Promise<void>((resolve) => {
            this.waiters.push(resolve);
            if (this.waiters.length === 2) {
              this.patchBarrier = false;
              for (const waiter of this.waiters.splice(0)) waiter();
            }
          });
        if (input.force !== false || this.commits.get(input.sha).parents[0] !== this.ref)
          throw Object.assign(new Error('not fast forward'), { status: 422 });
        this.ref = input.sha;
        if (this.failPatchAfterApply) {
          this.failPatchAfterApply = false;
          throw new Error('acknowledgement lost');
        }
        return { object: { sha: this.ref } };
      }
      if (endpoint.includes('/issues?')) return [];
      throw new Error(`Unexpected mock endpoint: ${method} ${endpoint}`);
    };
  }
  control(actor: string, mode: LeadershipMode = 'normal') {
    return new GitHubControl(config, {
      api: this.api(actor),
      now: () => this.now,
      host: `computer-${actor}`,
      leadershipMode: mode,
    });
  }
}
function checkpoint(actor = 'lead'): PortableCheckpoint {
  return buildCheckpoint(
    {
      schemaVersion: 1,
      runId: config.runId,
      paused: false,
      tasks: [],
      events: [],
      seenReports: [],
      notices: [],
      lastStatusAt: Date.parse(config.startedAt),
      context: {
        summary: 'PDF-first source-backed demo; no paid providers',
        requirements: ['Preserve the MVP'],
        priorities: ['Demo path'],
        decisions: [
          {
            id: 'decision-contract',
            kind: 'architecture',
            summary: 'Use shared schema',
            rationale: 'Workers need one stable response contract',
            actor: 'lead',
            at: config.startedAt,
          },
        ],
        answeredQuestions: [{ question: 'PDF or LaTeX first?', answer: 'PDF' }],
        recentMessages: [
          {
            id: 'request-1',
            role: 'user',
            text: 'Keep exports out of the critical path',
            at: config.startedAt,
            status: 'remembered',
          },
        ],
      },
    },
    config,
    actor,
    config.startedAt,
  );
}
function next(cp: PortableCheckpoint, actor: string): PortableCheckpoint {
  return { ...structuredClone(cp), actor, sequence: cp.sequence + 1 };
}
function task(): Task {
  return TaskSchema.parse({
    id: 'TASK-1',
    runId: config.runId,
    version: 1,
    planVersion: 1,
    title: 'Upload UI',
    description: 'Implement the upload UI',
    baseSha: 'a'.repeat(40),
    allowedPaths: ['app/upload'],
    acceptance: ['Test succeeds'],
    checkIds: ['test'],
    updatedAt: config.startedAt,
  });
}
async function assigned(gh: FakeControl, lead: GitHubControl) {
  const first = checkpoint();
  first.state.tasks = [task()];
  await lead.saveCheckpoint(first);
  const decision = next(first, 'lead');
  decision.context.decisions.push({
    id: 'dispatch-1',
    kind: 'dispatch',
    summary: 'Assign upload scope',
    rationale: 'Ready, independent task matches worker availability',
    taskId: 'TASK-1',
    planVersion: 1,
    actor: 'lead',
    at: config.startedAt,
  });
  await lead.saveCheckpoint(decision);
  const cp = next(decision, 'lead');
  cp.state.tasks[0] = {
    ...cp.state.tasks[0],
    state: 'Assigned',
    assignedWorker: 'agent-a',
    assignmentDecisionId: 'dispatch-1',
    branch: 'codex/portable/TASK-1',
    lease: {
      token: randomUUID(),
      epoch: 1,
      expiresAt: new Date(gh.now + config.leaseMs).toISOString(),
    },
  };
  await lead.saveCheckpoint(cp);
  return cp;
}

describe('portable leadership and checkpoints', () => {
  it('hands A to B to C to A with increasing epochs and preserved decisions/context', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    let cp = checkpoint();
    await a.saveCheckpoint(cp);
    let active = a;
    for (const [target, actor, epoch] of [
      ['agent-b', 'bob', 2],
      ['agent-c', 'carol', 3],
      ['agent-a', 'lead', 4],
    ] as const) {
      cp = next(cp, (await active.status())!.coordinator);
      const offer = await active.prepareHandoff(target, cp);
      expect(offer.phase).toBe('handoff');
      expect(offer.epoch).toBe(epoch - 1);
      await expect(active.renew()).rejects.toThrow('leadership lost');
      const receiver = gh.control(actor, 'resume');
      await receiver.acquire();
      expect(await receiver.status()).toMatchObject({
        coordinator: actor,
        epoch,
        phase: 'active',
        host: `computer-${actor}`,
      });
      expect((await receiver.loadCheckpoint())?.context).toEqual(cp.context);
      active = receiver;
    }
  });
  it('rejects a healthy coordinator takeover and a non-designated receiver', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    await expect(gh.control('bob', 'takeover').acquire()).rejects.toThrow('healthy leadership');
    const cp = checkpoint();
    await a.saveCheckpoint(cp);
    await a.prepareHandoff('agent-b', next(cp, 'lead'));
    await expect(gh.control('carol', 'resume').acquire()).rejects.toThrow('designated handoff');
    expect((await a.status())?.epoch).toBe(1);
  });
  it('permits crash recovery only after expiration plus safety margin', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    await a.saveCheckpoint(checkpoint());
    gh.now += config.leaseMs + 1;
    await expect(gh.control('bob', 'takeover').acquire()).rejects.toThrow('safety margin');
    gh.now += TAKEOVER_SAFETY_MS;
    const b = gh.control('bob', 'takeover');
    await b.acquire();
    expect((await b.status())?.epoch).toBe(2);
    expect((await b.loadCheckpoint())?.context.answeredQuestions[0].answer).toBe('PDF');
    await expect(a.renew()).rejects.toThrow('leadership lost');
  });
  it('allows only one of two genuinely concurrent takeover CAS attempts', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    await a.saveCheckpoint(checkpoint());
    gh.now += config.leaseMs + TAKEOVER_SAFETY_MS + 1;
    gh.patchBarrier = true;
    const result = await Promise.allSettled([
      gh.control('bob', 'takeover').acquire(),
      gh.control('carol', 'takeover').acquire(),
    ]);
    expect(result.filter((item) => item.status === 'fulfilled')).toHaveLength(1);
    expect(result.filter((item) => item.status === 'rejected')).toHaveLength(1);
    expect((await a.status())?.epoch).toBe(2);
  });
  it('reconstructs context independently of a native thread or credentials', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = checkpoint();
    await a.saveCheckpoint(cp);
    const bytes = Buffer.from([...gh.blobs.values()][0].content, 'base64').toString();
    expect(bytes).toContain('Workers need one stable response contract');
    for (const field of ['threadId', 'auth.json', 'access_token', 'refresh_token'])
      expect(bytes).not.toContain(field);
    expect(await gh.control('bob').loadCheckpoint()).toEqual(cp);
  });
  it('preserves the last good checkpoint after partial blob failure and rejects corrupted blobs', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = checkpoint();
    await a.saveCheckpoint(cp);
    const priorRef = gh.ref;
    gh.failBlob = true;
    await expect(a.saveCheckpoint(next(cp, 'lead'))).rejects.toThrow('upload disconnected');
    expect(gh.ref).toBe(priorRef);
    gh.failBlob = false;
    expect(await gh.control('bob').loadCheckpoint()).toEqual(cp);
    const pointer = (await a.status())!.checkpoint!;
    gh.blobs.get(pointer.blobSha)!.content = Buffer.from('{}').toString('base64');
    await expect(gh.control('bob').loadCheckpoint()).rejects.toThrow('incomplete or digest');
  });
  it('does not permit a new assignment unless its rationale was committed earlier', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = checkpoint();
    await a.saveCheckpoint(cp);
    const wrong = next(cp, 'lead');
    const work = task();
    work.state = 'Assigned';
    work.assignedWorker = 'agent-a';
    work.lease = { token: randomUUID(), epoch: 1, expiresAt: config.deadline };
    work.assignmentDecisionId = 'dispatch-now';
    wrong.state.tasks.push(work);
    wrong.context.decisions.push({
      id: 'dispatch-now',
      kind: 'dispatch',
      summary: 'Assign',
      rationale: 'Not committed earlier',
      taskId: work.id,
      planVersion: 1,
      actor: 'lead',
      at: config.startedAt,
    });
    await expect(a.saveCheckpoint(wrong)).rejects.toThrow('previously committed');
    expect((await a.loadCheckpoint())?.state.tasks).toEqual([]);
  });
  it('rejects a new lease in a paused checkpoint even after its dispatch decision was committed', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const first = checkpoint();
    first.state.tasks = [task()];
    await a.saveCheckpoint(first);
    const decision = next(first, 'lead');
    decision.context.decisions.push({
      id: 'paused-dispatch',
      kind: 'dispatch',
      summary: 'Assign upload scope',
      rationale: 'Previously approved independent task',
      taskId: 'TASK-1',
      planVersion: 1,
      actor: 'lead',
      at: config.startedAt,
    });
    await a.saveCheckpoint(decision);
    const priorRef = gh.ref;
    const paused = next(decision, 'lead');
    paused.state.paused = true;
    paused.state.tasks[0] = {
      ...paused.state.tasks[0],
      state: 'Assigned',
      assignedWorker: 'agent-a',
      assignmentDecisionId: 'paused-dispatch',
      branch: 'codex/portable/TASK-1',
      lease: {
        token: randomUUID(),
        epoch: 1,
        expiresAt: new Date(gh.now + config.leaseMs).toISOString(),
      },
    };
    await expect(a.saveCheckpoint(paused)).rejects.toThrow('Paused checkpoints cannot authorize');
    expect(gh.ref).toBe(priorRef);
    expect((await a.loadCheckpoint())?.state.tasks[0].state).toBe('Planned');
  });
  it('preserves active task token, epoch, branch, dependencies and completed evidence through handoff', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = await assigned(gh, a);
    cp.state.tasks.push(
      TaskSchema.parse({
        ...task(),
        id: 'DONE',
        state: 'Verified',
        evidence: [
          {
            kind: 'integration',
            summary: 'Confirmed check',
            at: config.startedAt,
            sha: 'b'.repeat(40),
          },
        ],
      }),
    );
    cp.sequence++;
    cp.state.tasks[0].dependencies = [];
    await a.saveCheckpoint(cp);
    await a.prepareHandoff('agent-b', next(cp, 'lead'));
    const b = gh.control('bob', 'resume');
    await b.acquire();
    expect((await b.loadCheckpoint())?.state.tasks).toEqual(cp.state.tasks);
  });
  it('fences an old coordinator that loses leadership while a blob is uploading', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = checkpoint();
    await a.saveCheckpoint(cp);
    const b = gh.control('bob', 'takeover');
    gh.blobHook = async () => {
      gh.now += config.leaseMs + TAKEOVER_SAFETY_MS + 1;
      await b.acquire();
    };
    await expect(a.saveCheckpoint(next(cp, 'lead'))).rejects.toThrow('leadership lost');
    expect((await b.loadCheckpoint())?.sequence).toBe(1);
    expect((await b.status())?.coordinator).toBe('bob');
  });
  it('recovers an ambiguous accepted ref update exactly once without repeating mutation', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = checkpoint();
    gh.failPatchAfterApply = true;
    await a.saveCheckpoint(cp);
    expect((await a.loadCheckpoint())?.sequence).toBe(1);
    expect(gh.writes.filter((write) => write.endpoint.includes('/git/refs/heads/'))).toHaveLength(
      1,
    );
    await a.renew();
  });
  it('rejects stale/out-of-order checkpoints and same-token scope changes', async () => {
    const gh = new FakeControl(),
      a = gh.control('lead');
    await a.acquire();
    const cp = await assigned(gh, a);
    await expect(a.saveCheckpoint(cp)).rejects.toThrow('sequence must increase');
    const changed = next(cp, 'lead');
    changed.state.tasks[0].allowedPaths = ['app/other'];
    await expect(a.saveCheckpoint(changed)).rejects.toThrow('cannot change ownership');
    const dropped = next(cp, 'lead');
    dropped.state.tasks = [];
    await expect(a.saveCheckpoint(dropped)).rejects.toThrow('cannot discard');
  });
  it('rejects sensitive checkpoint content and missing-checkpoint task publication before Issue writes', async () => {
    const gh = new FakeControl(),
      transport = new GitHubTransport(config, { api: gh.api('lead'), now: () => gh.now });
    await transport.acquireLeadership();
    await expect(transport.publishTask(task())).rejects.toThrow('shared checkpoint');
    const cp = checkpoint();
    cp.context.summary = `OPENAI_API_KEY=sk-${'z'.repeat(30)}`;
    await expect(transport.saveCheckpoint(cp)).rejects.toThrow('Sensitive content');
    expect(gh.writes.some((write) => write.endpoint.endsWith('/issues'))).toBe(false);
  });
});
