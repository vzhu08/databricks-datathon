import { z } from 'zod';
export { JobSchema, type Job } from '../../../packages/contracts/src/index';
export const StartJobSchema = z.object({
  type: z.string().regex(/^[a-z][a-z0-9-]{0,63}$/),
  input: z.unknown(),
  idempotencyKey: z.string().min(1).max(200).optional(),
});
export const IngestInputSchema = z.object({
  lines: z.array(z.string().max(10_000)).max(1000),
  delayMs: z.number().int().min(0).max(1000).default(10),
});
