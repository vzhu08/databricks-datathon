import { createClient } from '@supabase/supabase-js';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { z } from 'zod';
import type { Database } from '../src/database.types';
import { LOCAL_API_URL, LOCAL_PROJECT_ID, verifyLocalProject } from './prepare';

export const seedAccounts = [
  {
    email: 'alice@kit-demo.invalid',
    noteId: 'a1111111-1111-4111-8111-111111111111',
    title: 'Alice’s local note',
  },
  {
    email: 'bob@kit-demo.invalid',
    noteId: 'b2222222-2222-4222-8222-222222222222',
    title: 'Bob’s local note',
  },
] as const;
export interface SeedUser {
  id: string;
  email?: string;
  app_metadata: Record<string, unknown>;
}
export interface SeedPort {
  listUsers(page: number): Promise<SeedUser[]>;
  createUser(email: string, password: string): Promise<SeedUser>;
  noteOwner(id: string): Promise<string | null>;
  upsertNote(note: { id: string; owner_id: string; title: string; body: string }): Promise<void>;
}
/** Only the two marked synthetic accounts and their fixed note IDs are changed. */
export async function seedLocalAccounts(port: SeedPort, password: string) {
  z.string().min(12).max(100).parse(password);
  const users: SeedUser[] = [];
  for (let page = 1; page <= 5; page++) {
    const batch = await port.listUsers(page);
    users.push(...batch);
    if (batch.length < 100) break;
    if (page === 5) throw new Error('Demo seed refuses projects containing 500 or more users');
  }
  // Complete ownership preflight before any write, including an interrupted earlier seed.
  for (const account of seedAccounts) {
    const existing = users.find((user) => user.email === account.email);
    if (existing && existing.app_metadata.kitDemo !== LOCAL_PROJECT_ID)
      throw new Error(`Refusing unrelated account: ${account.email}`);
    const owner = await port.noteOwner(account.noteId);
    if (owner && owner !== existing?.id)
      throw new Error('Refusing a fixed seed note ID owned by an unrelated account');
  }
  for (const account of seedAccounts) {
    const user =
      users.find((value) => value.email === account.email) ??
      (await port.createUser(account.email, password));
    await port.upsertNote({
      id: account.noteId,
      owner_id: user.id,
      title: account.title,
      body: 'Synthetic local seed data. RLS should hide this note from the other account.',
    });
  }
  return { users: 2, notes: 2 };
}
export function createSeedPort(serviceRoleKey: string): SeedPort {
  // Intentionally no configurable URL: never direct this admin credential at a hosted project.
  const client = createClient<Database>(LOCAL_API_URL, z.string().min(1).parse(serviceRoleKey), {
    auth: { persistSession: false, autoRefreshToken: false },
    global: {
      fetch: (input, init) => fetch(input, { ...init, signal: AbortSignal.timeout(10_000) }),
    },
  });
  return {
    async listUsers(page) {
      const { data, error } = await client.auth.admin.listUsers({ page, perPage: 100 });
      if (error) throw new Error('Cannot list local seed accounts');
      return data.users;
    },
    async createUser(email, password) {
      const { data, error } = await client.auth.admin.createUser({
        email,
        password,
        email_confirm: true,
        app_metadata: { kitDemo: LOCAL_PROJECT_ID },
      });
      if (error || !data.user) throw new Error('Cannot create local seed account');
      return data.user;
    },
    async noteOwner(id) {
      const { data, error } = await client
        .from('kit_notes')
        .select('owner_id')
        .eq('id', id)
        .maybeSingle();
      if (error) throw new Error('Cannot inspect local note; apply the migration before seeding');
      return data?.owner_id ?? null;
    },
    async upsertNote(note) {
      const { error } = await client.from('kit_notes').upsert(note, { onConflict: 'id' });
      if (error) throw new Error('Cannot seed local note');
    },
  };
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = process.argv.slice(2);
  const apply = args.includes('--apply');
  const rest = args.filter((arg) => arg !== '--apply');
  if (rest.length && (rest.length !== 2 || rest[0] !== '--project-dir'))
    throw new Error('Usage: seed.ts [--project-dir .kit/supabase-demo] [--apply]');
  await verifyLocalProject(rest[1] ?? '.kit/supabase-demo');
  if (!apply)
    console.log(
      `Plan only: create/reuse two marked synthetic accounts and upsert their notes at ${LOCAL_API_URL}. Pass --apply to seed. Existing passwords are never rotated.`,
    );
  else {
    const password = z.string().min(12).max(100).parse(process.env.KIT_DEMO_PASSWORD);
    const key = z.string().min(1).parse(process.env.SUPABASE_SERVICE_ROLE_KEY);
    console.log(await seedLocalAccounts(createSeedPort(key), password));
  }
}
