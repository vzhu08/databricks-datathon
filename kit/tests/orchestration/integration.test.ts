import { afterEach, expect, it } from 'vitest';
import { mkdtemp, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { verifyIntegrated } from '../../tools/agents/integration';
import { ConfigSchema, TaskSchema } from '../../tools/agents/contracts';
import type { CommandRunner } from '../../tools/agents/runner';
const roots: string[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
const sha = 'a'.repeat(40);
const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'verify',
  repo: 'team/project',
  coordinator: 'lead',
  authorizedActors: ['lead'],
  workers: [{ name: 'a', githubLogin: 'a' }],
  startedAt: '2026-10-24T00:00:00Z',
  deadline: '2026-10-25T00:00:00Z',
  checks: [{ id: 'test', command: 'node', args: ['--test'] }],
});
const task = TaskSchema.parse({
  id: 'T1',
  runId: 'verify',
  version: 1,
  planVersion: 1,
  title: 'Merged fixture',
  description: 'Synthetic verification',
  state: 'Merged',
  baseSha: sha,
  allowedPaths: ['src'],
  acceptance: ['test'],
  checkIds: ['test'],
  updatedAt: '2026-10-24T01:00:00Z',
  evidence: [{ kind: 'merge', sha, summary: 'GitHub confirmed merge', at: '2026-10-24T01:00:00Z' }],
});
async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kit-integrated-'));
  roots.push(root);
  return root;
}
function mock(options: { dirty?: boolean; failedCheck?: boolean; changedHead?: boolean } = {}) {
  const commands: string[][] = [];
  const runner: CommandRunner = async (command, args) => {
    commands.push([command, ...args]);
    return {
      command,
      args,
      exitCode: command === 'node' && options.failedCheck ? 1 : 0,
      stdout:
        args[0] === 'rev-parse'
          ? options.changedHead
            ? 'b'.repeat(40)
            : sha
          : args[0] === 'status' && options.dirty
            ? ' M src/index.ts'
            : '',
      stderr: '',
      elapsedMs: 1,
      timedOut: false,
      truncated: false,
    };
  };
  return { runner, commands };
}
it('checks the exact merged SHA in a separate retained worktree and logs deterministic evidence', async () => {
  const root = await fixture(),
    m = mock();
  const result = await verifyIntegrated(config, task, sha, root, {
    runner: m.runner,
    installDependencies: true,
  });
  expect(result.sha).toBe(sha);
  expect(result.directory.startsWith(path.join(root, '.kit'))).toBe(true);
  expect(
    m.commands.some(
      (c) => c[0] === 'git' && c[1] === 'worktree' && c.includes('--detach') && c.includes(sha),
    ),
  ).toBe(true);
});
it('refuses checks that modify source or HEAD and refuses failed checks', async () => {
  const root = await fixture();
  await expect(
    verifyIntegrated(config, task, sha, root, {
      runner: mock({ dirty: true }).runner,
      installDependencies: true,
    }),
  ).rejects.toThrow('modified source');
  await expect(
    verifyIntegrated(config, task, sha, root, {
      runner: mock({ changedHead: true }).runner,
      installDependencies: true,
    }),
  ).rejects.toThrow('changed HEAD');
  await expect(
    verifyIntegrated(config, task, sha, root, {
      runner: mock({ failedCheck: true }).runner,
      installDependencies: true,
    }),
  ).rejects.toThrow('failed');
});
it('requires confirmed merge evidence and explicit dependency installation', async () => {
  const root = await fixture();
  await expect(
    verifyIntegrated(config, { ...task, state: 'Queued' }, sha, root, { runner: mock().runner }),
  ).rejects.toThrow('already merged');
  await expect(
    verifyIntegrated(config, task, 'b'.repeat(40), root, { runner: mock().runner }),
  ).rejects.toThrow('differs');
  await expect(
    verifyIntegrated(config, task, sha, root, { runner: mock().runner }),
  ).rejects.toThrow('dependencies absent');
});
