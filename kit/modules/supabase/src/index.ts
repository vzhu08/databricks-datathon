import { z } from 'zod';
export const NoteSchema = z.object({
  id: z.uuid(),
  owner_id: z.uuid(),
  title: z.string().trim().min(1).max(200),
  body: z.string().max(50_000),
  created_at: z.iso.datetime({ offset: true }),
});
export type Note = z.infer<typeof NoteSchema>;
export const NoteInputSchema = NoteSchema.pick({ title: true, body: true });
export interface NoteRepository {
  list(): Promise<Note[]>;
  create(input: z.input<typeof NoteInputSchema>): Promise<Note>;
  update(id: string, input: z.input<typeof NoteInputSchema>): Promise<Note>;
  delete(id: string): Promise<void>;
}
export const SupabaseConfigSchema = z.object({ url: z.url(), publishableKey: z.string().min(1) });
export type SupabaseConfig = z.infer<typeof SupabaseConfigSchema>;
export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string };
export async function loadNotes(repository: NoteRepository): Promise<LoadState<Note[]>> {
  try {
    const notes = await repository.list();
    return notes.length ? { status: 'ready', data: notes } : { status: 'empty' };
  } catch (error) {
    return {
      status: 'error',
      message: error instanceof Error ? error.message : 'Unable to load notes',
    };
  }
}
/** Explicit fixture auth boundary; never use a caller-supplied user ID for production authorization. */
export function createLocalNotes(
  userId: string,
  sharedRows = new Map<string, Note>(),
): NoteRepository {
  z.uuid().parse(userId);
  const owned = (id: string) => {
    const note = sharedRows.get(id);
    if (!note || note.owner_id !== userId) throw new Error('Note not found');
    return note;
  };
  return {
    async list() {
      return [...sharedRows.values()]
        .filter((note) => note.owner_id === userId)
        .map((note) => ({ ...note }));
    },
    async create(input) {
      const note = NoteSchema.parse({
        ...NoteInputSchema.parse(input),
        id: crypto.randomUUID(),
        owner_id: userId,
        created_at: new Date().toISOString(),
      });
      sharedRows.set(note.id, note);
      return { ...note };
    },
    async update(id, input) {
      const note = { ...owned(id), ...NoteInputSchema.parse(input) };
      sharedRows.set(id, note);
      return { ...note };
    },
    async delete(id) {
      owned(id);
      sharedRows.delete(id);
    },
  };
}
