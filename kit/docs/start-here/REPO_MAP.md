# Repository map

| Path                           | Responsibility                                                        | First read                |
| ------------------------------ | --------------------------------------------------------------------- | ------------------------- |
| starters/web                   | Minimal Next app, local transformation, health/ready                  | README.md in that starter |
| starters/python                | Optional validated FastAPI API, OCR worker, uv/container              | README.md in that starter |
| modules/<id>                   | Canonical feature code, eight-question README, fixtures/tests/example | module.json minimalRead   |
| packages/contracts             | Zod wire schemas, generated JSON Schema, fixtures                     | README.md                 |
| packages/runtime               | HTTP deadlines, errors, scoped cache, env checks                      | README.md                 |
| packages/ui                    | Accessible controlled components and theme                            | README.md                 |
| tools                          | Catalog, create/add/plan, doctor, eval, replay, reset, playground     | kit --help                |
| catalog                        | Schema and generated machine index                                    | module.schema.json        |
| examples                       | Three compositions and local studio                                   | composition README        |
| docs/start-here                | Human/agent orientation                                               | AGENT_START.md            |
| docs/architecture, docs/guides | Boundaries, configuration, deployment and maintenance                 | BOUNDARIES.md             |
| docs/playbooks                 | Actionable kit kickoff/collaboration workflows                        | DEVELOPMENT_PLAYBOOK.md   |
| docs/templates                 | Adaptable generated-project documents                                 | PROJECT_BRIEF.md          |
| docs/prompts                   | Bounded agent task prompts                                            | INDEX.md                  |
| docs/resources                 | Official integration references and supplied source                   | INTEGRATIONS.md           |
| docs/implementation            | This toolkit's plan, status and evidence                              | VERIFICATION.md           |
| tests                          | Catalog/adoption/export/browser checks                                | npm run test:exports      |

Catalog metadata is canonical; CATALOG.md and catalog/modules.json are generated. There is no second hand-edited capability registry. A small recipe map in tools/project.ts names dependency roots only; the graph determines their closure.
