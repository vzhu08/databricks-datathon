import { z } from 'zod';
import { ghApi, type GitHubApi } from './github';
import { type Config, type Task } from './contracts';
import { overlaps } from './coordinator';

export type PrObservation = {
  url: string;
  headSha: string;
  mergedSha?: string;
  ci: 'pending' | 'failed' | 'passed';
  summary: string;
};
export async function inspectPullRequest(
  config: Config,
  task: Task,
  api: GitHubApi = ghApi(),
): Promise<PrObservation> {
  const match = task.pr?.match(/^https:\/\/github\.com\/([^/]+\/[^/]+)\/pull\/([1-9]\d*)$/);
  if (!match || match[1].toLowerCase() !== config.repo.toLowerCase())
    throw new Error('PR must belong to this repository');
  const endpoint = `repos/${config.repo}/pulls/${match[2]}`;
  const pr = z
    .object({
      html_url: z.string().url(),
      merged: z.boolean(),
      merge_commit_sha: z.string().nullable(),
      head: z.object({ sha: z.string().regex(/^[a-f0-9]{40}$/), ref: z.string() }),
    })
    .parse(await api(endpoint, 'GET'));
  if (pr.head.ref !== task.branch) throw new Error('PR branch does not match task branch');
  const files: string[] = [];
  for (let page = 1; page <= 10; page++) {
    const result = z
      .array(z.object({ filename: z.string(), previous_filename: z.string().optional() }))
      .parse(await api(`${endpoint}/files?per_page=100&page=${page}`, 'GET'));
    files.push(
      ...result.flatMap((f) =>
        f.previous_filename ? [f.filename, f.previous_filename] : [f.filename],
      ),
    );
    if (result.length < 100) break;
    if (page === 10) throw new Error('PR file pagination limit reached');
  }
  if (!files.length) throw new Error('PR contains no changed files');
  for (const file of files) {
    if (
      !task.allowedPaths.some((p) => file === p || file.startsWith(p + '/')) ||
      config.reservedPaths.concat(task.reservedPaths).some((p) => overlaps(file, p))
    )
      throw new Error(`PR scope violation: ${file}`);
  }
  const sha = pr.head.sha;
  const runs = z
    .object({
      total_count: z.number(),
      check_runs: z.array(z.object({ status: z.string(), conclusion: z.string().nullable() })),
    })
    .parse(await api(`repos/${config.repo}/commits/${sha}/check-runs?per_page=100`, 'GET'));
  if (runs.total_count > 100) throw new Error('CI check capacity exceeded; inspect manually');
  const statuses = z
    .object({ total_count: z.number(), statuses: z.array(z.object({ state: z.string() })) })
    .parse(await api(`repos/${config.repo}/commits/${sha}/status?per_page=100`, 'GET'));
  if (statuses.total_count > 100) throw new Error('CI status capacity exceeded; inspect manually');
  const failed =
    runs.check_runs.some((r) =>
      ['failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure'].includes(
        r.conclusion ?? '',
      ),
    ) || statuses.statuses.some((s) => ['failure', 'error'].includes(s.state));
  const hasChecks = runs.check_runs.length + statuses.statuses.length > 0;
  const passed =
    hasChecks &&
    runs.check_runs.every((r) => r.status === 'completed' && r.conclusion === 'success') &&
    statuses.statuses.every((s) => s.state === 'success');
  return {
    url: pr.html_url,
    headSha: sha,
    mergedSha: pr.merged ? (pr.merge_commit_sha ?? undefined) : undefined,
    ci: failed ? 'failed' : passed ? 'passed' : 'pending',
    summary: hasChecks
      ? `${runs.check_runs.length} check runs, ${statuses.statuses.length} commit statuses inspected for ${sha}`
      : 'No CI checks; not verified',
  };
}
