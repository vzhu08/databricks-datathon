import { describe, it, expect } from 'vitest';
import { mkdtemp, mkdir, writeFile, rm, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ConfigSchema, TaskSchema } from '../../tools/agents/contracts';
import {
  assertAllowedPath,
  assertNoSecret,
  commitTask,
  inspectTaskDiff,
  runCommand,
  subscriptionEnvironment,
  type CommandRunner,
  type CommandResult,
} from '../../tools/agents/runner';

const sha = 'a'.repeat(40);
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
const task = TaskSchema.parse({
  id: 'task1',
  runId: 'run1',
  version: 1,
  planVersion: 1,
  title: 'Build feature',
  description: 'A scoped implementation',
  baseSha: sha,
  allowedPaths: ['src'],
  acceptance: ['Works'],
  checkIds: ['test'],
  branch: 'codex/run1/task1',
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

describe('deterministic task runner', () => {
  it('rejects traversal, unowned files, credentials and reserved scope', () => {
    for (const file of [
      '../escape',
      'src/../../escape',
      'src\\other',
      '/src/file',
      'package.json',
      'src/.env',
      'src/secret.key',
      'src/.ssh/config',
      'src/auth.json',
      'other.ts',
    ])
      expect(() => assertAllowedPath(file, task, config)).toThrow();
    expect(() => assertAllowedPath('src/index.ts', task, config)).not.toThrow();
    expect(() =>
      assertAllowedPath(
        'src/contracts/a.ts',
        { ...task, reservedPaths: ['src/contracts'] },
        config,
      ),
    ).toThrow('scope');
    expect(() => assertAllowedPath('src2/a.ts', task, config)).toThrow('scope');
    expect(() =>
      assertAllowedPath(
        'src/Contracts/a.ts',
        { ...task, reservedPaths: ['src/contracts'] },
        config,
      ),
    ).toThrow('scope');
  });
  it('detects credential material and strips provider API keys from child environments', () => {
    expect(() => assertNoSecret('-----BEGIN PRIVATE KEY-----', 'src/a')).toThrow('secret');
    expect(() => assertNoSecret(`key=ghp_${'x'.repeat(30)}`, 'src/a')).toThrow('secret');
    expect(
      subscriptionEnvironment({
        PATH: 'p',
        OPENAI_API_KEY: 's',
        CODEX_API_KEY: 's2',
        OPENAI_BASE_URL: 'https://evil.test',
        CODEX_HOME: 'local',
      }),
    ).toEqual({ PATH: 'p', CODEX_HOME: 'local' });
  });
  it('runs argument arrays, captures bounded output and times out a real local process', async () => {
    const okay = await runCommand(
      process.execPath,
      ['-e', 'process.stdout.write(process.argv[1])', 'literal;$(anything)'],
      { cwd: process.cwd() },
    );
    expect(okay.exitCode).toBe(0);
    expect(okay.stdout).toBe('literal;$(anything)');
    const capped = await runCommand(
      process.execPath,
      ['-e', 'process.stdout.write("x".repeat(10000))'],
      { cwd: process.cwd(), maxOutputBytes: 100 },
    );
    expect(capped.stdout.length).toBe(100);
    expect(capped.truncated).toBe(true);
    const timeout = await runCommand(process.execPath, ['-e', 'setTimeout(()=>{},10000)'], {
      cwd: process.cwd(),
      timeoutMs: 100,
    });
    expect(timeout.timedOut).toBe(true);
    expect(timeout.exitCode).not.toBe(0);
  });
  it('cancels before starting a subprocess', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      runCommand(process.execPath, ['-e', ''], { cwd: process.cwd(), signal: controller.signal }),
    ).rejects.toThrow('cancelled');
  });
  it('inspects untracked and tracked changes and refuses ignored credentials', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-diff-'));
    try {
      await mkdir(path.join(temp, 'src'));
      await writeFile(path.join(temp, 'src/a.ts'), 'export const works = true;');
      const runner: CommandRunner = async (command, args) =>
        result(
          command,
          args,
          args[0] === 'branch' ? task.branch : args[0] === 'diff' ? 'src/a.ts\0' : '',
        );
      expect(await inspectTaskDiff(temp, task, config, runner)).toEqual(['src/a.ts']);
      const ignored: CommandRunner = async (command, args, options) =>
        args.includes('--ignored')
          ? result(command, args, '.env.local\0')
          : runner(command, args, options);
      await expect(inspectTaskDiff(temp, task, config, ignored)).rejects.toThrow(
        'Ignored credential',
      );
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('does not commit empty tasks, changed HEADs, wrong branches or a failed fencing check', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-commit-'));
    try {
      const calls: string[][] = [];
      const runner: CommandRunner = async (command, args) => {
        calls.push(args);
        return result(command, args, args[0] === 'branch' ? task.branch : '');
      };
      expect(await commitTask(temp, task, config, async () => {}, runner)).toEqual({ files: [] });
      expect(calls.some((args) => args.includes('commit'))).toBe(false);
      await expect(
        commitTask(
          temp,
          task,
          config,
          async () => {
            throw new Error('revoked');
          },
          runner,
        ),
      ).rejects.toThrow('revoked');
      const wrong: CommandRunner = async (command, args) =>
        result(command, args, args[0] === 'branch' ? 'main' : '');
      await expect(commitTask(temp, task, config, async () => {}, wrong)).rejects.toThrow(
        'unauthorized',
      );
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('creates a scoped real Git commit and preserves unrelated base-checkout files', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-git-'));
    const git = async (...args: string[]) => {
      const value = await runCommand('git', args, { cwd: temp });
      if (value.exitCode) throw new Error(value.stderr);
      return value.stdout.trim();
    };
    try {
      await git('init');
      await git('config', 'user.name', 'Fixture');
      await git('config', 'user.email', 'fixture@example.test');
      await writeFile(path.join(temp, 'base.txt'), 'preserve');
      await git('add', '--', 'base.txt');
      await git('commit', '-m', 'base');
      const baseSha = await git('rev-parse', 'HEAD');
      await git('checkout', '-b', task.branch!);
      await mkdir(path.join(temp, 'src'));
      await writeFile(path.join(temp, 'src/feature.ts'), 'export const feature = true;');
      const committed = await commitTask(temp, { ...task, baseSha }, config, async () => {});
      expect(committed.sha).toMatch(/^[a-f0-9]{40}$/);
      expect(committed.files).toEqual(['src/feature.ts']);
      expect(await readFile(path.join(temp, 'base.txt'), 'utf8')).toBe('preserve');
      expect(await git('status', '--porcelain')).toBe('');
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
  it('checks staged content before committing, even when worktree content is harmless', async () => {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'orchestration-staged-secret-'));
    try {
      await mkdir(path.join(temp, 'src'));
      await writeFile(path.join(temp, 'src/a.ts'), 'safe');
      const calls: string[][] = [];
      const runner: CommandRunner = async (command, args) => {
        calls.push(args);
        return result(
          command,
          args,
          args[0] === 'branch'
            ? task.branch
            : args[0] === 'diff'
              ? 'src/a.ts\0'
              : args[0] === 'rev-parse'
                ? sha
                : args[0] === 'show'
                  ? `ghp_${'x'.repeat(30)}`
                  : '',
        );
      };
      await expect(commitTask(temp, task, config, async () => {}, runner)).rejects.toThrow(
        'secret',
      );
      expect(calls.some((args) => args.includes('commit'))).toBe(false);
    } finally {
      await rm(temp, { recursive: true, force: true });
    }
  });
});
