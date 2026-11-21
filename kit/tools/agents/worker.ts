import { open, mkdir, readFile, writeFile, unlink, lstat } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import {
  ConfigSchema,
  TaskSchema,
  type Config,
  type Task,
  type QueueTransport,
  type WorkerReport,
  type Evidence,
} from './contracts';
import {
  checkResult,
  commandEvidence,
  commitTask,
  inspectTaskDiff,
  runCommand,
  subscriptionEnvironment,
  writeCommandLog,
  type CommandRunner,
} from './runner';

type Receipt = { token: string; phase: 'running' | 'blocked' | 'done'; report?: WorkerReport };
export type WorkerOptions = {
  name: string;
  root?: string;
  signal?: AbortSignal;
  onEvent?: (message: string) => void;
  transport?: QueueTransport;
  runner?: CommandRunner;
  installDependencies?: boolean;
  /** A bounded polling iteration is useful in integration tests and explicit one-shot operation. */
  once?: boolean;
  taskTimeoutMs?: number;
  now?: () => number;
};
const delay = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal?.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal?.addEventListener('abort', done, { once: true });
  });
const message = (error: unknown) =>
  (error instanceof Error ? error.message : String(error))
    .replace(
      /\b(?:gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)\b/g,
      '[redacted]',
    )
    .slice(0, 1600);

export function codexWorkerArgs(config: Config): string[] {
  return [
    'exec',
    '--json',
    '--model',
    config.model,
    '--sandbox',
    'workspace-write',
    '-c',
    'sandbox_workspace_write.network_access=false',
    '-c',
    'model_reasoning_effort="medium"',
    '-c',
    'approval_policy="never"',
    '-c',
    'forced_login_method="chatgpt"',
    '-c',
    'model_provider="openai"',
    '-c',
    'features.multi_agent=false',
    '-c',
    'features.multi_agent_v2=false',
    '-',
  ];
}

/** Give inference no GitHub bearer tokens; deterministic gh commands keep their own environment. */
export function codexEnvironment(env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const clean = subscriptionEnvironment(env);
  for (const key of Object.keys(clean)) {
    if (/^(?:GH|GITHUB)(?:_ENTERPRISE)?_TOKEN$/i.test(key)) delete clean[key];
  }
  return clean;
}

export function taskPrompt(task: Task, contract = task.sharedContract): string {
  const prompt = [
    `Implement task ${task.id}: ${task.title}. Read repository AGENTS.md and scoped instructions.`,
    'You are the sole code-writing root in this isolated worktree. Native children are disabled.',
    'Do not run git add/commit/push, change branches, create PRs, install dependencies, publish, merge, deploy, send messages, or use paid APIs. Deterministic scripts own those actions.',
    `Exclusive writes: ${task.allowedPaths.join(', ')}. Reserved: ${task.reservedPaths.join(', ')}.`,
    'Do not create credential files or modify orchestration controls. Preserve provenance and existing application code.',
    'Keep investigation and output bounded to this task; use relevant files instead of reconstructing the entire repository history.',
    task.description,
    `Acceptance:\n${task.acceptance.map((x) => `- ${x}`).join('\n')}`,
    contract ? `Shared contract:\n${contract}` : '',
    'Make source/test changes only. Report a precise blocker if unable to finish. Your assertion is not verification; the runner validates the actual diff and checks.',
  ]
    .filter(Boolean)
    .join('\n\n');
  if (prompt.length > 64_000)
    throw new Error(
      'Task context exceeds the 64,000-character budget. Split the task or shorten its context before dispatch; no contract text was truncated and no inference started.',
    );
  return prompt;
}

