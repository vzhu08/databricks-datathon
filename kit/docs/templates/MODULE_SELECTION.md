# Module selection

| Requirement               | Capability                         | Reason                           | Setup/owner                     | Known limit                              | Verification                              |
| ------------------------- | ---------------------------------- | -------------------------------- | ------------------------------- | ---------------------------------------- | ----------------------------------------- |
| Inspect document evidence | documents + retrieval + extraction | Provenance-preserving local path | API owner; server parser        | OCR requires optional Python/native path | Run module tests and upload/evidence flow |
| [actual requirement]      | [selected ID]                      | [why it is needed]               | [env names, routes, migrations] | [limit]                                  | [command/result]                          |

Use kit.project.json for the actual dependency closure. Remove unneeded capabilities before adding services. Module README and manifest define exact entrypoints, packages, environment names, assets and checks. Optional live adapters still need explicit configuration and budget. A tool subscription does not grant application API credits.
