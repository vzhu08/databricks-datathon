# Verification record

Verified locally on **2026-10-09** against implementation commit **3be11b6675737e99afe6cb255c531a9e68503741** and its preceding integration working tree. Subsequent handoff changes are documentation only. Repository: local Git, no remote, no public deployment or release. No live provider usage, accounts, purchases or messages were initiated.

## Environment

macOS arm64; Node **22.23.2**, npm **10.9.8**, TypeScript **6.0.3**, Next **16.4.0**, React **19.3.0**, Vitest **5.0.3**, Playwright **1.64.0** with Chromium 156. Python **3.12.14**, uv **0.12.24**. Exact Node and Python transitive resolutions are committed in package-lock.json and starters/python/uv.lock. Python installation used isolated virtual environments, including in an exported project.

## Checks and observed results

| Check                       | Observed result                                                                                                                                                                                                               |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| npm run format:check        | Pass                                                                                                                                                                                                                          |
| npm run check               | TypeScript, ESLint, 15-module catalog/schema freshness and internal documentation links pass                                                                                                                                  |
| npm test                    | **146 passed; 1 skipped** across 23 files; the skipped check is the explicit Supabase service integration                                                                                                                     |
| npm run build               | Base web production build passes                                                                                                                                                                                              |
| npm run build:showcase      | Studio production build passes, including the three reference compositions, gallery and optional AI page                                                                                                                      |
| npm run test:browser        | **8 Chromium workflows pass**, described below                                                                                                                                                                                |
| npm run eval                | **8/8** authored local sanity cases pass; no external calls; estimated API cost $0                                                                                                                                            |
| Python frozen sync + pytest | **5 passed** in both the toolkit and independently exported document-python project                                                                                                                                           |
| npm run test:python-bridge  | Real TypeScript route → HTTP → FastAPI → shared result validation passes, including Unicode and malformed JSON                                                                                                                |
| npm run test:exports        | Five recipe configurations and existing-app adoption pass outside the toolkit; final document-python/full revisions rechecked after optional UI additions                                                                     |
| tests/export-browser.ts     | Exported browser → Next route → exported Python service → UI passes; exported optional AI fixture UI passes                                                                                                                   |
| Optional Supabase UI        | Module-author standalone production build and Chromium sign-in/CRUD/failure-retry/account-isolation walkthrough pass; local controller/route/setup tests are in the combined suite                                            |
| Developer tools             | Catalog/create/plan/add/doctor exercised; local playground HTTP/fixture/live-disabled boundaries tested; replay sanitization/opt-in/overwrite guard tested; reset dry-run/URL/header checks and actual memory reset exercised |
| git diff --check            | Pass                                                                                                                                                                                                                          |
| npm audit --omit=dev        | **3 moderate, 0 high, 0 critical** advisories; detail below                                                                                                                                                                   |

The small evaluation dataset checks local transformations, hard constraints, retrieval recall@3 and exact citation validity. It is a sanity test, not a general accuracy benchmark. Live evaluation has explicit opt-in, case/request/token/concurrency limits and unknown-cost reporting; it was not invoked.

## Browser coverage

1. Actual base transformation, empty input and validated API errors/request IDs.
2. Document source highlighting, rejected invalid review, retained draft, unsupported human-edit labeling in CSV/PDF, working report download, deliberate local sharing and revocation, source-grounded retrieval citations.
3. Unicode filename upload, stale-chat clearing, malformed PDF recovery and an empty document.
4. Hard-constraint exclusion and two actual WebSocket clients sharing votes.
5. Microphone/camera denial recovery, actual PNG decoding/resizing, completed local worker processing and cancellation.
6. Gallery filtering/pagination/error recovery; 390px layouts across document/group/media/gallery with no horizontal overflow. Desktop document and mobile gallery screenshots visually inspected.
7. Reset of actual local share/job state; foreign-origin reset rejection.
8. Explicitly labeled optional AI fixture output and live-disabled route behavior.

Device denial is simulated in Chromium. These checks do not establish physical microphone/camera availability, Safari/mobile codec support or live transcription/vision quality. Synthetic transcripts/detections remain visibly distinct from uploaded media.

