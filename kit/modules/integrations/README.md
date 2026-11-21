# Email, calendar, messaging and inbound webhooks

## 1. What problem does this solve, and when should I use it?

Use narrow, typed adapters for Resend email, Google Calendar timed events, Slack notifications and signed Slack inbound events. Local delivery sinks and fixture calendars keep demos deterministic and free of outbound actions. All outbound mutation methods require an explicit `{authorized:true,idempotencyKey}` application intent.

## 2. What is the smallest working example?

`node --import tsx modules/integrations/examples/demo.ts` delivers one email and notification to memory and creates a fixture calendar event. No provider is called. Import `LocalDeliverySink` and `FixtureCalendar` from `src/index.ts`. The live adapters live in `src/server.ts` and are constructed only by application server code.

## 3. How do I add it to a fresh project or an existing project?

Select `integrations`; preserve shared runtime utilities and Zod. Bind adapter construction to your authenticated server action after the user reviews the target and content. Register callback/webhook routes explicitly. Use a dedicated provider test account and separate credentials per environment. Keep consent in the application's user flow; an internal `authorized:true` flag records the application decision but is not itself a security check.

## 4. What does the API accept and return?

`EmailAdapter.send({from,to,subject,text},intent)` and `MessagingAdapter.post({channel,text},intent)` return `{id,mode}`. Email recipients are 1–10; subject <=200; body <=100,000. Notifications <=4000 characters. `CalendarAdapter.list(from,to)` returns events overlapping an ISO window. `create({summary,start,end,timeZone,description?},intent)` returns ID and mode. When Google omits an event-level timezone, list responses retain the calendar timezone and creation responses retain the requested timezone. Datetimes must include offset/Z; timezone must be valid IANA; end follows start.

`beginGoogleOAuth` returns URL/state/PKCE verifier/expiry; store state and verifier in a server-side session, bound to the current user, then remove them once the callback is consumed. `exchangeGoogleCode` verifies matching, unexpired state and sends PKCE proof; `refreshGoogleTokens` preserves the existing refresh token if Google omits a new one. `createGoogleCalendar` refreshes expiring tokens before use and persists them through your `saveTokens` callback. The callback must encrypt tokens at rest and store them per user; never use a global token store for multiple users.

`handleSlackWebhook(request,{secret,dedupe,handle})` validates HMAC over the exact raw body and a five-minute timestamp window, handles the signed URL challenge, normalizes `{id,source,type,data}` and deduplicates event IDs only after successful handling. Concurrent duplicates wait for the initial handler; failed processing remains retryable. Default dedupe is memory-bound (10,000 IDs, 24-hour TTL), not durable across restarts.

## 5. What prerequisites, environment variables, or credentials are needed?

Local: Node and Zod. Live secrets: `RESEND_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; nonsecret `GOOGLE_REDIRECT_URI`. Pass them to factories from your secret store, not browser bundles. Resend needs a verified allowed sender and test recipient. Slack needs `chat:write`, the bot installed to a test workspace, and channel membership; inbound event scopes depend on selected event subscriptions. Google needs Calendar API enabled, an OAuth consent screen/test users, and an exact allowed redirect URI. The requested scope is `https://www.googleapis.com/auth/calendar.events`; no mailbox scope is requested. Refresh requires offline consent and a retained refresh token.

## 6. What changes must I make to routes, schema, storage, or UI?

Create an authenticated Google OAuth start route; save the returned state/verifier server-side. In the callback, consume the one-time saved state, exchange code and persist encrypted user-scoped tokens. Register a raw-body Slack webhook POST endpoint and configure its public HTTPS URL in a test Slack app. Use an explicitly authorized development tunnel if needed; this kit does not create one. Enqueue slow webhook work durably before acknowledging; Slack expects prompt acknowledgments, so the supplied handler should complete quickly. A multi-instance deployment must replace WebhookDedupe with a durable atomic reservation/store. The class is deliberately local.

Show a preview before sending mail/posting/creating events, and surface provider errors without silently writing to the local sink. Google create uses a deterministic hexadecimal event ID from the idempotency key and `sendUpdates=none`; it sends no attendee invitations. Repeated create may return a conflict; reconcile the known ID rather than generating a different one. Resend forwards its idempotency key. Slack does not guarantee exactly-once posting through this adapter: persist an application outbox/receipt keyed by intent and do not blindly retry after an ambiguous network failure.

## 7. How do I verify it and handle expected failures?

`node node_modules/vitest/vitest.mjs run modules/integrations/tests`. Local tests cover sinks, idempotency conflict, reset, timezones, empty calendars, real HTTP request/response shapes, OAuth state/refresh, calendar creation, Slack errors, HMAC tamper/stale timestamps, concurrent duplicates and failed-handler retry. These are mocked transport tests, not live sends. No external messages/calendar changes were made. Handle 401 by reconnecting accounts; 403 by checking scopes/membership; 429 with an application-aware retry/outbox policy. Generic HTTP helpers never automatically retry mutations. Live verification requires explicit intent with test targets; never log token values.

## 8. What does it depend on, and what are its limits?

Node crypto, fetch, Zod and shared HTTP runtime only; no provider SDK needed. Requests default to 15s timeout and bounded response size. Calendar reads cap at 10 pages/1000 events and fail if truncated; all-day events fail explicitly and require a separate date-only contract to avoid timezone ambiguity. Arbitrary recurring-event authoring, attachments, rich HTML email, Slack interactive actions and full calendar synchronization are outside this narrow interface.

Sponsor adapter checklist: verify official base URL/auth/scopes; document request and response schemas, limits, price date and usage consent; add fixture, transport/error/cancellation tests; use no automatic mutation retries; retain provenance and licensing; record live test status honestly. `examples/sponsor-adapter.ts` implements a bounded authenticated read adapter with injected schema/fetcher rather than a TODO stub.

Official references checked 2026-10-09: [Resend send](https://resend.com/docs/api-reference/emails/send-email), [Google OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Calendar insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert), [Slack post](https://docs.slack.dev/reference/methods/chat.postMessage/), [Slack signature verification](https://docs.slack.dev/authentication/verifying-requests-from-slack/). Provider usage may incur costs; no allowance/pricing claim is assumed. Original source and synthetic fixtures: MIT.

Implementation: implemented. Local contract verification: passed. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Live provider verification: not run; requires authorized test accounts.

Verification record (2026-10-09, Node 22.23.2): 8 module tests passed, strict TypeScript and scoped ESLint passed, and the local demo ran successfully. Provider transports were mocked; no live usage occurred.
