import { NoteInputSchema, type Note } from '../../src/index';
import type { DemoUser, NotesSession } from './session';

export interface NotesView {
  phase: 'loading' | 'signed-out' | 'ready';
  user: DemoUser | null;
  notes: Note[];
  busy: boolean;
  error: string | null;
}
export function createNotesController(session: NotesSession) {
  let state: NotesView = { phase: 'loading', user: null, notes: [], busy: false, error: null };
  let generation = 0;
  const listeners = new Set<() => void>();
  const publish = (patch: Partial<NotesView>) => {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  };
  const run = async (operation: (current: () => boolean) => Promise<void>) => {
    if (state.busy) return false;
    const token = ++generation;
    const current = () => token === generation;
    publish({ busy: true, error: null });
    try {
      await operation(current);
      return current();
    } catch (error) {
      if (current())
        publish({
          error: error instanceof Error ? error.message : 'Request failed',
          phase: state.user ? 'ready' : 'signed-out',
        });
      return false;
    } finally {
      if (current()) publish({ busy: false });
    }
  };
  const load = async (current: () => boolean) => {
    const notes = await session.repository().list();
    if (current()) publish({ notes, phase: 'ready' });
  };
  return {
    snapshot: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    /** Invalidates pending view updates; it cannot undo a mutation already accepted by the server. */
    dispose() {
      generation++;
      publish({ busy: false });
    },
    initialize: () =>
      run(async (current) => {
        const user = await session.session();
        if (!current()) return;
        publish({ user, notes: [], phase: user ? 'loading' : 'signed-out' });
        if (user) await load(current);
      }),
    signIn: (email: string, password: string) =>
      run(async (current) => {
        const user = await session.signIn(email, password);
        if (!current()) return;
        publish({ user, notes: [], phase: 'loading' });
        await load(current);
      }),
    signOut: () =>
      run(async (current) => {
        await session.signOut();
        if (current()) publish({ user: null, notes: [], phase: 'signed-out' });
      }),
    reload: () => run(load),
    create: (input: { title: string; body: string }) =>
      run(async (current) => {
        const note = await session.repository().create(NoteInputSchema.parse(input));
        if (current()) publish({ notes: [note, ...state.notes] });
      }),
    update: (id: string, input: { title: string; body: string }) =>
      run(async (current) => {
        const note = await session.repository().update(id, NoteInputSchema.parse(input));
        if (current())
          publish({ notes: state.notes.map((value) => (value.id === id ? note : value)) });
      }),
    remove: (id: string) =>
      run(async (current) => {
        await session.repository().delete(id);
        if (current()) publish({ notes: state.notes.filter((value) => value.id !== id) });
      }),
  };
}
export type NotesController = ReturnType<typeof createNotesController>;
