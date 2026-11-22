# Design notes: the judge's path

Written on 21 November 2026 for the rework that made **Find care** the first screen.

## What a judge is looking for

Sources: the organiser's [challenge brief](https://docs.google.com/document/d/e/2PACX-1vQxhDNQmgZhPgjG0M6LCb_UXNV8CJryqBNQQuqWfIg_dm40ZU1AYAXzZKViC6haFoCmLNiRVfUSBMjf/pub)
and [event page](https://cmudsc.com/datathon-fall2026/).

- The build takes two inputs, a service and a location, and returns the best facility with an
  evidence-based explanation.
- "The one rule: show your reasoning." Every recommendation must answer **why this facility**
  (evidence it exists, offers the service and suits the location) and **how did you decide** (what
  was weighed and traded off).
- A submission must "support a clear non-technical user workflow", "cite the underlying facility
  text" for any important claim, and "communicate uncertainty instead of presenting weak evidence
  as fact".
- Judging criteria: exploration, modelling and impact ("actionable and impactful policies").
  Judges work from code, analysis and a video, so each screen has to read on a recording.

A judge's first three minutes, and what must be obvious at each point:

| Time | The judge | Must be obvious |
| --- | --- | --- |
| 0 to 20 s | Looks for the two inputs. | What the page is for, and where to choose the care and the place. |
| 20 to 60 s | Runs one request. | One campus, in a sentence, with the travel time. |
| 1 to 2 min | Asks why and how. | The record text, its date and sources. The points, the weights, and a nearer campus that lost and why. |
| 2 to 3 min | Probes weak evidence. | An unconfirmed claim shown as unconfirmed, with nothing recommended. One next action. |

## Brief (impeccable `shape`)

- **Job and audience.** A community health worker or coordinator with a patient in front of them.
  Operate mode: the page should disappear into the task.
- **Outcome and proof.** One referral. Proof is the cited record and the ranker's own numbers.
- **Direction.** The answer is drawn as a referral slip, the object the worker hands over. It is
  the one loud element. Flow: Ask, Recommendation, Why, Caveat, then the storm stress test.
- **Boundaries.** Invented data, offline, no ranking in the page. Availability is never implied.
- **States.** Answer with zero to two backups, only unconfirmed leads, no match, stale answer,
  missing data file.

No one was available to confirm the brief, so these are assumptions.

## Review scores (impeccable `critique`, Nielsen heuristics, 0 to 4)

⚠️ DEGRADED: single-context (sub-agents were not used, to keep the run cheap). The bundled detector
was not run, because that means downloading and running a third-party binary. Scores are one
reviewer's reading of the rendered pages.

| # | Heuristic | Finder before | Find care after | Storm before | Storm after |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Visibility of system status | 3 | 3 | 3 | 4 |
| 2 | Match with the real world | 1 | 3 | 2 | 3 |
| 3 | User control and freedom | 2 | 3 | 4 | 4 |
| 4 | Consistency and standards | 3 | 3 | 3 | 3 |
| 5 | Error prevention | 3 | 4 | 3 | 3 |
| 6 | Recognition rather than recall | 1 | 4 | 2 | 3 |
| 7 | Flexibility and efficiency | 1 | 2 | 3 | 3 |
| 8 | Aesthetic and minimalist design | 2 | 3 | 2 | 2 |
| 9 | Error recovery | 3 | 3 | 3 | 3 |
| 10 | Help and documentation | 1 | 3 | 2 | 3 |
| | **Total** | **20/40** | **31/40** | **27/40** | **31/40** |
| | Cognitive load checklist failures | 4 of 8 | 1 of 8 | 3 of 8 | 2 of 8 |

Before, the first screen was a viewer for driving-time responses: no inputs, a list of example
names, facility ids and routing states. It answered a developer's question. It is now the
technical page. What still scores low after: the points table is dense on a phone, there are no
keyboard shortcuts or shareable links on Find care, and the stress test still shows a setup row,
two maps and two tables at once.

`distill` removed the example picker, counts and routing states from the first screen and put raw
request and response under closed technical details. `clarify` replaced request ids with
"Patient 8", "scarcity-aware" with "urgency-aware", and reason codes with sentences.

## Technical check (impeccable `audit`, 0 to 4)

| Dimension | Score | Finding |
| --- | ---: | --- |
| Accessibility | 3 | Text contrast is 4.7:1 or better. Focus is visible and moves to the answer. Not tested with a screen reader. |
| Performance | 4 | Static files, no network, one short animation. |
| Theming | 3 | Colours are tokens. Light only, chosen for daytime use. |
| Responsive | 3 | No sideways scroll at 390 px. The points table scrolls inside its own box. |
| Implementation integrity | 3 | Detector not run. Checked by eye against both skills' lists of defaults. |
| **Total** | **16/20** | |
