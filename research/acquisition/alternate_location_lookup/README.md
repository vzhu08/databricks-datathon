# Alternate location lookup pilot (#251)

The sampler runs offline against pinned VF v0 and the older LOC-03 joint occurrence trace. It checks every original payload against the trace and preserves the full 10,088 occurrences and 10,077 upstream IDs in the denominator. The 30,264 service slots are context. The newer #206 aggregate reports 142 missed occurrences and 9,946 reached, but cannot identify those occurrences for sampling.

```sh
python -m research.acquisition.alternate_location_lookup.sample \
  --base /private/base.json --trace /private/occurrence-delta.jsonl.gz \
  --public-controls /private/public-controls.json --output /private/sample.json
```

The control input is a JSON array of objects with publisher-observed `names` (array of strings), `pin` (string), and `url` (publisher reference). Freeze the source-independent query text and publisher witness before the local link. The exact normalized name/PIN rule generates a candidate only, with competing addresses reviewed separately. Never use the private output as search input. It contains occurrence keys. Local sample order balances state and facility type within missed and competing strata, selecting 12 per stratum by a fixed hash seed and suppressing duplicate representatives within each stratum. This intentionally overrepresents difficult rows and does not support a population estimate.

For each eligible occurrence, record Google attempt/access state, then run the same independently published institutional name and locality on Bing India, DuckDuckGo India and Mappls. Keep published aliases in a separate round. Compare the first map card and the visible organic results with the dated operator or regulator address. Deduplicate by publisher. Record organization, locality, campus, entrance or branch, conflict, no result and access block separately. Only a new publisher-supported campus or branch beyond the frozen eligible baseline counts as recovery. See #251 for the comparison and scope limits.

Two actual replays matched byte for byte. The sampled 24 rows covered 19 state buckets and seven facility-type buckets. Neither of the two publisher records for the Sanathnagar public control linked by exact name/PIN, so all 24 sampled rows lack an approved public query witness in this pilot. The latest 142 misses have no occurrence-level crosswalk in the shared aggregate. A baseline candidate outcome is not evidence of a past Google search. Private keys and raw VF rows stay in the approved workspace.

## Cycle 02 eligibility replay

Use the verified #181 facility-only ZIP and manifest, plus the previously frozen
private sample. The archive member is checked against the manifest before use.

```sh
python -m research.acquisition.alternate_location_lookup.eligibility \
  --base /private/base.json --sample /private/sample.json \
  --archive /private/nhp-facility-directory-v1.zip \
  --manifest /private/manifest.json --output /private/e1-results.json
```

E1 freezes query text before the local join, using literal issuer name and
town, subdistrict or district in that order. District fallback is a locality
label and can be too broad for branch identification. Exact name/PIN candidates
still require branch and rival review. An NHP row locator is an edition record
key. The edition has no per-row effective branch date. Query candidates,
occurrence joins and reviewer work stay in private custody.
