# Storm routing replay page

A single offline page that plays one fictional Jaipur-area storm shift under two allocation
policies with the same arrivals and the same clock. It reads replays written by
`python -m app.simulation` (`storm-replay-v1`) and draws them. It does not rank, allocate or
estimate travel: every outcome on screen is read from the replay's events, and every total is
counted from the events announced so far.

## Open it

Open `app/storm_ui/index.html` in a browser. No server, install or network is needed. The fonts
and the replays are files in this folder.

To show a replay with another seed or setting, write it and open it with **Open replay file**:

```
python -m app.simulation --scenario overload --seed 23 --detour-minutes 10 > /tmp/replay.json
```

A file is checked before it replaces what is open: the lists, every campus, resource, origin and
request, and every event and capacity change. If any part is missing or malformed the page names
the problem and keeps the replay that was open, at the same minute.

## What is on the page

1. **Setup.** Scenario (storm, no surge, overload, arrivals reversed, slot count unknown at A, slot
   goes offline), the longest detour the scarcity-aware policy may ask for (0, 5, 10 or 15
   minutes), map or text-only view, and the file opener.
2. **Clock.** Restart, Back, Play or Pause, Next, and a scrubber. Next and Back jump to the next or
   previous minute at which something happens. Space plays or pauses and the arrow keys step.
   Nothing later than the clock minute is shown, including totals.
3. **Two policy panels.** Each has the rule in a sentence, a schematic map and running totals:
   served, highest-urgency requests served within their travel limit, not served, and extra
   travel. On the map each staffed slot is a small square beside its campus: filled when used,
   outlined when free, struck through when it went offline, dotted with a question mark when the
   count is unknown or out of date. A request is a line from its origin to its campus. Urgency is
   shown by colour and by shape (diamond, triangle, circle). Requests that were not served are
   crossed markers beside their origin.
4. **Requests so far.** One row per announced request with its outcome under each policy. Selecting
   a row, a line or a marker fills **Why this campus**: where it went and how far, the faster
   campus it passed over and the slot that detour kept free, whether that slot was later used, the
   slot counts before and after, the campuses that were usable, and why other pools were ruled out.
5. **End of shift.** Appears only at the last minute: a comparison table, a line saying whether
   the totals counted from events equal the totals stored in the replay file, and a short summary.
   The summary states totals as totals. Anything it says about individual requests comes from
   comparing their outcomes one by one, so equal totals are never described as the same result.
6. **Text-only view.** Replaces each map with an ordered log of what happened and a table of
   staffed slots by campus. It carries the same information as the map.

## Files

| File | Purpose |
| --- | --- |
| `index.html`, `storm.css`, `storm.js` | The page. Plain HTML, CSS and JavaScript with no dependencies. |
| `replay_state.js` | Pure functions that turn a replay and a clock minute into what a panel shows. Runs in the browser and in Node. |
| `build.py` | Writes `data/scenarios.js` from `app.simulation`: six scenarios at four detour caps, seed 17. |
| `data/scenarios.js` | Generated. Do not edit. `python -m app.storm_ui.build` rewrites it and `--check` verifies it. |
| `fonts/` | Overpass 400, 600 and 700, under the SIL Open Font License (`fonts/OFL.txt`). |

## Checks

```
python -m unittest discover -s tests/storm_ui
```

The tests confirm that the committed bundle matches the simulation, that its default replay equals
`contracts/fixtures/storm_replay.json`, that the page loads nothing from the network, and (with
Node.js installed) that no state shows information from a later minute, that slot counts reconcile
with the events, that derived totals equal the replay's own totals in all 24 bundled replays, that
malformed nested data is refused with a reason, and that a replay with equal totals but different
people served is reported as different.

## Design notes

The look follows a printed weather chart and a dispatch board: pale chart paper, navy ink, one
rule between the two policies, and the clock as the spine of the page. Red, amber and blue are
reserved for urgency. The only animation is the current minute's lines drawing in and their slots
filling, and it is switched off when the browser asks for reduced motion. All points, capacities,
travel minutes and connecting lines are fictional and labelled so on the page.
