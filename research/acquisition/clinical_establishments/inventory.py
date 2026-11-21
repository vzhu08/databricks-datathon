"""Inventory printed jurisdictions and substantive links, without inferring coverage."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from research.acquisition.common import canonical, digest, read_json, write_json

INDEX_URL = "https://clinicalestablishments.mohfw.gov.in/en/node/1390"
COPYRIGHT_URL = "https://clinicalestablishments.mohfw.gov.in/en/copyright-policy"


def text(node):
    return " ".join(node.get_text(" ", strip=True).split())


def inventory(raw: bytes, url: str = INDEX_URL):
    soup = BeautifulSoup(raw, "html.parser")
    jurisdictions, links, empty_links = [], [], []
    sections = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [text(c).casefold() for c in rows[0].find_all(["td", "th"])]
        if "state" not in header or not any("data" in c for c in header):
            continue
        heading = table.find_previous(["h2", "h3"])
        section = text(heading) if heading else f"section {len(sections) + 1}"
        section_no = len(sections) + 1
        sections.append(section)
        for physical_row, tr in enumerate(rows[1:], 2):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) != 3:
                raise ValueError(f"Unexpected index row shape at section {section_no}, row {physical_row}")
            serial, state = text(cells[0]), text(cells[1])
            if not serial.isdigit() or not state:
                raise ValueError("Missing printed jurisdiction or serial")
            key = f"section-{section_no}:row-{serial}"
            substantive = []
            for anchor_no, a in enumerate(cells[2].find_all("a", href=True), 1):
                label = text(a)
                target = urljoin(url, a["href"].strip())
                parsed = urlsplit(target)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("Index contains an unsafe destination")
                item = dict(jurisdiction_key=key, jurisdiction_printed=state,
                            section=section, section_no=section_no, printed_serial=serial,
                            physical_row=physical_row, anchor_no=anchor_no, label=label, url=target)
                item["link_id"] = "ce-link:" + digest(canonical([key, anchor_no, target]))
                # Decorative PDF icons and whitespace-only leftovers repeat links
                # to unrelated states. Preserve them for audit, never infer scope.
                if label:
                    item["kind"] = "file" if parsed.path.lower().endswith((".pdf", ".xlsx", ".xls", ".csv")) else "portal"
                    links.append(item)
                    substantive.append(item["link_id"])
                else:
                    item["reason"] = "empty_or_icon_only_anchor_not_jurisdiction_coverage"
                    empty_links.append(item)
            jurisdictions.append(dict(jurisdiction_key=key, section=section,
                                      section_no=section_no, printed_serial=serial,
                                      jurisdiction_printed=state, link_ids=substantive,
                                      notice=text(cells[2]) if not substantive else None))
    if not sections:
        raise ValueError("No jurisdiction index tables found")
    by_section = []
    for i, section in enumerate(sections, 1):
        js = [j for j in jurisdictions if j["section_no"] == i]
        by_section.append(dict(section=section, printed_entries=len(js),
                               linked_entries=sum(bool(j["link_ids"]) for j in js),
                               notice_only_entries=sum(not j["link_ids"] for j in js)))
    return dict(index_url=url, index_sha256=digest(raw), jurisdictions=jurisdictions,
                links=links, empty_anchors=empty_links,
                summary=dict(sections=by_section, printed_entries=len(jurisdictions),
                             linked_jurisdictions=sum(bool(j["link_ids"]) for j in jurisdictions),
                             substantive_links=len(links), unique_urls=len({l["url"] for l in links}),
                             link_kinds=dict(Counter(l["kind"] for l in links)),
                             empty_anchors=len(empty_links)))


def portal_inventory(acquisition, root):
    """One-hop document discovery; keep repeated and empty links in the audit."""
    output = []
    for link in acquisition["links"]:
        if link["kind"] != "portal":
            continue
        entry = {k: link[k] for k in ("jurisdiction_printed", "url", "status", "http_status", "sha256")}
        entry["children"] = []
        if link["status"] == "fetched":
            raw = (root / link["raw_path"]).read_bytes()
            if digest(raw) != link["sha256"]:
                raise ValueError("Portal capture hash changed")
            soup = BeautifulSoup(raw, "html.parser")
            for a in soup.select("a[href]"):
                target = urljoin(link["url"], a["href"])
                if urlsplit(target).path.lower().endswith((".pdf", ".xls", ".xlsx", ".csv", ".zip")):
                    entry["children"].append(dict(url=target, label=text(a), substantive=bool(text(a)),
                        reuse_status="unassessed", access_status="not_fetched_pending_reuse_review"))
            entry["unique_child_urls"] = len({c["url"] for c in entry["children"]})
            entry["substantive_unique_child_urls"] = len({c["url"] for c in entry["children"] if c["substantive"]})
            entry["form_count"] = len(soup.select("form"))
            entry["policy_links"] = [dict(label=text(a), url=urljoin(link["url"], a["href"]))
                for a in soup.select("a[href]") if any(w in text(a).casefold() for w in ("policy", "copyright", "terms"))]
        output.append(entry)
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", type=Path)
    p.add_argument("--acquisition", type=Path, help="Instead inventory child documents of captured portals")
    p.add_argument("--root", type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    if args.index and not args.acquisition:
        result = inventory(args.index.read_bytes())
    elif args.acquisition and args.root and not args.index:
        result = portal_inventory(read_json(args.acquisition), args.root)
    else:
        p.error("Use --index, or --acquisition with --root")
    write_json(args.out, result)
    print(canonical(result["summary"] if isinstance(result, dict) else {"portals": len(result)}).decode())


if __name__ == "__main__":
    main()
