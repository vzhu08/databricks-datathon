"""Look up a domain's captures in one Common Crawl crawl and read archived pages.

This reads Common Crawl's public ZipNum index straight from data.commoncrawl.org
instead of the CDX server at index.commoncrawl.org, which times out (HTTP 504)
under load. Three kinds of HTTP range requests are used:

1. cluster.idx (about 100 MB, read once per crawl): the first SURT key of each
   compressed index block, with its cdx-NNNNN.gz file, offset and length.
2. One index block (about 270 KB gzip) per domain: every capture line for keys
   that start with the domain's SURT.
3. One WARC record per selected page (a few KB to a few hundred KB gzip).

Every capture line carries a 14-digit timestamp, which is the date evidence.
"""
from __future__ import annotations

import bisect
import gzip
import json
import re
import urllib.request
from urllib.parse import urlsplit

DATA = "https://data.commoncrawl.org/"
USER_AGENT = "datathon-website-evidence/0.1 (research prototype)"

# Paths worth reading on a hospital site, besides the home page.
SERVICE_PATH = re.compile(
    r"(dialysis|kidney|nephro|mri|radiology|imaging|scan|trauma|emergency|casualty|accident|service"
    r"|facilit|department|speciali|about|infrastructure|our-|treatment)",
    re.I,
)
HOME_PATHS = {"/", "/index.html", "/index.php", "/index.htm", "/home"}


def _get(url: str, start: int | None = None, length: int | None = None, timeout: int = 60) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if start is not None:
        headers["Range"] = f"bytes={start}-{start + length - 1}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def surt_host(domain: str) -> str:
    """example.co.in -> in,co,example (Common Crawl drops a leading www)."""
    parts = domain.lower().strip(".").split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]
    return ",".join(reversed(parts))


class Crawl:
    def __init__(self, crawl_id: str, fetch=_get):
        self.crawl_id = crawl_id
        self.base = f"{DATA}cc-index/collections/{crawl_id}/indexes/"
        self.fetch = fetch
        self.keys: list[str] = []
        self.blocks: list[tuple[str, int, int]] = []
        self._cache: dict[int, list[str]] = {}

    def load_cluster(self, text: str | None = None) -> None:
        text = text if text is not None else self.fetch(self.base + "cluster.idx").decode()
        for line in text.splitlines():
            if not line:
                continue
            key, name, offset, length = line.split("\t")[:4]
            self.keys.append(key.split(" ")[0])
            self.blocks.append((name, int(offset), int(length)))

    def _block(self, i: int) -> list[str]:
        if i not in self._cache:
            name, offset, length = self.blocks[i]
            self._cache[i] = gzip.decompress(self.fetch(self.base + name, offset, length)).decode().splitlines()
        return self._cache[i]

    def captures(self, domain: str, max_blocks: int = 6) -> list[dict]:
        """All capture lines whose SURT key is the domain or one of its subdomains."""
        host = surt_host(domain)
        low, high = host + ")", host + "-"  # ')' and ',' (subdomains) both sort below '-'
        i = max(bisect.bisect_right(self.keys, low) - 1, 0)
        rows = []
        for n in range(max_blocks):
            if i >= len(self.keys) or (n and self.keys[i] > high):
                break
            for line in self._block(i):
                key, _, rest = line.partition(" ")
                if not (key.startswith(host + ")") or key.startswith(host + ",")):
                    continue
                timestamp, _, payload = rest.partition(" ")
                try:
                    j = json.loads(payload)
                except ValueError:
                    continue
                rows.append({
                    "url": j.get("url"), "timestamp": timestamp, "status": j.get("status"),
                    "mime": j.get("mime") or j.get("mime-detected"), "filename": j.get("filename"),
                    "offset": int(j.get("offset", 0)), "length": int(j.get("length", 0)),
                })
            if i + 1 < len(self.keys) and self.keys[i + 1] > high:
                break
            i += 1
        return rows

    def page(self, capture: dict) -> str:
        """The HTML body of one capture's WARC response record."""
        raw = gzip.decompress(self.fetch(DATA + capture["filename"], capture["offset"], capture["length"]))
        _, _, http = raw.partition(b"\r\n\r\n")  # WARC headers
        _, _, body = http.partition(b"\r\n\r\n")  # HTTP headers
        return body.decode("utf-8", "replace")


def _path(url: str) -> str:
    try:
        return urlsplit(url).path.rstrip("/") or "/"
    except ValueError:
        return url


def pick_pages(captures: list[dict], limit: int = 8) -> list[dict]:
    """Home page first, then distinct service-looking paths, shortest first."""
    html = [c for c in captures if c["status"] == "200" and "html" in (c["mime"] or "")]
    html.sort(key=lambda c: len(_path(c["url"])))
    seen, home, rest = set(), [], []
    for c in html:
        p = _path(c["url"])
        if p in seen:
            continue
        if p in HOME_PATHS:
            seen.add(p)
            home.append(c)
        elif SERVICE_PATH.search(p) and len(rest) < limit:
            seen.add(p)
            rest.append(c)
    return (home[:1] + rest)[:limit]
