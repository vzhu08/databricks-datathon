import { createHash } from 'node:crypto';
import { ConfigSchema, type Config, type RunState } from './contracts';
import {
  CheckpointSchema,
  MAX_CHECKPOINT_BYTES,
  SharedContextSchema,
  coordinatorActors,
  type PortableCheckpoint,
} from './handoff-contracts';

const secretPatterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?(?:-----END [^-]+PRIVATE KEY-----|$)/g,
  /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b/g,
  /\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]+\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/-]{8,}/gi,
  /\b[A-Z_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)[A-Z_]*\s*[:=]\s*["']?(?!\[redacted\])[^\s"'`,;]{8,}/gi,
  /([?&](?:token|key|signature|password|secret|credential)[^=]*=)[^&\s]+/gi,
];
export function redactTeamText(text: string, maximum = 2000): string {
  let value = text;
  for (const pattern of secretPatterns) value = value.replace(pattern, '[redacted]');
  value = value.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[private email]');
  return value.slice(0, maximum);
}
export function assertSharedSafe(value: unknown) {
  const visit = (item: unknown) => {
    if (typeof item === 'string') {
      for (const pattern of secretPatterns) {
        pattern.lastIndex = 0;
        if (pattern.test(item)) {
          pattern.lastIndex = 0;
          throw new Error(
            'Sensitive content cannot enter the shared checkpoint; configure credentials locally and redact project context',
          );
        }
      }
    } else if (Array.isArray(item)) item.forEach(visit);
    else if (item && typeof item === 'object') Object.values(item).forEach(visit);
  };
  visit(value);
}
export function policyDigest(config: Config) {
  return createHash('sha256')
    .update(JSON.stringify(ConfigSchema.parse(config)))
    .digest('hex');
}
export function validateCheckpoint(input: unknown, config: Config): PortableCheckpoint {
  const checkpoint = CheckpointSchema.parse(input);
  if (
    checkpoint.runId !== config.runId ||
    checkpoint.repo !== config.repo ||
    checkpoint.policyDigest !== policyDigest(config)
  )
    throw new Error(
      'Checkpoint project/run/policy mismatch; use the same committed orchestration configuration',
    );
  if (Buffer.byteLength(JSON.stringify(checkpoint)) > MAX_CHECKPOINT_BYTES)
    throw new Error(
      'Shared checkpoint exceeds 1 MB; compact historical evidence before continuing',
    );
  assertSharedSafe(checkpoint);
  if (checkpoint.state.events.some((e, i) => e.seq !== checkpoint.state.eventBaseSeq + i + 1))
    throw new Error('Checkpoint event sequence is incomplete');
  const tasks = checkpoint.state.tasks;
  if (new Set(tasks.map((t) => t.id)).size !== tasks.length)
    throw new Error('Checkpoint has duplicate task IDs');
  const actors = coordinatorActors(config);
  if (!actors.includes(checkpoint.actor.toLowerCase()))
    throw new Error('Checkpoint actor is not a configured coordinator');
  const decisions = checkpoint.context.decisions;
  if (
    new Set(decisions.map((d) => d.id)).size !== decisions.length ||
    decisions.some((d) => !actors.includes(d.actor.toLowerCase()))
  )
    throw new Error('Checkpoint contains duplicate or unauthorized decisions');
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const visited = new Set<string>(),
    visiting = new Set<string>();
  const visit = (id: string) => {
    if (visited.has(id)) return;
    const task = byId.get(id);
    if (!task) throw new Error('Checkpoint dependency is missing');
    if (visiting.has(id)) throw new Error('Checkpoint task dependency cycle');
    if (
      task.runId !== config.runId ||
      task.checkIds.some((id) => !config.checks.some((check) => check.id === id))
    )
      throw new Error('Checkpoint task has a foreign run or unconfigured check');
    if (
      task.assignmentDecisionId &&
      !decisions.some(
        (d) =>
          d.id === task.assignmentDecisionId &&
          d.kind === 'dispatch' &&
          d.taskId === task.id &&
          d.planVersion === task.planVersion,
      )
    )
      throw new Error('Checkpoint assignment lacks its matching dispatch rationale');
    visiting.add(id);
    task.dependencies.forEach(visit);
    visiting.delete(id);
    visited.add(id);
  };
  tasks.forEach((task) => visit(task.id));
  if (checkpoint.state.plan) {
    const plan = checkpoint.state.plan;
    if (
      plan.tasks.length !== tasks.length ||
      plan.tasks.some((task) => task.runId !== config.runId || !byId.has(task.id))
    )
      throw new Error('Checkpoint plan/task board mismatch');
    if (
      checkpoint.state.approvedVersion !== undefined &&
      checkpoint.state.approvedVersion !== plan.version
    )
      throw new Error('Checkpoint approval version is stale');
  } else if (checkpoint.state.approvedVersion !== undefined)
    throw new Error('Checkpoint approval has no plan');
  return checkpoint;
}
export function buildCheckpoint(
  state: RunState,
  config: Config,
  actor: string,
  at: string,
): PortableCheckpoint {
  const events = state.events.slice(-200);
  return validateCheckpoint(
    {
      schemaVersion: 2,
      runId: config.runId,
      repo: config.repo,
      policyDigest: policyDigest(config),
      sequence: (state.checkpointSequence ?? 0) + 1,
      at,
      actor,
      context: SharedContextSchema.parse(state.context ?? {}),
      state: {
        plan: state.plan,
        approvedVersion: state.approvedVersion,
        paused: state.paused,
        tasks: state.tasks,
        events: events.map((event) => ({
          ...event,
          message: redactTeamText(event.message, 16_000),
        })),
        eventBaseSeq: events.length ? events[0].seq - 1 : (state.eventBaseSeq ?? 0),
        seenReports: state.seenReports,
        notices: state.notices,
        lastStatusAt: state.lastStatusAt,
        pendingPublications: state.pendingPublications ?? [],
      },
    },
    config,
  );
}
