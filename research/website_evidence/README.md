# Dated service mentions from facility websites (proposal)

The Virtue Foundation (VF) service text is undated, so under [the service rules](../../docs/implementation/SERVICE_STATUS.md)
it cannot give a "yes". Most VF rows name their own website. Common Crawl keeps archived copies of
those sites, and every archived page carries its capture timestamp. This prototype reads each row's
first-party site from the archive and keeps the sentence that mentions **dialysis**, **MRI** or
**trauma care**, with the page URL and capture date.

A record here is a **dated website mention**, not a confirmed service. Every record has
`status_effect: "none_until_reviewed"`. It becomes a "yes" only if a named reviewer accepts the quote
for the right campus (for example as an external review, `{"kind":"external","evidence_id":...}`,
in `research/service_status`). Records on a domain shared by several VF rows (hospital chains)
carry `campus_attribution: "needs_review"`.

## Steps

1. `domains.py`: pick each row's own domain from `officialWebsite` and `websites`. Listing, social,
   map and directory sites are dropped, as are `.gov.in`/`.nic.in` portals and any domain used by
   more than 60 rows. A domain is kept when it contains a distinctive word of the facility name or
   its initials, or it is the row's `officialWebsite` and at most two rows use it. At most two
   domains per row. **8,207 of 10,088 rows** have one.
2. `cc_index.py`: look up the domain in Common Crawl's ZipNum index on `data.commoncrawl.org`
   (`cluster.idx`, then one compressed index block), pick the home page plus up to seven
   service-looking paths, and read each page's WARC record with an HTTP range request.
