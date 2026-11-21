import { createHash, randomBytes, createHmac, timingSafeEqual } from 'node:crypto';
import { z } from 'zod';
import { httpJson } from '../../../packages/runtime/src/index';
import {
  EmailSchema,
  NotificationSchema,
  CalendarEventInputSchema,
  SendIntentSchema,
  validateWindow,
  type EmailAdapter,
  type MessagingAdapter,
  type CalendarAdapter,
  type CalendarEvent,
  type CalendarEventInput,
} from './index';
export function createResendAdapter(apiKey: string, fetcher?: typeof fetch): EmailAdapter {
  if (!apiKey) throw new Error('Resend API key required');
  return {
    async send(message, intent) {
      SendIntentSchema.parse(intent);
      const body = EmailSchema.parse(message);
      const result = await httpJson('https://api.resend.com/emails', z.object({ id: z.string() }), {
        method: 'POST',
        headers: {
          authorization: `Bearer ${apiKey}`,
          'content-type': 'application/json',
          'idempotency-key': intent.idempotencyKey,
        },
        body: JSON.stringify(body),
        fetcher,
      });
      return { id: result.id, mode: 'live' };
    },
  };
}
export function createSlackAdapter(botToken: string, fetcher?: typeof fetch): MessagingAdapter {
  if (!botToken) throw new Error('Slack bot token required');
  return {
    async post(message, intent) {
      SendIntentSchema.parse(intent);
      const body = NotificationSchema.parse(message);
      const result = await httpJson(
        'https://slack.com/api/chat.postMessage',
        z.object({ ok: z.boolean(), ts: z.string().optional(), error: z.string().optional() }),
        {
          method: 'POST',
          headers: { authorization: `Bearer ${botToken}`, 'content-type': 'application/json' },
          body: JSON.stringify({ ...body, unfurl_links: false, unfurl_media: false }),
          fetcher,
        },
      );
      if (!result.ok || !result.ts)
        throw new Error(`Slack rejected message: ${result.error ?? 'missing timestamp'}`);
      return { id: result.ts, mode: 'live' };
    },
  };
}
const TokenResponseSchema = z.object({
  access_token: z.string(),
  expires_in: z.number().positive(),
  refresh_token: z.string().optional(),
  token_type: z.string(),
});
export type OAuthTokens = { accessToken: string; expiresAt: number; refreshToken?: string };
export type GoogleOAuthConfig = {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  fetcher?: typeof fetch;
};
const calendarScope = 'https://www.googleapis.com/auth/calendar.events';
export function beginGoogleOAuth(config: Pick<GoogleOAuthConfig, 'clientId' | 'redirectUri'>) {
  const state = randomBytes(32).toString('base64url');
  const verifier = randomBytes(32).toString('base64url');
  const url = new URL('https://accounts.google.com/o/oauth2/v2/auth');
  url.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: 'code',
    scope: calendarScope,
    state,
    code_challenge: createHash('sha256').update(verifier).digest('base64url'),
    code_challenge_method: 'S256',
    access_type: 'offline',
    prompt: 'consent',
  }).toString();
  return { url: url.href, state, verifier, expiresAt: Date.now() + 600_000 };
}
export async function exchangeGoogleCode(
  config: GoogleOAuthConfig,
  input: { code: string; state: string },
  session: { state: string; verifier: string; expiresAt: number },
): Promise<OAuthTokens> {
  const supplied = Buffer.from(input.state);
  const expected = Buffer.from(session.state);
  if (
    Date.now() > session.expiresAt ||
    supplied.length !== expected.length ||
    !timingSafeEqual(supplied, expected)
  )
    throw new Error('Invalid or expired OAuth state');
  const token = await httpJson('https://oauth2.googleapis.com/token', TokenResponseSchema, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: config.clientId,
      client_secret: config.clientSecret,
      redirect_uri: config.redirectUri,
      code: input.code,
      code_verifier: session.verifier,
      grant_type: 'authorization_code',
    }),
    fetcher: config.fetcher,
  });
  return {
    accessToken: token.access_token,
    refreshToken: token.refresh_token,
    expiresAt: Date.now() + token.expires_in * 1000,
  };
}
export async function refreshGoogleTokens(
  config: GoogleOAuthConfig,
  tokens: OAuthTokens,
): Promise<OAuthTokens> {
  if (!tokens.refreshToken) throw new Error('Reconnect Google Calendar: refresh token unavailable');
  const result = await httpJson('https://oauth2.googleapis.com/token', TokenResponseSchema, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: config.clientId,
      client_secret: config.clientSecret,
      refresh_token: tokens.refreshToken,
      grant_type: 'refresh_token',
    }),
    fetcher: config.fetcher,
  });
  return {
    accessToken: result.access_token,
    refreshToken: result.refresh_token ?? tokens.refreshToken,
    expiresAt: Date.now() + result.expires_in * 1000,
  };
}
const GoogleEventSchema = z.object({
  id: z.string(),
  summary: z.string().optional(),
  description: z.string().optional(),
  status: z.string().optional(),
  start: z.object({
    dateTime: z.string().optional(),
    date: z.string().optional(),
    timeZone: z.string().optional(),
  }),
  end: z.object({
    dateTime: z.string().optional(),
    date: z.string().optional(),
    timeZone: z.string().optional(),
  }),
});
function calendarEvent(
  value: z.infer<typeof GoogleEventSchema>,
  fallbackTimeZone?: string,
): CalendarEvent {
  if (!value.start.dateTime || !value.end.dateTime)
    throw new Error('All-day calendar events require the date-only extension described in README');
  return {
    ...CalendarEventInputSchema.parse({
      summary: value.summary ?? '(untitled)',
      start: value.start.dateTime,
      end: value.end.dateTime,
      timeZone: value.start.timeZone ?? fallbackTimeZone,
      description: value.description,
    }),
    id: value.id,
    mode: 'live',
  };
}
export function createGoogleCalendar(
  config: GoogleOAuthConfig & {
    calendarId?: string;
    tokens: OAuthTokens;
    saveTokens(tokens: OAuthTokens): Promise<void>;
  },
): CalendarAdapter {
  let tokens = config.tokens;
  let refreshing: Promise<void> | undefined;
  async function auth() {
    if (tokens.expiresAt - Date.now() < 60_000) {
      refreshing ??= refreshGoogleTokens(config, tokens)
        .then(async (fresh) => {
          await config.saveTokens(fresh);
          tokens = fresh;
        })
        .finally(() => {
          refreshing = undefined;
        });
      await refreshing;
    }
    return { authorization: `Bearer ${tokens.accessToken}`, 'content-type': 'application/json' };
  }
  const base = `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(config.calendarId ?? 'primary')}/events`;
  return {
    async list(from, to) {
      validateWindow(from, to);
      const events: CalendarEvent[] = [];
      let pageToken: string | undefined;
      for (let page = 0; page < 10; page++) {
        const url = new URL(base);
        url.search = new URLSearchParams({
          timeMin: from,
          timeMax: to,
          singleEvents: 'true',
          orderBy: 'startTime',
          maxResults: '100',
          ...(pageToken ? { pageToken } : {}),
        }).toString();
        const response = await httpJson(
          url,
          z.object({
            items: z.array(GoogleEventSchema).default([]),
            nextPageToken: z.string().optional(),
            timeZone: z.string().optional(),
          }),
          { headers: await auth(), fetcher: config.fetcher, retries: 1 },
        );
        for (const event of response.items)
          if (event.status !== 'cancelled') events.push(calendarEvent(event, response.timeZone));
        pageToken = response.nextPageToken;
        if (!pageToken) return events;
      }
      throw new Error('Calendar result exceeds 1000 events; narrow the time window');
    },
    async create(input: CalendarEventInput, intent) {
      SendIntentSchema.parse(intent);
      const event = CalendarEventInputSchema.parse(input);
      const id = createHash('sha256').update(intent.idempotencyKey).digest('hex');
      const response = await httpJson(`${base}?sendUpdates=none`, GoogleEventSchema, {
        method: 'POST',
        headers: await auth(),
        body: JSON.stringify({
          id,
          summary: event.summary,
          description: event.description,
          start: { dateTime: event.start, timeZone: event.timeZone },
          end: { dateTime: event.end, timeZone: event.timeZone },
        }),
        fetcher: config.fetcher,
      });
      return calendarEvent(response, event.timeZone);
    },
  };
}
export function verifySlackSignature(
  rawBody: string,
  headers: Headers,
  secret: string,
  now = Date.now(),
) {
  const timestamp = headers.get('x-slack-request-timestamp') ?? '';
  const signature = headers.get('x-slack-signature') ?? '';
  if (
    !secret ||
    !/^\d{10,}$/.test(timestamp) ||
    Math.abs(now / 1000 - Number(timestamp)) > 300 ||
    !/^v0=[a-f0-9]{64}$/.test(signature)
  )
    return false;
  const expected = `v0=${createHmac('sha256', secret).update(`v0:${timestamp}:${rawBody}`).digest('hex')}`;
  return timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
}
export type InboundEvent = {
  id: string;
  source: 'slack';
  type: string;
  data: Record<string, unknown>;
};
/** Local bounded dedupe. Multi-instance deployments must inject a shared durable reservation implementation. */
export class WebhookDedupe {
  private seen = new Map<string, number>();
  private active = new Map<string, Promise<void>>();
  constructor(
    private capacity = 10_000,
    private ttlMs = 86_400_000,
  ) {}
  async run(id: string, handler: () => Promise<void>) {
    const now = Date.now();
    for (const [key, expiry] of this.seen) if (expiry <= now) this.seen.delete(key);
    if (this.seen.has(id)) return false;
    const running = this.active.get(id);
    if (running) {
      await running;
      return false;
    }
    if (this.seen.size + this.active.size >= this.capacity)
      throw new Error('Webhook dedupe capacity reached');
    const operation = Promise.resolve().then(handler);
    this.active.set(id, operation);
    try {
      await operation;
      this.seen.set(id, now + this.ttlMs);
      return true;
    } finally {
      this.active.delete(id);
    }
  }
}
export async function handleSlackWebhook(
  request: Request,
  options: { secret: string; dedupe: WebhookDedupe; handle(event: InboundEvent): Promise<void> },
): Promise<Response> {
  if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
  const reader = request.body?.getReader();
  if (!reader) return new Response('Missing body', { status: 400 });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 1_000_000) {
        await reader.cancel();
        return new Response('Payload too large', { status: 413 });
      }
      chunks.push(value);
    }
  } catch {
    return new Response('Body read failed', { status: 400 });
  }
  const body = Buffer.concat(chunks).toString('utf8');
  if (!verifySlackSignature(body, request.headers, options.secret))
    return new Response('Invalid signature', { status: 401 });
  let payload;
  try {
    payload = z
      .object({
        type: z.string(),
        challenge: z.string().optional(),
        event_id: z.string().optional(),
        event: z.record(z.string(), z.unknown()).optional(),
      })
      .parse(JSON.parse(body));
  } catch {
    return new Response('Invalid payload', { status: 400 });
  }
  try {
    if (payload.type === 'url_verification' && payload.challenge)
      return Response.json({ challenge: payload.challenge });
    if (!payload.event_id || !payload.event) return new Response('Missing event', { status: 400 });
    const event: InboundEvent = {
      id: payload.event_id,
      source: 'slack',
      type: String(payload.event.type ?? 'unknown'),
      data: payload.event,
    };
    const processed = await options.dedupe.run(event.id, () => options.handle(event));
    return Response.json({ accepted: true, duplicate: !processed });
  } catch {
    return new Response('Webhook processing failed', { status: 500 });
  }
}
