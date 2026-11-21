# Handoff

Task/status: [ID, Review or Blocked]. Human owner: [name]. Branch/check-out/base/result SHA: [actual values]. Changed files: [paths]. Delivered behavior: [observable result]. Checks/results: [commands, pass/fail counts and manual evidence]. Contract/env changes: [names and compatibility, no secrets]. Known limits/unverified behavior: [specific]. Next action: [review/dependent task/precise blocker]. Merge/deploy authority: [recorded scope].

Before switching tools, stop the existing writer, preserve a task-branch checkpoint/patch and update this handoff. The receiving session inspects current diff, instructions and tests before editing. Two coding tools must not write simultaneously in the same checkout. An earlier test result describes its earlier commit only.
