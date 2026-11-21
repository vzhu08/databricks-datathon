# Supabase authentication, notes and private files

## 1. What problem does this solve, and when should I use it?

Add optional Supabase Auth, owner-isolated notes CRUD and private object storage. A local fixture repository supports the same notes interface without Docker or credentials. Use this when your app needs persistent user data and an explicit browser/server authentication boundary.

## 2. What is the smallest working example?

`node --import tsx modules/supabase/examples/demo.ts` exercises local empty/create/update/delete states. Its output is labeled fixture. For real local Supabase, install the Supabase CLI and Docker, run `supabase init` in your project, copy `migrations/001_notes.sql` to a new ordered migration in `supabase/migrations`, then `supabase start` and `supabase migration up`. Use the CLI's local URL/publishable/service-role key names, never commit their values. Apply migrations only after reviewing the target with the migration steward.

The optional [sign-in/private-notes UI](examples/README.md) runs as a separate Next app with fixture/live modes. [Isolated local setup](local/README.md) provides the pinned CLI config, guarded preparation and account seeding. Browser-only verification uses the optional development dependency @playwright/test 1.64.0; the project generator includes it only when this module is selected.

## 3. How do I add it to a fresh project or an existing project?

Select `supabase`, review its environment and migration plan, and install the exact SDK dependencies. `src/browser.ts` creates the public browser client; `src/server.ts` creates a request-specific cookie client. Neither needs an admin key. Copy `examples/next-auth-route.ts` to your app's `app/api/auth/route.ts`, adjust its import, and merge the scoped `examples/next-proxy.ts` with an existing Next.js 16 proxy instead of overwriting it. Regenerate database types after approved schema changes: `supabase gen types typescript --local > modules/supabase/src/database.types.ts`. The bundled file is the migration's reviewed type snapshot, not claimed output from a live database.

## 4. What does the API accept and return?

`NoteRepository` exposes async `list/create/update/delete`. Notes have UUID id/owner_id, title 1–200 characters, body up to 50,000 and ISO created_at. `createSupabaseNotes(client)` uses the authenticated client so RLS governs reads and writes. `createLocalNotes(userId,sharedRows?)` is a fixture that emulates isolation, not production authorization. `loadNotes` returns empty/ready/error; use a loading state before awaiting it.

`requireUser(client)` verifies via Auth `getUser`, never unverified session cookies. `handleAuthRequest` supports GET session/oauth/callback and POST signin/signout through `?action=...`. Signin JSON is `{email,password}`. Signin bodies are capped at 5000 raw bytes before decoding; oversized or stalled/cancelled streams return 413 or 408. The OAuth example uses GitHub and PKCE session exchange. Session responses expose only user ID/email. `uploadOwnedFile(client,blob,filename)` accepts PDF/plain text/PNG/JPEG up to 5MB, validates filename and prefixes the verified owner ID. `downloadOwnedFile` returns Blob; `signedFileUrl` returns a bearer URL expiring in 1–600 seconds.

## 5. What prerequisites, environment variables, or credentials are needed?

Fixtures: Node and Zod only. Live: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and `SITE_URL`; public keys are intentionally nonsecret. Hosted Supabase can replace Docker. Never expose `SUPABASE_SERVICE_ROLE_KEY`; it bypasses RLS and is used only by the explicit disposable-account integration test.

Enable password sign-in and create test users in your chosen environment. For GitHub OAuth, create the provider app, set its callback to the Supabase Auth callback URL shown by Supabase, configure its client secret in Supabase, and allow your application's exact `/api/auth?action=callback` URL in Supabase redirect settings. Register separate localhost/preview/production URLs. Auth cookies and refresh writes must reach the outgoing response; the supplied route/proxy examples preserve them. [SSR clients](https://supabase.com/docs/guides/auth/server-side/creating-a-client), [GitHub OAuth](https://supabase.com/docs/guides/auth/social-login/auth-github).

## 6. What changes must I make to routes, schema, storage, or UI?

The migration adds `public.kit_notes`, owner index, four authenticated-owner RLS policies, a private `kit-private` bucket and owner-prefix object policies. No anonymous reads, public bucket, or storage overwrite policy is created. Migrations are one-time ordered changes; do not execute the same create-policy statements twice. Authorize each server page before reading private data, never cache sessions publicly, and render loading/empty/error/retry states. The sign-in route checks same-origin POSTs. Add application rate limits, password-reset UX and email verification as needed.

Seed isolated fixture state with the example or create owned notes through a signed-in client. Reset local fixtures by creating a new Map. For database reset, first inspect `supabase status` and verify an isolated local instance, then use `supabase db reset --local`; this is destructive to local data and is not run automatically. Hosted resets are deliberately not scripted.

## 7. How do I verify it and handle expected failures?

`node node_modules/vitest/vitest.mjs run modules/supabase/tests` runs fixture isolation, validation, error states, client construction, cross-origin mutation and file validation tests. It skips the live/local-database test by default. After applying migrations, explicitly set `RUN_SUPABASE_INTEGRATION=true`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_SERVICE_ROLE_KEY`, then run `modules/supabase/tests/rls.integration.test.ts` through Vitest. It creates two disposable users, verifies cross-user CRUD/storage denial and signed access, then removes only its created records/users. Hosted testing additionally requires `ALLOW_HOSTED_SUPABASE_TEST=true`; use a dedicated test project. No database integration test was run in this build because Docker/credentials were not configured.

Expired sessions prompt reauthentication; invalid sign-in stays a generic error. RLS can make an unauthorized row look absent, so do not infer its existence. Storage signed URLs authorize anyone holding them until expiry: keep them out of logs and revoke underlying objects if necessary.

## 8. What does it depend on, and what are its limits?

Supabase JS 2.117.3, SSR 0.12.7, Zod; Next.js is used only in the supplied route/proxy examples. Lists are capped at 100 newest notes; add pagination for larger data. This is a small auth/data integration, not a complete account-management UI. Local fixture tests do not prove Postgres RLS; the explicit two-user integration test provides that verification when configured. [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [storage access control](https://supabase.com/docs/guides/storage/security/access-control). Original code and synthetic fixtures: MIT.

Implementation: implemented. Local contract verification: passed. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Supabase RLS/storage/OAuth live verification: not run; prerequisites and opt-in are documented above.

Verification record (2026-10-09, Node 22.23.2): 5 module tests passed, strict TypeScript and scoped ESLint passed, and the local demo ran successfully. One Supabase database integration test was intentionally skipped; Docker and Supabase CLI were unavailable.
