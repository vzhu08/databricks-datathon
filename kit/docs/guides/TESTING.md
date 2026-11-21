# Testing strategy

Run `npm run check` (types, lint, catalog and internal documentation links), `npm test` (module/contracts/adoption behavior), `npm run build` and `npm run build:showcase`. Format with `npm run format`; verify with `npm run format:check`. `npm run test:exports` generates apps in a temporary folder outside the kit and checks install/build/run plus source independence. `npm run eval` produces JSON and a concise local report in .kit/evaluations.

Browser setup: `npx playwright install chromium`, then `npm run test:browser`. Tests start local apps, exercise the actual UI/API boundary, inspect evidence and downloads, change constraints and votes, and test media permission/failure states where supported. Browser binaries may require installation/network access; a missing browser is a skipped prerequisite, not a passing flow. Physical camera/microphone, mobile Safari and public hosting remain separate manual checks.

Python: follow starters/python/README.md and run `uv run --frozen pytest` from that starter. JSON Schema and shared fixtures test wire agreement; UTF-16 offset conversion is tested. Supabase integration requires Docker or isolated test credentials; opt-in commands live in its README. Ordinary CI never calls paid APIs, sends email or posts messages. For a live test, name the provider/test account, max cases, token/output bounds, retry policy and cost policy before invoking it.

The final verification report identifies exact scope and failures. No coverage percentage replaces a working judge flow.

Optional Python: run uv sync --frozen --project starters/python, then uv run --frozen --project starters/python pytest starters/python/tests -q. npm run test:python-bridge starts a real loopback FastAPI process and exercises the TypeScript route through HTTP, including Unicode and malformed JSON. It defaults to starters/python/.venv/bin/python; KIT_PYTHON_EXECUTABLE can select another compatible executable.

Supabase fixture UI: follow modules/supabase/examples/README.md for its separate port 3004 and browser smoke. Native local Supabase, hosted accounts and OAuth still require their own opt-in checks.
