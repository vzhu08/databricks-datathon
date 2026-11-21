import { z } from 'zod';
import { EvidenceSchema, Id, PlanSchema, TaskSchema, type Config } from './contracts';

export const MAX_CHECKPOINT_BYTES = 1_000_000;
export const TAKEOVER_SAFETY_MS = 60_000;
export const DecisionInputSchema = z
  .object({
    kind: z.enum([
      'architecture',
      'preference',
      'clarification',
      'scope',
      'plan',
      'approval',
      'dispatch',
      'handoff',
      'control',
    ]),
    summary: z.string().min(1).max(1000),
    rationale: z.string().min(1).max(4000),
    taskId: Id.optional(),
    planVersion: z.number().int().positive().optional(),
    supersedes: Id.optional(),
  })
  .strict();
export type DecisionInput = z.infer<typeof DecisionInputSchema>;
export const DecisionSchema = DecisionInputSchema.extend({
  id: Id,
  at: z.string().datetime({ offset: true }),
  actor: z.string().min(1).max(100),
}).strict();
export const SharedMessageSchema = z
  .object({
    id: Id,
    role: z.enum(['user', 'assistant']),
    text: z.string().min(1).max(2000),
    at: z.string().datetime({ offset: true }),
    status: z.enum(['pending', 'answered', 'uncertain', 'remembered']),
  })
  .strict();
export const SharedContextSchema = z
  .object({
    summary: z.string().max(16_000).default(''),
    requirements: z.array(z.string().max(2000)).max(30).default([]),
    priorities: z.array(z.string().max(1000)).max(20).default([]),
    decisions: z.array(DecisionSchema).max(300).default([]),
    recentMessages: z.array(SharedMessageSchema).max(60).default([]),
    answeredQuestions: z
      .array(z.object({ question: z.string().max(2000), answer: z.string().max(2000) }).strict())
      .max(40)
      .default([]),
  })
  .strict();
export type SharedContext = z.infer<typeof SharedContextSchema>;
export const ContextUpdateSchema = z
  .object({
    summary: z.string().max(16_000).optional(),
    requirements: z.array(z.string().max(2000)).max(30).optional(),
    priorities: z.array(z.string().max(1000)).max(20).optional(),
    answeredQuestions: z
      .array(z.object({ question: z.string().max(2000), answer: z.string().max(2000) }).strict())
      .max(40)
      .optional(),
  })
  .strict();
export type ContextUpdate = z.infer<typeof ContextUpdateSchema>;
export type SharedMessage = z.infer<typeof SharedMessageSchema>;
export const PortableEventSchema = z
  .object({
    seq: z.number().int().positive(),
    at: z.string().datetime({ offset: true }),
    type: z.string().max(100),
    taskId: Id.optional(),
    worker: Id.optional(),
    message: z.string().max(16_000),
    evidence: z.array(EvidenceSchema).max(30).optional(),
  })
  .strict();
export const CheckpointSchema = z
  .object({
    schemaVersion: z.literal(2),
    runId: Id,
    repo: z.string(),
    policyDigest: z.string().regex(/^[a-f0-9]{64}$/),
    sequence: z.number().int().positive(),
    at: z.string().datetime({ offset: true }),
    actor: z.string().min(1).max(100),
    context: SharedContextSchema,
    state: z
      .object({
        plan: PlanSchema.optional(),
        approvedVersion: z.number().int().positive().optional(),
        paused: z.boolean(),
        tasks: z.array(TaskSchema).max(60),
        events: z.array(PortableEventSchema).max(200),
        eventBaseSeq: z.number().int().nonnegative(),
        seenReports: z.array(z.string().uuid()).max(20_000),
        notices: z.array(z.string().max(200)).max(1000),
        lastStatusAt: z.number(),
        pendingPublications: z.array(Id).max(100),
      })
      .strict(),
  })
  .strict();
export type PortableCheckpoint = z.infer<typeof CheckpointSchema>;
export const LeadershipStatusSchema = z
  .object({
    schemaVersion: z.literal(2),
    runId: Id,
    epoch: z.number().int().positive(),
    owner: z.string().uuid(),
    coordinator: z.string().min(1).max(100),
    host: z.string().max(100),
    expiresAt: z.number().int(),
    phase: z.enum(['active', 'handoff', 'released']),
    successor: z.string().max(100).optional(),
    checkpoint: z
      .object({
        blobSha: z.string().min(1).max(100),
        digest: z.string().regex(/^[a-f0-9]{64}$/),
        sequence: z.number().int().positive(),
        at: z.string().datetime({ offset: true }),
      })
      .strict()
      .optional(),
  })
  .strict();
export type LeadershipStatus = z.infer<typeof LeadershipStatusSchema>;
export type LeadershipMode = 'normal' | 'resume' | 'takeover';
export interface HandoffMethods {
  getLeadership(): Promise<LeadershipStatus | undefined>;
  loadCheckpoint(): Promise<PortableCheckpoint | undefined>;
  saveCheckpoint(checkpoint: PortableCheckpoint): Promise<LeadershipStatus>;
  prepareHandoff(successor: string, checkpoint: PortableCheckpoint): Promise<LeadershipStatus>;
}
export function coordinatorActors(config: Config): string[] {
  return [
    ...new Set(
      [
        config.coordinator,
        ...config.authorizedActors,
        ...config.workers.map((worker) => worker.githubLogin),
      ].map((actor) => actor.toLowerCase()),
    ),
  ];
}
