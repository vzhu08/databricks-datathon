"""Propose reviewable links between B1 rows and official identity references."""

from dataclasses import dataclass

from .rghs import normalize_words


GENERIC = {
    "and", "at", "of", "the", "centre", "center", "care", "health", "hospital", "hosp",
    "medical", "college", "govt", "government", "district", "general", "multispeciality",
    "multispecialty", "limited", "ltd", "private", "pvt", "trauma", "rajasthan",
}
ADDRESS_GENERIC = GENERIC | {"near", "opposite", "road", "rd", "plot", "no", "india"}


@dataclass(frozen=True)
class Campus:
    external_id: str
    source: str
    locator: str
    name: str | None
    district: str | None = None
    city: str | None = None
    address: str | None = None
    pin: str | None = None
    institution: str | None = None
    facility_type: str = "unknown"


def normalized_district(value: str | None) -> tuple[str, ...]:
    return tuple(normalize_words(value))


def name_terms(campus: Campus) -> tuple[str, ...]:
    locality = set(normalize_words(campus.district) + normalize_words(campus.city))
    words = normalize_words(campus.name)
    return tuple(word for word in words if word not in locality and word not in GENERIC)


def name_signals(left: Campus, right: Campus) -> list[str]:
    a, b = name_terms(left), name_terms(right)
    if not left.name or not right.name:
        return []

    populated = a and b
    signals = []
    if normalize_words(left.name) == normalize_words(right.name):
        signals.append("normalized_name_exact")
    if populated and a == b:
        signals.append("distinctive_name_terms_exact")
    if populated and (
        (len(a) == 1 and len(b) >= 2 and a[0] == "".join(word[0] for word in b))
        or (len(b) == 1 and len(a) >= 2 and b[0] == "".join(word[0] for word in a))
    ):
        signals.append("initialism_expansion")
    if populated and len(set(a) & set(b)) >= 2:
        signals.append("shared_distinctive_terms")
    return signals


def assess(left: Campus, right: Campus) -> dict | None:
    left_district, right_district = map(normalized_district, (left.district, right.district))
    known_districts = bool(left_district and right_district)
    district_agrees = known_districts and left_district == right_district
    signals = name_signals(left, right)
    has_direct_name_signals = bool(signals)
    institutional = right.institution and name_signals(left, Campus(
        right.external_id, right.source, right.locator, right.institution, right.district,
        right.city,
    ))
    if institutional:
        signals.append("associated_institution_name")
    if not signals:
        return None
    locality = set(left_district + right_district)
    for value in (left.city, right.city):
        locality.update(normalize_words(value))
    address_left = set(normalize_words(left.address)) - ADDRESS_GENERIC - locality
    address_right = set(normalize_words(right.address)) - ADDRESS_GENERIC - locality
    shared_address = sorted(address_left & address_right)
    issues = []
    if district_agrees:
        signals.append("district_exact")
    elif known_districts:
        issues.append("district_disagrees")
    else:
        issues.append("district_unavailable")
    if left.pin and right.pin:
        if left.pin != right.pin:
            issues.append("pin_disagrees")
        else:
            signals.append("pin_exact")
    if left.city and right.city and normalize_words(left.city) != normalize_words(right.city):
        issues.append("city_disagrees")
    if len(shared_address) >= 2:
        signals.append("address_terms_agree")
    elif address_left and address_right:
        issues.append("address_requires_review")
    else:
        issues.append("street_address_unavailable")
    # "District Hospital" on its own generates only a same-district lead.
    if not name_terms(left) and not name_terms(right) and not district_agrees:
        return None
    if "associated_institution_name" in signals:
        issues.append("institutional_affiliation_does_not_locate_campus")
    if right.facility_type in {"medical_college", "hospital_group"}:
        issues.append("institution_or_group_record_has_no_hospital_campus_boundary")
    relationship = "possible_hospital_campus"
    if not has_direct_name_signals or right.facility_type in {"medical_college", "hospital_group"}:
        relationship = "institutional_context"

    return {
        "external_facility_id": right.external_id,
        "source_key": right.source,
        "locator": right.locator,
        "name": right.name,
        "district": right.district,
        "city": right.city,
        "address": right.address,
        "pin": right.pin,
        "associated_institution": right.institution,
        "facility_type": right.facility_type,
        "relationship": relationship,
        "direct_name_signal": has_direct_name_signals,
        "signals": signals,
        "limitations": issues,
        "shared_address_terms": shared_address,
    }


def build_crosswalk(state: list[Campus], references: list[Campus]) -> list[dict]:
    """Return one ledger entry per B1 row. All identity proposals remain open."""
    ledger = []
    for left in state:
        candidates = [result for right in references if (result := assess(left, right))]
        candidates.sort(key=lambda item: (
            "district_disagrees" in item["limitations"],
            item["relationship"] == "institutional_context",
            not item["direct_name_signal"],
            "district_exact" not in item["signals"],
            "address_terms_agree" not in item["signals"],
            "normalized_name_exact" not in item["signals"],
            item["external_facility_id"],
        ))
        if not candidates:
            status = "unmatched"
        elif len(candidates) > 1 or set(candidates[0]["limitations"]) & {
            "district_disagrees", "pin_disagrees", "city_disagrees", "address_requires_review",
            "institutional_affiliation_does_not_locate_campus",
            "institution_or_group_record_has_no_hospital_campus_boundary",
        }:
            status = "ambiguous"
        else:
            status = "candidate"
        ledger.append({
            "state_external_facility_id": left.external_id,
            "state_locator": left.locator,
            "state_name": left.name,
            "state_district": left.district,
            "state_address": left.address,
            "status": status,
            "alternatives": candidates,
            "review_status": "pending",
            "reviewer": None,
            "reviewed_at": None,
        })
    return ledger
