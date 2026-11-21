# ACQ-B01 · Developer B · Deep Rajasthan trauma evidence programme

Task issue: https://github.com/vzhu08/databricks-datathon/issues/4

Owner: Developer B, a human research/integration lead; claim the role in this task's issue. Do not infer a GitHub username from prior assignments. Branch: `codex/acq-b-trauma-evidence`. This is a substantial research-and-engineering task, split across five research chats under B's accountability. B owns the final synthesis and cannot mark the work complete merely because the five chats returned.

## Planning checkpoint, then completion goal

Start B's lead chat in **Plan mode**. Read the current board, acquisition contract, registry, and this entire task. Produce a decision-complete plan specifying all five chat scopes, source acquisition methods, field/temporal interpretation, source-dependence map, review sampling, artifact storage, integration order, commands, and expected blockers. Resolve actual source access and input shapes through read-only inspection first. Do not write code or download a production corpus in this planning phase. Have the human B approve the plan and switch out of Plan mode.

Then paste this explicit goal instruction in B's lead chat:

> Create a goal: complete ACQ-B01 by delivering a reproducible, contract-valid Rajasthan trauma evidence package, the five research handoffs, a reviewed claim ledger, an independent audit, and a PR with every acceptance check evidenced. Use no token budget unless I specify one. Launch the five named research chats below in my account, each in a separate checkout and its own branch. Coordinate their outputs and keep working through all unblocked tasks. Do not mark the goal complete while required work remains; report access blockers truthfully. Do not merge, deploy, contact hospitals, or create recurring task-monitoring automations.

Selecting actual Plan mode and starting the goal happen in B's own chat. This document does not itself toggle a UI mode or start a goal. If that environment lacks a native goal tool, keep the same explicit completion checklist and report that limitation rather than pretending the mode was activated.

## Shared research standard

Capture source URL, publisher, original source family, acquisition timestamp, raw hash, publication/effective/valid-through dates separately, campus/address as written, exact excerpt, page/table/row locator, interpretation, confidence limits, and review metadata. Real source material and extracted claims stay in ignored `data/local/trauma/` or an authorized Volume, not Git. Git receives code, synthetic parser examples, source metadata and aggregate audit results only.

Collect evidence even when it conflicts or is incomplete. Distinguish: named trauma centre; stated level; stated operational status at a date; general emergency services; proposed/sanctioned/planned services; referrals; live acceptance unknown. Never combine these into one clinical capability flag. `Supports` means the source supports the stated claim, not that the facility is currently available.

## Five separate chats and exclusive scopes

### B1 — Rajasthan state trauma directory

Branch `codex/acq-b1-state`; write `research/trauma/state/`, `tests/research/trauma/state/`, and `research/trauma/handoffs/B1.md` only.

Launch prompt:

> Implement B1 under ACQ-B01. Acquire the Rajasthan Road Safety Cell trauma-centre table from the shared registry. Parse every row, preserve its exact facility/district wording and row locator, and capture all available source dates without inferring freshness from page copyright or retrieval. The inspected table had 57 entries; detect actual count drift rather than hard-code 57. Separate hospital identity, trauma designation, and ambulance columns. Do not infer current ambulance availability. Detect duplicate names, malformed district names, blank fields, and multiple vehicle values. Use synthetic HTML fixtures to test row extraction, layout changes, Unicode and missing cells. Emit source/identity/service-evidence batches and a coverage/error report. Produce a SHA/commands/artifact handoff; do not touch sibling scopes or the shared contract.

### B2 — Campus identity and RGHS crosswalk

Branch `codex/acq-b2-identity`; write `research/trauma/identity/`, `tests/research/trauma/identity/`, and `research/trauma/handoffs/B2.md` only.

Launch prompt:

> Implement B2 under ACQ-B01. Acquire the RGHS government-hospital list and extract hospital identifiers, names, addresses, districts, source page/row locators and available dates. Handle repeated headers, wrapped addresses, abbreviations and PDF layout problems. Build an auditable alias/campus candidate crosswalk for the state trauma list: name evidence plus address/district, with ambiguous and unmatched rows retained. Use JLN Hospital/Medical College in Ajmer as one case, but verify rather than assume same-campus equivalence. Seek official institutional pages only to resolve concrete ambiguities. Do not independently confirm matches to VF or replace C's matching decisions. Test same-name/different-campus and acronym collisions. Handoff all parsing failures and unresolved alternatives.

### B3 — National trauma-program history and levels

Branch `codex/acq-b3-national`; write `research/trauma/national/`, `tests/research/trauma/national/`, and `research/trauma/handoffs/B3.md` only.

Launch prompt:

> Implement B3 under ACQ-B01. Acquire the MoHFW trauma-program document and inspect the actual publication/as-of dates and table structure. Extract all Rajasthan entries, reported levels, and functional/planned/sanctioned status with exact page/row references. Examine the older linked copy only to establish document lineage or change, not to double-count it as independent evidence. Verify state-section boundaries visually when text extraction misassigns rows. Separate historical program records from current status; do not infer capability from funding alone. Create a temporal claim ledger and identify conflicting or stale claims. Test state-header carryover, multi-line rows, missing levels and conflicting dates with synthetic fixtures. Handoff the lineage comparison, counts and limitations.

### B4 — Accreditation scopes and official hospital evidence

