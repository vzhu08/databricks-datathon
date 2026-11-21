#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { readFile, writeFile, unlink, lstat } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { ConfigSchema, PlanSchema, MODEL, type Config } from './contracts';
import { Coordinator } from './coordinator';
import { GitHubTransport, ghApi } from './github';
import { runWorker } from './worker';
import { runCommand } from './runner';
import { runChat } from './chat';
import { AppServer } from './app-server';
import { simulate } from './simulate';
import { inspectPullRequest } from './ci';
import { verifyIntegrated } from './integration';
import { hostname } from 'node:os';
import { archiveInterruptedHandoff, enqueueHandoff, handoffReceipt } from './handoff-request';
import { coordinatorActors, TAKEOVER_SAFETY_MS, type LeadershipMode } from './handoff-contracts';

const print = (value: unknown) =>
  console.log(typeof value === 'string' ? value : JSON.stringify(value, null, 2));
const help = `Optional distributed Codex orchestration (no service starts on installation).
agents init --repo OWNER/PROJECT --workers a:github-a,b:github-b,c:github-c
  --coordinator GITHUB_LOGIN --deadline 2026-10-25T12:00:00-04:00 [--allow-push]
agents doctor [--live-model] [--name a]
agents chat [--recover-stopped]
agents handoff --to agent-b                 # offer; existing workers continue
agents coordinate --resume [--name agent-b] # designated successor acquires
agents takeover [--name agent-c]            # expired lease + 60-second margin
agents worker --name a [--install-dependencies]
agents status | timeline [--since ISO] | blockers
agents plan --file plan.json | approve --version N | reject --version N
agents pause | resume | cancel [--task TASK]
agents release --task TASK --confirm-stopped  # revoke only after old process is stopped
agents verify --task TASK --sha MERGE_SHA [--install-dependencies]
agents recover --confirm-stopped   # local stale lock only; does not reassign scopes
agents simulate --offline
Common: --root PATH --config PATH. Run control commands in the active chat with /pause,
/resume, /cancel TASK, /approve N, /reject N, /status. Separate CLI mutation commands
require no active local coordinator, except handoff uses its local request inbox. Init is local; chat dispatches approved tasks via
GitHub; workers use their own Codex/gh logins. Merge/deploy always remain human gates.`;