/** Leadership epochs fence coordinators; the existing task token fences this writer. */
export function currentAssignment(
  initial: Task,
  input: Task | undefined,
  worker: string,
  now: number,
): Task {
  const current = input ? TaskSchema.parse(input) : undefined;
  if (
    !current ||
    !initial.lease ||
    !current.lease ||
    current.runId !== initial.runId ||
    current.id !== initial.id ||
    current.assignedWorker !== worker ||
    current.lease?.token !== initial.lease?.token ||
    current.lease?.epoch !== initial.lease?.epoch ||
    current.version < initial.version ||
    Date.parse(current.lease?.expiresAt ?? '') <= now ||
    !['Assigned', 'Running'].includes(current.state)
  )
    throw new Error(
      'Assignment was paused/cancelled, lease expired, or fencing token changed; stopped without commit/push',
    );
  const execution = (task: Task) =>
    JSON.stringify({
      baseSha: task.baseSha,
      branch: task.branch,
      assignedWorker: task.assignedWorker,
      assignmentDecisionId: task.assignmentDecisionId,
      planVersion: task.planVersion,
      title: task.title,
      category: task.category,
      description: task.description,
      sharedContract: task.sharedContract,
      allowedPaths: task.allowedPaths,
      reservedPaths: task.reservedPaths,
      dependencies: task.dependencies,
      acceptance: task.acceptance,
      checkIds: task.checkIds,
      artifacts: task.artifacts,
    });
  if (execution(initial) !== execution(current))
    throw new Error(
      'Active assignment scope, branch, base, checks or shared contract changed; stop and reconcile instead of replacing the writer',
    );
  return current;
}

