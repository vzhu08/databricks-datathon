# Ownership and shared stewards

Fill actual names and paths before parallel work. One human owns each task; one active writer owns each file set. Use the authoritative TASK_BOARD for claims.

| Lane            | Human  | Actual file scope                  | Acceptance duty                      |
| --------------- | ------ | ---------------------------------- | ------------------------------------ |
| Product/UX      | [name] | [selected app pages/components]    | Usability, all visible states, demo  |
| Platform/API    | [name] | [named app/api routes, deployment] | Contracts, auth/storage, reliability |
| Core capability | [name] | [selected modules, evaluation]     | Technical quality and evidence       |

Stewards: packages/contracts [name]; package.json/package-lock [name]; app/layout.tsx/global styles [name]; .env examples [name]; migrations [name]; deployment config [name]. Merge coordinator: [name], rotates at [checkpoint]. Local ports, databases and demo state per checkout: [map]. Checkouts do not isolate external resources.
