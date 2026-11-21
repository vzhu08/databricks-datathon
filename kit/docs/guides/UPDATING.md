# Update a vendored capability

Generated kit.project.json records the source Git revision, dependency closure and exported file hashes. Commit the snapshot and your changes in the application. In a clean integration checkout, compare the imported module against the new kit source; use `kit plan` to identify conflicts. A modified imported file is never silently overwritten.

Review public contracts, package versions, migration names, environment requirements and supported combinations. Resolve local customizations intentionally; do not regenerate the whole app over its route tree. Re-run the module tests, existing app checks and actual affected flow. Update the recorded provenance only when that candidate is accepted. Archive the old revision as a recoverable Git commit.

Do not turn a toolkit branch into a moving runtime dependency. Promote project improvements back into a module only with generic inputs, removal of private fixtures and evidence that other consumers still work.
