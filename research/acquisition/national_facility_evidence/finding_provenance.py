"""Project claim-level provenance without changing search or service decisions.

The Find care adapter accepts the existing raw demonstration response or its
already-withheld warehouse counterpart. The claim summarizer accepts only
observations whose displayed facts and citations have already been cleared.
This module uses the standard library and can be loaded as a standalone file.
"""

from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
import re
from urllib.parse import urlsplit


SERVICES = ("dialysis", "mri", "trauma_care")
PRECISIONS = ("reported_position", "postal_area", "city", "locality", "district", "written_address",
              "identified_campus", "verified_entrance", "unknown")
SYNTHETIC = "Synthetic demo record"
WAREHOUSE_STATUSES = {"withheld", "no_match", "invalid_input", "unresolved_location", "ambiguous_location", "unavailable"}


@dataclass(frozen=True)
class Observation:
    publisher: str
    fact: str
    scope: str
    role: str = "context"  # support, conflict or context relative to the displayed claim
    match: str = "reported"  # exact fact and scope, reported only, or different/inapplicable scope
    origin: str | None = None
    independent: bool = False  # claim-specific, documented independence for this origin
    field: str | None = None
    observed_on: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    archive_captured_at: str | None = None
    citation: str | None = None
    citation_scope: str | None = None  # claim locator or record-level pointer
    assertion: str | None = None  # onsite_delivery, explicit_absence or all_cases_referral


@dataclass(frozen=True)
class Review:
    scope: str
    as_of: str
    decision: str | None = None  # existing reviewed decision, when there is one


