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

## Intake added before Find care (22 November 2026)

Issue 136 puts a fictional patient's problem in front of the finder. The judge's first minute is
now: pick a patient, see their story and what a clinician has already decided, answer the first
question. Choices made for that minute:

- **One screen, two columns kept.** The patient list is on the left where the finder form was. The
  story, the current question and the outcome are on the right, so the first question is in the
  first view at 1366 px without scrolling. An earlier draft stacked all of it on the left and put
  the first question below the fold.
- **One question at a time, three large answers.** Answers so far stay listed with a Change control.
  Changing one asks the later questions again, which keeps every state one the build step stored.
- **Nothing loud until there is an outcome.** While questions remain there is no outcome slip, only
  a line saying no campus is chosen yet. The slip appears with the outcome. The emergency outcome
  is the only one drawn in red, and it says "emergency" in words as well.
- **The clinician's decision is part of the story, not a control.** A visitor confirms that the
  summary matches the story. They cannot supply a referral or an urgency, and the finder takes both
  from the confirmed request.
- **A shortcut for a recording.** "Fill in the answers from the story" answers as the story says, so
  each outcome is two presses away.
- **The finder is unchanged** and one press away under "Care already decided".

Not reviewed with scores yet. Known weak spots: seven patients is a long list on a phone, and the
confirmed summary and the campus slip are both large, so the page scrolls to the campus after
Find a campus.

### Connected to the team's intake engine (22 November 2026)

The stand-in evaluator, questions, patients and wording were replaced by the team's engine,
question catalogue, stories and finder bridge. What changed on screen:

- **The stories answer most questions themselves.** Each story states its facts, and the page lists
  them under "The story already says". A visitor answers at most one question, the one the story
  leaves open, so the first view of the first story is already a care summary to confirm.
- **Choices come from the question.** Each question brings its own answers (for example Mild,
  Moderate, Severe, Not sure), so the three fixed buttons became a row that wraps.
- **The first sentence of the engine's message is the headline** and the rest sits under it. The
  emergency message is long, and as one headline it filled the slip.
- **References are a list of titles**, each linking to the page the rule cites. Nothing is fetched.
- **"Fill in the answers from the story" is gone.** With at most one question there is nothing to
  shortcut.

