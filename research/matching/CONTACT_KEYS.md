# Proposal: exact contact-key confirmation (prototype, not wired in)

**Status:** proposal for Oliver and Vincent. Nothing here changes `run.py`, `decide.py`,
ranking, ingest or any national output. Code: `research/matching/contact_keys.py`,
tests: `tests/research/matching/test_contact_keys.py`.

## Why

Every national run so far confirms zero campuses, by construction: the only automatic path is
an identifier shared in an inspected namespace, and national runs use `identity_policy: null`
(diagnosis on #40, issuecomment-7073268680). VF rows do carry their own contact keys. If an exact
phone, website host or email were accepted as an identifier against an outside list that VF did
not come from, some rows could be confirmed under the same rule `decide.auto_confirmation`
already applies.

## Rule measured

A pair counts as `would_confirm` only when all of these hold:

1. **Exact key after normalisation.** Phones become E.164 (`+91` plus 10 digits; numbers
   written without an STD code, toll-free `1800/1860` lines and placeholder digits are dropped).
   Websites become the lower-case host without `www.`; aggregator, social, directory and
   generic government portal hosts (Facebook, Justdial, Practo, IndiaMART, `nhp.gov.in`,
   `esic.nic.in` and others in `SHARED_HOSTS`) are never keys. Emails are lower-cased.
2. **Unique on both sides.** The key sits on exactly one of the 10,088 original VF rows (counted
   over every phone and website value in the row, including the noisy `phone_numbers` and
   `websites` lists) and on exactly one record of the outside source. This is what removes
   chains: `fortishealthcare.com` is on 14 VF rows and 5 NHP records, so it never confirms.
3. **Only VF's official fields propose a match:** `officialPhone`, `officialWebsite`, `email`.
   The list fields often carry other facilities' directory pages, so they only block.
4. **Geography agrees.** At least one of state, PIN or distance (5 km) can be compared and none
   disagrees. No comparable geography means review.
5. **One partner.** The VF row reaches only one record in that source.
6. **Names carry some evidence** (`normalize.name_evidence` is not `none`). Otherwise the pair
   goes to review.

## Results (VF snapshot 10,088 rows, run 2026-11-22)

VF keys: 9,445 rows have an official phone (8,740 with one no other row shares), 8,001 an
official website host (7,036 unique), 8,142 an email (7,899 unique).

| Outside list | Records with a key | Pairs on a shared key | Would confirm | Of which |
|---|---|---|---|---|
| NHP Hospital Directory 2025 (Bharatlas mirror, GODL) | 1,237 of 10,843 | 486 | **41 VF rows** | host 35, email 23, phone 4 |
| Wikidata hospitals in India (CC0, 2,854 items) | 628 web, 73 phone | 598 | **74 VF rows** | host 74, phone 1 |
| **Both, distinct VF rows** | | | **111** (4 in both) | |
| *Control: Overture, Meta-sourced* | 185,985 phone | 28,400 | *2,794* | not independent |
| *Control: Overture, Microsoft/Foursquare/PinMeTo* | 41,405 | 105,007 | *170* | not independent |

Blocked pairs: NHP 381 not unique, 56 geography conflict, 7 name review, 1 competing.
Wikidata 474 not unique, 41 geography conflict, 5 name review, 3 no geography, 1 competing.

Overture is shown only as a control. VF lists `overture` as a source type on most rows, and the
open-data probe found 7,489 of its 7,916 phone/website matches are Meta-sourced places, many
within 10 m. Overture can never be the independent side.

## Precision check

All 115 would-confirm pairs plus the 15 review pairs were read by hand on name, PIN and key
(`review_pairs.csv` in the project files, not committed: it holds VF row text). This was a
desk read, not a visit to each website or a phone call.

* 113 of 115 would-confirm pairs are the same facility by name and place.
* 2 are debatable: *Hero DMC Heart Institute* matched to *Dayanand Medical College & Hospital*
  by `dmch.edu` (a unit on the same campus, a different facility name), and *KJ Somaiya
  Hospital* whose VF PIN (401107) does not match the hospital's known locality, though the
  points are within 5 km.
* 0 clear false matches passed. The name gate caught the two false matches found
  (*Isha Multispeciality Hospital* with Pramukhswami Medical College's site; *MP Birla Hospital*
  with a Gwalior cancer hospital's site). It also sent 8 true matches to review whose names are
  worded differently (*Lisie Hospital* / *Mar Augustine Memorial Lisie Hospital*, *Kidwai*,
  *Borooah*, *Sancheti*, *Surana*, *Midas*, *Abhishek*, *CMC Hisar*).

Desk precision on the would-confirm set: 113 to 115 of 115 (98 to 100%).

## Independence caveats (owners to decide)

* NHP and OpenStreetMap are not independent of each other: about half of OSM hospitals carry
  `source=OpenGovernmentData`. Count one family, not both.
* The existing acquisition manifests mark NHP and OSM `shared_origin` ("independence from VF
  has not been assessed"). One VF row cites an `nhp.gov.in` page and one a Wikidata page; VF's
  "dynamic" rows were web-scraped, so a hospital's own site can feed both VF and Wikidata. A
  shared official website still points to the same organisation, but the owners should decide
  whether that counts as an independent source for confirmation.
* Wikidata items are sometimes organisations, not campuses (e.g. a dental chain); the geography
  requirement removed the one such case found.

## What adopting it would take

1. Owners accept contact keys as an identifier namespace and pick the sources and families.
2. Write the normalised key into one field per side (e.g. `contact_host`, `contact_email`,
   `contact_phone_e164`) in the prepared base rows and the external batch, so the existing
   `identity_policy` binding (`base_field`, `external_field`, `source_keys`) applies unchanged.
   `decide.auto_confirmation` already enforces exact text, uniqueness on both sides and no
   geography or competing-candidate conflict. The name gate (rule 6) would be new.
3. Add the OSM contact tags pull (in progress in the open-data probe) as a further family.

Expected effect: about 111 VF rows move from 0 confirmed to confirmed on current sources, with
15 more pairs ready for a short human review.

## Reproduce

```
python3 -m research.matching.contact_keys --base <base.json> \
  --nhp-tsv <nhp_2025_contacts.tsv> --wikidata <wikidata_india_hospitals.json> \
  [--overture-csv <overture_india_health_places.csv>] --out report.json
```

`base.json` is the prepared base export (original VF rows with `source_row`). The NHP TSV is
the contact columns of the 1,237 NHP records that have any phone, website or email, taken from
the mirror GeoJSON at the URL recorded in the matching handoff provenance (`NHP_Hospital_Directory_2025.geojson`, read 2026-11-22; its hash was not re-checked against `058ca806…2e47`).