export async function runWorker(configInput: Config, options: WorkerOptions): Promise<void> {
  const config = ConfigSchema.parse(configInput),
    root = path.resolve(options.root ?? '.');
  const identity = config.workers.find((worker) => worker.name === options.name);
  if (!identity) throw new Error(`Unknown configured worker: ${options.name}`);
  const now = options.now ?? Date.now,
    runner = options.runner ?? runCommand;
  const transport: QueueTransport =
    options.transport ?? new (await import('./github')).GitHubTransport(config, { cwd: root });
  const emit = (text: string) => options.onEvent?.(`${options.name}: ${text}`);
  const stateDir = path.join(root, '.kit', 'agents', 'workers', options.name);
  for (const directory of [
    root,
    path.join(root, '.kit'),
    path.join(root, '.kit', 'agents'),
    path.join(root, '.kit', 'agents', 'workers'),
    stateDir,
    path.join(root, '.kit', 'agents', 'worktrees'),
  ]) {
    if ((await lstat(directory).catch(() => undefined))?.isSymbolicLink())
      throw new Error(`Worker state/worktree directory cannot be a symlink: ${directory}`);
  }
  await mkdir(stateDir, { recursive: true });
  const lockPath = `${stateDir}.lock`,
    nonce = randomUUID();
  let lock;
  try {
    lock = await open(lockPath, 'wx', 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'EEXIST')
      throw new Error(
        `Worker ${options.name} already has a local lock. Stop its previous process and confirm no writer remains before removing ${lockPath}.`,
        { cause: error },
      );
    throw error;
  }
  await lock.writeFile(
    JSON.stringify({
      pid: process.pid,
      nonce,
      runId: config.runId,
      startedAt: new Date(now()).toISOString(),
    }),
  );
  try {
    const login = checkResult(
      await runner('gh', ['api', 'user', '--jq', '.login'], { cwd: root, signal: options.signal }),
    ).stdout.trim();
    if (login.toLowerCase() !== identity.githubLogin.toLowerCase())
      throw new Error(
        `GitHub account mismatch: worker ${options.name} requires ${identity.githubLogin}, current account is ${login}`,
      );
    checkResult(
      await runner('codex', ['login', 'status'], {
        cwd: root,
        signal: options.signal,
        env: codexEnvironment(),
      }),
    );
    const origin = checkResult(
      await runner('git', ['remote', 'get-url', 'origin'], { cwd: root, signal: options.signal }),
    ).stdout.trim();
    if (!originMatches(origin, config.repo))
      throw new Error(`origin must be the configured GitHub repository ${config.repo}`);
    if (config.maxChildren > 0)
      emit(
        'native subagent configuration has not been validated by this runner; falling back to one root with children disabled (cap 0).',
      );
    emit(
      `ready; exact model ${config.model}; local ChatGPT authentication; push/PR ${config.allowPush ? 'enabled by configuration' : 'disabled'}`,
    );
    do {
      if (options.signal?.aborted || now() >= Date.parse(config.deadline)) break;
      const tasks = (await transport.listTasks()).map((task) => TaskSchema.parse(task));
      const assigned = tasks.filter(
        (task) =>
          task.runId === config.runId &&
          task.assignedWorker === options.name &&
          ['Assigned', 'Running'].includes(task.state),
      );
      if (assigned.length > 1)
        throw new Error(
          'Coordinator assigned multiple active code-writing tasks to this worker; refusing all',
        );
      const task = assigned[0];
      if (task) {
        if (!task.lease || Date.parse(task.lease.expiresAt) <= now())
          emit(
            `${task.id}: expired/missing lease; waiting for coordinator confirmation, no writer started`,
          );
        else if (!task.issue)
          emit(`${task.id}: awaiting task/report issue publication; no writer started`);
        else if (
          task.dependencies.some(
            (id) =>
              !tasks.some((candidate) => candidate.id === id && candidate.state === 'Verified'),
          )
        )
          emit(`${task.id}: dependencies lack integrated verification; waiting`);
        else await executeTask(task);
      }
      if (!options.once) await delay(config.pollMs, options.signal);
    } while (!options.once && !options.signal?.aborted);
  } finally {
    await lock.close();
    const current = await readFile(lockPath, 'utf8').catch(() => '');
    if (current.includes(nonce)) await unlink(lockPath);
  }

  async function executeTask(initial: Task) {
    const receiptFile = path.join(stateDir, `${config.runId}-${initial.id}.json`);
    const previous = await readFile(receiptFile, 'utf8')
      .then((raw) => JSON.parse(raw) as Receipt)
      .catch((error: NodeJS.ErrnoException) => {
        if (error.code === 'ENOENT') return undefined;
        throw error;
      });
    if (previous?.token === initial.lease!.token) {
      if (previous.report) await transport.postReport(initial, previous.report);
      if (previous.phase === 'running')
        throw new Error(
          `${initial.id}: previous task process stopped before a result. Worktree retained; confirm old process is stopped and review its checkpoint before coordinator recovery. No duplicate writer started.`,
        );
      return;
    }
    // A different lease never silently reuses an existing worktree or branch.
    const branch = `codex/${config.runId}/${initial.id}`;
    if (initial.branch !== branch)
      throw new Error(`${initial.id}: assigned branch must be ${branch}`);
    const cwd = path.join(root, '.kit', 'agents', 'worktrees', `${config.runId}-${initial.id}`);
    const logs = path.join(stateDir, `${config.runId}-${initial.id}-logs`);
    let latest = initial,
      reportError: unknown,
      stopped = false;
    let lastPayload: WorkerReport | undefined;
    const taskController = new AbortController();
    const abort = () => taskController.abort(options.signal?.reason);
    options.signal?.addEventListener('abort', abort, { once: true });
    const duration = Math.min(
      options.taskTimeoutMs ?? 45 * 60_000,
      Math.max(1, Date.parse(config.deadline) - now()),
    );
    const deadlineTimer = setTimeout(
      () => taskController.abort(new Error('Task/deadline time budget reached')),
      duration,
    );
    let monitorBusy = false,
      timer: ReturnType<typeof setInterval> | undefined;
    let lastHeartbeat = 0;
    const evidence: Evidence[] = [];
    const save = (receipt: Receipt) =>
      writeFile(receiptFile, JSON.stringify(receipt, null, 2) + '\n', { mode: 0o600 });
    const report = async (kind: WorkerReport['kind'], extra: Partial<WorkerReport> = {}) => {
      const payload: WorkerReport = {
        reportId: randomUUID(),
        runId: config.runId,
        taskId: latest.id,
        version: latest.version,
        leaseToken: initial.lease!.token,
        worker: options.name,
        at: new Date(now()).toISOString(),
        kind,
        evidence: [],
        ...extra,
      };
      lastPayload = payload;
      await transport.postReport(latest, payload);
      return payload;
    };
    const fence = async () => {
      if (taskController.signal.aborted) throw new Error('Task cancelled or time budget reached');
      if (reportError) throw new Error(`Task communication lost: ${message(reportError)}`);
      const current = (await transport.listTasks()).find(
        (candidate) => candidate.id === initial.id && candidate.runId === config.runId,
      );
      try {
        latest = currentAssignment(initial, current, options.name, now());
      } catch (error) {
        stopped = true;
        taskController.abort();
        throw error;
      }
    };
    const command = async (name: string, args: string[], timeoutMs = 120_000, input?: string) => {
      const result = await runner(name, args, {
        cwd,
        signal: taskController.signal,
        timeoutMs: Math.min(timeoutMs, duration),
        input,
        env: name === 'codex' ? codexEnvironment() : undefined,
      });
      await writeCommandLog(logs, `${evidence.length}-${name}-${args.join(' ')}`, result);
      return result;
    };
    try {
      await fence();
      if (initial.checkIds.some((id) => !config.checks.some((check) => check.id === id)))
        throw new Error('Task requests an unconfigured check ID; no task process started');
      const prompt = taskPrompt(initial);
      await save({ token: initial.lease!.token, phase: 'running' });
      if (await lstat(cwd).catch(() => undefined))
        throw new Error('Task worktree already exists; retained for explicit human recovery');
      // Fetch only the validated base commit. No mutable upstream branch is substituted.
      checkResult(
        await runner('git', ['fetch', '--no-tags', 'origin', initial.baseSha], {
          cwd: root,
          signal: taskController.signal,
        }),
      );
      checkResult(
        await runner('git', ['worktree', 'add', '-b', branch, cwd, initial.baseSha], {
          cwd: root,
          signal: taskController.signal,
        }),
      );
      await report('started', {
        evidence: [
          {
            kind: 'process',
            summary: `Isolated worktree created on ${branch}`,
            at: new Date(now()).toISOString(),
          },
        ],
      });
      emit(`${initial.id}: process started in isolated worktree`);
      timer = setInterval(
        () => {
          if (monitorBusy) return;
          monitorBusy = true;
          void (async () => {
            try {
              await fence();
              if (now() - lastHeartbeat >= config.heartbeatMs) {
                await report('heartbeat');
                lastHeartbeat = now();
              }
            } catch (error) {
              reportError = error;
              taskController.abort();
            } finally {
              monitorBusy = false;
            }
          })();
        },
        Math.min(config.pollMs, config.heartbeatMs),
      );
      if (!(await lstat(path.join(cwd, 'node_modules')).catch(() => undefined))) {
        if (!options.installDependencies)
          throw new Error(
            'Task worktree has no dependencies; no inference started. Review the retained worktree, confirm the old process is stopped, and cancel/release this task before assigning a new task ID. Start workers with --install-dependencies only after reviewing npm lifecycle scripts, or prepare dependencies manually for explicit manual recovery.',
          );
        if (!(await lstat(path.join(cwd, 'package-lock.json')).catch(() => undefined)))
          throw new Error('Dependency install requires a committed package-lock.json');
        const install = await command('npm', ['ci', '--no-audit', '--no-fund'], 300_000);
        evidence.push(commandEvidence(install));
        await report('checkpoint', { evidence: [commandEvidence(install)] });
        checkResult(install);
      }
      await fence();
      const model = await command('codex', codexWorkerArgs(config), duration, prompt);
      const modelEvidence: Evidence = {
        ...commandEvidence(model),
        kind: 'process',
        summary: `${config.model} task process ${model.exitCode === 0 ? 'completed; validation pending' : 'failed'}`,
      };
      evidence.push(modelEvidence);
      await report('checkpoint', { evidence: [modelEvidence] });
      checkResult(model);
      await fence();
      await inspectTaskDiff(cwd, latest, config, runner);
      for (const id of initial.checkIds) {
        const check = config.checks.find((candidate) => candidate.id === id);
        if (!check) throw new Error(`Task requests unconfigured check ID: ${id}`);
        await fence();
        const result = await command(check.command, check.args, check.timeoutMs);
        const item = commandEvidence(result);
        evidence.push(item);
        await report('checkpoint', { evidence: [item] });
        checkResult(result);
      }
      await fence();
      const result = await commitTask(cwd, latest, config, fence, runner);
      if (!result.sha)
        throw new Error(
          'Task produced no changed files; acceptance needs review instead of an empty success claim',
        );
      evidence.push({
        kind: 'commit',
        at: new Date(now()).toISOString(),
        sha: result.sha,
        summary: `Scoped commit; ${result.files.length} files; configured checks passed`,
      });
      let pr: string | undefined;
      if (config.allowPush) {
        await fence();
        checkResult(await command('git', ['push', '--set-upstream', 'origin', branch]));
        await fence();
        const bodyPath = path.join(logs, 'pr-body.txt');
        await mkdir(logs, { recursive: true });
        await writeFile(
          bodyPath,
          `${initial.description}\n\nTask ${initial.id}; run ${config.runId}.\n\n${evidence
            .filter((item) => item.kind === 'check')
            .map((item) => `- ${item.command}: exit ${item.exitCode}`)
            .join(
              '\n',
            )}\n\nLocal verification only. Merge, deployment and integrated acceptance require human review.\n`,
        );
        const opened = checkResult(
          await command('gh', [
            'pr',
            'create',
            '--repo',
            config.repo,
            '--head',
            branch,
            '--draft',
            '--title',
            `${initial.id}: ${initial.title}`,
            '--body-file',
            bodyPath,
          ]),
        );
        pr = opened.stdout.trim();
        if (
          !new RegExp(
            `^https://github\\.com/${config.repo.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/pull/\\d+$`,
            'i',
          ).test(pr)
        )
          throw new Error(
            'PR creation returned an unexpected URL; reconcile manually before retry',
          );
        evidence.push({
          kind: 'pr',
          summary: 'Draft PR opened; CI/integration pending',
          url: pr,
          at: new Date(now()).toISOString(),
        });
      }
      const payload = await report('result', { evidence: evidence.slice(-30), pr });
      await save({ token: initial.lease!.token, phase: 'done', report: payload });
      emit(
        `${initial.id}: local checks and scoped commit completed${pr ? `; ${pr}` : '; push disabled, commit retained locally'}`,
      );
    } catch (error) {
      taskController.abort();
      const detail = message(error);
      emit(`${initial.id}: ${detail}`);
      let payload: WorkerReport | undefined;
      if (!stopped && !options.signal?.aborted) {
        payload = await report('blocked', {
          evidence: evidence.slice(-30),
          blocker: {
            id: `worker-${initial.id}`.slice(0, 64),
            question: detail,
            recommendation:
              'Inspect the retained worktree and bounded local logs; confirm no old process remains before issuing a fresh fenced task.',
            options: [
              'Review and recover this task explicitly',
              'Cancel this task and continue independent work',
            ],
            attempted: ['One bounded deterministic task attempt; no automatic second writer'],
            impact: 'This task is stopped; other worker scopes may continue.',
          },
        }).catch((reportFailure: unknown) => {
          emit(`blocker only logged locally; GitHub posting failed: ${message(reportFailure)}`);
          return undefined;
        });
        payload ??= lastPayload?.kind === 'blocked' ? lastPayload : undefined;
      }
      await save({ token: initial.lease!.token, phase: 'blocked', report: payload });
    } finally {
      if (timer) clearInterval(timer);
      clearTimeout(deadlineTimer);
      options.signal?.removeEventListener('abort', abort);
    }
  }
}

export function originMatches(origin: string, repo: string): boolean {
  return [
    `https://github.com/${repo}`,
    `https://github.com/${repo}.git`,
    `git@github.com:${repo}`,
    `git@github.com:${repo}.git`,
    `ssh://git@github.com/${repo}`,
    `ssh://git@github.com/${repo}.git`,
  ].some((expected) => origin.toLowerCase() === expected.toLowerCase());
}
