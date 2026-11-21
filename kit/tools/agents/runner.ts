import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { lstat, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { ConfigSchema, TaskSchema, type Config, type Evidence, type Task } from './contracts';

export type CommandResult = {
  command: string;
  args: string[];
  exitCode: number | null;
  stdout: string;
  stderr: string;
  elapsedMs: number;
  timedOut: boolean;
  truncated: boolean;
};
export type CommandOptions = {
  cwd: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  maxOutputBytes?: number;
  input?: string;
  env?: NodeJS.ProcessEnv;
  onOutput?: (chunk: string) => void;
};
export type CommandRunner = (
  command: string,
  args: string[],
  options: CommandOptions,
) => Promise<CommandResult>;

/** Never pass npm/codex command shims through a shell on Windows. */
export function resolveCommand(
  command: string,
  args: string[],
  platform = process.platform,
): { command: string; args: string[] } {
  if (platform !== 'win32' || !['npm', 'npx', 'codex'].includes(command)) return { command, args };
  const dirs = [path.dirname(process.execPath), ...(process.env.PATH ?? '').split(path.delimiter)];
  const suffix = command === 'codex' ? '@openai/codex/bin/codex.js' : `npm/bin/${command}-cli.js`;
  const candidates = [
    ...(command === 'npm' && process.env.npm_execpath ? [process.env.npm_execpath] : []),
    ...dirs.flatMap((dir) => [
      path.join(dir, 'node_modules', suffix),
      path.join(dir, '..', 'node_modules', suffix),
    ]),
  ];
  const script = candidates.find((file) => existsSync(file) && file.endsWith('.js'));
  if (!script)
    throw new Error(
      `Cannot locate ${command}'s JavaScript entrypoint. Install it in the normal Node/npm PATH; shell shims are not executed.`,
    );
  return { command: process.execPath, args: [script, ...args] };
}

export function subscriptionEnvironment(env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const clean = { ...env };
  for (const key of Object.keys(clean)) {
    if (
      /^(OPENAI_API_KEY|CODEX_API_KEY|AZURE_OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENAI_BASE_URL|OPENAI_API_BASE|OPENAI_ORG_ID|OPENAI_PROJECT_ID)$/i.test(
        key,
      )
    )
      delete clean[key];
  }
  return clean;
}

export const runCommand: CommandRunner = async (command, args, options) => {
  if (options.signal?.aborted) throw new Error('Command cancelled before launch');
  const executable = resolveCommand(command, args);
  const started = Date.now();
  const cap = options.maxOutputBytes ?? 256_000;
  return await new Promise<CommandResult>((resolve, reject) => {
    const child = spawn(executable.command, executable.args, {
      cwd: options.cwd,
      env: options.env ?? subscriptionEnvironment(),
      shell: false,
      windowsHide: true,
      detached: process.platform !== 'win32',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '',
      stderr = '',
      bytes = 0,
      truncated = false,
      timedOut = false;
    let killTimer: ReturnType<typeof setTimeout> | undefined;
    const stop = () => {
      if (child.pid && process.platform === 'win32') {
        const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
          windowsHide: true,
          shell: false,
          stdio: 'ignore',
        });
        killer.on('error', () => child.kill());
        killer.on('close', (code) => {
          if (code !== 0) child.kill();
        });
        killTimer = setTimeout(() => {
          if (child.exitCode === null) child.kill();
        }, 2000);
        killTimer.unref();
      } else if (child.pid) {
        try {
          process.kill(-child.pid, 'SIGTERM');
        } catch {
          child.kill('SIGTERM');
        }
        killTimer = setTimeout(() => {
          try {
            process.kill(-child.pid!, 'SIGKILL');
          } catch {
            child.kill('SIGKILL');
          }
        }, 2000);
        killTimer.unref();
      } else child.kill();
    };
    const timer = setTimeout(() => {
      timedOut = true;
      stop();
    }, options.timeoutMs ?? 120_000);
    options.signal?.addEventListener('abort', stop, { once: true });
    const collect = (chunk: Buffer, stream: 'stdout' | 'stderr') => {
      // Progress callbacks are bounded as well: never leak a full transcript into events.
      const remaining = Math.max(0, cap - bytes);
      const part = chunk.subarray(0, remaining).toString('utf8');
      bytes += Buffer.byteLength(part);
      if (chunk.length > remaining) truncated = true;
      if (stream === 'stdout') stdout += part;
      else stderr += part;
      if (part) options.onOutput?.(part);
    };
    child.stdout.on('data', (chunk: Buffer) => collect(chunk, 'stdout'));
    child.stderr.on('data', (chunk: Buffer) => collect(chunk, 'stderr'));
    const cleanup = () => {
      clearTimeout(timer);
      if (killTimer) clearTimeout(killTimer);
      options.signal?.removeEventListener('abort', stop);
    };
    child.on('error', (error) => {
      cleanup();
      reject(error);
    });
    child.on('close', (exitCode) => {
      cleanup();
      resolve({
        command,
        args,
        exitCode,
        stdout,
        stderr,
        elapsedMs: Date.now() - started,
        timedOut,
        truncated,
      });
    });
    child.stdin.on('error', () => {});
    child.stdin.end(options.input);
  });
};

export function checkResult(result: CommandResult): CommandResult {
  if (result.exitCode !== 0 || result.timedOut)
    throw new Error(
      `${result.command} failed (${result.timedOut ? 'timeout' : result.exitCode}): ${result.stderr.slice(-1500)}`,
    );
  if (result.truncated)
    throw new Error(`${result.command} output exceeded the bounded capture limit`);
  return result;
}

export function commandEvidence(result: CommandResult, now = new Date().toISOString()): Evidence {
  return {
    kind: 'check',
    at: now,
    command: [result.command, ...result.args].join(' ').slice(0, 2000),
    exitCode: result.exitCode,
    summary: `${result.timedOut ? 'Timed out' : result.exitCode === 0 ? 'Passed' : 'Failed'} in ${result.elapsedMs}ms${result.truncated ? '; output truncated' : ''}`,
  };
}

export const inScope = (file: string, scopes: string[]) =>
  scopes.some(
    (scope) =>
      file.toLowerCase() === scope.toLowerCase() ||
      file.toLowerCase().startsWith(`${scope.toLowerCase()}/`),
  );
export function assertAllowedPath(file: string, task: Task, config: Config) {
  if (
    !file ||
    file.includes('\\') ||
    file.startsWith('/') ||
    file.includes(':') ||
    file.split('/').some((p) => p === '..' || p === '.')
  )
    throw new Error(`Unsafe changed path: ${file}`);
  if (
    /(^|\/)(\.env[^/]*|\.git|\.kit|\.aws|\.ssh|\.codex|\.npmrc|\.netrc|auth\.json)(\/|$)/i.test(
      file,
    ) ||
    /\.(pem|key|p12|pfx|jks)$/i.test(file) ||
    /(^|\/)(credentials|secrets)(\.|\/|$)/i.test(file)
  )
    throw new Error(`Protected credential or state path: ${file}`);
  if (inScope(file, ['tools/agents', 'orchestration.json']))
    throw new Error(`Worker cannot change orchestration controls: ${file}`);
  if (
    !inScope(file, task.allowedPaths) ||
    inScope(file, [...config.reservedPaths, ...task.reservedPaths])
  )
    throw new Error(`Changed path is outside exclusive task scope: ${file}`);
}

export function assertNoSecret(content: string, file: string) {
  if (
    /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b/.test(
      content,
    )
  )
    throw new Error(`Possible secret in staged content: ${file}`);
}

async function rejectSymlinks(cwd: string, file: string) {
  let current = cwd;
  for (const part of file.split('/')) {
    current = path.join(current, part);
    const info = await lstat(current).catch((error: NodeJS.ErrnoException) => {
      if (error.code === 'ENOENT') return undefined;
      throw error;
    });
    if (info?.isSymbolicLink()) throw new Error(`Symlink in changed path: ${file}`);
  }
}

export async function inspectTaskDiff(
  cwd: string,
  taskInput: Task,
  configInput: Config,
  runner = runCommand,
): Promise<string[]> {
  const task = TaskSchema.parse(taskInput),
    config = ConfigSchema.parse(configInput);
  const git = async (args: string[]) =>
    checkResult(await runner('git', args, { cwd, maxOutputBytes: 2_000_000 })).stdout;
  const branch = (await git(['branch', '--show-current'])).trim();
  const expected = `codex/${config.runId}/${task.id}`;
  if (branch !== expected || task.branch !== expected)
    throw new Error(`Refusing commit on unauthorized task branch: ${branch}`);
  const files = [
    ...new Set(
      (await git(['diff', '--name-only', '--no-renames', '-z', 'HEAD']))
        .split('\0')
        .concat((await git(['ls-files', '--others', '--exclude-standard', '-z'])).split('\0'))
        .filter(Boolean),
    ),
  ].sort();
  if (files.length > 500) throw new Error('Changed-file limit exceeded');
  for (const file of files) {
    assertAllowedPath(file, task, config);
    await rejectSymlinks(cwd, file);
    const info = await lstat(path.join(cwd, file)).catch(() => undefined);
    if (info && !info.isFile()) throw new Error(`Changed path is not an ordinary file: ${file}`);
    if (info?.isFile()) {
      if (info.size > 2_000_000)
        throw new Error(`Changed file exceeds 2MB inspection limit: ${file}`);
      assertNoSecret(await readFile(path.join(cwd, file), 'utf8'), file);
    }
  }
  // Ignored credential files are never staged; fail visibly if an agent creates one.
  const ignored = (
    await git(['ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z'])
  )
    .split('\0')
    .filter(Boolean);
  if (
    ignored.some((file) =>
      /(^|\/)(\.env[^/]*|\.aws|\.ssh|auth\.json|credentials)(\/|$)/i.test(file),
    )
  )
    throw new Error('Ignored credential file appeared in task worktree');
  return files;
}

export async function commitTask(
  cwd: string,
  task: Task,
  config: Config,
  fence: () => Promise<void>,
  runner = runCommand,
): Promise<{ sha?: string; files: string[] }> {
  await fence();
  const files = await inspectTaskDiff(cwd, task, config, runner);
  if (!files.length) return { files };
  const git = async (args: string[]) =>
    checkResult(await runner('git', args, { cwd, maxOutputBytes: 2_000_000 })).stdout;
  // A fresh task worktree must have no model-made commits or pre-existing index edits.
  if ((await git(['rev-parse', 'HEAD'])).trim() !== task.baseSha)
    throw new Error('Task HEAD changed outside deterministic runner');
  await git(['add', '--', ...files]);
  const staged = (await git(['diff', '--cached', '--name-only', '--no-renames', '-z']))
    .split('\0')
    .filter(Boolean);
  if (staged.length !== files.length || staged.some((f) => !files.includes(f)))
    throw new Error('Staged index differs from validated task files');
  for (const file of (await git(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']))
    .split('\0')
    .filter(Boolean)) {
    assertAllowedPath(file, task, config);
    assertNoSecret(await git(['show', `:${file}`]), file);
  }
  await fence();
  await git(['-c', 'core.hooksPath=', 'commit', '-m', `${task.id}: ${task.title}`]);
  const sha = (await git(['rev-parse', 'HEAD'])).trim();
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error('Invalid result commit SHA');
  return { sha, files };
}

export async function writeCommandLog(directory: string, id: string, result: CommandResult) {
  await mkdir(directory, { recursive: true });
  const key = createHash('sha256').update(id).digest('hex').slice(0, 16);
  await writeFile(path.join(directory, `${key}.json`), JSON.stringify(result, null, 2) + '\n', {
    mode: 0o600,
  });
}