## Standalone consumption evidence

Every exported project uses its own npm ci installation, no symlink to toolkit dependencies and no unpublished workspace package. Source/config scans reject embedded toolkit absolute paths and source symlinks. Each selected recipe passes types, tests, production build, an actual HTTP page and its transformation API outside the source checkout.

| Recipe                | Selected module closure                                               | Result                                                                                                                  |
| --------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| web                   | none; Next/React/React DOM/Zod runtime only                           | Pass; AI/PDF/Supabase/WebSocket SDKs absent from the base lock                                                          |
| document-python       | documents, retrieval, extraction, exports + optional Python companion | Pass; exported Python frozen install, shared tests and actual browser bridge also pass                                  |
| group                 | recommendations, realtime                                             | Pass                                                                                                                    |
| media                 | media, voice, jobs                                                    | Pass                                                                                                                    |
| full                  | all 15 modules                                                        | Pass; optional AI browser route also passes                                                                             |
| Existing Next/npm app | recommendations added to a modified app                               | Original home, second route and AGENTS.md preserved; repeat plan idempotent; rebuild and original-route HTTP smoke pass |

Conflict tests also cover changed imported files, stale plans, target symlink replacement, traversal paths, dependency cycles, missing module IDs and export exclusion of local credentials/embedded repositories. Automatic adoption deliberately supports npm + Next App Router; other frameworks require the documented manual source-integration path. Migrations and existing routes are never silently rewritten.

## Separate verification boundaries

**Live providers:** OpenAI/Anthropic, speech/vision, Tavily/site fetching, Mapbox, Resend/Slack, Google OAuth/Calendar, and Supabase auth/database/RLS/storage/OAuth were not run against real accounts. Local contract fixtures are evidence of adapter behavior only. The two-user Supabase integration exists and is opt-in; it is the recorded skip.

**Native/services/hosting:** Docker was unavailable, so Python/job container builds, actual local Supabase startup/migrations, Tesseract/PDFium OCR, persistent-volume hosting and deployment were not executed. OCR and containers are implemented and documented, with explicit prerequisites. The hosted GitHub Actions workflow has not run. Linux, native Windows and the documented WSL2 route have no local certification.

**Runtime scope:** in-process jobs, local share links and collaboration rooms are demos. The separate SQLite worker has local restart/retry/cancellation evidence but is a single-host queue, not distributed/HA infrastructure. Node 22 labels its built-in SQLite API experimental. Public deployment needs application authorization and suitable persistence. Report PDFs preserve exact Unicode evidence in an attachment; their base font substitutes unsupported visible glyphs.

**Dependency advisory:** npm reports a precision-format denial-of-service advisory in sprintf-js, propagated through argparse into Mammoth: three affected package entries in one chain. The kit uses Mammoth's library API, accepts no user-supplied format strings and does not expose its CLI. npm proposes an obsolete Mammoth downgrade rather than a compatible fix; it was not applied. Recheck the upstream advisory before public document ingestion. See [third-party notices](../../THIRD_PARTY_NOTICES.md).

**Upstream warning:** Python's tests emit a Starlette/httpx deprecation warning; all five checks pass. This is recorded rather than suppressed.

## Reproduce and inspect

Use [testing instructions](../guides/TESTING.md), [developer tools](../guides/DEVELOPER_TOOLS.md), [the requirement map](REQUIREMENTS.md) and [README](../../README.md). Browser prerequisites: npx playwright install chromium. Python prerequisites: uv sync --frozen --project starters/python. Optional standalone Supabase fixture UI has its own [launch/smoke guide](../../modules/supabase/examples/README.md).

The scripts, lockfiles and this report are the committed evidence. Ignored .kit/verification contains audit output, export reports and screenshots for this session; external test projects remain in the OS temporary directories printed by test:exports. Those caches/binaries are not exported with projects. To repeat the additional browser bridge, run `node --import tsx tests/export-browser.ts /absolute/generated-project` after installing/building the export and syncing its Python starter when selected.
