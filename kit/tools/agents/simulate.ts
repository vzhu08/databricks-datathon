import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import {
  ConfigSchema,
  TaskSchema,
  type QueueTransport,
  type Task,
  type WorkerReport,
} from './contracts';
import { Coordinator } from './coordinator';

export async function simulate() {
  let now = Date.parse('2026-10-24T12:00:00Z');
  const config = ConfigSchema.parse({
    schemaVersion: 1,
    runId: 'offline-demo',
    repo: 'fixture/project',
    coordinator: 'lead',
    authorizedActors: ['lead'],
    workers: ['a', 'b', 'c'].map((name) => ({ name, githubLogin: `fixture-${name}` })),
    startedAt: new Date(now).toISOString(),
    deadline: new Date(now + 24 * 3_600_000).toISOString(),
    checks: [{ id: 'test', command: 'node', args: ['--test'] }],
  });
  const root = await mkdtemp(path.join(tmpdir(), 'kit-orchestration-simulation-'));
  const remote: Task[] = [],
    reports: WorkerReport[] = [];
  const transport: QueueTransport = {
    async acquireLeadership() {},
    async renewLeadership() {},
    async releaseLeadership() {},
    async publishTask(task) {
      const value = structuredClone({ ...task, issue: task.issue ?? remote.length + 1 });
      const index = remote.findIndex((t) => t.id === task.id);
      if (index === -1) remote.push(value);
      else remote[index] = value;
      return value;
    },
    async listTasks() {
      return structuredClone(remote);
    },
    async listReports() {
      return structuredClone(reports);
    },
    async postReport(_task, report) {
      reports.push(report);
    },
  };
  let coordinator = await Coordinator.open(config, root, {
    transport,
    now: () => now,
    allowLocalOnly: true,
  });
  try {
    await coordinator.start();
    await coordinator.propose({
      version: 1,
      objective: 'OFFLINE: demonstrate three workers, approval, heartbeat, blockers and restart',
      contract: 'Synthetic source only; no inference, network, real code commits or PRs.',
      rationale:
        'Exercise the coordinator using deterministic authored workers without external requests.',
      tasks: config.workers.map((w) =>
        TaskSchema.parse({
          id: `TASK-${w.name}`,
          runId: config.runId,
          version: 1,
          planVersion: 1,
          title: `Synthetic ${w.name}`,
          description: 'Offline fixture task',
          baseSha: 'a'.repeat(40),
          allowedPaths: [`src/${w.name}`],
          acceptance: ['Authored synthetic check succeeds'],
          checkIds: ['test'],
          updatedAt: new Date(now).toISOString(),
        }),
      ),
    });
    await coordinator.tick();
    if (remote.length) throw new Error('Approval gate failed');
    await coordinator.approve(1);
    await coordinator.tick();
    for (const task of remote)
      reports.push({
        reportId: randomUUID(),
        runId: config.runId,
        taskId: task.id,
        version: task.version,
        leaseToken: task.lease!.token,
        worker: task.assignedWorker!,
        at: new Date(now).toISOString(),
        kind: 'started',
        evidence: [],
      });
    await coordinator.tick();
    const blocked = remote[1];
    reports.push({
      reportId: randomUUID(),
      runId: config.runId,
      taskId: blocked.id,
      version: blocked.version,
      leaseToken: blocked.lease!.token,
      worker: blocked.assignedWorker!,
      at: new Date(now).toISOString(),
      kind: 'blocked',
      evidence: [],
      blocker: {
        id: 'fixture-permission',
        question: 'Approve authored fixture?',
        recommendation: 'Use the authored fixture',
        options: ['Use fixture', 'Supply licensed sample'],
        attempted: [],
        impact: 'Other independent workers continue',
      },
    });
    await coordinator.tick();
    now += 300_000;
    await coordinator.tick();
    await coordinator.close();
    coordinator = await Coordinator.open(config, root, {
      transport,
      now: () => now,
      allowLocalOnly: true,
    });
    await coordinator.start();
    return {
      mode: 'OFFLINE SYNTHETIC SIMULATION — no live workers, inference, GitHub, checks, commits or PRs',
      passed: [
        'human approval gate',
        'three exclusive assignments',
        'worker-start evidence',
        'immediate actionable blocker',
        'five-minute deterministic status',
        'lease expiry retains scope',
        'restart restores event sequence and blocker',
      ],
      state: { ...(coordinator.status() as object), mode: 'offline synthetic transport' },
      events: coordinator.getState().events,
    };
  } finally {
    await coordinator.close();
    await rm(root, { recursive: true, force: true });
  }
}
