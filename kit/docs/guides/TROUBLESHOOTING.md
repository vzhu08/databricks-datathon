# Troubleshooting

| Symptom                               | Likely boundary                    | Concrete fix                                                                                         |
| ------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Node version/SQLite import error      | runtime                            | Use Node >=22.23; jobs imports node:sqlite only on server                                            |
| Missing package or stale lock         | dependency graph                   | npm ci from the correct root; steward updates lockfile when dependencies change                      |
| tsx IPC EPERM in a restricted shell   | sandbox process socket             | use node --import tsx tools/kit.ts rather than tsx CLI                                               |
| catalog check says stale              | generated metadata                 | npm run kit -- catalog build, inspect diff, re-run check                                             |
| Unknown module or dependency cycle    | manifest                           | correct the ID or graph; do not skip validation                                                      |
| add reports modified file             | ownership                          | compare existing/source revisions; preserve custom work and merge manually                           |
| add reports package range conflict    | conservative adoption              | verify compatibility, resolve exact tested version in a review, or import manually                   |
| Python says operation missing         | cross-language schema              | regenerate catalog/schema from request input mode and run shared fixture tests                       |
| PDF needs OCR                         | scanned image rather than text     | install optional Python/OCR prerequisites and use explicit OCR path                                  |
| Voice/camera permission denied        | browser permission/context         | use localhost/HTTPS, review site permissions, retry; sample mode remains explicit                    |
| Realtime disconnected                 | loopback server absent             | npm run realtime; same ws URL/room, distinct user IDs, allowed origin                                |
| No recommendations                    | hard constraints                   | inspect exclusions; do not silently relax constraints                                                |
| Live provider rejects model/key       | adapter/config                     | verify model availability in your account and server env names; never replace with unlabeled fixture |
| Upload works locally but fails hosted | platform request cap/native binary | direct storage upload or container processing; inspect provider limits                               |
| Job disappears on restart             | demo memory store                  | choose SQLite persistent volume or a reviewed hosted durable implementation                          |

Report request ID, actual command, boundary, observed result and expected contract; never paste secrets or private documents in an issue.
