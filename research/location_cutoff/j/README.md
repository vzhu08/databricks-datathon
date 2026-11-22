# Physical-site check for the location cutoff

The unit is one original VF occurrence. The screen keeps every original and both
members of identical payload pairs. A geometric observation records where an
upstream point falls on the map. Verifying that an institution occupies a
particular building requires independent branch-specific evidence. A campus can
contain several buildings. A mapped entrance can serve a different building,
traffic direction or user group.

The source editions are VF facilities at Delta version 0, the frozen #163
occurrences and service decisions, and the 1 November 2026 Geofabrik India PBF
from #111 (© OpenStreetMap contributors, ODbL 1.0). The directory-v4 occurrence
file has a separate audience. Its authorized custodian can run the optional
intersection. No v4 rows or address-shortlist rows are included in the handoff.

Use the optional packages pinned in
`research/acquisition/issuer_campus_geometry/requirements.txt`. From the
repository root, set `VF` to the private #163 directory containing
`occurrences.jsonl.gz` and `decisions.jsonl.gz`, `PBF` to the verified India
edition, and `OUT` to an existing private working directory with several GB of
free temporary storage.

```sh
python -m research.location_cutoff.j.areas "$PBF" "$OUT/outlines.jsonl"
python -m research.location_cutoff.j.compare "$VF" "$OUT/outlines.jsonl" \
  "$OUT/clinical.jsonl" "$OUT/clinical-summary.json"
python -m research.location_cutoff.j.buildings "$VF" "$PBF" \
  "$OUT/buildings.jsonl" "$OUT/buildings-summary.json"
python -m research.location_cutoff.j.rollup "$OUT"
python -m unittest discover -s tests/research/location_cutoff/j -v
```

The clinical pass uses closed OSM ways and assembled multipolygons carrying
hospital, clinic, doctors or health-centre amenity/healthcare values, or medical
building tags. It compares full normalized name variants, structured street
address and postcode where available. It tests strict containment, boundary
touches, whole-building containment within clinical grounds, and disjoint
nearby exact-name alternatives. The 300 m candidate window uses a local
longitude/latitude approximation. Single points, road centroids and imagery
cannot enter the clinical polygon comparison. Absence of an assembled polygon
does not establish the absence of a physical building.

The separate all-building pass tests containment in every assembled
building-tagged polygon in the pinned map except those tagged no, construction,
proposed, demolished or ruins. It preserves inner holes, exact boundary hits,
multiple overlapping building outlines and different occurrences at the same
point. Generic footprints have no necessary connection to healthcare. A literal
name mismatch can reflect an alias, transliteration or a different institution.
The counts of spatial disagreements do not measure a labelled false-match rate.

The archived clinical and all-building editions each contain a national JSONL
and its summary with SHA-256. Place verified copies together for the rollup.
The custodian can supply the exact compressed directory-v4 ledger with
`--v4 /private/occurrences.jsonl.gz`. The program checks the pinned hash, all
10,088 occurrence keys, and the three directory status margins before selecting
7,418. An optional `--subset` accepts a private JSONL of distinct original
occurrence-key strings from an eligible source. The command emits counts only.
For A's narrower source use the in-memory comparison below.

```sh
python -m research.location_cutoff.j.address_shortlist \
  "$A_METHOD" "$NABH_SQLITE" "$VF/occurrences.jsonl.gz" "$OUT" "$PBF"
```

This comparison checks A's full method manifest and frozen inputs. It rebuilds
the 16 original candidates and three tied civic-number/street cases in memory.
For the issuer side it uses only uniquely linked numeric map points from the
permitted directory. It checks whether both source points fall in the same
mapped clinical outline or building, and whether the outline identifies the branch.
Publication is limited to the count aggregate. D adjudicates any physical-site
claim and measures cross-method overlap in the applicable custody.
