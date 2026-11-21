"""Capture public index destinations with bounded downloads and immutable receipts.

Fetching for private source inspection does not grant reuse permission. Build/release
requires a separate reviewed rights decision. No login, CAPTCHA or access bypass.
"""
from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests

from research.acquisition.common import atomic_bytes, canonical, digest, read_json, utc_now, write_json

MAX_BYTES = 150 * 1024 * 1024


def fetch_one(url, root, timeout=40, retry_failed=False):
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) destinations are allowed")
    key = digest(url.encode())
    receipt_path = root / "receipts" / f"{key}.json"
    if receipt_path.exists():
        result = read_json(receipt_path)
        if result.get("raw_path") and digest((root / result["raw_path"]).read_bytes()) != result["sha256"]:
            raise ValueError("Persisted raw artifact hash changed")
        if result["status"] in {"fetched", "restricted"} or not retry_failed:
            return result
        # Preserve each failed attempt; never replace the first successful capture.
        write_json(root / "attempts" / f"{key}-{digest(canonical(result))}.json", result)
    result = dict(url=url, retrieved_at=utc_now(), status="unavailable", http_status=None,
                  final_url=None, content_type=None, byte_count=0, sha256=None, raw_path=None)
    try:
        started = time.monotonic()
        with requests.get(url, stream=True, timeout=(12, timeout),
                          headers={"User-Agent": "Datathon-source-inspection/1.0"}) as response:
            result.update(http_status=response.status_code, final_url=response.url,
                          content_type=response.headers.get("Content-Type"))
            if response.status_code != 200:
                result["status"] = "restricted" if response.status_code in {401, 403, 429} else "http_error"
            else:
                parts, size = [], 0
                for part in response.iter_content(1024 * 128):
                    if time.monotonic() - started > 120:
                        raise requests.exceptions.Timeout()
                    size += len(part)
                    if size > MAX_BYTES:
                        raise ValueError("download_size_limit")
                    parts.append(part)
                raw = b"".join(parts)
                sha = digest(raw)
                ext = ".pdf" if raw.startswith(b"%PDF-") else ".html" if b"<html" in raw[:4096].lower() or b"<!doctype" in raw[:4096].lower() else ".bin"
                rel = f"raw/{sha}{ext}"
                atomic_bytes(root / rel, raw)
                result.update(status="fetched", byte_count=len(raw), sha256=sha, raw_path=rel)
    except requests.exceptions.SSLError:
        result["status"] = "tls_error"
    except requests.exceptions.Timeout:
        result["status"] = "timeout"
    except requests.exceptions.RequestException:
        result["status"] = "network_error"
    except ValueError as exc:
        if str(exc) != "download_size_limit":
            raise
        result["status"] = "size_limit"
    write_json(receipt_path, result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument("--retry-failed", action="store_true")
    args = p.parse_args()
    inv = read_json(args.inventory)
    urls = sorted({link["url"] for link in inv["links"]})
    # Two workers bound load on the single Ministry host.
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda u: fetch_one(u, args.root, args.timeout, args.retry_failed), urls))
    by_url = {r["url"]: r for r in receipts}
    groups = defaultdict(list)
    for item in receipts:
        if item["sha256"]:
            groups[item["sha256"]].append(item["url"])
    result = dict(index_sha256=inv["index_sha256"], receipts=receipts,
                  links=[{**link, **by_url[link["url"]]} for link in inv["links"]],
                  duplicate_byte_groups=[dict(sha256=k, urls=v) for k, v in groups.items() if len(v) > 1],
                  summary=dict(urls=len(urls), outcomes=dict(Counter(r["status"] for r in receipts)),
                               unique_raw_hashes=len(groups), total_download_bytes=sum(r["byte_count"] for r in receipts)))
    write_json(args.root / "acquisition.json", result)
    print(canonical(result["summary"]).decode())


if __name__ == "__main__":
    main()
