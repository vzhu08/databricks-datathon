# Rajasthan candidate extract (ACQ-A02)

This offline command selects smaller, reviewable subsets from A's accepted OSM/NHP snapshots for B and C. It preserves the original national batch for recall. It makes no campus match, clinical claim, state correction, freshness claim or new independent-source assertion.

## Reproduce from the accepted ACQ-A01 artifacts

From the repository root, activate the environment described in [README.md](README.md). No new dependency or network request is needed.

```sh
source research/acquisition/.venv/bin/activate
acq_public=data/local/acquisition/public
python3 -m research.acquisition.rajasthan \
  --snapshot "$acq_public/snapshots/hot_osm_health/5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3" \
  --snapshot "$acq_public/snapshots/nhp_hospitals_mirror/058ca80693d6ee3c20b8588cfd1889e6ae3f7241a33a717854fbbc3d354e2e47" \
  --national-batch "$acq_public/runs/0eac1025996c46409dd3b07aeca8e283/batch.json" \
  --output-dir data/local/acquisition/rajasthan-v1
```

Pass the complete accepted snapshot directories, including their manifests and raw/support artifacts. `--snapshot` may be repeated. Every saved file hash is verified, original bytes are reparsed, the accepted normalized batch/coverage must reproduce exactly, and the supplied national envelope must equal the union of the snapshots. A mismatched or corrupted input fails before publication. The extractor never downloads replacement data or overwrites source artifacts.

`--output-dir` must be new or contain an identical previous extraction. Repeating the command verifies byte-identical replay, including the manifest, report and decision index. A changed/corrupt existing output is refused, not overwritten; choose a new directory for a different input/rule version. Input/output directory overlap is refused. Output files appear together via an atomic directory rename, with no wall-clock field in their deterministic content.

## Frozen selection rule

`rajasthan_rules.json` defines `rajasthan-candidates-1.0.0`; its canonical-JSON SHA-256 is recorded in each report/manifest. The parser folds Latin accents (so `Rājasthān` equals `Rajasthan`), case, punctuation and whitespace while retaining Hindi vowel marks. Original row values are never normalized in place.

1. **Explicit state:** the entire normalized `state` is `rajasthan` or `राजस्थान`.
2. **Explicit address:** the original address ends in a recognized Rajasthan state token, optionally followed by a six-digit PIN and/or `India`/`भारत`. State suffixes are matched on word boundaries. A name containing Rajasthan, `Rajasthan Road`, a city/district name, or a postal prefix alone is not state evidence. The frozen suffix list includes full English state names for detecting competing address signals; undocumented abbreviations are not expanded.
3. **Conflicts:** explicit Rajasthan address plus another nonmissing state, explicit Rajasthan state plus a recognized other-state address suffix, or explicit Rajasthan text plus coordinates outside the geographic rectangle goes to additional review. Missing coordinates do not contradict explicit text.
4. **Additional geographic candidates:** rows with missing or other-state labels whose normalized coordinates fall inside the rectangle go to additional review. Missing-state tokens are null/empty, `0`, `unknown`, `not available`, `n/a` or `na`. Coordinates are not repaired or geocoded.
5. **Excluded from the smaller extracts:** everything else remains available in the unchanged national batch. No claim is made that these rows cannot match a Rajasthan campus.

The inclusive screening rectangle is **longitude 69.4–78.35, latitude 23.0–30.25**. It rounds outward from the [Rajasthan State GIS portal's published extent](https://rajdharaa.rajasthan.gov.in/), inspected November 21, 2026. It is **not a state polygon** and includes substantial neighboring-state territory. `other_state_inside_geographic_screen` is a recall signal, not proof of a location/state error. The additional batch can therefore be larger than the explicit batch. C should prioritize explicit candidates, inspect additional candidates as needed, and retain national recall. A future polygon filter would require a new pinned rule/artifact and its own provenance; it is not silently assumed here.

## Outputs

- `explicit.json`: a v1.0.0 envelope with explicit Rajasthan state/address support and no detected conflicting signal.
- `additional_review.json`: a separate v1 envelope of geographic recall candidates and text/coordinate disagreements. Each gets a deterministic `rajasthan_candidate_review` item linked to its unchanged external ID.
- `decisions.json`: one decision per unique national external ID, including exclusions, snapshot ID, bucket, reason codes and screening signals. It stays outside Git with the real data.
- `report.json`: per-snapshot source hashes, national/source paths and hashes, partition counts by source, rule details and limitations. For every snapshot: `explicit + additional_review + excluded = unique_national_rows`; `unique_national_rows + identical_input_occurrences_removed = input_occurrences`. Original raw input counts and A01 exact-repeat counts are also preserved for reconciliation back to the downloads.
- `manifest.json`: hashes of all four output files, the national batch hash and the rule hash. Hashes cover each file's canonical UTF-8 JSON bytes plus a final newline.

Both envelopes include all original source-snapshot reference rows, even if one source contributes zero candidates. Selected external rows are copied unchanged, including all identifiers, source locators, types, original names/addresses, coordinates, quality flags, provenance and first retrieval time. Existing review items follow their selected external rows; source-global reviews would appear in both. Linked evidence/matches or base-linked review context are rejected because this command is restricted to A's unlinked acquisition inputs. Existing source/evidence rows are not reinterpreted as Rajasthan service evidence.

Repeated identical external IDs deduplicate deterministically. A changed payload under an existing ID fails; separate variants under distinct external IDs survive even when the original source ID or facility name repeats. New selection reviews hash the rule hash, external ID and reasons. They do not mutate or replace acquisition reviews.

## Verify

```sh
python3 -m unittest discover -s tests/research/acquisition -p 'test_*.py' -v
```

Producer schema/reference checks run automatically. D's merged validator can independently validate the two envelopes with an empty base array, because no matching is asserted:

```sh
# This creates a local validation input, not a Marketplace export.
python3 -c 'from pathlib import Path; Path("data/local/acquisition/empty-base.json").write_text("[]\n")'
python3 databricks/enrichment/validate_batch.py \
  --batch data/local/acquisition/rajasthan-v1/explicit.json \
  --batch data/local/acquisition/rajasthan-v1/additional_review.json \
  --base data/local/acquisition/empty-base.json --as-of 2026-11-21
```

An empty base only checks unlinked batch compatibility. It cannot establish base coverage, reviewed matches or live Databricks publication. Real source data, extracts, decisions, validator outputs and manifests stay in ignored `data/local/` or an authorized Volume. Copy the complete source directories and national batch for another environment, preserving original immutable metadata and recording physical relocation separately.

The [ACQ-A02 handoff](../../docs/handoffs/ACQ-A02.md) records actual counts, hashes, exact tested SHA, validation results and review limitations for #21 and C's #5.
