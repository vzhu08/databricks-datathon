import { describe, expect, it } from 'vitest';
import { inspectPullRequest } from '../../tools/agents/ci';
import { ConfigSchema, TaskSchema, WorkerReportSchema } from '../../tools/agents/contracts';
import type { GitHubApi } from '../../tools/agents/github';
const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'ci',
  repo: 'fixture/project',
  coordinator: 'lead',
  authorizedActors: ['lead'],
  workers: [{ name: 'a', githubLogin: 'worker' }],
  startedAt: '2026-10-24T00:00:00Z',
  deadline: '2026-10-25T00:00:00Z',
  checks: [{ id: 'test', command: 'node', args: ['--test'] }],
});
const task = TaskSchema.parse({
  id: 'T1',
  runId: 'ci',
  version: 1,
  planVersion: 1,
  title: 'Test',
  description: 'Fixture',
  baseSha: 'a'.repeat(40),
  allowedPaths: ['src/ui'],
  acceptance: ['tests pass'],
  checkIds: ['test'],
  updatedAt: '2026-10-24T01:00:00Z',
  branch: 'codex/ci/T1',
  pr: 'https://github.com/fixture/project/pull/1',
});
function api(
  options: {
    conclusion?: string | null;
    files?: string[];
    merged?: boolean;
    noChecks?: boolean;
  } = {},
): GitHubApi {
  return async (endpoint) => {
    if (endpoint.includes('/files?'))
      return (options.files ?? ['src/ui/index.ts']).map((filename) => ({ filename }));
    if (endpoint.includes('/check-runs'))
      return {
        total_count: options.noChecks ? 0 : 1,
        check_runs: options.noChecks
          ? []
          : [
              {
                status: 'completed',
                conclusion: options.conclusion === undefined ? 'success' : options.conclusion,
              },
            ],
      };
    if (endpoint.includes('/status?')) return { total_count: 0, statuses: [] };
    return {
      html_url: task.pr,
      merged: !!options.merged,
      merge_commit_sha: options.merged ? 'b'.repeat(40) : null,
      head: { sha: 'c'.repeat(40), ref: task.branch },
    };
  };
}
describe('actual PR/CI evidence', () => {
  it('distinguishes CI passed from human merge and integration', async () => {
    expect(await inspectPullRequest(config, task, api())).toMatchObject({
      ci: 'passed',
      mergedSha: undefined,
    });
    expect(await inspectPullRequest(config, task, api({ merged: true }))).toMatchObject({
      ci: 'passed',
      mergedSha: 'b'.repeat(40),
    });
  });
  it('does not turn absent/skipped/failing checks or worker assertions into verification', async () => {
    expect((await inspectPullRequest(config, task, api({ noChecks: true }))).ci).toBe('pending');
    expect((await inspectPullRequest(config, task, api({ conclusion: 'skipped' }))).ci).toBe(
      'pending',
    );
    expect((await inspectPullRequest(config, task, api({ conclusion: 'failure' }))).ci).toBe(
      'failed',
    );
    expect(() =>
      WorkerReportSchema.parse({
        reportId: '11111111-1111-4111-8111-111111111111',
        runId: 'ci',
        taskId: 'T1',
        version: 1,
        leaseToken: '11111111-1111-4111-8111-111111111111',
        worker: 'a',
        at: '2026-10-24T01:00:00Z',
        kind: 'result',
        evidence: [
          { kind: 'deployment', summary: 'Unverified model assertion', at: '2026-10-24T01:00:00Z' },
        ],
      }),
    ).toThrow('Workers cannot assert');
  });
  it('rejects out-of-scope PR changes and foreign repository links', async () => {
    await expect(
      inspectPullRequest(config, task, api({ files: ['package.json'] })),
    ).rejects.toThrow('scope');
    await expect(
      inspectPullRequest(config, { ...task, pr: 'https://github.com/other/repo/pull/1' }, api()),
    ).rejects.toThrow('repository');
  });
});