Branch `codex/acq-b4-accreditation`; write `research/trauma/accreditation/`, `tests/research/trauma/accreditation/`, and `research/trauma/handoffs/B4.md` only.

Launch prompt:

> Implement B4 under ACQ-B01. Build a reproducible lookup/review workflow for NABH campus-specific scope certificates and official hospital department pages. Review up to 20 Rajasthan facilities, prioritizing likely VF overlaps, conflicting identities, and varied districts/ownership types once those inputs exist. Before live overlap is available, use clearly labelled candidates from B1/B2. For each lookup record success, unavailable source, no located certificate, identity mismatch, outdated scope or unresolved interpretation. Capture certificate number, exact campus address, actual dates, explicit relevant service text and locator. General emergency medicine alone does not verify a trauma level; a certificate's date range alone does not prove current unsuspended accreditation. Missing accreditation is not a negative clinical finding. Do not bypass CAPTCHA/login or scrape paid services. Test expiry, branch mismatch, referral/planned wording and negation using synthetic documents. Handoff a selection ledger so absence and selection bias remain visible.

### B5 — Independent claim and provenance audit

Branch `codex/acq-b5-audit`; write `research/trauma/audit/`, `tests/research/trauma/audit/`, and `research/trauma/handoffs/B5.md` only. Read B1–B4 outputs without editing them.

Launch prompt:

> Implement B5 under ACQ-B01 as an independent reviewer. First define the audit rubric using synthetic cases. When B1–B4 artifacts exist, reopen original sources rather than trusting their summaries. Audit up to 30 service claims, or all if fewer; stratify across source types, dates, explicit vs indirect language, campus ambiguity and unresolved cases. Check exact quote containment, locator correctness, campus attribution, temporal interpretation, service specificity and source independence. Record pass/fail/uncertain with reasons, corrections requested and re-review results. Build a source-dependence map, including repeated government PDFs and self-published hospital claims. Do not call an audit independent merely because it is in a separate chat; document that adjudication uses the same available public evidence. Report selection bias and residual uncertainty. Tests must catch copied-source double counting, historical-to-current upgrades and campus-misattributed claims. Never edit another research chat's outputs silently.

## B lead integration tasks

B owns common `research/trauma/pipeline.py`, `research/trauma/README.md`, `research/trauma/requirements.txt`, other common files directly under `research/trauma/`, and `docs/handoffs/ACQ-B01.md`. Subchat scopes are exclusive. Use separate clones/branches; integrate reviewed child commits into B's branch without editing an active child's checkout. Child branches never merge directly to main.

1. Publish the planning checkpoint and record the five chat/branch links in your task issue. Start B1/B2/B3 independently. B4 starts its parser/review structure immediately and consumes priority identities when ready. B5 starts the audit rubric immediately and audits real artifacts after handoff.
2. Implement `python -m research.trauma.pipeline --input-dir <path> --output-dir <path>` to combine source outputs into contract batches without losing lineage or silently overwriting conflicts. Use sibling parser interfaces rather than rewriting their logic.
3. Preserve an evidence ledger and a facility lookup ledger, including failures and gaps. Separate a proposed alias from an accepted identity link; C owns VF matching, and B supplies its review evidence.
4. Coordinate with A on NHP lineage and with C on campus questions. Provide D batches with stable IDs, complete provenance, and an artifact inventory. Flag shared origins and unknown independence explicitly.
5. Request corrections identified by B5 and re-run affected tests. Freeze a reviewed artifact set with hashes; do not modify accepted raw snapshots in place.
6. Produce counts by source, district, claim type, temporal status, review outcome and missingness. Describe the selection rule for targeted accreditation review. Never report source coverage as coverage of all Rajasthan hospitals.
7. Provide a compact executive finding: what additional evidence is actually usable, what is historical only, what conflicts remain, and what the app must not claim. No arbitrary authenticity percentage.

## Acceptance and finish line

- All required source families attempted with success/failure evidence; accessible state and national Rajasthan rows captured with reconciled counts and exact locators.
- RGHS extraction/campus crosswalk delivered, or a documented acquisition blocker plus completed parser/tests and alternative official identity evidence for reviewed candidates.
- Up to 20 targeted accreditation/official-site reviews completed; if fewer eligible candidates exist, state the denominator and reasons. Do not fabricate completeness or bypass access restrictions.
- Up to 30 claims independently checked by B5; every accepted audited claim has an exact passage/locator, correct campus and temporal scope. Unresolved/failed claims are excluded from verified use and enter the review queue.
- No unreviewed inferred trauma level, no live availability claim, no source-family double-counting, no name-only identity confirmation, no raw/credential data in Git.
- Execute `python3 -m unittest discover -s tests/research/trauma -p 'test_*.py' -v`; ensure recursive discovery actually executes each child suite (package markers or explicit per-child commands). Report per-suite test counts, not just exit code.
- D's schema/referential validator accepts the combined batch when available; until then validate against the shared JSON Schema and list cross-table checks still pending. Resolve actual failures before claiming readiness.
- Final PR contains reproducible code, all five synthetic test suites, audit method/results and `docs/handoffs/ACQ-B01.md`. Include child chat/branch/head references, exact commands, snapshot hashes/counts, artifact locations, corrected findings and remaining external/live blockers.

This is complete only when the accepted evidence package and audit can be reproduced from the handoff. A list of links, an unreviewed LLM summary, five finished chats, or a synthetic-only demonstration is not completion. B does not merge the PR or deploy the app.
