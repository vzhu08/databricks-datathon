import { z } from 'zod';
import type {
  ContextUpdate,
  DecisionInput,
  HandoffMethods,
  LeadershipStatus,
  SharedContext,
  SharedMessage,
} from './handoff-contracts';

export const MODEL = 'gpt-6-astra';
export const Id = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/);
export const RelativePath = z
  .string()
  .min(1)
  .max(300)
  .refine(
    (p) =>
      !p.includes('\\') &&
      !p.includes('\0') &&
      !p.includes(':') &&
      !p.startsWith('/') &&
      !p.split('/').some((s) => !s || s === '.' || s === '..') &&
      !/[?*[\]{}]/.test(p),
    'Use a literal repository-relative file or directory prefix, without globs',
  );
export const CheckSchema = z
  .object({
    id: Id,
    command: z.enum(['node', 'npm', 'npx', 'git']),
    args: z.array(z.string().max(500)).max(40),
    timeoutMs: z.number().int().min(1000).max(900_000).default(120_000),
  })
  .strict();
export const ConfigSchema = z
  .object({
    schemaVersion: z.literal(1),
    runId: Id,
    repo: z.string().regex(/^[\w.-]+\/[\w.-]+$/),
    coordinator: z.string().regex(/^[\w-]+$/),
    authorizedActors: z
      .array(z.string().regex(/^[\w-]+$/))
      .min(1)
      .max(20),
    workers: z
      .array(z.object({ name: Id, githubLogin: z.string().regex(/^[\w-]+$/) }).strict())
      .min(1)
      .max(3),
    model: z.string().min(1).default(MODEL),
    startedAt: z.string().datetime({ offset: true }),
    deadline: z.string().datetime({ offset: true }),
    pollMs: z.number().int().min(5000).max(300_000).default(15_000),
    heartbeatMs: z.number().int().min(10_000).max(120_000).default(60_000),
    leaseMs: z.number().int().min(180_000).max(900_000).default(300_000),
    maxChildren: z.number().int().min(0).max(2).default(0),
    checks: z.array(CheckSchema).min(1).max(20),
    reservedPaths: z
      .array(RelativePath)
      .default([
        'package.json',
        'package-lock.json',
        'packages/contracts',
        '.github',
        'migrations',
        '.codex',
      ]),
    allowPush: z.boolean().default(false),
  })
  .strict()
  .superRefine((c, ctx) => {
    if (new Set(c.workers.map((w) => w.name)).size !== c.workers.length)
      ctx.addIssue({ code: 'custom', message: 'Worker names must be unique', path: ['workers'] });
    if (!c.authorizedActors.includes(c.coordinator))
      ctx.addIssue({
        code: 'custom',
        message: 'Coordinator must be authorized',
        path: ['coordinator'],
      });
    if (Date.parse(c.deadline) <= Date.parse(c.startedAt))
      ctx.addIssue({ code: 'custom', message: 'Deadline must be after start', path: ['deadline'] });
  });
export type Config = z.infer<typeof ConfigSchema>;
export const States = [
  'Planned',
  'Ready',
  'Assigned',
  'Running',
  'Review',
  'Queued',
  'Merged',
  'Verified',
  'Blocked',
  'Paused',
  'Failed',
  'Cancelled',
] as const;
export const EvidenceSchema = z
  .object({
    kind: z.enum([
      'process',
      'check',
      'commit',
      'pr',
      'ci',
      'merge',
      'integration',
      'deployment',
      'checkpoint',
    ]),
    summary: z.string().min(1).max(2000),
    at: z.string().datetime({ offset: true }),
    url: z.string().url().optional(),
    command: z.string().max(2000).optional(),
    exitCode: z.number().int().nullable().optional(),
    sha: z
      .string()
      .regex(/^[a-f0-9]{40}$/)
      .optional(),
  })
  .strict();
export type Evidence = z.infer<typeof EvidenceSchema>;
export const BlockerSchema = z
  .object({
    id: Id,
    question: z.string().min(1).max(2000),
    recommendation: z.string().min(1).max(1000),
    options: z.array(z.string().min(1).max(500)).min(2).max(3),
    attempted: z.array(z.string().max(1000)).max(3),
    impact: z.string().max(1000),
    resolved: z.string().max(2000).optional(),
  })
  .strict();
