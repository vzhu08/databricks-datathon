import { describe, it, expect, vi } from 'vitest';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import {
  ConfigSchema,
  TaskSchema,
  type Task,
  type QueueTransport,
  type WorkerReport,
} from '../../tools/agents/contracts';
import {
  runWorker,
  codexWorkerArgs,
  codexEnvironment,
  originMatches,
  taskPrompt,
  currentAssignment,
} from '../../tools/agents/worker';
import type { CommandRunner, CommandResult } from '../../tools/agents/runner';

const sha = 'a'.repeat(40),
  now = Date.parse('2026-10-24T01:00:00Z');
const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'run1',
  repo: 'owner/app',
  coordinator: 'lead',
  authorizedActors: ['lead'],
  workers: [{ name: 'a', githubLogin: 'alice' }],
  startedAt: '2026-10-24T00:00:00Z',
  deadline: '2026-10-25T00:00:00Z',
  checks: [{ id: 'test', command: 'node', args: ['--version'] }],
});
const makeTask = (): Task =>
  TaskSchema.parse({
    id: 'task1',
    runId: 'run1',
    version: 1,
    planVersion: 1,
    title: 'Build feature',
    description: 'A scoped implementation',
    state: 'Assigned',
    assignedWorker: 'a',
    lease: { token: randomUUID(), epoch: 1, expiresAt: '2026-10-24T01:05:00Z' },
    baseSha: sha,
    allowedPaths: ['src'],
    acceptance: ['Works'],
    checkIds: ['test'],
    branch: 'codex/run1/task1',
    issue: 1,
    updatedAt: '2026-10-24T00:00:00Z',
  });
const result = (command: string, args: string[], stdout = ''): CommandResult => ({
  command,
  args,
  stdout,
  stderr: '',
  elapsedMs: 1,
  exitCode: 0,
  timedOut: false,
  truncated: false,
});
const queue = (tasks: Task[], reports: WorkerReport[]): QueueTransport => ({
  acquireLeadership: async () => {},
  renewLeadership: async () => {},
  releaseLeadership: async () => {},
  publishTask: async (task) => task,
  listTasks: async () => tasks,
  listReports: async () => reports,
  postReport: async (_task, report) => {
    reports.push(report);
  },
});

