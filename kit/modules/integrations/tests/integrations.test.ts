import { describe, expect, it } from 'vitest';
import fixture from '../fixtures/sample.json';
import { createHmac } from 'node:crypto';
import {
  LocalDeliverySink,
  FixtureCalendar,
  CalendarEventInputSchema,
  type SendIntent,
} from '../src/index';
import {
  beginGoogleOAuth,
  exchangeGoogleCode,
  refreshGoogleTokens,
  createGoogleCalendar,
  createResendAdapter,
  createSlackAdapter,
  handleSlackWebhook,
  verifySlackSignature,
  WebhookDedupe,
} from '../src/server';
const email = {
  from: 'demo@example.test',
  to: ['judge@example.test'],
  subject: 'Demo ready',
  text: 'Local fixture delivery',
};
const event = {
  summary: 'Demo rehearsal',
  start: '2026-10-09T10:00:00-04:00',
  end: '2026-10-09T10:30:00-04:00',
  timeZone: 'America/New_York',
};
const intent: SendIntent = { authorized: true, idempotencyKey: 'demo1' };
const google = {
  clientId: 'fixture-id',
  clientSecret: 'fixture-secret',
  redirectUri: 'http://localhost/callback',
};
describe('local integration contracts', () => {
  it('deduplicates local delivery, detects conflict, supports reset, and requires action intent', async () => {
    const sink = new LocalDeliverySink();
    const sent = await sink.send(email, intent);
    expect((await sink.send(email, intent)).id).toBe(sent.id);
    expect(sink.emails).toHaveLength(1);
    await expect(sink.send({ ...email, text: 'changed' }, intent)).rejects.toThrow('conflict');
    await sink.post({ channel: 'demo', text: 'Ready' }, intent);
    expect(sink.messages).toHaveLength(1);
    await expect(
      sink.send(email, { ...intent, authorized: false } as unknown as SendIntent),
    ).rejects.toThrow();
    sink.reset();
    expect(sink.emails).toEqual([]);
  });
  it('validates timezone windows and returns fixture events without contacting Google', async () => {
    const calendar = new FixtureCalendar();
    expect(await calendar.list('2026-10-09T00:00:00Z', '2026-10-10T00:00:00Z')).toEqual([]);
    const created = await calendar.create(event, intent);
    expect((await calendar.create(event, intent)).id).toBe(created.id);
    expect((await calendar.list('2026-10-09T00:00:00Z', '2026-10-10T00:00:00Z'))[0].mode).toBe(
      'fixture',
    );
    expect(() => CalendarEventInputSchema.parse({ ...event, timeZone: 'No/SuchZone' })).toThrow();
    expect(() => CalendarEventInputSchema.parse({ ...event, end: event.start })).toThrow();
  });
});
describe('real adapters using mocked HTTP transport', () => {
  it('preserves the calendar response timezone and the creation timezone when events omit it', async () => {
    const adapter = createGoogleCalendar({
      ...google,
      tokens: { accessToken: 'fixture', expiresAt: Date.now() + 3_600_000 },
      saveTokens: async () => {},
      fetcher: async (_url, init) =>
        Response.json(
          init?.method === 'POST' ? fixture.calendarResponse.items[0] : fixture.calendarResponse,
        ),
    });
    expect((await adapter.list('2026-10-09T00:00:00Z', '2026-10-10T00:00:00Z'))[0].timeZone).toBe(
      'America/New_York',
    );
    expect((await adapter.create(event, intent)).timeZone).toBe('America/New_York');
  });
  it('sends Resend idempotency headers and surfaces Slack application errors', async () => {
    let headers: Headers | undefined;
    const resend = createResendAdapter('fixture-secret', async (_, init) => {
      headers = new Headers(init?.headers);
      return Response.json({ id: 'mail1' });
    });
    expect(await resend.send(email, intent)).toEqual({ id: 'mail1', mode: 'live' });
    expect(headers!.get('idempotency-key')).toBe('demo1');
    const slack = createSlackAdapter('fixture-secret', async () =>
      Response.json({ ok: false, error: 'channel_not_found' }),
    );
    await expect(slack.post({ channel: 'bad', text: 'Hello' }, intent)).rejects.toThrow(
      'channel_not_found',
    );
    const good = createSlackAdapter('fixture-secret', async () =>
      Response.json({ ok: true, ts: '1.2' }),
    );
    expect((await good.post({ channel: 'demo', text: 'Hello' }, intent)).id).toBe('1.2');
  });
  it('uses OAuth PKCE, checks state, and preserves refresh tokens', async () => {
    const start = beginGoogleOAuth(google);
    expect(new URL(start.url).searchParams.get('code_challenge_method')).toBe('S256');
    await expect(exchangeGoogleCode(google, { code: 'x', state: 'wrong' }, start)).rejects.toThrow(
      'state',
    );
    const config = {
      ...google,
      fetcher: async () =>
        Response.json({
          access_token: 'access',
          refresh_token: 'refresh',
          expires_in: 3600,
          token_type: 'Bearer',
        }),
    };
    const token = await exchangeGoogleCode(config, { code: 'x', state: start.state }, start);
    expect(token.refreshToken).toBe('refresh');
    const refreshed = await refreshGoogleTokens(
      {
        ...google,
        fetcher: async () =>
          Response.json({ access_token: 'fresh', expires_in: 3600, token_type: 'Bearer' }),
      },
      token,
    );
    expect(refreshed).toMatchObject({ accessToken: 'fresh', refreshToken: 'refresh' });
  });
  it('refreshes before calendar access, reads timed events and emits zoned creation data', async () => {
    const saved: string[] = [];
    const calls: { url: string; body: string }[] = [];
    const calendar = createGoogleCalendar({
      ...google,
      tokens: { accessToken: 'expired', refreshToken: 'refresh', expiresAt: 0 },
      saveTokens: async (tokens) => {
        saved.push(tokens.accessToken);
      },
      fetcher: async (url, init) => {
        calls.push({ url: String(url), body: String(init?.body ?? '') });
        if (String(url).includes('oauth2'))
          return Response.json({ access_token: 'fresh', expires_in: 3600, token_type: 'Bearer' });
        const result = {
          id: 'evt',
          summary: event.summary,
          start: { dateTime: event.start, timeZone: event.timeZone },
          end: { dateTime: event.end, timeZone: event.timeZone },
        };
        return Response.json(init?.method === 'POST' ? result : { items: [result] });
      },
    });
    expect((await calendar.list('2026-10-09T00:00:00Z', '2026-10-10T00:00:00Z'))[0].timeZone).toBe(
      'America/New_York',
    );
    expect(saved).toEqual(['fresh']);
    await calendar.create(event, intent);
    expect(JSON.parse(calls.at(-1)!.body).start.timeZone).toBe(event.timeZone);
    expect(calls.at(-1)!.url).toContain('sendUpdates=none');
  });
});
describe('signed inbound webhooks', () => {
  const secret = 'fixture-signing-secret';
  function request(body: string, offset = 0) {
    const timestamp = String(Math.floor(Date.now() / 1000) + offset);
    const signature = `v0=${createHmac('sha256', secret).update(`v0:${timestamp}:${body}`).digest('hex')}`;
    return new Request('http://localhost/webhook', {
      method: 'POST',
      body,
      headers: { 'x-slack-request-timestamp': timestamp, 'x-slack-signature': signature },
    });
  }
  it('verifies raw bytes and timestamp, normalizes event, and deduplicates', async () => {
    const body = JSON.stringify({
      type: 'event_callback',
      event_id: 'ev1',
      event: { type: 'message', text: 'hi' },
    });
    const valid = request(body);
    expect(verifySlackSignature(body, valid.headers, secret)).toBe(true);
    expect(verifySlackSignature(`${body} `, valid.headers, secret)).toBe(false);
    expect(verifySlackSignature(body, request(body, -301).headers, secret)).toBe(false);
    const seen: string[] = [];
    const options = {
      secret,
      dedupe: new WebhookDedupe(),
      handle: async (event: { id: string }) => {
        seen.push(event.id);
      },
    };
    expect((await handleSlackWebhook(request(body), options)).status).toBe(200);
    expect(await (await handleSlackWebhook(request(body), options)).json()).toMatchObject({
      duplicate: true,
    });
    expect(seen).toEqual(['ev1']);
    expect((await handleSlackWebhook(request(body, -301), options)).status).toBe(401);
  });
  it('does not mark failed handlers as processed, including concurrent retries', async () => {
    const dedupe = new WebhookDedupe(1);
    let reject: (error: Error) => void = () => {};
    const first = dedupe.run(
      'x',
      () =>
        new Promise<void>((_, fail) => {
          reject = fail;
        }),
    );
    const second = dedupe.run('x', async () => {});
    await Promise.resolve();
    reject(new Error('failure'));
    const results = await Promise.allSettled([first, second]);
    expect(results.every((result) => result.status === 'rejected')).toBe(true);
    expect(await dedupe.run('x', async () => {})).toBe(true);
    await expect(dedupe.run('y', async () => {})).rejects.toThrow('capacity');
  });
});