export const TaskSchema = z
  .object({
    id: Id,
    runId: Id,
    version: z.number().int().min(1),
    planVersion: z.number().int().min(1),
    title: z.string().min(1).max(200),
    description: z.string().min(1).max(12_000),
    sharedContract: z.string().max(16_000).default(''),
    assignmentDecisionId: Id.optional(),
    category: z.enum(['feature', 'fix', 'verification', 'demo']).default('feature'),
    state: z.enum(States).default('Planned'),
    dependencies: z.array(Id).max(30).default([]),
    baseSha: z.string().regex(/^[a-f0-9]{40}$/),
    allowedPaths: z.array(RelativePath).min(1).max(30),
    reservedPaths: z.array(RelativePath).max(50).default([]),
    acceptance: z.array(z.string().min(1).max(2000)).min(1).max(20),
    checkIds: z.array(Id).min(1).max(20),
    artifacts: z.array(z.string().max(500)).max(20).default([]),
    assignedWorker: Id.optional(),
    lease: z
      .object({
        token: z.string().uuid(),
        epoch: z.number().int().min(1),
        expiresAt: z.string().datetime({ offset: true }),
      })
      .strict()
      .optional(),
    branch: z
      .string()
      .regex(/^codex\/[a-zA-Z0-9_/-]+$/)
      .optional(),
    issue: z.number().int().positive().optional(),
    pr: z.string().url().optional(),
    evidence: z.array(EvidenceSchema).max(200).default([]),
    blockers: z.array(BlockerSchema).max(30).default([]),
    retries: z.number().int().min(0).max(2).default(0),
    updatedAt: z.string().datetime({ offset: true }),
  })
  .strict();
export type Task = z.infer<typeof TaskSchema>;
export const PlanSchema = z
  .object({
    version: z.number().int().min(1),
    objective: z.string().min(1).max(4000),
    contract: z.string().min(1).max(16_000),
    rationale: z.string().min(1).max(4000).optional(),
    tasks: z.array(TaskSchema).min(1).max(60),
  })
  .strict();
export type Plan = z.infer<typeof PlanSchema>;
export const WorkerReportSchema = z
  .object({
    reportId: z.string().uuid(),
    runId: Id,
    taskId: Id,
    version: z.number().int().min(1),
    leaseToken: z.string().uuid(),
    worker: Id,
    at: z.string().datetime({ offset: true }),
    kind: z.enum(['started', 'heartbeat', 'checkpoint', 'result', 'blocked', 'stopped']),
    evidence: z.array(EvidenceSchema).max(30).default([]),
    blocker: BlockerSchema.optional(),
    pr: z.string().url().optional(),
  })
  .strict()
  .superRefine((report, context) => {
    if (
      report.evidence.some((item) =>
        ['ci', 'merge', 'integration', 'deployment'].includes(item.kind),
      )
    )
      context.addIssue({
        code: 'custom',
        message: 'Workers cannot assert external CI, merge, integration or deployment verification',
        path: ['evidence'],
      });
  });
export type WorkerReport = z.infer<typeof WorkerReportSchema>;
export type Event = {
  seq: number;
  at: string;
  type: string;
  taskId?: string;
  worker?: string;
  message: string;
  evidence?: Evidence[];
};
export type RunState = {
  schemaVersion: 1;
  runId: string;
  plan?: Plan;
  approvedVersion?: number;
  paused: boolean;
  tasks: Task[];
  events: Event[];
  seenReports: string[];
  notices: string[];
  lastStatusAt: number;
  threadId?: string;
  pendingPublications?: string[];
  pendingAuthorizations?: string[];
  context?: SharedContext;
  eventBaseSeq?: number;
  checkpointSequence?: number;
  leadership?: LeadershipStatus;
  reconstructed?: boolean;
};

// Transport owns authenticated GitHub I/O; coordinator alone mutates issue task records.
export interface QueueTransport extends Partial<HandoffMethods> {
  acquireLeadership(): Promise<void>;
  renewLeadership(): Promise<void>;
  releaseLeadership(): Promise<void>;
  publishTask(task: Task): Promise<Task>;
  listTasks(): Promise<Task[]>;
  listReports(): Promise<WorkerReport[]>;
  postReport(task: Task, report: WorkerReport): Promise<void>;
}
export interface ChatBridge {
  config: Config;
  getState(): RunState;
  saveThread(id: string): Promise<void>;
  status(): unknown;
  propose(plan: Plan): Promise<unknown>;
  approve(version: number): Promise<unknown>;
  reject(version: number): Promise<unknown>;
  action(action: 'pause' | 'resume' | 'cancel', taskId?: string): Promise<unknown>;
  resolve(taskId: string, blockerId: string, answer: string): Promise<unknown>;
  tick(): Promise<void>;
  onEvent(listener: (event: Event) => void): () => void;
  recordDecision?(decision: DecisionInput): Promise<unknown>;
  updateContext?(update: ContextUpdate): Promise<unknown>;
  rememberMessage?(message: SharedMessage): Promise<unknown>;
  handoff?(successor: string): Promise<unknown>;
  setHandoffGuard?(guard: () => Promise<void | (() => void)>): () => void;
}
