import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
const state = vi.hoisted(() => ({
  plans: [] as { status: number; headers?: Record<string, string>; body?: string }[],
  calls: [] as { url: string; addresses: unknown }[],
}));
vi.mock('node:https', () => ({
  request: (
    url: URL,
    options: {
      lookup: (
        hostname: string,
        options: { all: true },
        callback: (error: unknown, addresses: unknown) => void,
      ) => void;
    },
    receive: (
      response: PassThrough & { statusCode: number; headers: Record<string, string> },
    ) => void,
  ) => {
    const req = new EventEmitter() as EventEmitter & {
      end: () => void;
      destroy: (error: Error) => void;
    };
    req.destroy = (error) => {
      queueMicrotask(() => req.emit('error', error));
    };
    req.end = () =>
      queueMicrotask(() => {
        options.lookup(url.hostname, { all: true }, (_error, addresses) =>
          state.calls.push({ url: url.href, addresses }),
        );
        const plan = state.plans.shift();
        if (!plan) {
          req.emit('error', new Error('Unplanned network call'));
          return;
        }
        const res = Object.assign(new PassThrough(), {
          statusCode: plan.status,
          headers: plan.headers ?? { 'content-type': 'text/html' },
        });
        receive(res);
        if (!res.destroyed) res.end(plan.body ?? '');
      });
    return req;
  },
}));
import { safeFetchHTML } from '../src/server';
const resolver = async () => [{ address: '93.184.216.34', family: 4 }];
beforeEach(() => {
  state.plans = [];
  state.calls = [];
});
describe('DNS-pinned network transport', () => {
  it('pins prevalidated DNS and resolves a public relative redirect', async () => {
    state.plans = [
      { status: 302, headers: { location: '/article' } },
      { status: 200, body: '<p>Evidence</p>' },
    ];
    const r = await safeFetchHTML('https://example.org/start', { resolver });
    expect(r.finalURL).toBe('https://example.org/article');
    expect(r.html).toContain('Evidence');
    expect(state.calls).toHaveLength(2);
    expect(state.calls[0]!.addresses).toEqual([{ address: '93.184.216.34', family: 4 }]);
  });
  it('rejects redirects into metadata and private networks before connection', async () => {
    state.plans = [
      { status: 302, headers: { location: 'http://169.254.169.254/latest/meta-data' } },
    ];
    await expect(safeFetchHTML('https://example.org', { resolver })).rejects.toMatchObject({
      code: 'UNSAFE_URL',
    });
    expect(state.calls).toHaveLength(1);
  });
  it('bounds redirects, response bytes and content type', async () => {
    state.plans = [{ status: 302, headers: { location: '/again' } }];
    await expect(
      safeFetchHTML('https://example.org', { resolver, maxRedirects: 0 }),
    ).rejects.toMatchObject({ code: 'TOO_MANY_REDIRECTS' });
    state.plans = [{ status: 200, body: 'way too large' }];
    await expect(
      safeFetchHTML('https://example.org', { resolver, maxBytes: 2 }),
    ).rejects.toMatchObject({ code: 'RESPONSE_TOO_LARGE' });
    state.plans = [{ status: 200, headers: { 'content-type': 'application/pdf' } }];
    await expect(safeFetchHTML('https://example.org', { resolver })).rejects.toMatchObject({
      code: 'UNSUPPORTED_CONTENT',
    });
  });
  it('times out DNS resolution without issuing a request', async () => {
    await expect(
      safeFetchHTML('https://example.org', { resolver: () => new Promise(() => {}), timeoutMs: 5 }),
    ).rejects.toThrow();
    expect(state.calls).toHaveLength(0);
  });
});
