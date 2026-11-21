# Isolated local Supabase project

This optional setup targets a disposable local project named `hackathon-kit-supabase-demo`. It never links to or deploys a hosted project. The kit's fixture demos work without it.

Prerequisites: a running Docker-compatible container runtime, repository dependencies (`npm ci`), and Supabase CLI. The configuration follows official CLI **2.120.0** documentation (release 2026-10-06); pin that version for reproducibility, or review config changes before choosing another. Neither Docker nor the CLI was available in the build environment, so actual startup/migration execution is explicitly unverified.

## Prepare and start

Run from the repository root:

```sh
node --import tsx modules/supabase/local/prepare.ts
supabase start --workdir .kit/supabase-demo
supabase status --workdir .kit/supabase-demo
```

If invoking without a system CLI, replace `supabase` with `npx --yes supabase@2.120.0` after approving its download locally. The preparation script performs only filesystem work: it copies `local/supabase/config.toml` and the module's canonical `migrations/001_notes.sql` into the ignored `.kit/supabase-demo/supabase` directory. A checksum marker identifies the copied inputs. Repeating preparation is safe when those inputs are unchanged. It refuses nonempty unmarked directories, changed copied files, and symlink paths. Do not run the CLI directly against the template directory: its migration lives in the canonical module location until preparation copies it.

The dedicated ports are API **56321**, Postgres **56322**, shadow database **56320**, Studio **56323**, and local mail viewer **56324**. Postgres is pinned to major version **17**. Other local Supabase projects can use their normal ports. Public signup, anonymous sign-in, analytics, the connection pooler, and Edge Runtime are disabled. The mail viewer is local; no external SMTP or OAuth credentials are configured. `supabase start` applies the copied migration, creating the notes table, RLS policies, and private storage bucket. If a port is already occupied, inspect that service; do not stop or reset unrelated projects.

## Seed two synthetic accounts

First inspect the plan; this does not require credentials and makes no network calls:

```sh
node --import tsx modules/supabase/local/seed.ts
```

Set `SUPABASE_SERVICE_ROLE_KEY` from this local project's status output and choose a local-only `KIT_DEMO_PASSWORD` of 12–100 characters in your shell or secret manager. Do not paste secrets into committed files, screenshots, or logs. Then explicitly apply:

```sh
node --import tsx modules/supabase/local/seed.ts --apply
```

The script's API URL is fixed to `http://127.0.0.1:56321`. It verifies the isolated project's marker and exact configuration before constructing an admin client. It creates `alice@kit-demo.invalid` and `bob@kit-demo.invalid`, confirms them locally without sending email, marks them in `app_metadata`, and upserts one fixed synthetic note per account. It refuses matching unmarked accounts or note IDs belonging to another user before performing any writes. Pagination and each network request are bounded. Existing marked users are reused and **their passwords are not changed**; reusing a different `KIT_DEMO_PASSWORD` does not change their sign-in credentials. Run only one seed process at a time against this isolated project. A partially completed seed can be rerun.

The service-role key is used only by this explicit seed operation or the opt-in integration test. The UI uses the local **publishable/anon key**. Follow [the UI instructions](../examples/README.md) to run live sign-in and CRUD, or leave the example in explicit fixture mode for UI-only use.

## Verify real database and storage isolation

After starting and migrating the local project, set `SUPABASE_URL=http://127.0.0.1:56321`, `SUPABASE_PUBLISHABLE_KEY` to its public key, and `SUPABASE_SERVICE_ROLE_KEY` to its local admin key, then run:

```sh
RUN_SUPABASE_INTEGRATION=true node node_modules/vitest/vitest.mjs run modules/supabase/tests/rls.integration.test.ts
```

This existing integration test creates two disposable accounts; verifies sign-in, own-note CRUD, rejected forged ownership, and cross-user note/storage denial; then removes the accounts and file it created. It is skipped in ordinary tests. A successful fixture UI test is not evidence this integration test passed. Do not set `ALLOW_HOSTED_SUPABASE_TEST` for this local workflow.

## Reset or stop only this project

Before a reset, inspect `supabase status --workdir .kit/supabase-demo` and confirm the project ID, ports, and disposable data. The next command is destructive to this **local project's database**, including its local accounts and notes. It is an explicit operator action; no script runs it automatically:

```sh
supabase db reset --local --workdir .kit/supabase-demo
node --import tsx modules/supabase/local/seed.ts --apply
```

The reset reapplies the copied migration. SQL seeding is disabled because account creation goes through the Auth admin API. Recheck storage objects after a database reset; Docker volumes and object data have their own lifecycle and this guide does not promise complete file erasure. Never add `--linked` or a remote `--db-url`. To stop only this stack while retaining its local data, use:

```sh
supabase stop --project-id hackathon-kit-supabase-demo
```

Do not use broad `--all` cleanup. Inspect the CLI's version-specific help before removing volumes or backups. If changing the canonical migration later, stop this disposable project and prepare a new empty target with `prepare.ts --target PATH`; do not overwrite the checksum-marked copy or repoint it at a real application database. A second target with the same project ID is the same Docker stack, not a second independent database.

Official references: [CLI config](https://supabase.com/docs/guides/local-development/cli/config), [database migrations](https://supabase.com/docs/guides/local-development/database-migrations), [local seeding](https://supabase.com/docs/guides/local-development/seeding-your-database), and [CLI 2.120.0 release](https://github.com/supabase/cli/releases/tag/v2.120.0).
