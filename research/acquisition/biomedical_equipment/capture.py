"""Bounded public-download capture and an offline, occurrence-preserving index.

Only catalogue download links are followed. No dashboard APIs or logins.
Captured bytes are working copies; review file rights before team transfer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import html

BASE = "https://nhsrcindia.org"
INDEX_URLS = {"catalogue-0": BASE + "/HCT-DME", **{
    f"catalogue-{i}": BASE + f"/HCT-DME?page=%2C{i}" for i in range(1, 5)},
    "copyright": BASE + "/copyright-policy",
    "dashboards": BASE + "/bemmp-map-table",
    "programme": BASE + "/biomedical-equipment-management-and-maintenance-program-bemmp"}
MAX_BYTES = 64 * 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value) + "\n", encoding="utf-8")


def parse_catalogue(pages):
    """Keep numbered catalogue occurrences, including repeated URLs."""
    entries = []
    for page, content in sorted(pages.items()):
        doc = html.fromstring(content)
        for table in doc.xpath('//table[contains(@class,"views-table")]'):
            state = " ".join(table.xpath("string(caption)").split())
            for row in table.xpath(".//tr[td]"):
                cells = row.xpath("./td")
                if len(cells) != 3:
                    raise ValueError("unexpected catalogue column count")
                number = int(cells[0].text_content().strip())
                title = " ".join(cells[1].text_content().split())
                links = cells[2].xpath(".//a/@href")
                if not state or len(links) != 1:
                    raise ValueError("catalogue state or link missing/ambiguous")
                url = urljoin(BASE, links[0])
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname not in {"nhsrcindia.org", "www.nhsrcindia.org"}:
                    raise ValueError("catalogue file needs separate publisher review")
                entries.append({"entry": number, "page": page, "state_printed": state,
                                "title": title, "url": url,
                                "publication_date": None, "observation_period": None,
                                "date_note": "Neither upload path nor filename is an observation date."})
    numbers = [x["entry"] for x in entries]
    if len(numbers) != len(set(numbers)):
        raise ValueError("duplicate catalogue entry number")
    return sorted(entries, key=lambda x: x["entry"])


def fetch(url, root, key, max_bytes=MAX_BYTES):
    """Capture a receipt even for timeout, HTTP failure, or unexpected content."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"nhsrcindia.org", "www.nhsrcindia.org"}:
        raise ValueError("capture accepts only NHSRC HTTPS URLs")
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        target = Path(tmp) / "download"
        response = subprocess.run([
            "curl", "--silent", "--show-error", "--location", "--max-redirs", "5",
            "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "15",
            "--max-time", "90", "--max-filesize", str(max_bytes), "--output", str(target),
            "--write-out", "%{http_code}\n%{url_effective}\n%{content_type}", url],
            capture_output=True, text=True, timeout=100)
        lines = response.stdout.splitlines()
        receipt = {"key": key, "url": url,
                   "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "curl_exit": response.returncode, "http_status": lines[0] if lines else None,
                   "effective_url": lines[1] if len(lines) > 1 else None,
                   "content_type": lines[2] if len(lines) > 2 else None,
                   "error": response.stderr.strip() or None}
        accepted = (response.returncode == 0 and receipt["http_status"] == "200" and
                    urlsplit(receipt["effective_url"]).hostname in {"nhsrcindia.org", "www.nhsrcindia.org"})
        receipt["download_ok"] = accepted
        if target.is_file():
            digest = sha256(target)
            dest = root / "blobs" / digest
            dest.parent.mkdir(exist_ok=True)
            if not dest.exists():
                target.replace(dest)
            receipt.update(sha256=digest, bytes=dest.stat().st_size, path=f"blobs/{digest}")
        return receipt


def collect(root, workers=3):
    root = Path(root)
    pages = {i: (root / "index" / f"catalogue-{i}.html").read_bytes() for i in range(5)}
    entries = parse_catalogue(pages)
    if [e["entry"] for e in entries] != list(range(1, 95)):
        raise ValueError("catalogue changed: review pagination before download")
    write_json(root / "catalogue.json", entries)
    urls = sorted({e["url"] for e in entries})
    old_path = root / "downloads.json"
    previous = json.loads(old_path.read_text()) if old_path.exists() else []
    usable = {x["url"]: x for x in previous if x.get("download_ok") and
              (root / x["path"]).is_file() and sha256(root / x["path"]) == x["sha256"]}
    def download(url):
        if url in usable:
            return usable[url]
        try:
            return fetch(url, root, hashlib.sha256(url.encode()).hexdigest())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"url": url, "download_ok": False, "error": str(exc),
                    "retrieved_at": datetime.now(timezone.utc).isoformat()}
    receipts = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for receipt in pool.map(download, urls):
            receipts.append(receipt)
            write_json(old_path, sorted(receipts, key=lambda x: x["url"]))
    by_digest = defaultdict(list)
    for receipt in receipts:
        if receipt.get("download_ok"):
            by_digest[receipt["sha256"]].append(receipt["url"])
    summary = {"catalogue_entries": len(entries), "unique_urls": len(urls),
               "state_headings": sorted({x["state_printed"] for x in entries}),
               "unique_downloaded_editions": len(by_digest),
               "successful_urls": sum(x.get("download_ok", False) for x in receipts),
               "failed_urls": [x["url"] for x in receipts if not x.get("download_ok")],
               "byte_identical_url_groups": [v for v in by_digest.values() if len(v) > 1],
               "by_suffix": dict(Counter(Path(urlsplit(u).path).suffix.lower() for u in urls))}
    write_json(root / "capture-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["index", "collect"])
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "index":
        receipts = []
        for key, url in INDEX_URLS.items():
            receipt = fetch(url, args.root, key)
            receipts.append(receipt)
            if not receipt["download_ok"]:
                write_json(args.root / "index" / "receipts.json", receipts)
                raise RuntimeError(f"index failed: {key}")
            dest = args.root / "index" / f"{key}.html"
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes((args.root / receipt["path"]).read_bytes())
        write_json(args.root / "index" / "receipts.json", receipts)
    else:
        print(canonical(collect(args.root)))


if __name__ == "__main__":
    main()
