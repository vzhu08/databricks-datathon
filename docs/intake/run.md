# Replay the fictional intake demo

From the root of a clean checkout of the integrated intake revision, use Python 3.9 or newer. The CLI needs only the Python standard library and the checked-in fixtures.

```sh
python3 -m app.intake
python3 -m app.intake injury_to_assessment
python3 -m app.intake --help
```

The first command replays all seven journeys. The second shows the injury questionnaire, the stop for clinician assessment, the later scripted assessment, and confirmation before the fictional campus appears. Use `warning_overrides_plan` for an immediate stop, `incomplete_history` for unresolved answers, or `edit_after_confirmation` to see an old confirmation rejected before a new confirmation can reopen the finder.

Standard output is a JSON receipt. It includes the fixture SHA-256 and the actual input, assessment and finder response at each step. A blocked step has a null request and a null finder response. The receipt identifies the synthetic scenario and origin. Run it from the repository checkout so the versioned fictional scripts and travel fixture are present. This workflow demonstrates software behavior with fictional inputs and destinations.

Run the journey checks, the offline CLI check, and the existing finder and storm regressions from the same checkout.

```sh
python3 -m unittest tests.intake.test_scenarios tests.intake_e2e.test_cli
python3 -m tests.intake.test_scenarios
python3 -m unittest tests.ranking.test_urgency tests.ranking.test_urgency_cli \
  tests.find_care.test_find_care tests.simulation.test_storm_replay \
  tests.storm_ui.test_storm_ui tests.storm_ui.test_finder_ui tests.storm_ui.test_ask_ui
```

The standalone scenario module emits reachable assessment counts and the longest path using the same question choices as the offline page. Counts include the paired ready assessment wherever confirmation is available. The legacy screen and browser tests may require Streamlit or Node.js with Playwright. The replay CLI itself runs without warehouse or routing credentials.