def _date(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return None


def _covers(observation, target):
    if target is None:
        return False
    start, end = _date(observation.effective_from), _date(observation.effective_to)
    if observation.effective_from is not None or observation.effective_to is not None:
        return start is not None and end is not None and start <= target <= end
    return _date(observation.observed_on) == target


def summarize_claim(kind, scope, observations=(), *, service=None, precision=None, as_of=None,
                    review=None, missing_check=None):
    """Describe evidence at the caller's permitted fact, branch and time grain.

    ``match="exact"`` requires documented same-fact scope. An exact service
    observation also needs an observation date or effective interval covering
    ``as_of``. ``reported`` retains relevant direct wording at its stated scope.
    A review with an applicable exact supporting statement can carry an
    existing decision. Inputs with unknown lineage stay visible.
    """
    if kind == "service" and (service not in SERVICES or precision is not None):
        raise ValueError("Service claims require one target service and no location precision")
    if kind == "location" and (precision not in PRECISIONS or service is not None):
        raise ValueError("Location claims require one location precision and no service")
    if kind not in {"location", "service"}:
        raise ValueError("Unknown claim kind")

    sources, supports, exact, conflicts = [], [], [], []
    target = _date(as_of)
    for obs in observations or ():
        if obs.role not in {"support", "conflict", "context"} or obs.match not in {"exact", "reported", "different"}:
            raise ValueError("Unknown evidence role or scope match")
        dated_scope = (kind == "location" and target is None) or _covers(obs, target)
        comparable = obs.match == "exact" and obs.scope == scope and dated_scope
        role = obs.role
        if obs.match == "different" or (role == "conflict" and not comparable):
            role = "context"
        if role == "support" and (obs.scope != scope or (obs.match == "exact" and not comparable)):
            role = "context"
        if role == "support":
            supports.append(obs)
            if comparable:
                exact.append(obs)
        if role == "conflict":
            conflicts.append(obs)
        source = asdict(obs)
        source.update(role=role, lineage="known" if obs.origin else "unknown")
        sources.append(source)

    # A cited or repeated publication never creates a new lineage. Missing
    # ancestry makes the total unknown, even if a documented subset agrees.
    documented = {obs.origin for obs in exact if obs.origin and obs.independent}
    known = {obs.origin for obs in supports if obs.origin}
    if observations is None:
        origins = None
    elif not supports:
        origins = 0
    elif any(not obs.origin for obs in supports):
        origins = None
    elif len(known) == 1:
        origins = 1
    else:
        origins = len(documented) if documented == known else None
    if observations is None:
        strength = None
    elif conflicts:
        strength = "conflicting_evidence"
    elif len(documented) >= 2:
        strength = "corroborated"
    else:
        strength = "reported" if supports else "no_evidence"

    decision = "unconfirmed" if kind == "service" else None
    shown_review = None
    if review is not None and review.scope == scope and target is not None and _date(review.as_of) == target:
        if kind == "location" and exact and not conflicts:
            shown_review = {"scope": review.scope, "as_of": review.as_of}
        elif kind == "service":
            assertions = {"yes": {"onsite_delivery"}, "no": {"explicit_absence", "all_cases_referral"}}
            eligible = assertions.get(review.decision, set())
            if not conflicts and any(obs.assertion in eligible for obs in exact):
                decision = review.decision
                shown_review = {"scope": review.scope, "as_of": review.as_of}

    if missing_check is None and conflicts:
        missing_check = "Resolve the conflicting statements at the same branch and applicable scope."
    if missing_check is None and decision == "unconfirmed":
        missing_check = "Check a dated statement of onsite delivery or explicit absence at the exact branch."
    return {"kind": kind, "service": service, "scope": scope, "precision": precision, "decision": decision,
            "strength": strength, "as_of": target.isoformat() if target else None, "review": shown_review,
            "source_records": None if observations is None else len(sources),
            "independent_supporting_origins": origins, "sources": sources,
            "missing_check": missing_check}


def _valid_number(value, limit):
    return type(value) in {float, int} and -limit <= value <= limit and isfinite(value)


def _reported_precision(location):
    latitude, longitude = location.get("latitude"), location.get("longitude")
    if _valid_number(latitude, 90) and _valid_number(longitude, 180) and (latitude or longitude):
        return "reported_position", "latitude / longitude"
    pin = location.get("pin")
    if isinstance(pin, str) and re.fullmatch(r"[1-9][0-9]{5}", pin.strip()):
        return "postal_area", "pin"
    for field in ("locality", "city"):
        value = location.get(field)
        if isinstance(value, str) and value.strip():
            return field, field
    return "unknown", None


def _fixture_pointer(links):
    for value in links or ():
        if isinstance(value, str):
            try:
                parsed = urlsplit(value)
            except ValueError:
                continue
            if parsed.scheme == "https" and parsed.netloc == "example.invalid" and not parsed.query and not parsed.fragment:
                return value
    return None


def _synthetic_finding(card, service):
    if not isinstance(card.get("facility_id"), str) or not card["facility_id"].startswith("demo-"):
        raise ValueError("The demonstration adapter requires the tracked synthetic result")
    scope = "Fictional facility record"
    precision, location_field = _reported_precision(card.get("location") or {})
    location_sources = ()
    if location_field:
        location_sources = (Observation(SYNTHETIC, "The demonstration record reports this location field.", scope,
                                        role="support", origin="demo_fixture", field=location_field),)
    location = summarize_claim("location", scope, location_sources, precision=precision,
                               missing_check="Check the exact physical branch or patient entrance.")
    pointer = _fixture_pointer(card.get("record_source_urls"))
    service_sources = ()
    if card.get("evidence_strength") in {"direct", "indirect"} and card.get("evidence_excerpt"):
        role = "support" if card["evidence_strength"] == "direct" else "context"
        service_sources = (Observation(SYNTHETIC, card["evidence_excerpt"], scope, role=role, origin="demo_fixture",
                                       field=card.get("evidence_field"), citation=pointer,
                                       citation_scope="record" if pointer else None),)
    claim = summarize_claim("service", scope, service_sources, service=service,
                            missing_check="Check a dated statement of onsite delivery at the exact branch.")
    return {"location": location, "service": claim}


def _warehouse_summary(response, service):
    safe = response.get("withheld") is True
    status = response.get("status") if safe and response.get("status") in WAREHOUSE_STATUSES else "unavailable"
    evidence = response.get("evidence")
    signal = evidence if status == "withheld" and evidence in {"direct", "related"} else None
    return {"status": status, "text_signal": signal, "service": service, "decision": "unconfirmed",
            "precision": "unknown", "branch": None, "as_of": None, "strength": None,
            "source_records": None, "independent_supporting_origins": None, "sources": [],
            "missing_check": "Check an audience-cleared branch link and dated, applicable onsite evidence."}


def project_find_care(response, service, *, mode):
    """Describe the current raw demo response or already-withheld warehouse summary."""
    if service not in SERVICES:
        raise ValueError("Use the current target service")
    if mode == "warehouse":
        summary = _warehouse_summary(response, service)
        return {"grain": "warehouse_summary", "status": summary["status"], "findings": [], "summary": summary}
    if mode != "demo" or response.get("withheld"):
        raise ValueError("Use the configured data mode and its corresponding response")
    status = response.get("status")
    group = {"ok": "direct_results", "needs_confirmation": "indirect_leads"}.get(status)
    cards = response.get(group, ()) if group is not None else ()
    findings = [{"result_group": group, "index": index, **_synthetic_finding(card, service)}
                for index, card in enumerate(cards)]
    return {"grain": "synthetic_finding", "status": status, "findings": findings, "summary": None}
