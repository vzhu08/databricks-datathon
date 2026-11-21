"""Bounded public HTTP acquisition; temporary downloads are never accepted data."""
from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import AcquisitionError, public_url, safe_url, utc_now

ALLOWED_TYPES = {
    "html": {"text/html", "application/xhtml+xml"},
    "json": {"application/json", "application/geo+json", "application/octet-stream", "binary/octet-stream", "text/plain"},
    "zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream", "binary/octet-stream"},
}


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, log_path, timeout=30, attempts=3, max_bytes=256 * 1024 * 1024,
                 opener=None, sleep=time.sleep, clock=utc_now):
        if not 0 < timeout <= 120 or not 1 <= attempts <= 5:
            raise ValueError("timeout must be (0,120], attempts must be [1,5]")
        self.log_path = Path(log_path)
        self.timeout, self.attempts, self.max_bytes = timeout, attempts, max_bytes
        self.opener = opener or urllib.request.build_opener(PublicRedirect()).open
        self.sleep, self.clock = sleep, clock

    def log(self, event):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    def download(self, url, destination, kind, source):
        destination = Path(destination)
        public_url(url)
        for attempt in range(1, self.attempts + 1):
            started = time.monotonic()
            event = {"source": source, "url": safe_url(url), "attempt": attempt,
                     "attempted_at": self.clock(), "outcome": "failed"}
            retry = False
            reason = "download_failed"
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "HealthcareEvidenceAcquisition/1.0 (public research)",
                    "Accept-Encoding": "identity",
                })
                with self.opener(req, timeout=self.timeout) as response:
                    event["http_status"] = response.status
                    if response.status != 200:
                        retry = response.status in {408, 429, 500, 502, 503, 504}
                        raise AcquisitionError("http_error")
                    final_url = public_url(response.geturl())
                    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if content_type not in ALLOWED_TYPES[kind]:
                        raise AcquisitionError("unexpected_content_type")
                    total = 0
                    with destination.open("wb") as stream:
                        while True:
                            data = response.read(1024 * 1024)
                            if not data:
                                break
                            total += len(data)
                            if total > self.max_bytes:
                                raise AcquisitionError("download_size_limit")
                            if time.monotonic() - started > self.timeout:
                                retry = True
                                raise AcquisitionError("download_deadline")
                            stream.write(data)
                    expected = response.headers.get("Content-Length")
                    if expected is not None and (not expected.isdigit() or int(expected) != total):
                        retry = True
                        raise AcquisitionError("truncated_download")
                    if not total:
                        raise AcquisitionError("empty_download")
                    with destination.open("rb") as stream:
                        prefix = stream.read(512).lstrip().lower()
                    if kind != "html" and (prefix.startswith(b"<") or b"<html" in prefix):
                        raise AcquisitionError("html_masquerading_as_data")
                    event.update(outcome="downloaded", bytes=total, content_type=content_type,
                                 final_url=safe_url(final_url), retrieved_at=self.clock())
                    self.log(event)
                    return event
            except urllib.error.HTTPError as exc:
                event["http_status"] = exc.code
                reason = "http_error"
                retry = exc.code in {408, 429, 500, 502, 503, 504}
                if exc.fp is not None:
                    exc.close()
            except (TimeoutError, socket.timeout, urllib.error.URLError, http.client.IncompleteRead, ConnectionError):
                reason, retry = "transport_error", True
            except AcquisitionError as exc:
                reason = str(exc)
            finally:
                if event["outcome"] != "downloaded":
                    destination.unlink(missing_ok=True)
            event["reason"] = reason
            self.log(event)
            if retry and attempt < self.attempts:
                self.sleep(min(2 ** (attempt - 1), 8))
            else:
                raise AcquisitionError(reason)
        raise AcquisitionError("retry_exhausted")