describe('distributed worker', () => {
  it('keeps assignment fences independent of coordinator epochs and rejects in-place scope replacement', () => {
    const initial = makeTask();
    const current = structuredClone(initial);
    current.version += 5;
    current.state = 'Running';
    current.lease!.expiresAt = '2026-10-24T01:10:00Z';
    expect(currentAssignment(initial, current, 'a', now)).toEqual(current);
    for (const change of [
      { allowedPaths: ['another-scope'] },
      { sharedContract: 'a different wire contract' },
      { branch: 'codex/run1/another-task' },
      { baseSha: 'c'.repeat(40) },
      { assignmentDecisionId: 'new-decision' },
      { checkIds: ['unapproved'] },
    ])
      expect(() => currentAssignment(initial, { ...current, ...change }, 'a', now)).toThrow(
        'changed',
      );
    expect(() => currentAssignment(initial, { ...current, state: 'Cancelled' }, 'a', now)).toThrow(
      'paused/cancelled',
    );
    expect(() => currentAssignment(initial, undefined, 'a', now)).toThrow('fencing token');
    expect(() =>
      currentAssignment(
        initial,
        { ...current, lease: { ...current.lease!, expiresAt: '2026-10-24T00:00:00Z' } },
        'a',
        now,
      ),
    ).toThrow('lease expired');
  });
  it('preserves the complete shared contract and rejects oversized context before inference', () => {
    const task = makeTask();
    task.sharedContract = 'Authoritative approved wire contract';
    expect(taskPrompt(task)).toContain(task.sharedContract);
    task.description = 'd'.repeat(12_000);
    task.sharedContract = 'c'.repeat(16_000);
    task.acceptance = Array.from({ length: 20 }, () => 'a'.repeat(2000));
    expect(() => taskPrompt(task)).toThrow('64,000-character budget');
  });
  it('preserves exact model, disables unvalidated children, and accepts only exact repository remotes', () => {
    const args = codexWorkerArgs(config);
    expect(args).toContain('gpt-6-astra');
    expect(args).toContain('forced_login_method="chatgpt"');
    expect(args).toContain('features.multi_agent=false');
    expect(args).toContain('features.multi_agent_v2=false');
    expect(args).toContain('sandbox_workspace_write.network_access=false');
    expect(originMatches('git@github.com:owner/app.git', config.repo)).toBe(true);
    expect(originMatches('https://github.com.evil.test/owner/app.git', config.repo)).toBe(false);
    expect(originMatches('https://github.com/owner/another', config.repo)).toBe(false);
  });
  it('scrubs GitHub bearer tokens only for the inference process without mutating its parent environment', () => {
    const env = {
      PATH: 'bin',
      GH_TOKEN: 'gh',
      GITHUB_TOKEN: 'github',
      GH_ENTERPRISE_TOKEN: 'enterprise',
      GITHUB_ENTERPRISE_TOKEN: 'enterprise2',
      OPENAI_API_KEY: 'key',
      CODEX_HOME: 'local',
    };
    expect(codexEnvironment(env)).toEqual({ PATH: 'bin', CODEX_HOME: 'local' });
    expect(env.GH_TOKEN).toBe('gh');
    expect(env.GITHUB_TOKEN).toBe('github');
  });
  it('does not infer or write when there are no assignments', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-empty-')),
      calls: string[][] = [];
    try {
      const runner: CommandRunner = async (command, args) => {
        calls.push([command, ...args]);
        return result(
          command,
          args,
          command === 'gh'
            ? 'alice'
            : command === 'git'
              ? 'https://github.com/owner/app.git'
              : 'Logged in using ChatGPT',
        );
      };
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport: queue([], []),
        runner,
        once: true,
        now: () => now,
      });
      expect(calls.some((call) => call.includes('exec'))).toBe(false);
      expect(calls.some((call) => call.includes('worktree'))).toBe(false);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('waits without a worktree or receipt until the authoritative assignment has a report issue', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-await-issue-'));
    const calls: string[][] = [],
      reports: WorkerReport[] = [],
      task = makeTask(),
      events: string[] = [];
    task.issue = undefined;
    const runner: CommandRunner = async (command, args) => {
      calls.push([command, ...args]);
      if (args[0] === 'worktree') await mkdir(args[4], { recursive: true });
      return result(
        command,
        args,
        command === 'gh' ? 'alice' : args[0] === 'remote' ? 'https://github.com/owner/app.git' : '',
      );
    };
    try {
      const transport = queue([task], reports);
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => now,
        onEvent: (event) => events.push(event),
      });
      expect(events.some((event) => event.includes('awaiting task/report issue'))).toBe(true);
      expect(calls.some((call) => call.includes('worktree') || call.includes('exec'))).toBe(false);
      expect(reports).toEqual([]);
      await expect(
        readFile(path.join(temp, '.kit/agents/workers/a/run1-task1.json')),
      ).rejects.toMatchObject({ code: 'ENOENT' });
      task.issue = 1;
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => now,
      });
      expect(calls.filter((call) => call.includes('worktree'))).toHaveLength(1);
      expect(reports[0].kind).toBe('started');
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('blocks missing dependencies before inference and never starts a second writer after restart', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-deps-')),
      calls: string[][] = [],
      reports: WorkerReport[] = [];
    const task = makeTask();
    try {
      const runner: CommandRunner = async (command, args) => {
        calls.push([command, ...args]);
        if (args[0] === 'worktree') await mkdir(args[4], { recursive: true });
        return result(
          command,
          args,
          command === 'gh'
            ? 'alice'
            : args[0] === 'remote'
              ? 'https://github.com/owner/app.git'
              : '',
        );
      };
      const transport = queue([task], reports);
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => now,
      });
      expect(reports.map((report) => report.kind)).toEqual(['started', 'blocked']);
      expect(reports[1].blocker?.question).toContain('--install-dependencies');
      expect(calls.some((call) => call.includes('exec'))).toBe(false);
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => now,
      });
      expect(calls.filter((call) => call.includes('worktree')).length).toBe(1);
      expect(reports[2].reportId).toBe(reports[1].reportId);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('refuses mismatched local identity, duplicate local workers and multiple assignments', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-lock-'));
    try {
      const wrong: CommandRunner = async (command, args) => result(command, args, 'mallory');
      await expect(
        runWorker(config, {
          name: 'a',
          root: temp,
          transport: queue([], []),
          runner: wrong,
          once: true,
          now: () => now,
        }),
      ).rejects.toThrow('account mismatch');
      const runner: CommandRunner = async (command, args) =>
        result(
          command,
          args,
          command === 'gh'
            ? 'alice'
            : args[0] === 'remote'
              ? 'https://github.com/owner/app.git'
              : '',
        );
      await expect(
        runWorker(config, {
          name: 'a',
          root: temp,
          transport: queue([makeTask(), { ...makeTask(), id: 'task2' }], []),
          runner,
          once: true,
          now: () => now,
        }),
      ).rejects.toThrow('multiple');
      const lock = path.join(temp, '.kit/agents/workers/a.lock');
      await writeFile(lock, 'existing');
      await expect(
        runWorker(config, {
          name: 'a',
          root: temp,
          transport: queue([], []),
          runner,
          once: true,
          now: () => now,
        }),
      ).rejects.toThrow('already has a local lock');
      expect(await readFile(lock, 'utf8')).toBe('existing');
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('does not start expired leases or dependencies that are merely merged', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-lease-')),
      calls: string[][] = [];
    try {
      const runner: CommandRunner = async (command, args) => {
        calls.push(args);
        return result(
          command,
          args,
          command === 'gh'
            ? 'alice'
            : args[0] === 'remote'
              ? 'https://github.com/owner/app.git'
              : '',
        );
      };
      const task = makeTask();
      task.lease!.expiresAt = '2026-10-24T00:00:00Z';
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport: queue([task], []),
        runner,
        once: true,
        now: () => now,
      });
      const waiting = makeTask();
      waiting.dependencies = ['dep'];
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport: queue(
          [waiting, { ...makeTask(), id: 'dep', assignedWorker: undefined, state: 'Merged' }],
          [],
        ),
        runner,
        once: true,
        now: () => now,
      });
      expect(calls.some((call) => call.includes('worktree'))).toBe(false);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('runs scoped implementation/check/commit/push/PR as distinct deterministic stages', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-success-')),
      calls: string[][] = [],
      reports: WorkerReport[] = [];
    const task = makeTask();
    let committed = false;
    try {
      const runner: CommandRunner = async (command, args, options) => {
        calls.push([command, ...args]);
        if (command === 'gh')
          return result(
            command,
            args,
            args[0] === 'pr' ? 'https://github.com/owner/app/pull/1' : 'alice',
          );
        if (command === 'codex' && args[0] === 'exec') {
          expect(options.input).toContain('Do not run git add/commit/push');
          await writeFile(path.join(options.cwd, 'src/feature.ts'), 'export const works = true;');
        }
        if (args[0] === 'worktree') {
          await mkdir(path.join(args[4], 'node_modules'), { recursive: true });
          await mkdir(path.join(args[4], 'src'));
        }
        if (args.includes('commit')) committed = true;
        let stdout = '';
        if (args[0] === 'remote') stdout = 'https://github.com/owner/app.git';
        if (args[0] === 'branch') stdout = task.branch!;
        if (args[0] === 'diff') stdout = 'src/feature.ts\0';
        if (args[0] === 'rev-parse') stdout = committed ? 'b'.repeat(40) : sha;
        if (args[0] === 'show') stdout = 'export const works = true;';
        return result(command, args, stdout);
      };
      await runWorker(
        { ...config, allowPush: true },
        {
          name: 'a',
          root: temp,
          transport: queue([task], reports),
          runner,
          once: true,
          now: () => now,
        },
      );
      expect(reports.at(-1)?.kind).toBe('result');
      expect(reports.at(-1)?.pr).toBe('https://github.com/owner/app/pull/1');
      expect(reports.at(-1)?.evidence.map((e) => e.kind)).toEqual([
        'process',
        'check',
        'commit',
        'pr',
      ]);
      expect(calls.findIndex((call) => call[0] === 'node')).toBeLessThan(
        calls.findIndex((call) => call.includes('commit')),
      );
      expect(calls.findIndex((call) => call.includes('commit'))).toBeLessThan(
        calls.findIndex((call) => call.includes('push')),
      );
      expect(calls.find((call) => call[1] === 'add')).toEqual([
        'git',
        'add',
        '--',
        'src/feature.ts',
      ]);
      expect(calls.some((call) => call.includes('merge') || call.includes('deploy'))).toBe(false);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('keeps one model process and its result through consecutive handoffs while authenticated heartbeats preserve reachability', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-handoff-'));
    const task = makeTask(),
      reports: WorkerReport[] = [],
      calls: string[][] = [];
    const originalToken = task.lease!.token,
      originalBranch = task.branch;
    let clock = now,
      epoch = 1,
      phase: 'active' | 'handoff' = 'active',
      committed = false;
    let modelStarted!: () => void, finishModel!: () => void;
    const started = new Promise<void>((resolve) => {
      modelStarted = resolve;
    });
    const finish = new Promise<void>((resolve) => {
      finishModel = resolve;
    });
    const transport = queue([task], reports);
    transport.getLeadership = async () => ({
      schemaVersion: 2,
      runId: config.runId,
      epoch,
      owner: '11111111-1111-4111-8111-111111111111',
      coordinator: epoch === 1 ? 'lead' : epoch === 2 ? 'bob' : 'carol',
      host: `computer-${epoch}`,
      expiresAt: clock + 300_000,
      phase,
    });
    transport.listTasks = async () => {
      const current = structuredClone(task);
      const live = reports.filter(
        (r) =>
          r.worker === 'a' &&
          r.leaseToken === originalToken &&
          ['started', 'heartbeat', 'checkpoint'].includes(r.kind),
      );
      current.lease!.expiresAt = new Date(
        Math.max(
          Date.parse(current.lease!.expiresAt),
          ...live.map((r) => Date.parse(r.at) + config.leaseMs),
        ),
      ).toISOString();
      return [current];
    };
    const runner: CommandRunner = async (command, args, options) => {
      calls.push([command, ...args]);
      if (command === 'gh') return result(command, args, 'alice');
      if (args[0] === 'worktree') {
        await mkdir(path.join(args[4], 'node_modules'), { recursive: true });
        await mkdir(path.join(args[4], 'src'));
      }
      if (command === 'codex' && args[0] === 'exec') {
        modelStarted();
        await finish;
        expect(options.signal?.aborted).toBe(false);
        await writeFile(path.join(options.cwd, 'src/feature.ts'), 'export const continued = true;');
      }
      if (args.includes('commit')) committed = true;
      let stdout = '';
      if (args[0] === 'remote') stdout = 'https://github.com/owner/app.git';
      if (args[0] === 'branch') stdout = originalBranch!;
      if (args[0] === 'diff') stdout = 'src/feature.ts\0';
      if (args[0] === 'rev-parse') stdout = committed ? 'b'.repeat(40) : sha;
      if (args[0] === 'show') stdout = 'export const continued = true;';
      return result(command, args, stdout);
    };
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
    let run: Promise<void> | undefined;
    try {
      run = runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => clock,
      });
      await started;
      phase = 'handoff';
      for (let tick = 0; tick < 28; tick++) {
        clock += 15_000;
        if (tick === 4) {
          epoch = 2;
          phase = 'active';
        }
        if (tick === 12) phase = 'handoff';
        if (tick === 16) {
          epoch = 3;
          phase = 'active';
        }
        await vi.advanceTimersByTimeAsync(15_000);
      }
      expect(clock).toBeGreaterThan(Date.parse(task.lease!.expiresAt));
      expect(reports.some((r) => r.kind === 'heartbeat')).toBe(true);
      finishModel();
      await run;
      expect(calls.filter((c) => c[0] === 'codex' && c[1] === 'exec')).toHaveLength(1);
      expect(calls.filter((c) => c[1] === 'worktree')).toHaveLength(1);
      expect(reports.at(-1)?.kind).toBe('result');
      expect(reports.at(-1)?.leaseToken).toBe(originalToken);
      expect(reports.at(-1)?.evidence.some((e) => e.kind === 'commit')).toBe(true);
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => clock,
      });
      expect(calls.filter((c) => c[0] === 'codex' && c[1] === 'exec')).toHaveLength(1);
      expect(reports.at(-1)?.reportId).toBe(reports.at(-2)?.reportId);
    } finally {
      finishModel();
      await run;
      vi.useRealTimers();
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('stops after lease revocation before checks, commits or pushes', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-revoke-')),
      calls: string[][] = [],
      reports: WorkerReport[] = [];
    const task = makeTask();
    try {
      const runner: CommandRunner = async (command, args) => {
        calls.push([command, ...args]);
        if (args[0] === 'worktree')
          await mkdir(path.join(args[4], 'node_modules'), { recursive: true });
        if (args[0] === 'exec') task.lease!.token = randomUUID();
        return result(
          command,
          args,
          command === 'gh'
            ? 'alice'
            : args[0] === 'remote'
              ? 'https://github.com/owner/app.git'
              : '',
        );
      };
      const transport = queue([task], reports);
      // listTasks uses copies, as actual JSON transport does: the initial token is retained by the worker.
      transport.listTasks = async () => structuredClone([task]);
      await runWorker(config, {
        name: 'a',
        root: temp,
        transport,
        runner,
        once: true,
        now: () => now,
      });
      expect(reports.at(-1)?.kind).not.toBe('result');
      expect(
        calls.some(
          (call) => call.includes('commit') || call.includes('push') || call[0] === 'node',
        ),
      ).toBe(false);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('never commits or pushes when a configured check fails', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-worker-check-')),
      calls: string[][] = [],
      reports: WorkerReport[] = [];
    const task = makeTask();
    try {
      const runner: CommandRunner = async (command, args, options) => {
        calls.push([command, ...args]);
        if (args[0] === 'worktree') {
          await mkdir(path.join(args[4], 'node_modules'), { recursive: true });
          await mkdir(path.join(args[4], 'src'));
        }
        if (args[0] === 'exec') await writeFile(path.join(options.cwd, 'src/a.ts'), 'safe');
        if (command === 'node')
          return { ...result(command, args), exitCode: 1, stderr: 'fixture assertion failed' };
        return result(
          command,
          args,
          command === 'gh'
            ? 'alice'
            : args[0] === 'remote'
              ? 'https://github.com/owner/app.git'
              : args[0] === 'branch'
                ? task.branch
                : args[0] === 'diff'
                  ? 'src/a.ts\0'
                  : '',
        );
      };
      await runWorker(
        { ...config, allowPush: true },
        {
          name: 'a',
          root: temp,
          transport: queue([task], reports),
          runner,
          once: true,
          now: () => now,
        },
      );
      expect(reports.at(-1)?.kind).toBe('blocked');
      expect(reports.at(-1)?.evidence.some((e) => e.kind === 'check' && e.exitCode === 1)).toBe(
        true,
      );
      expect(calls.some((call) => call.includes('commit') || call.includes('push'))).toBe(false);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
});
