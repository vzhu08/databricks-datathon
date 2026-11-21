"""Public GET only; bounded responses, verified TLS, and source-specific failures."""
import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .common import SourceError, now, require, sha

HOSTS = {"qps.nhsrcindia.org", "nqas.nhsrcindia.org", "nhsrcindia.org"}
QUERY_KEYS = {"field_state1_value", "field_district1_value", "title", "page"}


def public_url(url):
    p = urlsplit(url)
    require(p.scheme == "https" and p.hostname in HOSTS and p.port in (None, 443)
            and not p.username and not p.password and not p.fragment, "unexpected_source_url")
    require(all(k in QUERY_KEYS for k, _ in parse_qsl(p.query, keep_blank_values=True)), "unexpected_query_field")
    return url


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, root, timeout=30, attempts=2, max_bytes=8 * 1024 * 1024, opener=None, sleep=time.sleep):
        require(0 < timeout <= 60 and 1 <= attempts <= 3, "invalid_fetch_limits")
        self.root = Path(root)
        (self.root / "raw").mkdir(parents=True, exist_ok=True)
        self.timeout, self.attempts, self.max_bytes = timeout, attempts, max_bytes
        self.opener = opener or urllib.request.build_opener(Redirect()).open
        self.sleep = sleep
        self.attempt_log = []
        self.first_seen = {}

    def get(self, url):
        public_url(url)
        last_reason = "not_attempted"
        for number in range(1, self.attempts + 1):
            event = {"url": url, "attempt": number, "attempted_at": now()}
            retry = False
            try:
                request = urllib.request.Request(url, headers={
                    "User-Agent": "Datathon-NQAS-Research/1.0 (+https://github.com/vzhu08/databricks-datathon)",
                    "Accept-Encoding": "identity"})
                with self.opener(request, timeout=self.timeout) as response:
                    require(response.status == 200, "unexpected_http_status")
                    public_url(response.geturl())
                    media = response.headers.get("Content-Type", "").split(";")[0].lower()
                    require(media in {"text/html", "application/xhtml+xml"}, "unexpected_content_type")
                    raw = response.read(self.max_bytes + 1)
                    require(0 < len(raw) <= self.max_bytes, "response_size_limit")
                    length = response.headers.get("Content-Length")
                    require(length is None or (length.isdigit() and int(length) == len(raw)), "truncated_response")
                    digest = sha(raw)
                    first = self.first_seen.setdefault(digest, now())
                    artifact = "raw/" + digest + ".html"
                    path = self.root / artifact
                    if path.exists():
                        require(sha(path.read_bytes()) == digest, "existing_artifact_hash_mismatch")
                    else:
                        path.write_bytes(raw)
                    result = {"url": url, "final_url": response.geturl(), "http_status": 200,
                              "sha256": digest, "bytes": len(raw), "artifact": artifact, "retrieved_at": first}
                    event.update(status="ok", sha256=digest)
                    self.attempt_log.append(event)
                    return result
            except urllib.error.HTTPError as error:
                last_reason = "http_" + str(error.code)
                retry = error.code in {408, 429, 500, 502, 503, 504}
                error.close()
            except (urllib.error.URLError, ssl.SSLError, socket.timeout, TimeoutError) as error:
                reason = getattr(error, "reason", error)
                if isinstance(reason, ssl.SSLCertVerificationError):
                    last_reason = "tls_certificate_expired" if "expired" in str(reason).lower() else "tls_certificate_verification_failed"
                else:
                    last_reason, retry = "transport_timeout_or_error", True
            except SourceError as error:
                last_reason = str(error)
            except (http.client.IncompleteRead, ConnectionError):
                last_reason, retry = "truncated_response", True
            event.update(status="failed", reason=last_reason)
            self.attempt_log.append(event)
            if retry and number < self.attempts:
                self.sleep(1)
            else:
                break
        raise SourceError(last_reason)