3. `extract.py`: visible text only (scripts, styles and menus' markup removed), split into
   sentences, match the three services, and grade the best quote:
   - `direct`: a full sentence that ties the service to the facility ("we", "our", "in-house",
     "equipped", "unit", "24x7", "1.5 Tesla", ...);
   - `listed`: a short menu or list item ("Dialysis Unit", "Emergency & Trauma Care");
   - `weak` (dropped): blog/tag/news paths, patient-education wording ("your doctor may order an
     MRI"), menus, and qualified wording ("coming soon", "planning", "referred to").
   Thin pages (under 300 visible characters, usually a bot check or a JavaScript shell) give nothing.
4. `build.py`: join the run back to rows and write `evidence.jsonl` (one record per row × service)
   and `report.json` (coverage and the hand-review tally).

`browser_run.js` is the same pipeline in browser JavaScript. It is what produced the numbers below,
because the cloud workers cannot reach Common Crawl at all and `index.commoncrawl.org`'s CDX server
answered HTTP 504 to every query. Throttle it to about three requests a second: an unthrottled run
with six workers was blocked by CloudFront for about 20 minutes.

```sh
python -m research.website_evidence.build --rows PRIVATE/sample_rows.json --domains PRIVATE/sample_domains.txt \
  --status PRIVATE/status.txt --hits PRIVATE/hits.psv --crawl CC-MAIN-2026-39 --out PRIVATE/out
python -m unittest tests.research.website_evidence.test_website_evidence
```

The run outputs contain VF identifiers and website text, so they stay out of Git (see `AGENTS.md`).

## Results: random sample, one crawl (CC-MAIN-2026-39, captured 4 to 17 September 2026)

A random sample of 2,000 of the 8,207 rows with a first-party domain (seed 20261122; 2,403
distinct domains). All 2,403 domains were read.

| Sample rows (n = 2,000) | Rows | Share |
|---|---:|---:|
| No capture of the domain in this crawl | 1,026 | 51% |
| Captured, but no readable page (bot check, JavaScript shell, non-HTML) | 277 | 14% |
| At least one readable archived page | 697 | 35% |
| **Gain a dated, quotable mention of at least one service** | **202** | **10.1%** (about ±1.3 points) |
| of which a full sentence tying the service to the facility (`direct`) | 121 | 6.1% |
| Dialysis mention | 129 | 6.5% |
| MRI mention | 73 | 3.7% |
| Trauma-care mention | 101 | 5.1% |

Among rows with a readable page, 29% gain a mention. Scaled to all 8,207 first-party rows, that is
roughly **830 rows with a dated mention, about 500 of them `direct`**. Captures date from 4 to
17 September 2026. 26 records sit on domains shared by several rows and need campus attribution.

**Hand check.** Every kept quote (290 domain × service quotes) was read and labelled once by an AI
reviewer, not by a named team reviewer: A = says the facility provides the service onsite,
B = lists the service on the facility's own page without more detail, C = not usable (patient
education, another hospital, a network-wide page of a chain, a course, a planned service, a menu).

| Grade | Quotes | A | B | C | A or B |
|---|---:|---:|---:|---:|---:|
| `direct` | 155 | 112 | 21 | 22 | 86% |
| `listed` | 135 | 3 | 112 | 20 | 85% |

By service, A-or-B is 88% for dialysis, 89% for trauma care and 78% for MRI (MRI pages often explain
the scan rather than offer it). Typical misses: chain home pages ("across its network"), vascular
access for dialysis, ocular or dental trauma, orthopaedic trauma surgery counted as trauma care, and
department drop-down menus. The labels travel with each record (`review`), so a team reviewer can
start from them.

## Specialists listed on doctor pages (same sample, same crawl)

`specialists.py` reads up to six archived doctor, team or department pages per domain and counts
the doctors listed for five specialties: nephrology (supports dialysis), radiology (MRI), and
orthopaedics, neurosurgery and emergency/trauma medicine (trauma care). A "Dr. ..." entry counts for
a specialty when its line or the next three lines (stopping at the next "Dr." line) name it.

**Privacy.** Names exist only in memory, to count each doctor once per domain. The outputs keep a
count per row and specialty, the page URL and the capture date. Profile URLs that carry a name are
stored as `/doctor/[name removed]/`. Context read for the hand check had names masked.

| Sample rows (n = 2,000) | Rows | Share |
|---|---:|---:|
| No readable HTML capture | 1,183 | 59% |
| Readable site, but no doctor or department page archived | 324 | 16% |
| Doctor page archived, no named doctor on it | 120 | 6% |
| **Site lists named doctors** | **373** | **18.7%** |
| of which at least one of the five specialties | 142 | 7.1% |
| Orthopaedics / neurosurgery / emergency-trauma | 90 / 54 / 26 | |
| Radiology / nephrology | 48 / 39 | |

**Agreement with the service quotes** (373 rows that list named doctors; quotes are the A or B
quotes from the run above):

| Service | Rows with the specialist | Of those, also a service quote | Rows with a quote | Of those, also the specialist |
|---|---:|---:|---:|---:|
| Dialysis (nephrologist) | 39 | 24 (62%) | 87 | 24 (28%) |
| MRI (radiologist) | 48 | 11 (23%) | 45 | 11 (24%) |
| Trauma care (ortho, neuro or emergency) | 114 | 32 (28%) | 66 | 32 (48%) |

A nephrologist is a fair pointer to dialysis. A radiologist or an orthopaedic surgeon says much less
about MRI or trauma care, because most hospitals have them. The 15 dialysis rows with a
nephrologist and no quote are the most useful leads for a reviewer.

**Hand check.** 45 random (domain, specialty) pairs read once by an AI reviewer with names masked:
37 correct (82%). The misses were menu or form text after a name (3), dental or ENT doctors next to
a department word (3), a blog byline (1) and a founder paragraph (1). Blog-style pages
("best-orthopaedic-hospital-in-...") can also count a doctor once. Counts are a lower bound on
staff lists and say nothing about whether a doctor is resident or visiting.

```sh
python -m research.website_evidence.specialists --rows PRIVATE/sample_rows.json \
  --run PRIVATE/specialists_run.psv --crawl CC-MAIN-2026-39 --out PRIVATE/out
```

### Wider run: hospital-type sites (same crawl, final rules)

After the sample, the counter was run on 4,094 more domains whose VF row name looks like a hospital,
medical college, diagnostic or specialty centre (dental, eye, IVF, skin and AYUSH names were left
out; in the sample those rows held 87% of specialist hits). Rows counted are the 5,508 whose every
domain was read.

| Rows (n = 5,508) | Rows | Share |
|---|---:|---:|
| No readable HTML capture | 3,330 | 60% |
| Readable site, no doctor or department page archived | 684 | 12% |
| Doctor page archived, no named doctor | 355 | 6% |
| **Site lists named doctors** | **1,139** | **21%** |
| of which at least one of the five specialties | 497 | 9.0% |
| Orthopaedics / radiology / nephrology / neurosurgery / emergency-trauma | 329 / 171 / 163 / 161 / 69 | |

Final rules (also re-run on the sample, where 121 rows now list a target specialty, down from 142):
an entry is skipped when it is a dental, ENT, physiotherapy or AYUSH doctor, a menu or form, or a
blog byline; and only the **first** specialty named after the name counts, so a later "Department of
Orthopaedics" heading is not credited to a nephrologist. Sample agreement under these rules:
nephrologist and dialysis quote 65% (20 of 31), radiologist and MRI 25%, trauma specialists and
trauma quote 30%.

Hand check of 50 random pairs from the wider run: 40 correct (80%). Remaining misses: another
specialty in the same entry (neurologist, urologist, gynaecologist, occupational therapist), event
or paragraph text, and filter headings. An earlier check of the second rule set across the wider
run gave 73%, which is why the first-specialty rule was added.

**Nephrologist but no dialysis quote (15 sample rows).** Reading up to ten more archived pages per
site: 1 row gains an own-site dialysis sentence, 3 have weaker wording (patient story, blog,
doctor profile), 4 are chain sites whose dialysis pages belong to another campus or the network,
and 7 have no dialysis wording archived. A nephrologist listing alone is a pointer, not evidence.

## Limits and next steps

- **One crawl only.** Most misses are domains Common Crawl did not visit in that crawl. Adding two
  or three older crawls (for example 2025 and early 2026) should raise capture coverage and also gives
  a second, earlier date for the same claim. That needs one more `cluster.idx` per crawl.
- **Live check not done.** The plan included a small live fetch that respects `robots.txt`. Neither
  the cloud workers nor a browser tab could do it (blocked network, and hospital sites send no CORS
  headers), so every quote here is archive-only.
- **Wayback Machine not used.** It asks for a manual approval per page in the browser used here.
- **Campus attribution.** Chains publish network-wide pages. Records on shared domains are flagged;
  single-row domains can still describe a group (for example an "about us" page listing branches).
- **Reviewer rule.** Nothing here changes a service status. A named reviewer must accept each quote.
