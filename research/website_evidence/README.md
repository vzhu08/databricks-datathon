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
