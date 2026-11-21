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
