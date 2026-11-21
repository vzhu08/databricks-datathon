# Realtime rooms and votes

## 1. What problem does this solve, and when should I use it?

Build small collaborative rooms with presence, shared votes/results, duplicate handling, reconnect and subscription cleanup. The local transport is a real WebSocket server, and the optional Supabase adapter uses private-channel presence. This suits a live group-decision demo and a modest authenticated app after adding its authorization callback.

## 2. What is the smallest working example?

`node --import tsx modules/realtime/examples/demo.ts` starts a loopback server on an ephemeral port, connects Alice and Bob, sends a vote and exits after both clients receive shared state. `node --import tsx modules/realtime/examples/server.ts` keeps the server on port 8788 for a browser demo. `RoomClient` uses the browser WebSocket by default; tests inject the `ws` client.

## 3. How do I add it to a fresh project or an existing project?

Select `realtime`. Start `startRealtimeServer({port,host,authorize})` in a persistent Node service; serve the browser separately. Import `RoomClient` from `src/browser.ts`, call `connect`, subscribe with `onState`, and call `close` when a component unmounts. Do not import the server from a client bundle. For existing infrastructure, choose a distinct port and explicitly register the service URL.

## 4. What does the API accept and return?

Room/user/event IDs contain 1–80 ASCII alphanumeric/underscore/hyphen characters. `RoomClient({url,room,userId,token?,onStatus?})` exposes `connect`, `vote(choice,eventId?)`, `onState(listener)` returning unsubscribe, and `close`. State is `{room,members,votes,revision}`. `tallyVotes` returns deterministic counts, sorted by count then choice. The server checks every message with Zod; max payload is 8KB. It closes malformed/unauthorized connections. Duplicate user+event IDs are acknowledged without reapplying votes. A vote updates only the identity bound during join, never an identity supplied in the vote.

## 5. What prerequisites, environment variables, or credentials are needed?

Node 22+, `ws`, Zod; port access on loopback. `REALTIME_PORT` is optional for the example. Browser connection URLs use ws locally and wss behind production TLS. A non-loopback server requires `authorize({room,userId,token})`; validate the actual session and room membership there. Never trust the client's userId on its own. Optional Supabase requires an authenticated client, enabled realtime and private-channel RLS restricting `realtime.messages` to authorized room topics.

## 6. What changes must I make to routes, schema, storage, or UI?

The local server is a separate long-running process, not a Next.js request handler; many serverless platforms do not host a persistent WebSocket server. Reverse-proxy the service with TLS and origin/rate controls for production. Render connection status, room members, vote selection and tally. `onStatus` reports connecting/connected/disconnected/error. Queued client events replay after joining again with their original IDs. Reconnect uses exponential delay, max eight attempts (configurable), no retry after policy violation. On close, listeners and queued events are cleared.

`joinSupabaseRoom(client,room,userId,listener)` returns async `vote` and `close`; identity/presence must be protected by your channel RLS. Use [Supabase realtime authorization](https://supabase.com/docs/guides/realtime/authorization) and [presence](https://supabase.com/docs/guides/realtime/presence). No permissive RLS migration is installed automatically.

## 7. How do I verify it and handle expected failures?

`node node_modules/vitest/vitest.mjs run modules/realtime/tests`. Integration tests create three actual WebSocket clients across two rooms, check shared votes, event dedupe, reconnect with queued votes, presence cleanup, unauthorized joins, offline queue capacity and empty tallies. Sandboxed environments must allow loopback listening; EPERM indicates environment permission, not a passed integration check. Local realtime integration was run successfully with loopback permission. No Supabase live call was made.

## 8. What does it depend on, and what are its limits?

`ws` 8.22.0, Zod, optional Supabase SDK 2.117.3. Local state is ephemeral: votes survive disconnects in that server process but disappear on restart. Empty rooms remain until server shutdown to preserve reconnect history; default capacity is 100 rooms, 100 clients and 1000 recorded voters per room. Each connection is limited to 200 messages per minute; clients exceeding a 1MB outgoing backlog are disconnected. Event dedupe retains the most recent 2000 IDs per room; older replays may apply again. Client offline queue is capped at 100 events. Snapshots are authoritative and revisions reset after restart. The Supabase adapter's votes are presence-based and disappear with that user's last connection; it does not claim durable voting or server-authoritative results. Persist decisions separately if they must outlive a session. [ws source/docs](https://github.com/websockets/ws). Original source and synthetic fixtures: MIT.

Implementation: implemented. Local verification: two-client integration and failure checks passed. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Hosted realtime verification: not run.

Verification record (2026-10-09, Node 22.23.2): 3 module tests passed, strict TypeScript and scoped ESLint passed, and the local demo ran successfully. Loopback permission was granted for the actual socket/process tests.