async function configAt(root: string, name: string) {
  return ConfigSchema.parse(JSON.parse(await readFile(path.resolve(root, name), 'utf8')));
}
async function requestLocalHandoff(config: Config, root: string, successor: string) {
  const transport = new GitHubTransport(config, { cwd: root });
  const status = await transport.getLeadership();
  const actor = ((await ghApi(root)('user', 'GET')) as { login: string }).login;
  if (!coordinatorActors(config).includes(actor.toLowerCase()))
    throw new Error('Current GitHub account is not an eligible coordinator');
  if (status && status.coordinator.toLowerCase() !== actor.toLowerCase())
    throw new Error('Issue handoff on the computer/account currently coordinating');
  const target =
    config.workers.find((worker) => worker.name === successor)?.githubLogin ?? successor;
  if (!coordinatorActors(config).includes(target.toLowerCase()))
    throw new Error('Successor is not a configured teammate');
  if (status?.phase === 'handoff') {
    if (status.successor?.toLowerCase() !== target.toLowerCase())
      throw new Error('A different successor offer is pending; reconcile it rather than overwrite');
    print({
      status: 'offered',
      completed: false,
      successor: target,
      epoch: status.epoch,
      next: 'Receiver: npm run agents -- coordinate --resume',
    });
    return;
  }
  const lockPath = path.join(root, '.kit', 'orchestration', config.runId, 'coordinator.lock');
  const lock = await lstat(lockPath).catch((error) => {
    if (error.code !== 'ENOENT') throw error;
  });
  if (lock?.isSymbolicLink()) throw new Error('Coordinator lock cannot be a symlink');
  if (lock) {
    const request = await enqueueHandoff(root, config.runId, successor, actor);
    print({
      status: 'requested locally',
      completed: false,
      next: 'Waiting for the active coordinator to checkpoint context and offer leadership.',
    });
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      const receipt = await handoffReceipt(root, config.runId, request.id);
      if (receipt) {
        print({
          ...receipt,
          completed: false,
          next: 'Receiver: npm run agents -- coordinate --resume',
        });
        if (receipt.status === 'rejected') process.exitCode = 1;
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const observed = await transport.getLeadership();
    if (
      observed?.phase === 'handoff' &&
      observed.successor?.toLowerCase() === target.toLowerCase()
    ) {
      print({
        status: 'offered',
        completed: false,
        successor: target,
        warning: 'Shared authority confirms the offer; the local receipt was unavailable.',
        next: 'Receiver: npm run agents -- coordinate --resume',
      });
      return;
    }
    if (
      status &&
      observed?.phase === 'active' &&
      observed.coordinator.toLowerCase() === target.toLowerCase() &&
      observed.epoch > status.epoch
    ) {
      print({
        status: 'receiver acquired leadership',
        completed: true,
        successor: target,
        epoch: observed.epoch,
      });
      return;
    }
    throw new Error(
      'Local handoff receipt timed out; transfer is not confirmed. Inspect status and the old coordinator before retrying.',
    );
  }
  if (status?.phase === 'active' && status.expiresAt > Date.now())
    throw new Error(
      'An active coordinator exists but its local inbox is unavailable; run handoff on that computer',
    );
  const coordinator = await Coordinator.open(config, root, { transport });
  await coordinator.start();
  try {
    print(await coordinator.handoff(successor));
  } finally {
    await coordinator.close();
  }
}
async function doctor(
  root: string,
  config: Config | undefined,
  live: boolean,
  workerName?: string,
) {
  const checks: { name: string; ok: boolean; detail: string }[] = [];
  for (const [name, command, args] of [
    ['node', 'node', ['--version']],
    ['git', 'git', ['--version']],
    ['gh', 'gh', ['--version']],
    ['codex', 'codex', ['--version']],
    ['codex-auth', 'codex', ['login', 'status']],
    ['git-repository', 'git', ['rev-parse', '--show-toplevel']],
  ] as const) {
    try {
      const result = await runCommand(command, [...args], { cwd: root, timeoutMs: 30_000 });
      const stdout = result.stdout ?? '',
        stderr = result.stderr ?? '';
      let ok = result.exitCode === 0;
      if (name === 'codex') {
        const match = `${stdout} ${stderr}`.match(/(\d+)\.(\d+)\.(\d+)/);
        ok = ok && !!match && (Number(match[1]) > 0 || Number(match[2]) >= 153);
      }
      checks.push({ name, ok, detail: (stdout || stderr).slice(0, 500) });
    } catch (error) {
      checks.push({ name, ok: false, detail: String(error) });
    }
  }
  try {
    const api = ghApi(root);
    const user = (await api('user', 'GET')) as { login: string };
    const expected = workerName
      ? config?.workers.find((w) => w.name === workerName)?.githubLogin
      : config?.coordinator;
    checks.push({
      name: 'github-identity',
      ok: !expected || expected.toLowerCase() === user.login.toLowerCase(),
      detail: user.login,
    });
    if (config) {
      const repo = (await api(`repos/${config.repo}`, 'GET')) as {
        permissions?: { push?: boolean };
      };
      checks.push({
        name: 'github-repo-write',
        ok: repo.permissions?.push === true,
        detail: config.repo,
      });
    }
  } catch (error) {
    checks.push({ name: 'github-access', ok: false, detail: String(error) });
  }
  if (live) {
    const server = new AppServer({ cwd: root });
    try {
      await server.start();
      const account = (await server.request('account/read', {})) as { account?: { type: string } };
      if (account.account?.type !== 'chatgpt')
        throw new Error(
          'Use local codex login with your ChatGPT account; API-key inference is disabled',
        );
      const model = config?.model ?? MODEL;
      const thread = await server.startThread({
        model,
        cwd: root,
        developerInstructions: 'Reply OK. Do not use tools or change files.',
      });
      const trial = await server.runTurn(thread, 'Reply OK without tools.', {
        model,
        effort: 'high',
      });
      if (trial.status !== 'completed')
        throw new Error('Model trial was interrupted; access has not been verified');
      checks.push({
        name: 'model-inference',
        ok: true,
        detail: `${model}: successful authenticated trial turn; this consumes your subscription allowance`,
      });
    } catch (error) {
      checks.push({ name: 'model-inference', ok: false, detail: String(error) });
    } finally {
      await server.close();
    }
  } else
    checks.push({
      name: 'model-inference',
      ok: false,
      detail:
        'NOT RUN: use doctor --live-model on each account to opt into one subscription inference trial; model catalog is not entitlement proof',
    });
  print({
    mode: live ? 'explicit live prerequisite trial' : 'read-only prerequisites; no inference',
    checks,
    nativeChildren:
      'Disabled conservatively unless runtime proves child/depth enforcement; parent-only fallback works.',
    ready: checks.every((c) => c.ok),
  });
  if (
    checks.some((c) => !c.ok && c.name !== 'model-inference') ||
    (live && checks.some((c) => !c.ok))
  )
    process.exitCode = 1;
}

export async function main(args = process.argv.slice(2)) {
  const { positionals, values } = parseArgs({
    args,
    allowPositionals: true,
    options: {
      root: { type: 'string' },
      config: { type: 'string' },
      help: { type: 'boolean' },
      repo: { type: 'string' },
      workers: { type: 'string' },
      coordinator: { type: 'string' },
      deadline: { type: 'string' },
      name: { type: 'string' },
      model: { type: 'string' },
      file: { type: 'string' },
      version: { type: 'string' },
      task: { type: 'string' },
      since: { type: 'string' },
      sha: { type: 'string' },
      'allow-push': { type: 'boolean' },
      'live-model': { type: 'boolean' },
      offline: { type: 'boolean' },
      'install-dependencies': { type: 'boolean' },
      'recover-stopped': { type: 'boolean' },
      'confirm-stopped': { type: 'boolean' },
      to: { type: 'string' },
      resume: { type: 'boolean' },
    },
  });
  const command = positionals[0],
    root = path.resolve(values.root ?? '.'),
    filename = values.config ?? 'orchestration.json';
  if (!command || values.help || command === 'help') {
    print(help);
    return;
  }
  if (command === 'simulate') {
    if (!values.offline)
      throw new Error('Use simulate --offline; it never contacts providers or GitHub');
    print(await simulate());
    return;
  }
  if (command === 'init') {
    if (!values.repo || !values.workers || !values.coordinator || !values.deadline)
      throw new Error(
        'init requires --repo, --workers name:github-login,..., --coordinator and --deadline with timezone offset',
      );
    const config = ConfigSchema.parse({
      schemaVersion: 1,
      runId: `run-${randomUUID().slice(0, 8)}`,
      repo: values.repo,
      coordinator: values.coordinator,
      authorizedActors: [values.coordinator],
      workers: values.workers.split(',').map((worker) => {
        const parts = worker.split(':');
        if (parts.length !== 2) throw new Error('Workers must use name:github-login pairs');
        return { name: parts[0], githubLogin: parts[1] };
      }),
      model: values.model ?? MODEL,
      startedAt: new Date().toISOString(),
      deadline: values.deadline,
      checks: [
        { id: 'typecheck', command: 'npm', args: ['run', 'typecheck'], timeoutMs: 120_000 },
        { id: 'test', command: 'npm', args: ['test', '--', '--run'], timeoutMs: 180_000 },
      ],
      allowPush: values['allow-push'] ?? false,
    });
    await writeFile(path.resolve(root, filename), JSON.stringify(config, null, 2) + '\n', {
      flag: 'wx',
    });
    print({
      created: path.resolve(root, filename),
      runId: config.runId,
      next: 'Review identities, commands, reserved paths and deadline. Commit nonsecret config to your project; each worker uses its own local logins. doctor --live-model on every computer verifies entitlement.',
    });
    return;
  }
  const config = await configAt(root, filename).catch((e) => {
    if (command === 'doctor' && e.code === 'ENOENT') return undefined;
    throw e;
  });
  if (command === 'doctor') {
    await doctor(root, config, values['live-model'] ?? false, values.name);
    return;
  }
  if (!config) throw new Error('Initialize orchestration first');
  if (command === 'handoff') {
    if (!values.to) throw new Error('Use handoff --to <configured teammate name>');
    await requestLocalHandoff(config, root, values.to);
    return;
  }
  if (command === 'recover') {
    if (!values['confirm-stopped'])
      throw new Error(
        'Stop the old coordinator process, then explicitly pass --confirm-stopped. Healthy coding workers keep their scopes and do not need to stop.',
      );
    const lock = path.join(root, '.kit', 'orchestration', config.runId, 'coordinator.lock');
    await unlink(lock).catch((e) => {
      if (e.code !== 'ENOENT') throw e;
    });
    const archivedInbox = await archiveInterruptedHandoff(root, config.runId);
    print({
      recovered: 'local stale coordinator lock removed',
      archivedInbox,
      next: 'Review retained branches, workers and issues before chat --recover-stopped. A different active leader will still reject acquisition.',
    });
    return;
  }
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  try {
    if (command === 'worker') {
      if (!values.name) throw new Error('worker requires --name');
      await runWorker(config, {
        name: values.name,
        root,
        signal: controller.signal,
        installDependencies: values['install-dependencies'] ?? false,
        onEvent: print,
      });
      return;
    }
    const mode: LeadershipMode =
      command === 'takeover'
        ? 'takeover'
        : command === 'coordinate' && values.resume
          ? 'resume'
          : 'normal';
    if (command === 'coordinate' && !values.resume)
      throw new Error('Use coordinate --resume for a designated handoff successor');
    if (values.name && !config.workers.some((worker) => worker.name === values.name))
      throw new Error('Unknown host worker identifier');
    const transport = new GitHubTransport(config, {
      cwd: root,
      recoverExpiredLeadership: values['recover-stopped'] ?? false,
      leadershipMode: mode,
      host: values.name ?? hostname(),
    });
    const coordinator = await Coordinator.open(config, root, {
      transport,
      resume: mode === 'resume',
      takeover: mode === 'takeover',
      inspectPr: (task) => inspectPullRequest(config, task, ghApi(root)),
    });
    if (['status', 'timeline', 'blockers'].includes(command)) {
      // Read remote records, never acquire leadership or perform inference for status.
      const tasks = await transport.listTasks();
      const leadership = await transport.getLeadership();
      const checkpoint = await transport.loadCheckpoint();
      if (command === 'status')
        print({
          ...(coordinator.status() as object),
          objective: checkpoint?.state.plan?.objective ?? 'No shared plan proposed',
          sharedSummary: checkpoint?.context.summary ?? '',
          leadership: leadership
            ? {
                ...leadership,
                leaseStatus:
                  leadership.phase === 'active'
                    ? leadership.expiresAt > Date.now()
                      ? 'valid'
                      : 'expired'
                    : leadership.phase,
              }
            : undefined,
          takeoverSafetyMs: TAKEOVER_SAFETY_MS,
          checkpoint: leadership?.checkpoint,
          pendingPlanApproval:
            checkpoint?.state.plan &&
            checkpoint.state.approvedVersion !== checkpoint.state.plan.version
              ? checkpoint.state.plan.version
              : undefined,
          pendingHumanDecisions: tasks.flatMap((task) =>
            task.blockers.filter((blocker) => !blocker.resolved),
          ).length,
          counts: Object.fromEntries(
            [
              'Planned',
              'Assigned',
              'Running',
              'Review',
              'Queued',
              'Merged',
              'Verified',
              'Blocked',
              'Paused',
              'Cancelled',
            ].map((state) => [state, tasks.filter((task) => task.state === state).length]),
          ),
          remoteTasks: tasks.map((t) => ({
            id: t.id,
            worker: t.assignedWorker,
            state: t.state,
            evidence: t.evidence,
          })),
        });
      else if (command === 'blockers')
        print(
          tasks.flatMap((t) =>
            t.blockers.filter((b) => !b.resolved).map((b) => ({ task: t.id, ...b })),
          ),
        );
      else
        print({
          source: checkpoint
            ? 'recent shared checkpoint journal; older full journals remain on their original computers'
            : 'local persisted journal',
          events: (checkpoint?.state.events ?? coordinator.getState().events).filter(
            (e) => !values.since || Date.parse(e.at) >= Date.parse(values.since),
          ),
        });
      return;
    }
    await coordinator.start();
    try {
      if (['chat', 'coordinate', 'takeover'].includes(command))
        await runChat(coordinator, { root, signal: controller.signal });
      else if (command === 'plan') {
        if (!values.file) throw new Error('plan requires --file');
        print(
          await coordinator.propose(
            PlanSchema.parse(JSON.parse(await readFile(path.resolve(root, values.file), 'utf8'))),
          ),
        );
      } else if (command === 'approve' || command === 'reject') {
        if (!values.version) throw new Error(`${command} requires --version`);
        print(await coordinator[command](Number(values.version)));
        await coordinator.tick();
      } else if (command === 'verify') {
        if (!values.task || !values.sha) throw new Error('verify requires --task and --sha');
        await coordinator.tick();
        const task = coordinator.getState().tasks.find((t) => t.id === values.task);
        if (!task) throw new Error('Unknown task');
        let polling = false;
        const timer = setInterval(() => {
          if (polling) return;
          polling = true;
          void coordinator
            .tick()
            .catch((error) => {
              controller.abort(error);
            })
            .finally(() => {
              polling = false;
            });
        }, config.pollMs);
        let result;
        try {
          result = await verifyIntegrated(config, task, values.sha, root, {
            installDependencies: values['install-dependencies'],
            signal: controller.signal,
          });
        } finally {
          clearInterval(timer);
        }
        print(await coordinator.recordIntegrated(task.id, result.sha, result.summary));
        print({ retainedVerificationCheckout: result.directory });
      } else if (command === 'release') {
        if (!values.task || !values['confirm-stopped'])
          throw new Error(
            'release requires --task and --confirm-stopped after stopping the worker',
          );
        print(await coordinator.confirmStopped(values.task));
      } else if (['pause', 'resume', 'cancel'].includes(command)) {
        print(await coordinator.action(command as 'pause' | 'resume' | 'cancel', values.task));
      } else throw new Error(`Unknown command ${command}; run agents --help`);
    } finally {
      await coordinator.close();
    }
  } finally {
    process.removeListener('SIGINT', stop);
    process.removeListener('SIGTERM', stop);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
