import { z } from 'zod';
export const IdentifierSchema = z
  .string()
  .regex(/^[a-zA-Z0-9_-]{1,80}$/)
  .refine(
    (value) => !['__proto__', 'constructor', 'prototype'].includes(value),
    'Reserved identifier',
  );
export const RoomStateSchema = z.object({
  room: IdentifierSchema,
  members: z.array(IdentifierSchema),
  votes: z.record(z.string(), z.string()),
  revision: z.number().int().nonnegative(),
});
export type RoomState = z.infer<typeof RoomStateSchema>;
export const ClientMessageSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('join'),
    room: IdentifierSchema,
    userId: IdentifierSchema,
    token: z.string().max(4096).optional(),
  }),
  z.object({ type: z.literal('vote'), id: IdentifierSchema, choice: z.string().min(1).max(120) }),
]);
export function tallyVotes(state: RoomState) {
  const counts: Record<string, number> = Object.create(null);
  for (const choice of Object.values(state.votes)) counts[choice] = (counts[choice] ?? 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
