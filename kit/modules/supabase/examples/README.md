# Optional sign-in and private notes UI

This standalone Next.js example is optional. Nothing is mounted into the kit's base application. It requires only the repository's existing Node dependencies in fixture mode.

From the repository root, after `npm ci`:

```sh
node node_modules/next/dist/bin/next dev modules/supabase/examples --webpack --hostname 127.0.0.1 --port 3004
```

Open <http://127.0.0.1:3004>. The **FIXTURE** badge means an in-memory repository and simulated sign-in. Use `alice@kit-demo.invalid` or `bob@kit-demo.invalid` with password `fixture-only`. Each widget owns its fixture state; browser reload clears notes and session. Fixture mode makes no Supabase calls, and `/api/auth` and `/api/notes` return 503 rather than accidentally contacting configured providers.

Try sign-in, create, edit, delete, refresh, sign-out, and switching accounts. The fixture control panel can inject a request failure; disable it and use **Retry loading**. A failed mutation retains its draft and shows an error. Loading and empty states are visible and accessible. The controller serializes user operations and ignores late view updates after unmount; it cannot undo writes already accepted by a server.

## Use actual Supabase authentication and CRUD

Follow [the isolated local setup](../local/README.md) to start Supabase, apply the canonical RLS migration, and seed the two synthetic accounts. This mode makes real calls to a running Supabase instance. It never substitutes fixture data on a failure.

Create the ignored `modules/supabase/examples/.env.local` using the local public key shown by `supabase status --workdir .kit/supabase-demo`:

```dotenv
NEXT_PUBLIC_SUPABASE_EXAMPLE_MODE=live
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:56321
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=YOUR_LOCAL_PUBLISHABLE_OR_ANON_KEY
SITE_URL=http://127.0.0.1:3004
```

Restart the example and use the seeded email/password you chose in `KIT_DEMO_PASSWORD`. For a production build, set the mode before `next build` because the homepage is prerendered; changing only runtime environment does not change that built page. Do not place a service-role key in this environment file or any browser variable. `SITE_URL` must exactly match the browser origin, including hostname and port, because mutating routes check `Origin`.

The flow is UI → same-origin `/api/auth` → `handleAuthRequest`, which verifies sessions with Supabase `getUser`; UI → same-origin `/api/notes` → `requireUser` → `createSupabaseNotes` → the authenticated Supabase client and database RLS. Requests forward refreshed cookies; responses are `no-store`. The server derives identity from the session, never from a submitted owner ID. Inputs use the existing schema, reject extra fields, and have bounded request bodies. The browser's request deadline is 15 seconds. Server SDK transport timeouts and upstream availability follow your application hosting configuration; a timed-out browser operation may already have reached the server, so refresh before repeating a write.

GitHub OAuth is optional and disabled in the supplied local config. To use an operator-configured Supabase OAuth provider, configure its client and callback URLs according to [Supabase's GitHub guide](https://supabase.com/docs/guides/auth/social-login/auth-github), allow the app's exact callback URL `/api/auth?action=callback`, and set server-only `KIT_EXAMPLE_GITHUB_OAUTH=1`. This exposes the existing OAuth route/link. No GitHub app or credentials are provisioned by this example. Changing the isolated local config intentionally causes the guarded seed script to refuse it; use a separately managed integration project for OAuth customization.

## Mount in another Next application

For a fixture-only preview, import and render:

```tsx
import { AuthNotesDemo } from './path/to/modules/supabase/examples/components/AuthNotesDemo';
export default function Page() {
  return <AuthNotesDemo mode="fixture" />;
}
```

For live mode, explicitly register the two route files from `app/api/auth/route.ts` and `app/api/notes/route.ts` in your app and adjust their relative imports to the retained module files. The adapters under `server/` must remain server-only. Set the environment above and render `<AuthNotesDemo mode="live" />`. The widget expects `/api/auth` and `/api/notes`; do not overwrite existing routes with those names. Change both the registration and `components/session.ts` if your app uses another prefix. If changing `mode` after mount, use `key={mode}` to replace the widget and its session state. Keep the `demo.css` import or replace it with application styles.

Live route registration is deliberately separate from importing the widget. Existing `next-auth-route.ts` and `next-proxy.ts` remain standalone templates; this example's session wrapper handles cookie forwarding directly. For a broader protected app, adapt your existing session refresh middleware/proxy and preserve all outgoing cookies. There is no signup/recovery/admin interface, and no storage UI here; the module's storage adapter and RLS integration test cover storage separately.

## Checks and scope of evidence

```sh
node node_modules/vitest/vitest.mjs run modules/supabase/tests
node node_modules/next/dist/bin/next build modules/supabase/examples --webpack
# With the fixture dev server above running and Playwright Chromium installed:
node --import tsx modules/supabase/examples/browser-smoke.ts
```

Use `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` for an already installed Chrome executable when the bundled Playwright browser is absent. The smoke script only accepts loopback HTTP origins and requires the fixture badge before interacting. It checks sign-in, create/edit/delete, failure recovery, account isolation, and the disabled live route; it does not prove database RLS. The opt-in actual two-user auth/database/storage test is documented in [local setup](../local/README.md).

Implemented and checked locally: strict TypeScript, route/controller/seed tests and a Chrome fixture browser walkthrough. Supabase Docker startup, actual database auth/RLS/storage, and OAuth require operator prerequisites and are not claimed as executed here. See [the module README](../README.md) for its broader API and limitations.
