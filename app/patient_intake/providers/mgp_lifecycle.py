"""Server-only MGP development candidate. All exchanges must be explicitly injected."""

from base64 import b64encode
import re
from threading import Lock
from time import monotonic

from .mgp import _identifier, _UUID
from .transport import Reply, Transport

_ROOT = "/api/mgp/v1/"
_SCOPES = "user:write patient:write survey:read survey:write question:read question:write"
_TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]{1,8192}")
_NO_CREATE = {"access_denied", "rate_limited", "budget_exhausted", "invalid_request", "busy"}


class SandboxSession:
    """Share this instance across encounters so auth and API calls share a quota."""

    def __init__(self, *, exchange, attempts=0, enabled=False, clock=monotonic):
        self._transport = Transport(host="api.dev.infermedica.com", headers={}, attempts=attempts,
                                    exchange=exchange, clock=clock)
        self._enabled = enabled is True
        self._clock = clock
        self._token = None
        self._expires_at = 0
        self._lock = Lock()

    def authenticate(self, instance, app_id, app_key, *, encounter):
        with self._lock:
            self._token = None
            if not self._enabled:
                return Reply("unavailable")
            if (not _identifier(instance, re.compile(r"[A-Za-z0-9._-]{1,128}"))
                    or any(type(v) is not str or not 1 <= len(v) <= 1024 or not v.isascii()
                           or not v.isprintable() for v in (app_id, app_key)) or ":" in app_id):
                return Reply("invalid_request")
            basic = b64encode(f"{app_id}:{app_key}".encode()).decode()
            start = self._clock()
            result = self._transport.request(
                "POST", "/api/auth/token", encounter=encounter,
                headers={"Instance-Id": instance, "Authorization": "Basic " + basic},
                payload={"grant_type": "client_credentials", "scope": _SCOPES},
            )
            if result.status != "received":
                return Reply(result.status, rate=result.rate)
            data = result.data
            ttl = data.get("expires_in")
            if (data.get("token_type") != "Bearer" or not _identifier(data.get("access_token"), _TOKEN)
                    or type(ttl) is not int or ttl <= 0):
                return Reply("invalid_response")
            self._expires_at = start + min(ttl, 3600)
            self._token = data["access_token"]
            return Reply("authenticated")

    def request(self, method, path, *, payload=None, encounter):
        with self._lock:
            if not self._enabled or self._token is None or self._clock() >= self._expires_at:
                self._token = None
                return Reply("access_denied")
            token = self._token
        if not path.startswith(_ROOT):
            return Reply("invalid_request")
        return self._transport.request(method, path, encounter=encounter, payload=payload,
                                       headers={"Authorization": "Bearer " + token})


class AnonymousSurvey:
    """Own exactly one create chain. Retain verified IDs until disposal succeeds."""

    def __init__(self, session, *, budget):
        self._session = session
        self._budget = budget
        self._owned = {}
        self._started = False
        self._ready = False
        self._unknown_create = False
        self._lock = Lock()

    @property
    def survey_id(self):
        with self._lock:
            return self._owned.get("surveys") if self._ready else None

    def create(self, *, confirmed_initial=(), prefill_enabled=False, demographics=None):
        """Only accept current patient-confirmed concepts from this MGP edition's Q reviews."""
        if type(confirmed_initial) not in (list, tuple) or len(confirmed_initial) > 32:
            return "unsupported_correction"
        if confirmed_initial:
            if (type(demographics) is not dict or set(demographics) != {"age_years", "sex"}
                    or demographics["sex"] not in ("female", "male")
                    or type(demographics["age_years"]) is not int or not 0 <= demographics["age_years"] <= 130):
                return "unsupported_correction"
            patient_fields = dict(sex=demographics["sex"], age=dict(unit="year", value=demographics["age_years"]))
        elif demographics is None:
            patient_fields = {}
        else:
            return "invalid_request"
        evidence = []
        seen = set()
        for review in confirmed_initial:
            candidate = review.get("candidate") if type(review) is dict else None
            if (prefill_enabled is not True or type(candidate) is not dict
                    or review.get("origin") != "patient_review" or review.get("decision") != "confirm"
                    or review.get("patient_presence") != "present" or candidate.get("presence") != "present"
                    or candidate.get("temporality") != "current"
                    or not _identifier(candidate.get("concept_id"), re.compile(r"[sp]_[0-9]{1,10}"))
                    or candidate["concept_id"] in seen):
                return "unsupported_correction"
            seen.add(candidate["concept_id"])
            evidence.append(dict(id=candidate["concept_id"], choice_id="present", source="initial"))
        with self._lock:
            if self._started:
                return "already_started"
            self._started = True
            for resource in ("users", "patients", "surveys"):
                body = {}
                if resource == "patients":
                    body.update(user_id=self._owned["users"], **patient_fields)
                elif resource == "surveys":
                    body.update(type="triage", patient_id=self._owned["patients"])
                expected_binding = body.copy()
                if resource == "surveys" and evidence:
                    body["evidence"] = evidence
                reply = self._session.request("POST", _ROOT + resource, payload=body, encounter=self._budget)
                if reply.status != "received":
                    self._unknown_create = reply.status not in _NO_CREATE
                    return reply.status if reply.status != "empty" else "invalid_response"
                data = reply.data
                if (reply.http_status != 201 or not _identifier(data.get("id"), _UUID)
                        or any(data.get(k) != v for k, v in expected_binding.items())
                        or (resource == "users" and any(data.get(k) for k in ("email", "phone")))):
                    self._unknown_create = True
                    return "invalid_response"
                self._owned[resource] = data["id"]
            self._ready = True
            return "created"

    def dispose(self):
        with self._lock:
            self._started = True
            self._ready = False
            for resource in reversed(tuple(self._owned)):
                path = _ROOT + resource + "/" + self._owned[resource]
                reply = self._session.request("DELETE", path, encounter=self._budget)
                if reply.status not in ("empty", "not_found"):
                    return "disposal_pending"
                del self._owned[resource]
            return "creation_unresolved" if self._unknown_create else "disposed"
