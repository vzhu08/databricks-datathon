import { z } from 'zod';
import {
  createLocalNotes,
  NoteInputSchema,
  NoteSchema,
  type Note,
  type NoteRepository,
} from '../../src/index';

export const DemoUserSchema = z.object({ id: z.uuid(), email: z.email().optional() });
export type DemoUser = z.infer<typeof DemoUserSchema>;
export interface NotesSession {
  readonly mode: 'fixture' | 'live';
  session(): Promise<DemoUser | null>;
  signIn(email: string, password: string): Promise<DemoUser>;
  signOut(): Promise<void>;
  repository(): NoteRepository;
  setFailure?(enabled: boolean): void;
}
export const fixtureAccounts = [
  { id: '11111111-1111-4111-8111-111111111111', email: 'alice@kit-demo.invalid' },
  { id: '22222222-2222-4222-8222-222222222222', email: 'bob@kit-demo.invalid' },
] as const;
export const fixturePassword = 'fixture-only';

/** An in-memory, per-widget fixture. It does not authenticate with Supabase. */
export function createFixtureSession(delayMs = 150): NotesSession {
  const rows = new Map<string, Note>();
  let user: DemoUser | null = null;
  let failure = false;
  const before = async () => {
    if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (failure) throw new Error('Simulated request failure. Disable it and retry.');
  };
  return {
    mode: 'fixture',
    setFailure(enabled) {
      failure = enabled;
    },
    async session() {
      await before();
      return user;
    },
    async signIn(email, password) {
      await before();
      const found = fixtureAccounts.find((account) => account.email === email.trim().toLowerCase());
      if (!found || password !== fixturePassword)
        throw new Error('Fixture credentials did not match.');
      user = { ...found };
      return user;
    },
    async signOut() {
      await before();
      user = null;
    },
    repository() {
      if (!user) throw new Error('Sign in required');
      const owner = user.id;
      const repository = createLocalNotes(owner, rows);
      const guarded = async <T>(operation: () => Promise<T>) => {
        await before();
        if (user?.id !== owner) throw new Error('Session changed. Sign in again.');
        return operation();
      };
      return {
        list: () => guarded(() => repository.list()),
        create: (input) => guarded(() => repository.create(input)),
        update: (id, input) => guarded(() => repository.update(id, input)),
        delete: (id) => guarded(() => repository.delete(id)),
      };
    },
  };
}

/** Same-origin HTTP only. The server owns cookies, verified auth, and the RLS-backed repository. */
export function createLiveSession(fetcher: typeof fetch = fetch): NotesSession {
  const call = async (url: string, method = 'GET', body?: unknown): Promise<unknown> => {
    const response = await fetcher(url, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(15_000),
    });
    const data: unknown = await response.json();
    if (!response.ok) {
      const error = z.object({ error: z.string().max(1000) }).safeParse(data);
      throw new Error(error.success ? error.data.error : `Request failed (${response.status})`);
    }
    return data;
  };
  const sessionSchema = z.object({ user: DemoUserSchema.nullable() });
  const repository: NoteRepository = {
    list: async () => z.array(NoteSchema).parse(await call('/api/notes')),
    create: async (input) =>
      NoteSchema.parse(await call('/api/notes', 'POST', NoteInputSchema.parse(input))),
    update: async (id, input) =>
      NoteSchema.parse(
        await call(`/api/notes?id=${z.uuid().parse(id)}`, 'PATCH', NoteInputSchema.parse(input)),
      ),
    delete: async (id) => {
      await call(`/api/notes?id=${z.uuid().parse(id)}`, 'DELETE');
    },
  };
  return {
    mode: 'live',
    session: async () => sessionSchema.parse(await call('/api/auth?action=session')).user,
    async signIn(email, password) {
      const user = sessionSchema.parse(
        await call('/api/auth?action=signin', 'POST', { email, password }),
      ).user;
      if (!user) throw new Error('Sign in did not create a session');
      return user;
    },
    async signOut() {
      await call('/api/auth?action=signout', 'POST');
    },
    repository: () => repository,
  };
}
