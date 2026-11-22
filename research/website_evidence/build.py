"""Turn one archive run into row-level dated website evidence and a coverage report.

Inputs (all kept outside Git, because they are derived from Marketplace rows):
  --rows      JSON list of {facility_id, name, state, domains} (domains.first_party output)
  --domains   whitespace-separated domain list, in the order the run used
  --status    one character per domain: 0 not read (index request failed or rate-limited),
              1 no capture in the crawl, 2 captures but no readable HTML page, 3 at least one readable page
  --hits      pipe-separated lines: domain|service|strength|timestamp|url|quote|pages_with_mention[|review]
              (review is an optional hand label: A direct onsite claim, B list-level mention, C not usable)
  --crawl     Common Crawl crawl id, recorded on every evidence record

Outputs: evidence.jsonl (one record per row x service with a quote) and report.json.
Every record says "dated_website_mention", never "yes": SERVICE_STATUS.md still needs a
named reviewer and campus attribution before a mention can become a confirmed service.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
from pathlib import Path

from research.website_evidence.extract import QUALIFIERS, strength

SERVICES = ("dialysis", "mri", "trauma_care")
RANK = {"direct": 0, "listed": 1, "weak": 2}


def iso(ts: str) -> str:
    return dt.datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load_hits(path: Path) -> dict:
    hits = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        domain, service, _, ts, url, quote, pages = parts[:7]
        review = parts[7] if len(parts) > 7 else None
        qualified = bool(QUALIFIERS.search(quote))
        hits[(domain, service)] = {
            "timestamp": ts, "url": url, "quote": quote, "pages_with_mention": int(pages),
            "strength": strength(quote, url, qualified), "qualified": qualified, "review": review,
        }
    return hits


def build(rows, domains, status, hits, crawl):
    state = dict(zip(domains, status))
    use = collections.Counter(d for r in rows for d in r["domains"])
    evidence, row_state = [], collections.Counter()
    gained = {s: collections.Counter() for s in SERVICES}
    reviewed = {s: collections.Counter() for s in SERVICES}
    any_gain = collections.Counter()
    for r in rows:
        codes = [state.get(d, "0") for d in r["domains"]]
        if "0" in codes:
            row_state["not_read"] += 1
            continue
        best = max(codes)
        row_state[{"1": "no_capture", "2": "capture_unreadable", "3": "readable"}[best]] += 1
        tiers = set()
        for service in SERVICES:
            found = [(d, hits[(d, service)]) for d in r["domains"] if (d, service) in hits]
            if not found:
                continue
            domain, h = min(found, key=lambda x: (RANK[x[1]["strength"]], -len(x[1]["quote"])))
            if h["strength"] == "weak":
                continue
            shared = use[domain] > 1
            evidence.append({
                "facility_id": r["facility_id"], "service": service,
                "kind": "dated_website_mention", "status_effect": "none_until_reviewed",
                "strength": h["strength"], "qualified": h["qualified"],
                "domain": domain, "domain_shared_by_rows": use[domain],
                "campus_attribution": "needs_review" if shared else "single_row_domain",
                "source": {"publisher": "first-party website", "archive": "Common Crawl", "crawl": crawl,
                           "url": h["url"], "captured_at": iso(h["timestamp"]),
                           "locator": f"https://data.commoncrawl.org/ (index {crawl}, url {h['url']}, timestamp {h['timestamp']})"},
                "quote": h["quote"], "pages_with_mention": h["pages_with_mention"],
                "review": h["review"],
            })
            gained[service][h["strength"]] += 1
            if h["review"]:
                reviewed[service][(h["strength"], h["review"])] += 1
            tiers.add(h["strength"])
        if tiers:
            any_gain["direct" if "direct" in tiers else "listed"] += 1
    read = sum(v for k, v in row_state.items() if k != "not_read")
    report = {
        "crawl": crawl,
        "rows_in_sample": len(rows),
        "rows_read": read,
        "rows_by_archive_state": dict(row_state),
        "rows_with_dated_mention": {
            "any_service": dict(any_gain),
            **{s: dict(gained[s]) for s in SERVICES},
        },
        "share_of_read_rows": {
            "any_service": round(sum(any_gain.values()) / read, 4) if read else None,
            "any_service_direct": round(any_gain["direct"] / read, 4) if read else None,
            **{s: round(sum(gained[s].values()) / read, 4) if read else None for s in SERVICES},
        },
        "hand_review": {s: {f"{k[0]}:{k[1]}": v for k, v in sorted(reviewed[s].items())} for s in SERVICES},
        "records_on_shared_domains": sum(e["campus_attribution"] == "needs_review" for e in evidence),
    }
    return evidence, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for name in ("rows", "domains", "status", "hits", "out"):
        p.add_argument(f"--{name}", required=True, type=Path)
    p.add_argument("--crawl", required=True)
    a = p.parse_args(argv)
    rows = json.loads(a.rows.read_text())
    evidence, report = build(rows, a.domains.read_text().split(), a.status.read_text().strip(),
                             load_hits(a.hits), a.crawl)
    a.out.mkdir(parents=True, exist_ok=True)
    with (a.out / "evidence.jsonl").open("w") as f:
        for e in evidence:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    (a.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
