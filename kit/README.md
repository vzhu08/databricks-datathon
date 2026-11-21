# Hackathon Kit

**Reusable capabilities for a three-developer team building with Codex, Claude Code, or both.** Start with a small working app, copy only the modules you need, and keep evidence of what actually works.

- [Create a project](docs/start-here/CREATE.md)
- [Add to an existing project](docs/start-here/ADOPT.md)
- [Find a capability](CATALOG.md)
- [Contribute to the kit](CONTRIBUTING.md)
- [Optional three-computer orchestration](docs/guides/ORCHESTRATION.md): adopt on a separate project branch after the current MVP is saved; existing chats join through explicitly started local workers.
- [Human–AI team workflow](docs/templates/HUMAN_AI_TEAM_WORKFLOW.md): flexible human accountability, checkpoints and feedback; generated as `docs/HUMAN_AI_TEAM_WORKFLOW.md`, usable with manual coordination or optional orchestration.

## Run the first working slice

Requires Node **22.23+** and npm. No keys, Python, Docker or paid services.

```sh
npm ci
npm run dev
```

Open http://localhost:3000. Normalize text and see validated results from the local API. For the three integrated reference apps and UI gallery:

```sh
npm run dev:showcase
```

Open http://localhost:3001. The studio also includes an optional AI fixture/live processing page at /ai. [Documents](examples/document-workbench/README.md) · [Group decisions](examples/group-decision/README.md) · [Media assistant](examples/media-assistant/README.md).

## Take only what you need

Run from the toolkit checkout. Choose an empty destination outside this repository:

```sh
npm run kit -- list
npm run kit -- search "PDF"
npm run kit -- inspect documents
npm run kit -- create /tmp/my-demo --starter document
```

Then follow the generated README. Recipes: `web`, `document`, `document-python`, `group`, `media`, `full`. Extra modules: `--modules ai,maps`. Modules are local source snapshots, with recorded revision and hashes. No hosted package registry or symlink back to the kit is needed.

For an existing npm/Next App Router project:

```sh
npm run kit -- plan --target /path/to/app --modules recommendations
npm run kit -- add --target /path/to/app --modules recommendations
npm run kit -- add --target /path/to/app --modules recommendations --apply
```

The first two commands only report a plan. Unsupported frameworks, modified files and version conflicts receive manual-integration guidance. Existing routes and agent instructions are preserved.

## Verify and explore

```sh
npm run check
npm test
npm run build
npm run build:showcase
npm run test:exports
npm run test:browser
npm run eval
npm run playground
npm run demo:reset
npm run kit -- doctor --port 3000
```

Browser checks require a Chromium binary; see [testing](docs/guides/TESTING.md). The playground binds to loopback. [Developer tools](docs/guides/DEVELOPER_TOOLS.md) explain bounded live opt-in, sanitized replay, evaluation and actual demo reset. Ordinary checks use authored local fixtures and never call paid providers. Credentials and deployment status are recorded separately from implementation status in each manifest and the [verification report](docs/implementation/VERIFICATION.md).

## Start here with your team

Read [agent start](docs/start-here/AGENT_START.md), [repository map](docs/start-here/REPO_MAP.md), [kickoff playbook](docs/playbooks/DEVELOPMENT_PLAYBOOK.md) and [collaboration](docs/playbooks/COLLABORATION.md). Use [bounded agent prompts](docs/prompts/INDEX.md) and [project templates](docs/templates/PROJECT_BRIEF.md) for a generated project; root AGENTS.md governs maintenance of this toolkit. Provider adapters are server-side and optional. Coding-assistant subscriptions do not supply application API credits.

Original toolkit code and authored fixtures use [MIT](LICENSE). Preserve [third-party notices](THIRD_PARTY_NOTICES.md), source provenance and event-specific reuse rules. This repository is local; no public hosting or live service verification is implied.
