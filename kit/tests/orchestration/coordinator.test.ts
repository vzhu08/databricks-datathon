import { afterEach, describe, expect, it } from 'vitest';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import {
  ConfigSchema,
  PlanSchema,
  TaskSchema,
  type Config,
  type Plan,
  type QueueTransport,
  type Task,
  type WorkerReport,
} from '../../tools/agents/contracts';
import { Coordinator, overlaps, validatePlan } from '../../tools/agents/coordinator';
import type { PrObservation } from '../../tools/agents/ci';

const initialTime = Date.parse('2026-10-24T12:00:00Z');
const base = 'a'.repeat(40),
  mergedSha = 'b'.repeat(40);
const roots: string[] = [],
  open: Coordinator[] = [];
afterEach(async () => {
  for (const coordinator of open.splice(0)) await coordinator.close();
  for (const root of roots.splice(0)) {
    if (!path.basename(root).startsWith('kit-coordinator-test-'))
      throw new Error('Unsafe test cleanup');
    await rm(root, { recursive: true, force: true });
  }
});
function configuration(): Config {
  return ConfigSchema.parse({
    schemaVersion: 1,
    runId: 'demo',
    repo: 'team/project',
    coordinator: 'lead',
    authorizedActors: ['lead'],
    workers: [
      { name: 'a', githubLogin: 'alice' },
      { name: 'b', githubLogin: 'bob' },
      { name: 'c', githubLogin: 'carol' },
    ],
    startedAt: new Date(initialTime).toISOString(),
    deadline: new Date(initialTime + 86_400_000).toISOString(),
    checks: [{ id: 'unit', command: 'npm', args: ['test'] }],
  });
}
function task(id: string, changes: Partial<Task> = {}): Task {
  return TaskSchema.parse({
    id,
    runId: 'demo',
    version: 1,
    planVersion: 1,
    title: id,
    description: `Implement ${id} using the shared contract`,
    allowedPaths: [`src/${id}`],
    baseSha: base,
    acceptance: ['Targeted behavior passes'],
    checkIds: ['unit'],
    updatedAt: new Date(initialTime).toISOString(),
    ...changes,
  });
}
function plan(tasks: Task[], version = 1): Plan {
  return PlanSchema.parse({
    version,
    objective: 'Working source-backed demo',
    rationale:
      'Use existing authored fixtures and independent scopes to deliver an integrated demo early.',
    contract: 'Shared result schema: {text:string}; authored fixture.',
    tasks,
  });
}
class MemoryTransport implements QueueTransport {
  tasks = new Map<string, Task>();
  reports: WorkerReport[] = [];
  held = false;
  renewError = false;
  failPublication = false;
  async acquireLeadership() {
    if (this.held) throw new Error('occupied');
    this.held = true;
  }
  async renewLeadership() {
    if (this.renewError) throw new Error('network unavailable');
  }
  async releaseLeadership() {
    this.held = false;
  }
  async listTasks() {
    return structuredClone([...this.tasks.values()]);
  }
  async listReports() {
    return structuredClone(this.reports);
  }
  async postReport(_task: Task, report: WorkerReport) {
    this.reports.push(structuredClone(report));
  }
  async publishTask(input: Task) {
    if (this.failPublication) {
      this.failPublication = false;
      throw new Error('publication disconnected');
    }
    const previous = this.tasks.get(input.id);
    const next = TaskSchema.parse({
      ...structuredClone(input),
      issue: previous?.issue ?? this.tasks.size + 1,
      version: previous ? Math.max(previous.version, input.version) + 1 : input.version,
    });
    this.tasks.set(next.id, next);
    return structuredClone(next);
  }
}
async function setup(
  options: {
    transport?: MemoryTransport;
    inspectPr?: (task: Task) => Promise<PrObservation>;
    root?: string;
  } = {},
) {
  const testDirectory = path.join(process.cwd(), '.kit', 'coordinator-tests');
  await mkdir(testDirectory, { recursive: true });
  const root = options.root ?? (await mkdtemp(path.join(testDirectory, 'kit-coordinator-test-')));
  if (!roots.includes(root)) roots.push(root);
  const clock = { now: initialTime },
    transport = options.transport ?? new MemoryTransport();
  const coordinator = await Coordinator.open(configuration(), root, {
    allowLocalOnly: true,
    transport,
    now: () => clock.now,
    inspectPr: options.inspectPr,
  });
  await coordinator.start();
  open.push(coordinator);
  return { root, coordinator, clock, transport };
}
function report(
  assigned: Task,
  kind: WorkerReport['kind'],
  at = initialTime,
  changes: Partial<WorkerReport> = {},
): WorkerReport {
  return {
    reportId: randomUUID(),
    runId: assigned.runId,
    taskId: assigned.id,
    version: assigned.version,
    leaseToken: assigned.lease!.token,
    worker: assigned.assignedWorker!,
    at: new Date(at).toISOString(),
    kind,
    evidence: [],
    ...changes,
  };
}
async function dispatch(
  setupResult: Awaited<ReturnType<typeof setup>>,
  tasks: Task[] = [task('one')],
) {
  await setupResult.coordinator.propose(plan(tasks));
  await setupResult.coordinator.approve(1);
  await setupResult.coordinator.tick();
  return setupResult.coordinator.getState().tasks;
}

