# Offline urgency-weighted service finder

From the repository root, run these three requests against the same fictional campuses. The fixture uses synthetic evidence and travel times from one invented origin.

```sh
python3 -m app.ranking contracts/fixtures/urgent_finder.json
python3 -m app.ranking contracts/fixtures/urgent_finder.json --urgency highest
python3 -m app.ranking contracts/fixtures/urgent_finder.json --service trauma_care
```

The routine MRI request ranks the 27-minute campus first because it has the preferred wider-bore scanner. Highest urgency ranks the 20-minute campus first. The trauma-care request returns `needs_confirmation` with an empty `ranked` array. Both campuses have unconfirmed trauma evidence.

## Request

The command reads one UTF-8 JSON object from the file or from stdin with `python3 -m app.ranking -`. It passes normalized inputs directly to `app.ranking.urgency.rank_campuses`. The caller supplies adjudicated evidence and travel estimates. The command runs offline.

| Field | Expected value |
| --- | --- |
| `service` and `urgency` | One of `dialysis`, `mri`, `trauma_care` and one of `routine`, `time_sensitive`, `highest`. The command-line overrides replace only these fields. |
| `as_of` | The requested assessment date, formatted as `YYYY-MM-DD`. |
| `travel_metric` and `travel_budget` | Choose `travel_minutes` or `distance_km` for the entire request. The positive budget has that unit. Each campus needs its measurement from the same origin and transport mode to qualify. |
| `required` and `preferred` | Optional arrays of feature keys. Every required capability must have a reviewed onsite `yes` for the requested campus and service. Preferred features earn points. An omitted preference redistributes those points among the other factors. |
| `candidates` | An array with one unique `facility_id` per campus. Supply the matching `as_of` date, the travel field, and a `services` object keyed by requested service. |
| `limit` and `half_life_months` | Optional positive result limit and positive evidence-recency half-life. The finder returns up to three results and uses 24 months by default. |

Each service decision carries a `status` of `yes`, `no`, or `unconfirmed`. Put the service claim’s **assertion date** in `source_date`, the reviewed upstream family labels in `independent_families`, and each feature’s reviewed `yes`, `no`, or `unconfirmed` in `capabilities`. A qualifying assertion must apply to the campus, service, and assessment date. Both `yes` and `no` need a valid assertion date on or before `as_of`. A webpage refresh, retrieval time, or signed review timestamp cannot substitute for that date. Producers collapse mirrors and reused upstream sources before supplying the family labels.

## Response

Valid requests emit one JSON object on stdout and exit 0. `ok` returns scored campuses with the travel value, factors, weights, source date, and availability. Availability stays `unknown`. `needs_confirmation` returns unscored leads with reasons. `no_match` means this request had no eligible result or confirmation lead in the supplied candidate pool. A malformed request writes an `invalid_input` JSON diagnostic to stderr and exits 2.

## Individual Find care selection

Call `select_individual(service, candidates, *, allocation=None, emergency=False, withheld_summary=None)` from `ranking.individual` in the packaged app. Use the current request’s server-produced allocator result and the candidate fields already cleared for the receiving audience. Each candidate has a stable `key`, optional `name` and `area`, separate mapper `location` and `service` claims, and an established `source_scope`. Optional observations are `availability`, `travel` (sourced ordinary-car minutes) and `distance_km` from the same origin. Missing observations stay unknown.

For a private edition, retain original occurrences with a left join on the pinned occurrence key and requested service. For synthetic cards, bind the mapper’s `(result_group, index)` within the same response and retain the card's ID. Unconfirmed service and missing secondary evidence can both yield a lead. For the judge-facing warehouse path, pass only the mapper’s already-cleared `summary` as `withheld_summary` with an empty candidate list.

Display and export the returned decision together. A supported allocator preview carries the allocator’s chosen option, source and mode. A reviewed real assignment also needs a matching cleared campus projection. For a provisional result, use the selected candidate’s two claim objects, `reason`, `missing` and `next_action` for the confirmation note. A location-only lead requests branch and service verification. The selector performs no network or storage operations.

For example, the invented Campus A fixture reports “dialysis unit” in `procedures`. The claim has one source family, a reported locality, an unknown observation date and unknown staffed availability. A private projection explicitly classified as VF-only yields **Provisional · VF only** and a confirmation note. The public synthetic demo uses **Provisional** and displays its synthetic origin. Both preserve the source field and leave the road time unknown.
