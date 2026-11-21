# Add a capability to an existing app

Automatic adoption supports an npm project using Next App Router (app/ or src/app/). For another framework, use the module README and copy its portable source/dependency closure manually; the tool refuses automatic transformations.

1. Commit or save existing work. Inspect the target's package.json, routes, import aliases, environment examples and migration names.
2. Run `npm run kit -- plan --target /path/to/app --modules recommendations`. No writes occur. Review source files, dependency versions and manual registration steps.
3. `npm run kit -- add --target /path/to/app --modules recommendations` is also a dry run. Use `--apply` only after reviewing the concrete plan.
4. Install/update the npm lockfile, run the target's existing checks and the imported module test. Exercise the original route as well as the new behavior.

Existing app routes/configuration and AGENTS.md/CLAUDE.md are never replaced. The import uses relative paths, so it does not require rewriting aliases. A new .env.kit.example lists names only. Link docs/kit/SELECTED_MODULES.md from existing instructions yourself after review. Database migrations and route registration are copied instructions, never silently executed.

A differing file or package version stops the operation before writes. Resolve the exact conflict in a reviewed change or use manual integration. Previously imported local edits are recognized by kit.project.json hashes and preserved. Repeating an unchanged import produces unchanged files. To revert, review the plan and use your saved Git diff; no global delete/reset command is used.
