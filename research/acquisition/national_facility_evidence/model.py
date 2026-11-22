"""Private evidence grains and deterministic two-way coverage."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from research.matching.common import digest

SERVICES = ("dialysis", "mri", "trauma_care")
DISPOSITIONS = ("exact", "ambiguous", "unmatched", "unresolved_before_comparison")
CLAIM_SCOPES = (
    "programme", "equipment_inventory", "pooled_report", "training",
    "reported_scope_unknown", "planned", "referral", "onsite_delivery",
    "onsite_exclusion",
)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def index(rows, field_name):
    result = {}
    for row in rows:
        key = row[field_name]
        need(isinstance(key, str) and key and key not in result, f"invalid or duplicate {field_name}")
        result[key] = row
    return result


def identifier(grain, *values):
    return f"{grain}:{digest(values)}"


def optional_date(value):
    if value is None:
        return None
    need(isinstance(value, str), "date must be a YYYY-MM-DD string")
    parsed = date.fromisoformat(value)
    need(parsed.isoformat() == value, "date must be a YYYY-MM-DD string")
    return parsed


@dataclass
class EvidenceBatch:
    method: str
    inventory: dict
    records: list = field(default_factory=list)
    premises: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    links: list = field(default_factory=list)

    def validate(self, originals):
        records = index(self.records, "record_id")
        premises = index(self.premises, "premises_id")
        claims = index(self.claims, "claim_id")
        need(isinstance(self.method, str) and bool(self.method), "missing method")
        for record in records.values():
            need(all(record.get(k) for k in ("edition", "family", "origin_record", "locator")),
                 "source record missing edition, family, original key or locator")
        for site in premises.values():
            need(site["record_id"] in records, "orphan premises hypothesis")
            need(type(site["comparable"]) is bool and type(site["identity_reviewed"]) is bool,
                 "premises dispositions must be explicit")
            witness_keys = ("family", "locator", "role")
            need(all(all(w.get(k) for k in witness_keys) for w in site["witnesses"]),
                 "premises witness needs a family, locator and role")
            if site["identity_reviewed"]:
                need(len(physical_families(site)) >= 2, "independent premises review needs two distinct physical source families")
        for claim in claims.values():
            need(claim["record_id"] in records, "orphan service claim")
            need(claim["premises_id"] is None or claim["premises_id"] in premises, "unknown claim premises")
            need(claim["service"] in SERVICES and claim["scope"] in CLAIM_SCOPES and claim["locator"],
                 "service claim needs a supported service, scope and locator")
            optional_date(claim["publication_date"])
            optional_date(claim["observation_date"])
            start, end = (optional_date(claim[k]) for k in ("effective_from", "effective_to"))
            need(not (start and end and start > end), "inverted effective interval")
        seen = set()
        for link in self.links:
            occ, site = link["occurrence_key"], link["premises_id"]
            pair = occ, site
            need(occ in originals and site in premises and pair not in seen, "orphan or duplicate candidate link")
            need(premises[site]["comparable"] and link["basis"], "candidate needs a comparable premise and a positive basis")
            need(type(link["exact_candidate"]) is bool and isinstance(link["conflicts"], list),
                 "candidate needs explicit exact and conflict fields")
            seen.add(pair)
        return premises


def physical_families(site):
    return {w["family"] for w in site["witnesses"] if w["role"] in ("civic_address", "surveyed_premises")}


def link_outcomes(batch, originals):
    """Apply reverse uniqueness by original payload, retaining each occurrence."""
    sites = batch.validate(originals)
    from_occ, from_site = defaultdict(list), defaultdict(list)
    for link in batch.links:
        from_occ[link["occurrence_key"]].append(link)
        from_site[link["premises_id"]].append(link)

    def exact(link):
        reverse = from_site[link["premises_id"]]
        payloads = {originals[r["occurrence_key"]]["payload_sha256"] for r in reverse}
        return link["exact_candidate"] and not link["conflicts"] and len(payloads) == 1

    forward = {}
    for key in originals:
        matches = from_occ[key]
        if len(matches) == 1 and exact(matches[0]):
            status = "exact"
        else:
            status = "ambiguous" if matches else "unmatched"
        forward[key] = {"status": status, "candidates": matches}

    reverse = {}
    for site, hypothesis in sites.items():
        matches = from_site[site]
        if not hypothesis["comparable"]:
            status = "unresolved_before_comparison"
        elif not matches:
            status = "unmatched"
        elif all(forward[r["occurrence_key"]]["status"] == "exact" for r in matches):
            status = "exact"
        else:
            status = "ambiguous"
        reverse[site] = {"status": status, "candidates": matches}
    return forward, reverse


def dated_onsite(claim):
    return (claim["scope"] == "onsite_delivery" and claim["premises_id"] is not None
            and bool(claim["observation_date"] or claim["effective_from"]))


def claim_conflicts(claims):
    """Flag explicit opposite claims only when their known dates overlap."""
    keyed = defaultdict(list)
    for claim in claims:
        if claim["premises_id"] is not None and claim["scope"] in ("onsite_delivery", "onsite_exclusion"):
            keyed[claim["premises_id"], claim["service"]].append(claim)

    def interval(claim):
        if claim["effective_from"]:
            return claim["effective_from"], claim["effective_to"] or claim["effective_from"]
        point = claim["observation_date"]
        return point, point

    conflicts = set()
    for pair, group in keyed.items():
        for yes in (r for r in group if r["scope"] == "onsite_delivery"):
            start, end = interval(yes)
            for no in (r for r in group if r["scope"] == "onsite_exclusion"):
                other_start, other_end = interval(no)
                if start and end and other_start and other_end and max(start, other_start) <= min(end, other_end):
                    conflicts.add(pair)
    return conflicts


def disposition_counts(rows):
    counts = Counter(row["status"] for row in rows)
    return {name: counts[name] for name in DISPOSITIONS}


def shared_index(batches, table, key):
    """Permit reuse of a byte-equivalent source fact across methods."""
    result = {}
    for batch in batches:
        for row in getattr(batch, table):
            need(result.setdefault(row[key], row) == row, f"incompatible reuse of {key}")
    return result


def source_counts(batches):
    records = shared_index(batches, "records", "record_id")
    premises = shared_index(batches, "premises", "premises_id")
    claims = list(shared_index(batches, "claims", "claim_id").values())
    independent = {sid for sid, row in premises.items() if row["identity_reviewed"]}
    conflicts = claim_conflicts(claims)
    dated_pairs = {(r["premises_id"], r["service"]) for r in claims if dated_onsite(r)}
    reviewed = {pair for pair in dated_pairs if pair[0] in independent and pair not in conflicts}
    from_origin = Counter((records[r["record_id"]]["family"], records[r["record_id"]]["origin_record"],
                           r["premises_id"], r["service"], r["scope"], r["observation_date"],
                           r["effective_from"], r["effective_to"]) for r in claims)
    return {
        "source_records": len(records),
        "source_record_family_counts": dict(Counter(r["family"] for r in records.values())),
        "premises_hypotheses": len(premises),
        "unresolved_premises_hypotheses": sum(not p["comparable"] for p in premises.values()),
        "independently_supported_physical_sites": len(independent),
        "claims": len(claims),
        "unbound_claims": sum(r["premises_id"] is None for r in claims),
        "additional_claims_in_same_origin_record_scope": sum(n - 1 for n in from_origin.values()),
        "claims_without_service_observation_or_effective_start": sum(
            not (r["observation_date"] or r["effective_from"]) for r in claims),
        "claims_with_unknown_availability": sum(r["availability"] is None for r in claims),
        "claims_with_unknown_capacity": sum(r["capacity"] is None for r in claims),
        "by_service": {
            service: {
                "claims_by_scope": dict(Counter(r["scope"] for r in claims if r["service"] == service)),
                "premises_with_dated_onsite_claim": sum(s == service for _, s in dated_pairs),
                "independently_supported_site_service_review_candidates": sum(s == service for _, s in reviewed),
                "sites_with_conflicting_dated_claims": sum(s == service for _, s in conflicts),
            } for service in SERVICES
        },
    }
