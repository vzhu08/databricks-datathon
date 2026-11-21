import { describe, expect, it, vi } from 'vitest';
import { createNotesController } from '../examples/components/controller';
import {
  createFixtureSession,
  createLiveSession,
  fixtureAccounts,
  fixturePassword,
  type NotesSession,
} from '../examples/components/session';
import { createNotesHandler } from '../examples/server/notes-route';
import { createLocalNotes } from '../src/index';
import { KitError } from '../../../packages/runtime/src/index';

describe('optional notes example', () => {
  it('shows loading, signed-out, empty, CRUD, error/retry, and account isolation', async () => {
    const session = createFixtureSession(0);
    const controller = createNotesController(session);
    expect(controller.snapshot().phase).toBe('loading');
    await controller.initialize();
    expect(controller.snapshot().phase).toBe('signed-out');
    expect(await controller.signIn(fixtureAccounts[0].email, 'wrong')).toBe(false);
    expect(controller.snapshot().error).toContain('credentials');
    await controller.signIn(fixtureAccounts[0].email, fixturePassword);
    expect(controller.snapshot().notes).toEqual([]);
    await controller.create({ title: 'Private', body: 'Alice' });
    const id = controller.snapshot().notes[0].id;
    await controller.update(id, { title: 'Updated', body: 'Still Alice' });
    expect(controller.snapshot().notes[0].title).toBe('Updated');
    session.setFailure!(true);
    expect(await controller.remove(id)).toBe(false);
    expect(controller.snapshot().notes).toHaveLength(1);
    expect(controller.snapshot().error).toContain('Simulated');
    session.setFailure!(false);
    expect(await controller.reload()).toBe(true);
    await controller.signOut();
    expect(controller.snapshot().notes).toEqual([]);
    await controller.signIn(fixtureAccounts[1].email, fixturePassword);
    expect(controller.snapshot().notes).toEqual([]);
    expect(await controller.remove(id)).toBe(false);
    await controller.signOut();
    await controller.signIn(fixtureAccounts[0].email, fixturePassword);
    await controller.remove(id);
    expect(controller.snapshot().notes).toEqual([]);
  });
  it('serializes actions and ignores an unmounted session completion', async () => {
    let resolveSession!: (user: (typeof fixtureAccounts)[0] | null) => void;
    const session: NotesSession = {
      ...createFixtureSession(0),
      session: vi.fn(
        () =>
          new Promise<(typeof fixtureAccounts)[0] | null>((resolve) => {
            resolveSession = resolve;
          }),
      ),
    };
    const controller = createNotesController(session);
    const pending = controller.initialize();
    expect(controller.snapshot().busy).toBe(true);
    expect(await controller.initialize()).toBe(false);
    expect(session.session).toHaveBeenCalledTimes(1);
    controller.dispose();
    resolveSession(fixtureAccounts[0]);
    expect(await pending).toBe(false);
    expect(controller.snapshot().user).toBeNull();
    expect(controller.snapshot().busy).toBe(false);
  });
  it('guards stale fixture repositories after account changes', async () => {
    const session = createFixtureSession(0);
    await session.signIn(fixtureAccounts[0].email, fixturePassword);
    const stale = session.repository();
    await session.signOut();
    await session.signIn(fixtureAccounts[1].email, fixturePassword);
    await expect(stale.create({ title: 'wrong owner', body: '' })).rejects.toThrow(
      'Session changed',
    );
  });
  it('keeps live failures visible, validates responses, and bounds requests', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ error: 'Sign in required' }, { status: 401 }));
    const session = createLiveSession(fetcher);
    await expect(session.repository().list()).rejects.toThrow('Sign in required');
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      credentials: 'same-origin',
      cache: 'no-store',
      signal: expect.any(AbortSignal),
    });
    fetcher.mockResolvedValueOnce(Response.json({ user: { id: 'malformed' } }));
    await expect(session.signIn('a@example.test', 'password')).rejects.toThrow();
    fetcher.mockResolvedValueOnce(Response.json({ user: fixtureAccounts[0] }));
    expect(await session.signIn('alice@kit-demo.invalid', 'password')).toEqual(fixtureAccounts[0]);
  });
});

describe('optional authenticated notes endpoint', () => {
  const origin = 'http://127.0.0.1:3004';
  const request = (method: string, body?: unknown, query = '') =>
    new Request(`${origin}/api/notes${query}`, {
      method,
      headers: { origin, 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  it('uses the session repository for real route CRUD and strict input validation', async () => {
    const repository = createLocalNotes(fixtureAccounts[0].id);
    const authorize = vi.fn(async () => repository);
    const handler = createNotesHandler({ siteUrl: origin, authorize });
    expect(await (await handler(request('GET'))).json()).toEqual([]);
    const created = await handler(request('POST', { title: 'Route test', body: '' }));
    expect(created.status).toBe(201);
    const note = await created.json();
    expect(note.owner_id).toBe(fixtureAccounts[0].id);
    expect(
      (
        await handler(
          request('POST', { title: 'forged', body: '', owner_id: fixtureAccounts[1].id }),
        )
      ).status,
    ).toBe(400);
    expect(
      (await handler(request('PATCH', { title: 'Edited', body: 'a' }, `?id=${note.id}`))).status,
    ).toBe(200);
    expect((await repository.list())[0].title).toBe('Edited');
    expect((await handler(request('DELETE', undefined, `?id=${note.id}`))).status).toBe(200);
    expect(await repository.list()).toEqual([]);
    expect(authorize).toHaveBeenCalledTimes(5);
  });
  it('requires authentication, protects mutations from foreign origins, and bounds raw bodies', async () => {
    const authorize = vi.fn(async () => {
      throw new KitError('unauthorized', 'Sign in required', 401);
    });
    const handler = createNotesHandler({ siteUrl: origin, authorize });
    expect((await handler(request('GET'))).status).toBe(401);
    expect(
      (
        await handler(
          new Request(`${origin}/api/notes`, {
            method: 'POST',
            headers: { origin: 'https://foreign.example' },
            body: '{}',
          }),
        )
      ).status,
    ).toBe(403);
    expect((await handler(request('PUT'))).status).toBe(405);
    expect(authorize).toHaveBeenCalledTimes(1);
    const authorized = createNotesHandler({
      siteUrl: origin,
      authorize: async () => createLocalNotes(fixtureAccounts[0].id),
    });
    expect(
      (await authorized(request('POST', { title: 'Huge', body: 'x'.repeat(210_001) }))).status,
    ).toBe(413);
    expect((await authorized(request('DELETE', undefined, '?id=bad'))).status).toBe(400);
  });
});