describe('coordinator plan, ownership and evidence controls', () => {
  it('requires the exact human-approved plan version before dispatching three workers', async () => {
    const s = await setup();
    await s.coordinator.propose(plan([task('one'), task('two'), task('three')]));
    await s.coordinator.tick();
    expect(s.transport.tasks.size).toBe(0);
    await expect(s.coordinator.approve(2)).rejects.toThrow('stale');
    await s.coordinator.approve(1);
    await s.coordinator.tick();
    const tasks = s.coordinator.getState().tasks;
    expect(tasks.map((t) => t.assignedWorker)).toEqual(['a', 'b', 'c']);
    expect(new Set(tasks.map((t) => t.lease?.token)).size).toBe(3);
    expect(tasks.every((t) => t.state === 'Assigned' && !t.evidence.length)).toBe(true);
    expect(
      s.coordinator.getState().events.filter((e) => e.type === 'task-dispatched'),
    ).toHaveLength(3);
    expect(s.coordinator.getState().events.some((e) => e.type === 'worker-started')).toBe(false);
  });
  it('validates DAG dependencies, duplicate IDs, check IDs, reserved paths and protected state paths', () => {
    const config = configuration();
    expect(() => validatePlan(plan([task('one', { dependencies: ['missing'] })]), config)).toThrow(
      'Missing dependency',
    );
    expect(() =>
      validatePlan(
        plan([task('one', { dependencies: ['two'] }), task('two', { dependencies: ['one'] })]),
        config,
      ),
    ).toThrow('cycle');
    expect(() => validatePlan(plan([task('one'), task('one')]), config)).toThrow('Duplicate');
    expect(() =>
      validatePlan(plan([task('one', { checkIds: ['shell-comment'] })]), config),
    ).toThrow('Unknown check');
    for (const name of [
      'package.json',
      'packages/contracts/schema.json',
      '.github/workflows/check.yml',
    ])
      expect(() => validatePlan(plan([task('one', { allowedPaths: [name] })]), config)).toThrow(
        'Reserved path',
      );
    for (const name of ['.kit/private', 'src/.env.local', '.ssh/key'])
      expect(() => validatePlan(plan([task('one', { allowedPaths: [name] })]), config)).toThrow(
        'Protected path',
      );
  });
  it('treats directory overlap conservatively across teammate operating systems', async () => {
    expect(overlaps('src/UI', 'src/ui/button.ts')).toBe(true);
    expect(overlaps('src/ui', 'src/ui-next')).toBe(false);
    const s = await setup();
    await dispatch(s, [
      task('one', { allowedPaths: ['src/UI'] }),
      task('two', { allowedPaths: ['src/ui/button.ts'] }),
      task('three'),
    ]);
    expect(s.coordinator.getState().tasks.map((t) => t.state)).toEqual([
      'Assigned',
      'Planned',
      'Assigned',
    ]);
  });
  it('rejects fabricated new task evidence and a replan that modifies an active writer', async () => {
    const s = await setup();
    await expect(
      s.coordinator.propose(
        plan([
          task('one', {
            evidence: [
              {
                kind: 'check',
                summary: 'invented',
                at: new Date(initialTime).toISOString(),
                exitCode: 0,
              },
            ],
          }),
        ]),
      ),
    ).rejects.toThrow('fabricated');
    await dispatch(s, [task('one'), task('future', { dependencies: ['one'] })]);
    await expect(
      s.coordinator.propose(plan([task('one', { title: 'Replace running work' })], 2)),
    ).rejects.toThrow('preserve active task');
    const retained = s.coordinator.getState().tasks;
    const revised = plan([...retained, task('new', { planVersion: 2 })], 2);
    revised.contract = 'Revised shared contract for future tasks';
    await s.coordinator.propose(revised);
    expect(s.coordinator.getState().tasks.find((t) => t.id === 'future')?.sharedContract).toBe(
      revised.contract,
    );
    expect(s.coordinator.getState().tasks.find((t) => t.id === 'one')?.sharedContract).not.toBe(
      revised.contract,
    );
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks.find((t) => t.id === 'new')?.state).toBe('Planned');
  });
  it('applies process evidence without equating heartbeats with code progress', async () => {
    const s = await setup(),
      [assigned] = await dispatch(s);
    s.transport.reports.push(report(assigned, 'heartbeat', initialTime + 60_000));
    s.clock.now += 60_000;
    await s.coordinator.tick();
    const current = s.coordinator.getState().tasks[0];
    expect(current.state).toBe('Assigned');
    expect(current.evidence).toEqual([]);
    expect(Date.parse(current.lease!.expiresAt)).toBe(s.clock.now + configuration().leaseMs);
    expect(s.coordinator.getState().events.some((e) => e.type === 'worker-heartbeat')).toBe(false);
    s.transport.reports.push(
      report(current, 'started', s.clock.now, {
        evidence: [
          { kind: 'process', summary: 'Worktree created', at: new Date(s.clock.now).toISOString() },
        ],
      }),
    );
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[0].state).toBe('Running');
  });
  it('emits one deterministic five-minute snapshot during active work', async () => {
    const s = await setup();
    await dispatch(s);
    s.clock.now += 299_999;
    await s.coordinator.tick();
    expect(s.coordinator.getState().events.filter((e) => e.type === 'status')).toHaveLength(0);
    s.clock.now++;
    await s.coordinator.tick();
    await s.coordinator.tick();
    const statuses = s.coordinator.getState().events.filter((e) => e.type === 'status');
    expect(statuses).toHaveLength(1);
    const snapshot = JSON.parse(statuses[0].message);
    expect(snapshot.workers).toHaveLength(3);
    expect(snapshot.objective).toBe('Working source-backed demo');
    expect(snapshot.remainingMinutes).toBe(1435);
    expect(snapshot.workers[0].lastVerified).toBeUndefined();
  });
  it('surfaces and deduplicates actionable blockers immediately while other workers continue', async () => {
    const s = await setup(),
      [assigned] = await dispatch(s, [task('one'), task('two')]);
    const blocked = report(assigned, 'blocked', initialTime, {
      blocker: {
        id: 'fixture-choice',
        question: 'Which fixture may be used?',
        recommendation: 'Use authored fixture',
        options: ['Use authored fixture', 'Supply licensed sample'],
        attempted: ['Checked current samples'],
        impact: 'one is stopped; two continues',
      },
    });
    s.transport.reports.push(blocked, blocked);
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks.map((t) => t.state)).toEqual(['Blocked', 'Assigned']);
    expect(s.coordinator.getState().events.filter((e) => e.type === 'worker-blocked')).toHaveLength(
      1,
    );
    expect((s.coordinator.status() as { blockers: unknown[] }).blockers).toHaveLength(1);
    await s.coordinator.resolve('one', 'fixture-choice', 'Use authored fixture');
    expect((s.coordinator.status() as { blockers: unknown[] }).blockers).toHaveLength(0);
    expect(s.coordinator.getState().tasks[0].state).toBe('Blocked');
  });
  it('ignores reports carrying another worker, run or fencing token', async () => {
    const s = await setup(),
      [assigned] = await dispatch(s);
    s.transport.reports.push(
      report(assigned, 'started', initialTime, { worker: 'b' }),
      report(assigned, 'started', initialTime, { runId: 'other' }),
      report(assigned, 'started', initialTime, { leaseToken: randomUUID() }),
    );
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[0].state).toBe('Assigned');
  });
  it('retains paused/cancelled scopes and never reassigns an expired writer automatically', async () => {
    const s = await setup(),
      [assigned] = await dispatch(s, [
        task('one'),
        task('two', { allowedPaths: ['src/one/file.ts'] }),
      ]);
    await s.coordinator.action('pause', 'one');
    s.clock.now += configuration().leaseMs + 1;
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[0].lease?.token).toBe(assigned.lease?.token);
    expect(s.coordinator.getState().tasks[1].state).toBe('Planned');
    await s.coordinator.action('resume', 'one');
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[0].state).toBe('Paused');
    await s.coordinator.action('cancel', 'one');
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[1].state).toBe('Planned');
    await expect(
      s.coordinator.propose(
        plan([task('two', { allowedPaths: ['src/one/file.ts'], planVersion: 2 })], 2),
      ),
    ).rejects.toThrow('preserve active task one');
    await s.coordinator.confirmStopped('one');
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[0].state).toBe('Failed');
    expect(s.coordinator.getState().tasks[0].lease).toBeUndefined();
    expect(s.coordinator.getState().tasks[1].state).toBe('Assigned');
  });
  it('refuses release of an active writer before a pause/cancel request', async () => {
    const s = await setup();
    await dispatch(s);
    await expect(s.coordinator.confirmStopped('one')).rejects.toThrow('Pause or cancel');
  });
  it('pauses dispatch if distributed leadership renewal fails', async () => {
    const s = await setup();
    await s.coordinator.propose(plan([task('one')]));
    await s.coordinator.approve(1);
    s.transport.renewError = true;
    await expect(s.coordinator.tick()).rejects.toThrow('network unavailable');
    expect(s.coordinator.getState().paused).toBe(true);
    expect(s.transport.tasks.size).toBe(0);
  });
  it('replays an interrupted assignment publication after restart without creating another writer', async () => {
    const s = await setup();
    await s.coordinator.propose(plan([task('one')]));
    await s.coordinator.approve(1);
    s.transport.failPublication = true;
    await expect(s.coordinator.tick()).rejects.toThrow('publication disconnected');
    const interrupted = s.coordinator.getState().tasks[0];
    expect(interrupted.state).toBe('Assigned');
    expect(s.transport.tasks.size).toBe(0);
    expect(s.coordinator.getState().pendingPublications).toContain('one');
    await s.coordinator.close();
    const recovered = await setup({ root: s.root, transport: s.transport });
    await recovered.coordinator.tick();
    expect(recovered.coordinator.getState().tasks[0].lease?.token).toBe(interrupted.lease?.token);
    expect(s.transport.tasks.size).toBe(1);
    expect(recovered.coordinator.getState().pendingPublications).toEqual([]);
  });
  it('rejects another local coordinator for the same run without disturbing the active lock', async () => {
    const s = await setup();
    const second = await Coordinator.open(configuration(), s.root, { transport: s.transport });
    await expect(second.start()).rejects.toThrow('already locked');
    await s.coordinator.propose(plan([task('one')]));
    await s.coordinator.approve(1);
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[0].state).toBe('Assigned');
  });
  it('restores conversation IDs, approvals, blockers and contiguous event sequence after restart', async () => {
    const s = await setup(),
      [assigned] = await dispatch(s);
    await s.coordinator.saveThread('thread-123');
    s.transport.reports.push(
      report(assigned, 'blocked', initialTime, {
        blocker: {
          id: 'permission',
          question: 'Approve sample?',
          recommendation: 'Use authored fixture',
          options: ['Use fixture', 'Supply sample'],
          attempted: [],
          impact: 'one stopped',
        },
      }),
    );
    await s.coordinator.tick();
    const before = s.coordinator.getState();
    await s.coordinator.close();
    const restarted = await setup({ root: s.root, transport: s.transport });
    const restored = restarted.coordinator.getState();
    expect(restored.threadId).toBe('thread-123');
    expect(restored.approvedVersion).toBe(1);
    expect(restored.tasks[0].blockers).toEqual(before.tasks[0].blockers);
    expect(restored.events.map((e) => e.seq)).toEqual(restored.events.map((_e, i) => i + 1));
    expect(restored.events.filter((e) => e.type === 'approval-requested')).toHaveLength(1);
    await restarted.coordinator.tick();
    expect(
      restarted.coordinator.getState().events.filter((e) => e.type === 'worker-blocked'),
    ).toHaveLength(1);
  });
  it('keeps CI pass, human merge and integrated verification distinct before releasing dependencies', async () => {
    let observation: PrObservation = {
      url: 'https://github.com/team/project/pull/1',
      headSha: base,
      ci: 'passed',
      summary: 'unit passed',
    };
    const s = await setup({ inspectPr: async () => observation });
    const [assigned] = await dispatch(s, [task('one'), task('two', { dependencies: ['one'] })]);
    s.transport.reports.push(
      report(assigned, 'result', initialTime, {
        pr: observation.url,
        evidence: [
          {
            kind: 'check',
            summary: 'npm test passed',
            command: 'npm test',
            exitCode: 0,
            at: new Date(initialTime).toISOString(),
          },
        ],
      }),
    );
    s.clock.now += 60_000;
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks.map((t) => t.state)).toEqual(['Queued', 'Planned']);
    await expect(s.coordinator.recordIntegrated('one', mergedSha, 'passed')).rejects.toThrow(
      'confirmed merged',
    );
    observation = { ...observation, mergedSha };
    s.clock.now += 60_000;
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks.map((t) => t.state)).toEqual(['Merged', 'Planned']);
    await expect(s.coordinator.recordIntegrated('one', base, 'passed')).rejects.toThrow(
      'confirmed merge commit',
    );
    await s.coordinator.recordIntegrated('one', mergedSha, 'configured checks passed on merge');
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks.map((t) => t.state)).toEqual(['Verified', 'Blocked']);
    expect(s.coordinator.getState().tasks[1].lease).toBeUndefined();
    const replan = s.coordinator
      .getState()
      .tasks.map((t) =>
        t.id === 'two'
          ? { ...t, state: 'Planned' as const, planVersion: 2, baseSha: mergedSha, blockers: [] }
          : t,
      );
    await s.coordinator.propose(plan(replan, 2));
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[1].state).toBe('Planned');
    await s.coordinator.approve(2);
    await s.coordinator.tick();
    expect(s.coordinator.getState().tasks[1].state).toBe('Assigned');
    expect(s.coordinator.getState().tasks[1].baseSha).toBe(mergedSha);
  });
  it('freezes new features in the final three hours while allowing approved fixes and demo verification', async () => {
    const s = await setup();
    s.clock.now = Date.parse(configuration().deadline) - 3 * 3_600_000;
    await dispatch(s, [
      task('feature'),
      task('fix', { category: 'fix' }),
      task('verify', { category: 'verification' }),
      task('demo', { category: 'demo' }),
    ]);
    expect(s.coordinator.getState().tasks.map((t) => t.state)).toEqual([
      'Blocked',
      'Assigned',
      'Assigned',
      'Assigned',
    ]);
    const feature = s.coordinator.getState().tasks[0];
    expect(feature.lease).toBeUndefined();
    expect(feature.blockers[0].question).toContain('Feature freeze');
    expect(
      s.coordinator
        .getState()
        .tasks.slice(1)
        .map((t) => t.assignedWorker),
    ).toEqual(['a', 'b', 'c']);
  });
  it('sends deadline thresholds once and stops new dispatch at the actual entered deadline', async () => {
    const s = await setup();
    await s.coordinator.propose(plan([task('one')]));
    await s.coordinator.approve(1);
    s.clock.now = Date.parse(configuration().deadline);
    await s.coordinator.tick();
    await s.coordinator.tick();
    expect(s.transport.tasks.size).toBe(0);
    expect(
      s.coordinator.getState().events.filter((e) => e.type === 'deadline-notice'),
    ).toHaveLength(5);
  });
});
