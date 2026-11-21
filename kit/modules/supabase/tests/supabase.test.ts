import { describe, expect, it } from 'vitest';
import { createLocalNotes, loadNotes, NoteSchema, type Note } from '../src/index';
import { createSupabaseBrowser } from '../src/browser';
import { createSupabaseServer, handleAuthRequest } from '../src/server';
import { uploadOwnedFile } from '../src/data';
const alice = '11111111-1111-4111-8111-111111111111';
const bob = '22222222-2222-4222-8222-222222222222';
describe('Supabase local contracts', () => {
  it('stops oversized chunked sign-in bodies before reading the full stream', async () => {
    const client = createSupabaseServer(
      { url: 'http://127.0.0.1:54321', publishableKey: 'fixture-public-key' },
      { getAll: () => [], setAll: () => {} },
    );
    let chunks = 0;
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (++chunks <= 20) controller.enqueue(new Uint8Array(2048));
        else controller.close();
      },
      cancel() {
        cancelled = true;
      },
    });
    const request = new Request('http://localhost/api/auth?action=signin', {
      method: 'POST',
      headers: { origin: 'http://localhost' },
      body,
      duplex: 'half',
    } as RequestInit);
    expect((await handleAuthRequest(request, client, 'http://localhost')).status).toBe(413);
    expect(chunks).toBeLessThan(20);
    expect(cancelled).toBe(true);
    const malformed = new Request('http://localhost/api/auth?action=signin', {
      method: 'POST',
      headers: { origin: 'http://localhost' },
      body: new Uint8Array([0xff]),
    });
    expect((await handleAuthRequest(malformed, client, 'http://localhost')).status).toBe(400);
  });
  it('performs owner-isolated CRUD and exposes empty/error states', async () => {
    const rows = new Map<string, Note>();
    const a = createLocalNotes(alice, rows);
    const b = createLocalNotes(bob, rows);
    expect(await loadNotes(a)).toEqual({ status: 'empty' });
    const note = await a.create({ title: 'Demo', body: 'Private evidence' });
    expect((await a.list())[0].id).toBe(note.id);
    expect(await b.list()).toEqual([]);
    await expect(b.update(note.id, { title: 'Stolen', body: '' })).rejects.toThrow('not found');
    await expect(b.delete(note.id)).rejects.toThrow('not found');
    await a.update(note.id, { title: 'Edited', body: 'Updated' });
    expect((await loadNotes(a)).status).toBe('ready');
    await a.delete(note.id);
    expect(await a.list()).toEqual([]);
    expect(
      await loadNotes({
        ...a,
        list: async () => {
          throw new Error('Offline');
        },
      }),
    ).toEqual({ status: 'error', message: 'Offline' });
  });
  it('validates title, user and timezone offsets', async () => {
    expect(() => createLocalNotes('bad')).toThrow();
    await expect(createLocalNotes(alice).create({ title: ' ', body: '' })).rejects.toThrow();
    expect(
      NoteSchema.parse({
        id: alice,
        owner_id: alice,
        title: 'OK',
        body: '',
        created_at: '2026-10-09T00:00:00+00:00',
      }).title,
    ).toBe('OK');
  });
  it('constructs separate clients without using privileged keys or network', () => {
    const config = { url: 'http://127.0.0.1:54321', publishableKey: 'fixture-public-key' };
    expect(createSupabaseBrowser(config)).toBeDefined();
    expect(createSupabaseServer(config, { getAll: () => [], setAll: () => {} })).toBeDefined();
  });
  it('rejects cross-origin auth mutation and oversized or unsupported files before transport', async () => {
    const client = createSupabaseServer(
      { url: 'http://127.0.0.1:54321', publishableKey: 'fixture-public-key' },
      { getAll: () => [], setAll: () => {} },
    );
    expect(
      (
        await handleAuthRequest(
          new Request('http://localhost/api/auth?action=signin', {
            method: 'POST',
            headers: { origin: 'https://foreign.example' },
            body: '{}',
          }),
          client,
          'http://localhost',
        )
      ).status,
    ).toBe(403);
    await expect(
      uploadOwnedFile(client, new Blob(['x'], { type: 'text/html' }), 'bad.html'),
    ).rejects.toThrow('Unsupported');
  });
});
