import { mkdtemp, readFile, realpath, rm, symlink, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LOCAL_PROJECT_ID, prepareLocalProject, verifyLocalProject } from '../local/prepare';
import { seedAccounts, seedLocalAccounts, type SeedPort, type SeedUser } from '../local/seed';
const directories: string[] = [];
async function temporary() {
  const path = await mkdtemp(join(await realpath(tmpdir()), 'kit-supabase-test-'));
  directories.push(path);
  return path;
}
afterEach(async () => {
  await Promise.all(
    directories.splice(0).map((path) => rm(path, { recursive: true, force: true })),
  );
});

describe('isolated Supabase preparation', () => {
  it('copies the canonical migration, repeats without changing files, and detects changed config', async () => {
    const target = join(await temporary(), 'project');
    const first = await prepareLocalProject(target);
    expect(await prepareLocalProject(target)).toEqual(first);
    expect((await verifyLocalProject(target)).projectId).toBe(LOCAL_PROJECT_ID);
    expect(
      await readFile(join(target, 'supabase/migrations/20261009000000_notes.sql'), 'utf8'),
    ).toContain('enable row level security');
    await writeFile(join(target, 'supabase/config.toml'), 'project_id = "unrelated"');
    await expect(prepareLocalProject(target)).rejects.toThrow('overwrite changed');
    await expect(verifyLocalProject(target)).rejects.toThrow('changed');
  });
  it('refuses unrelated nonempty targets and symlink paths', async () => {
    const parent = await temporary();
    const unrelated = join(parent, 'unrelated');
    await mkdir(unrelated);
    await writeFile(join(unrelated, 'keep.txt'), 'user work');
    await expect(prepareLocalProject(unrelated)).rejects.toThrow('nonempty');
    await symlink(
      unrelated,
      join(parent, 'link'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );
    await expect(prepareLocalProject(join(parent, 'link'))).rejects.toThrow('symlinks');
    expect(await readFile(join(unrelated, 'keep.txt'), 'utf8')).toBe('user work');
  });
});

function fixturePort() {
  const users: SeedUser[] = [];
  const notes = new Map<string, { owner_id: string; title: string }>();
  const port: SeedPort = {
    listUsers: vi.fn(async () => [...users]),
    createUser: vi.fn(async (email) => {
      const user = { id: crypto.randomUUID(), email, app_metadata: { kitDemo: LOCAL_PROJECT_ID } };
      users.push(user);
      return user;
    }),
    noteOwner: async (id) => notes.get(id)?.owner_id ?? null,
    upsertNote: vi.fn(async (note) => {
      notes.set(note.id, note);
    }),
  };
  return { users, notes, port };
}
describe('bounded local demo seed', () => {
  it('creates two accounts and notes, then safely reuses accounts without changing passwords', async () => {
    const { users, notes, port } = fixturePort();
    await seedLocalAccounts(port, 'local-fixture-password');
    await seedLocalAccounts(port, 'different-password');
    expect(users).toHaveLength(2);
    expect(notes.size).toBe(2);
    expect(port.createUser).toHaveBeenCalledTimes(2);
    expect(notes.get(seedAccounts[0].noteId)?.owner_id).toBe(users[0].id);
  });
  it('refuses unmarked accounts and note collisions before any write', async () => {
    const { users, notes, port } = fixturePort();
    users.push({ id: 'user', email: seedAccounts[1].email, app_metadata: {} });
    await expect(seedLocalAccounts(port, 'long-enough-password')).rejects.toThrow(
      'unrelated account',
    );
    expect(port.createUser).not.toHaveBeenCalled();
    users.length = 0;
    notes.set(seedAccounts[0].noteId, { owner_id: 'unrelated', title: 'Keep' });
    await expect(seedLocalAccounts(port, 'long-enough-password')).rejects.toThrow(
      'unrelated account',
    );
    expect(port.upsertNote).not.toHaveBeenCalled();
  });
  it('limits pagination and rejects short passwords without network calls', async () => {
    const { port } = fixturePort();
    await expect(seedLocalAccounts(port, 'short')).rejects.toThrow();
    expect(port.listUsers).not.toHaveBeenCalled();
    port.listUsers = vi.fn(async () =>
      Array.from({ length: 100 }, (_, i) => ({ id: `${i}`, app_metadata: {} })),
    );
    await expect(seedLocalAccounts(port, 'long-enough-password')).rejects.toThrow('500');
    expect(port.listUsers).toHaveBeenCalledTimes(5);
    expect(port.createUser).not.toHaveBeenCalled();
  });
});
