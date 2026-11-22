# Find care app

`app.py` is the Streamlit screen for Databricks Apps. It takes a service and a location, typed on
one line as a city or town (with the state after a comma), a six-digit PIN code, or coordinates,
and words what the team's search returns. It follows the
[search contract](../docs/implementation/SEARCH_CONTRACT.md) and never ranks or filters on its own.
`find_care.py` holds the wording and the two rules below as pure functions.

## Data mode

The mode is named at the top of the screen (`Data: demonstration`, `Data: real records` or
`Data: not available`) and is decided by `find_care.data_mode` from the app's settings:

| Setting | Mode |
| --- | --- |
| `FIND_CARE_DATA=demo`, or none of the five warehouse settings present | Demonstration on the six invented facilities in `demo_facilities.json` |
| `FIND_CARE_DATA=warehouse`, or any of the five warehouse settings present | Real records through `search_warehouse` |

The five warehouse settings are `DATABRICKS_WAREHOUSE_ID`, `DATABRICKS_PREPARED_TABLE`,
`DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET`. Databricks Apps supplies
the last three to every app, so a deployed app is a demonstration only because `app.yaml` says
`FIND_CARE_DATA=demo`. A warehouse that is only partly configured, including the host or the
credentials on their own, is a setup problem and never a fallback to invented data. The screen
names each missing setting without repeating any value, and stops.
A table that cannot be read gives "The facility records cannot be reached right now."

## What each mode shows

**Demonstration.** One facility, the exact words from its invented record with the field they came
from, its record sources, what is not confirmed, up to two backups, a referral note to copy or
save, and the request and response under Technical details.

**Real records.** The v0 search answers `ok` when a record states the service and orders by
straight-line distance. That is not enough for a referral, and the team's verified count of
eligible real destinations is zero. So every warehouse response passes through
`find_care.withheld` before anything else sees it. The screen says whether nearby records mention
the service and that none is reviewed and approved. It shows no facility name, place, distance,
record text, source link or identifier, no backup, no referral note, no download, no place-name
choices, and no response payload: Technical details holds the request and the status only. The
withheld form is also all that is kept in session state. Lifting this needs an adjudicated
service, a reviewed campus, an approved destination and display-permitted fields through a
verified interface, and is Oliver's decision.

The screen has no print control of its own in either mode.

In both modes the form always shows the request the answer is for: an example fills the form before
it searches. When the form is changed after an answer, the answer is marked as being for the earlier
request and greyed, and the backups, the referral note and the download are taken away until Find a
facility is pressed again.

## Run it

```
pip install -r app/requirements.txt
streamlit run app/app.py
```

To deploy, use `app/` as the app's source folder: `app.yaml` runs `streamlit run app.py` there and
sets `FIND_CARE_DATA=demo`. The demonstration facilities are inside `app/` so that folder is
enough on its own. `demo_facilities.json` is a copy of `contracts/fixtures/search.json`, and a
test fails if the two differ.

Not done here: no deployment has been made, and the screen has not read the real table. Live
deployment and publication need a separate decision.

## Checks

```
python -m unittest tests.find_care.test_find_care
```

Nine wording and rule tests run on the shared fixture. Ten screen tests drive the app through
Streamlit's test harness, including a stub warehouse whose v0 answer is `ok` only because a record
states the service, a half-configured warehouse, a read failure, and a request changed after its
answer. Two more copy `app/` to an empty folder, answer the demonstration example there, and start
the server with the command in `app.yaml`. The twelve tests that need Streamlit are skipped when it
is not installed.

## Design review

Reviewed on 21 November 2026 against a judge's first minutes: find the two inputs, run one request,
ask why and how, then probe weak evidence. Nielsen's ten heuristics, 0 to 4 each, one reviewer
reading the rendered screen at 1366 px and 390 px. No automated detector was run.

| # | Heuristic | Before | After |
| --- | --- | ---: | ---: |
| 1 | Visibility of system status | 2 | 3 |
| 2 | Match with the real world | 2 | 3 |
| 3 | User control and freedom | 2 | 3 |
| 4 | Consistency and standards | 2 | 3 |
| 5 | Error prevention | 1 | 3 |
| 6 | Recognition rather than recall | 2 | 3 |
| 7 | Flexibility and efficiency | 2 | 2 |
| 8 | Aesthetic and minimalist design | 2 | 3 |
| 9 | Error recovery | 3 | 3 |
| 10 | Help and documentation | 2 | 3 |
| | **Total** | **20/40** | **29/40** |
| | Cognitive load checklist failures | 3 of 8 | 1 of 8 |

What was wrong before, in the order a judge would hit it:

1. The location boxes showed "Jaipur" and "Rajasthan" as grey hints that read as filled in, so the
   first press of Find a facility answered "Type the city or town." The demonstration form now
   starts filled, and the first press answers.
2. The examples sat under the form, below the fold. The form is shorter (one location box in place
   of a mode switch and up to two boxes), so they are in the first view, and each one fills the form.
3. The data mode, the screen's main honesty signal, was the faintest text on it. It is a band under
   the title.
4. The answer's parts had the same weight, and the cited record text, which the brief asks for, was
   the greyest. The answer is now the same referral slip as the offline Find care page: the request,
   the facility, the distance, why this facility, what its record says with its field and source,
   then the caveat.
5. An answer stayed on screen unmarked after the form changed, with its referral note still there
   to copy. See the paragraph above.
6. "About 6.7 km in a straight line from the middle of that place." is now "About 6.7 km away, in a
   straight line.", with the approximation said once under the answer.

What still scores low: Enter in the location box does not search, the screen shows no progress
while a warehouse query runs, and on a phone the answer lands below the form and the examples.
