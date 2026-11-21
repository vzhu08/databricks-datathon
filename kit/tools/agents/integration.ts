import { mkdir, access, lstat } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { checkResult, runCommand, writeCommandLog, type CommandRunner } from './runner';
import type { Config, Task } from './contracts';

/** Verify the exact human-merged commit in its own retained checkout. No merge/deploy. */
export async function verifyIntegrated(
  config: Config,
  task: Task,
  sha: string,
  root: string,
  options: { installDependencies?: boolean; runner?: CommandRunner; signal?: AbortSignal } = {},
) {
  if (task.state !== 'Merged' || !/^[a-f0-9]{40}$/.test(sha))
    throw new Error('Select an already merged task and exact merge SHA');
  const merged = [...task.evidence].reverse().find((e) => e.kind === 'merge');
  if (merged?.sha !== sha) throw new Error('SHA differs from GitHub-confirmed merge');
  const run = options.runner ?? runCommand;
  const directory = path.resolve(
    root,
    '.kit',
    'orchestration',
    config.runId,
    'integration',
    `${task.id}-${randomUUID().slice(0, 8)}`,
  );
  const base = path.resolve(root, '.kit', 'orchestration', config.runId, 'integration');
  if (!directory.startsWith(base + path.sep))
    throw new Error('Verification checkout must remain inside the run');
  let current = path.parse(base).root;
  for (const part of path.relative(current, base).split(path.sep)) {
    current = path.join(current, part);
    if ((await lstat(current).catch(() => undefined))?.isSymbolicLink())
      throw new Error('Verification cannot follow symlink ancestors');
  }
  await mkdir(base, { recursive: true });
  checkResult(
    await run('git', ['fetch', 'origin'], { cwd: root, timeoutMs: 60_000, signal: options.signal }),
  );
  checkResult(
    await run('git', ['worktree', 'add', '--detach', directory, sha], {
      cwd: root,
      timeoutMs: 60_000,
      signal: options.signal,
    }),
  );
  const logs = path.join(
    root,
    '.kit',
    'orchestration',
    config.runId,
    'integration-logs',
    path.basename(directory),
  );
  if (options.installDependencies) {
    const result = await run('npm', ['ci', '--no-audit', '--no-fund'], {
      cwd: directory,
      timeoutMs: 600_000,
      signal: options.signal,
    });
    await writeCommandLog(logs, 'npm-ci', result);
    checkResult(result);
  } else {
    await access(path.join(directory, 'node_modules')).catch(() => {
      throw new Error(
        `Verification worktree retained at ${directory}; dependencies absent. Repeat verify with --install-dependencies to opt into npm ci.`,
      );
    });
  }
  for (const check of config.checks) {
    const result = await run(check.command, check.args, {
      cwd: directory,
      timeoutMs: check.timeoutMs,
      signal: options.signal,
    });
    await writeCommandLog(logs, check.id, result);
    checkResult(result);
  }
  const actual = checkResult(
    await run('git', ['rev-parse', 'HEAD'], { cwd: directory }),
  ).stdout.trim();
  if (actual !== sha) throw new Error('Verification command changed HEAD; result refused');
  const dirty = checkResult(
    await run('git', ['status', '--porcelain', '--untracked-files=all'], { cwd: directory }),
  ).stdout.trim();
  if (dirty)
    throw new Error(
      'Verification commands modified source files; exact merge verification refused',
    );
  return {
    sha,
    summary: `${config.checks.map((c) => c.id).join(', ')} passed for exact merge commit; bounded logs at ${path.relative(root, logs)}`,
    directory,
  };
}
