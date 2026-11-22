"""Audit the public BEMMP index; no credentials, hidden APIs or bulk exports."""
import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import html, etree

from .capture import canonical, sha256, write_json

STATES = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
          "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
          "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
          "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
          "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
          "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"]
ALIASES = {"A&N lsland": ["Andaman and Nicobar Islands"],
           "D&N Haveli and Daman & Diu": ["Dadra and Nagar Haveli and Daman and Diu"],
           "Jammu and Kashmir + Ladakh": ["Jammu and Kashmir", "Ladakh"]}


def parse_index(content):
    records = []
    for row in html.fromstring(content).xpath("//table//tr[td]"):
        cells = [" ".join(c.text_content().split()) for c in row.xpath("./td")]
        if len(cells) != 4:
            raise ValueError("unexpected BEMMP index columns")
        state, mode, operator, label = cells
        links = [x.strip() for x in row.xpath(".//a/@href")]
        if len(links) != 1:
            raise ValueError("unexpected BEMMP link count")
        raw = links[0]
        url = raw if urlsplit(raw).scheme in {"http", "https"} else None
        if raw == "mhbemp.in":
            url = "https://" + raw
        scopes = ALIASES.get(state, [state])
        if any(x not in STATES for x in scopes):
            raise ValueError("unrecognised jurisdiction requires review")
        records.append({"index_row": len(records) + 1, "state_printed": state,
                        "jurisdictions": scopes, "mode": mode, "operator_printed": operator,
                        "link_printed": raw, "url": url,
                        "url_note": "HTTPS assumed for scheme-less publisher link" if raw == "mhbemp.in" else None,
                        "access_route": "https://nhsrcindia.org/contact-us",
                        "division_route": "https://www.nhsrcindia.org/hc-technology",
                        "bulk_permission": "not_established", "export_attempted": False})
    return records


def inspect_landing(record, root):
    if not record["url"]:
        return {**record, "access_status": "no_dashboard_link_in_index", "next_owner": "Vincent/NHSRC access qualification"}
    key = hashlib.sha256(record["url"].encode()).hexdigest()
    dest = root / f"{key}.html"
    url = urldefrag(record["url"])[0]
    done = subprocess.run(["curl", "-sS", "-L", "--max-redirs", "5", "--connect-timeout", "10", "--max-time", "30",
                           "--max-filesize", "2097152", "--proto", "=http,https", "--proto-redir", "=http,https",
                           "-o", str(dest), "-w", "%{http_code}\n%{url_effective}\n%{content_type}", url],
                          capture_output=True, text=True, timeout=40)
    lines = done.stdout.splitlines()
    result = {**record, "retrieved_at": datetime.now(timezone.utc).isoformat(),
              "curl_exit": done.returncode, "http_status": lines[0] if lines else None,
              "effective_url": lines[1] if len(lines) > 1 else None,
              "error": done.stderr.strip() or None, "access_status": "landing_only_no_bulk_authorization",
              "next_owner": "Vincent/NHSRC or named state operator access qualification"}
    if dest.exists():
        result.update(sha256=sha256(dest), bytes=dest.stat().st_size, path=f"dashboard-landings/{dest.name}")
        try:
            doc = html.fromstring(dest.read_bytes())
            result["title"] = " ".join(doc.xpath("string(//title)").split())
            result["has_password_input"] = bool(doc.xpath('//input[translate(@type,"PASSWORD","password")="password"]'))
            result["visible_terms_or_export_links"] = [{"text": " ".join(a.text_content().split()), "url": urljoin(result["effective_url"], a.get("href"))}
                for a in doc.xpath('//a[@href]') if re.search(r"copyright|terms|privacy|export|download|\.xlsx?|\.csv", a.text_content() + " " + a.get("href"), re.I)]
        except (ValueError, etree.ParserError):
            result["content_note"] = "not parseable HTML"
    if done.returncode or result["http_status"] != "200":
        result["access_status"] = "request_failed_or_non_200"
    if "jk.bmmp.in" in url:
        result["manual"] = {"url": "https://jk.bmmp.in/help_jk.pdf", "page": 2,
                             "finding": "Viewing is public; Excel/service-report download requires credentials on request."}
    return result


def run(root):
    root = Path(root)
    records = parse_index((root / "index/dashboards.html").read_bytes())
    dest = root / "dashboard-landings"
    dest.mkdir(exist_ok=True)
    results = []
    def inspect(record):
        try:
            return inspect_landing(record, dest)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {**record, "access_status": "request_failed", "error": str(exc)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(inspect, records):
            results.append(result)
            write_json(root / "dashboard-register.json", results)
    catalogue = json.loads((root / "catalogue.json").read_text())
    coverage = [{"jurisdiction": state, "dashboard_index_rows": [x["index_row"] for x in records if state in x["jurisdictions"]],
                 "catalogue_entries": [x["entry"] for x in catalogue if x["state_printed"] == state],
                 "facility_inventory_completeness": None, "matched_VF_occurrences": None,
                 "bulk_dashboard_reuse": "not_established"} for state in STATES]
    write_json(root / "jurisdiction-coverage.json", coverage)
    return {"index_rows": len(results), "jurisdictions": len(coverage),
            "linked_rows": sum(bool(x["url"]) for x in records),
            "download_authorizations_established": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(run(args.root)))


if __name__ == "__main__":
    main()
