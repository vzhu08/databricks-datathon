# Compatibility matrix

| Path           | Local evidence                                                  | Intended route                                     | Limits                                                            |
| -------------- | --------------------------------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------- |
| Node/Next      | macOS, Node 22.23.2, npm 10.9.8; exact versions in package-lock | Node >=22.23, macOS/Linux                          | Broader OS CI status is separate                                  |
| Python         | bundled Python 3.12.14; uv.lock in starter                      | Python 3.12, uv sync --frozen                      | System Python 3.9 is too old                                      |
| Browser        | automated Chromium when available; see verification             | modern browser with secure context                 | Hardware microphone/camera and Safari require manual verification |
| Windows        | route documented, not locally tested                            | WSL2 Ubuntu, Node 22+, Git and optional Python/uv  | No native Windows guarantee                                       |
| Supabase local | SQL/tests provided                                              | Docker + Supabase CLI                              | Docker absent on build host; live RLS check separate              |
| Durable jobs   | Node SQLite local tests                                         | persistent Linux container volume, one-host SQLite | No distributed/HA queue claim                                     |

On WSL2, clone inside the Linux filesystem, install Node and npm there, and run the README commands in WSL. Keep all worktrees and node_modules in the same environment. Browser permissions still belong to the host browser. Use distinct ports and callbacks for concurrent tasks. Lockfiles reproduce dependencies but cannot reproduce service availability or native OCR installations.
