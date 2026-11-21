import { expect, it } from 'vitest';
import { createClient } from '@supabase/supabase-js';
import { randomUUID } from 'node:crypto';
import type { Database } from '../src/database.types';
import {
  createSupabaseNotes,
  uploadOwnedFile,
  signedFileUrl,
  downloadOwnedFile,
} from '../src/data';

// Explicit integration opt-in only; uses disposable accounts and deletes only records it created.
it.skipIf(process.env.RUN_SUPABASE_INTEGRATION !== 'true')(
  'enforces database and storage RLS across two real authenticated users',
  async () => {
    const url = process.env.SUPABASE_URL!;
    const key = process.env.SUPABASE_PUBLISHABLE_KEY!;
    const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;
    if (!url || !key || !serviceKey)
      throw new Error('Set SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and SUPABASE_SERVICE_ROLE_KEY');
    if (
      !['localhost', '127.0.0.1'].includes(new URL(url).hostname) &&
      process.env.ALLOW_HOSTED_SUPABASE_TEST !== 'true'
    )
      throw new Error('Hosted test accounts require ALLOW_HOSTED_SUPABASE_TEST=true');
    const options = { auth: { persistSession: false, autoRefreshToken: false } };
    const admin = createClient<Database>(url, serviceKey, options);
    const users: string[] = [];
    let objectPath: string | undefined;
    try {
      const clients = [];
      for (let i = 0; i < 2; i++) {
        const email = `kit-${randomUUID()}@example.test`;
        const password = `${randomUUID()}Aa!`;
        const created = await admin.auth.admin.createUser({ email, password, email_confirm: true });
        if (created.error || !created.data.user) throw created.error;
        users.push(created.data.user.id);
        const client = createClient<Database>(url, key, options);
        const login = await client.auth.signInWithPassword({ email, password });
        if (login.error) throw login.error;
        clients.push(client);
      }
      const [a, b] = clients;
      const repoA = createSupabaseNotes(a);
      const repoB = createSupabaseNotes(b);
      const note = await repoA.create({ title: 'Disposable RLS test', body: 'Private' });
      expect((await repoA.list()).some((n) => n.id === note.id)).toBe(true);
      expect((await repoB.list()).some((n) => n.id === note.id)).toBe(false);
      await expect(
        repoB.update(note.id, { title: 'Unauthorized', body: '' }),
      ).rejects.toBeDefined();
      await expect(repoB.delete(note.id)).rejects.toBeDefined();
      const forged = await b
        .from('kit_notes')
        .insert({ owner_id: users[0], title: 'Forged owner' });
      expect(forged.error).toBeTruthy();
      objectPath = await uploadOwnedFile(
        a,
        new Blob(['fixture'], { type: 'text/plain' }),
        `${randomUUID()}.txt`,
      );
      expect(await (await downloadOwnedFile(a, objectPath)).text()).toBe('fixture');
      expect(await signedFileUrl(a, objectPath)).toContain('token=');
      await expect(downloadOwnedFile(b, objectPath)).rejects.toBeDefined();
      await expect(signedFileUrl(b, objectPath)).rejects.toBeDefined();
      await repoA.delete(note.id);
    } finally {
      if (objectPath) await admin.storage.from('kit-private').remove([objectPath]);
      for (const user of users) await admin.auth.admin.deleteUser(user);
    }
  },
  30_000,
);
