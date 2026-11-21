# ACQ-E01 · Developer E · Source-link check and quick reference

Task issue: https://github.com/vzhu08/databricks-datathon/issues/7

Owner: Ayuush (`ayushrgupta906`, the Ayush account in the original board). Branch: `codex/acq-e-source-links`. This is a small support task, approximately 30–45 minutes. It has no dependency on Databricks access and does not block the data pipeline.

Write only `docs/source-checks/ACQ-E01.md` and `docs/handoffs/ACQ-E01.md`. Read the board and source registry. Claim the issue before starting; preserve any existing DATA-01 branch and leave a handoff if it contains work.

## Checklist

1. Open these eight registry entry points once: HOT OSM report, NHP mirror landing page, Rajasthan trauma directory, RGHS hospital PDF, MoHFW trauma PDF, NABH directory, Overture getting-data documentation, and India Post PIN directory. Do not download nationwide datasets.
2. Make one compact Markdown table: source, exact checked URL, UTC check time, observed page title/publisher, result (`opens`, `login/CAPTCHA`, `timeout`, `broken`, or `redirect`), and a short note. Record redirected URLs only if actually observed. Retry a failed page once; leave unresolved failures visible.
3. Below the table write three plain-language sentences for the demo: identity corroboration is separate from service evidence; historical claims do not prove current availability; buildings alone do not prove care quality. Use the agreed contract wording and link it.
4. Open one PR with the two files. In the handoff include the PR/head SHA, eight attempted checks, actual results and remaining failures. Post its link in the task issue.

## Done means

All eight checks have a recorded outcome, every link in the note has been opened or explicitly marked failed, the three demo sentences agree with the contract, and the PR contains only your two files. A timeout or login screen is a valid reported result, not a reason to invent success. No code, parser tests, facility research, screenshots, raw hospital records, paid tools, additional chats, or edits to other developers' files are required. Do not merge the PR or change the shared registry; report suggested corrections to the orchestrator.
