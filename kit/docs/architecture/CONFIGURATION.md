# Configuration and environments

No key is required for base web, studio local samples or ordinary tests. Each module.json records environment variable names, secrecy, required status and local/live scope. `kit doctor` prints missing names only and does not read secret values from .env files. Generated .env.kit.example is documentation, not enabled configuration.

| Setting         | Local                                                  | Preview                           | Production                                 |
| --------------- | ------------------------------------------------------ | --------------------------------- | ------------------------------------------ |
| Browser origin  | localhost port for your checkout                       | exact preview origin              | exact public origin                        |
| Server API URL  | loopback service                                       | deployed container/service URL    | reviewed stable service URL                |
| Browser API URL | reachable from browser; never Docker-internal hostname | HTTPS same-origin proxy preferred | HTTPS with explicit CORS if separate       |
| Provider keys   | absent by default; test account only                   | separate test credentials         | managed server secrets                     |
| Supabase        | isolated local Docker or test project                  | isolated preview data             | production project after policies verified |
| OAuth redirect  | exact localhost callback                               | allowlisted preview callback      | allowlisted production callback            |
| APP_REVISION    | local or Git SHA                                       | deployment SHA                    | known-good deployment SHA                  |

Only safe public configuration uses NEXT_PUBLIC names. Provider keys and refresh tokens never do. Do not copy production .env into the kit or another task. Configure allowed origins explicitly; wildcard credentialed CORS is not an option. For Supabase cookie sessions use the SSR adapter and verify the user server-side, not merely a client-provided user ID. API clients must handle expiry/refreshed sessions and non-idempotent failures.
