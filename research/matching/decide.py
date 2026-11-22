"""Turn retrieved candidates into contract rows.

Only one path confirms automatically: an unambiguous identifier shared in an
inspected namespace, with no campus conflict and no competing candidate. Every
other pair stays a `candidate` until a named reviewer records a decision.
"""
from __future__ import annotations

from collections import Counter

from .common import field_value, require, stable_id

MATCH_NS, REVIEW_NS = "acq-c-match", "acq-c-review"

# First applicable reason wins. Severity says how misleading an unreviewed link would be.
REVIEW_REASONS = (
    ("identifier_conflict", "high", "Two records disagree about an identifier in the same namespace. Check both source records before linking."),
    ("identifier_not_unique", "high", "The shared identifier is not unique on both sides, or its values are not exact text. Resolve the duplicate before linking."),
    ("identifier_campus_conflict", "high", "The identifier agrees but geography or a competing candidate disagrees. Review the campus before confirming."),
    ("ambiguous_campus", "medium", "Several campuses fit this name. Compare address, district and coordinates, then confirm at most one."),
    ("geography_conflict", "medium", "Name evidence agrees but state, place, PIN or coordinates disagree. Decide whether this is another campus."),
    ("shared_switchboard", "medium", "The phone number is shared by several records. Do not treat it as campus identity."),
    ("acronym_only", "medium", "Only an acronym links these names. Expand it from an official source before linking."),
    ("name_only", "medium", "Name evidence only; no usable geography on one side. Find address or coordinate evidence first."),
    ("proximity_only", "low", "Nearby record with no name evidence. Likely a different facility; link only with independent evidence."),
    ("non_hospital_type", "low", "The external record is not typed as a hospital. Check that it is the same kind of facility."),
)
REASON_INDEX = {reason: (severity, action) for reason, severity, action in REVIEW_REASONS}


def check_policy(policy):
    """Same shape D accepts for --identity-policy."""
    require(isinstance(policy, dict), "identity_policy", "expected namespace mapping")
    for namespace, binding in policy.items():
        require(isinstance(namespace, str) and namespace.strip() and isinstance(binding, dict),
                "identity_policy", "invalid namespace binding")
        require(set(binding) == {"base_field", "external_field", "source_keys"},
                "identity_policy", "binding needs base_field, external_field, source_keys")
        require(all(isinstance(binding[k], str) and binding[k].strip() for k in ("base_field", "external_field")),
                "identity_policy", "blank field")
        require(isinstance(binding["source_keys"], list) and binding["source_keys"]
                and all(isinstance(s, str) and s.strip() for s in binding["source_keys"]),
                "identity_policy", "nonempty allowed source_keys required")
    return policy


def identifier_counts(bases, externals, policy):
    """Occurrences of each identifier value per namespace on both sides,
    counted exactly as D's validator counts them."""
    result = {}
    for namespace, binding in policy.items():
        base_counter = Counter(str(field_value(b["row"], binding["base_field"])) for b in bases
                               if field_value(b["row"], binding["base_field"]) is not None)
        ext_counter = Counter(str(field_value(e["row"], binding["external_field"])) for e in externals
                              if field_value(e["row"], binding["external_field"]) is not None
                              and e["source_key"] in binding["source_keys"])
        result[namespace] = (base_counter, ext_counter)
    return result


def _geography_conflict(signals):
    return (signals["state"] == "conflict" or signals["place"] == "conflict" or signals["pin"] == "conflict"
            or signals["distance_band"] in ("far", "region"))


def auto_confirmation(candidate, base_row, external_row, policy, counts):
    """Return (proof, None) when automatic confirmation is allowed, else (None, reason).

    (None, None) means no identifier is shared at all. Namespaces are tried in
    sorted order; the first one that is exact text and unique on both sides wins.
    """
    signals = candidate["signals"]
    if not signals["identifiers"]:
        return None, None
    if signals["identifier_disagrees"]:
        return None, "identifier_conflict"
    proof = None
    for namespace in signals["identifiers"]:
        binding = policy[namespace]
        base_value = field_value(base_row, binding["base_field"])
        external_value = field_value(external_row, binding["external_field"])
        if not (isinstance(base_value, str) and isinstance(external_value, str) and base_value == external_value):
            continue
        base_counter, ext_counter = counts[namespace]
        if base_counter[base_value] == 1 and ext_counter[external_value] == 1:
            proof = {"namespace": namespace, "value": base_value, "base_field": binding["base_field"],
                     "external_field": binding["external_field"]}
            break
    if proof is None:
        return None, "identifier_not_unique"
    if _geography_conflict(signals) or candidate["other_bases_for_external"]:
        return None, "identifier_campus_conflict"
    return proof, None


def primary_reason(candidate, blocked):
    flags = set(candidate["flags"])
    if blocked:
        return blocked
    if "identifier_disagrees" in flags:
        return "identifier_conflict"
    if "ambiguous_campus" in flags:
        return "ambiguous_campus"
    if flags & {"state_conflict", "place_conflict", "pin_conflict", "coordinates_far_apart", "competing_coordinates",
                "premises_conflict", "street_conflict", "branch_qualifier_conflict", "own_postal_state_conflict",
                "multiple_observed_pins"}:
        return "geography_conflict"
    for reason in ("shared_switchboard", "acronym_only", "name_only", "proximity_only", "non_hospital_type"):
        if reason in flags:
            return reason
    return None


def _phrase(signals):
    distance = "unavailable" if signals["distance_m"] is None else f"{signals['distance_m']} m ({signals['distance_band']})"
    observed_pin = (" Observed postal PINs disagree, including a PIN from address text."
                    if signals.get("premises", {}).get("observed_pin_conflict") else "")
    return (f"Name evidence: {signals['name_level']} ({signals['name_detail']}"
            f"{', via alias' if signals['name_via_alias'] else ''}). "
            f"State {signals['state']}; place {signals['place']}; PIN {signals['pin']}; "
            f"address {signals['address']}; distance {distance}.{observed_pin}")


def rationale(candidate, proof):
    s = candidate["signals"]
    if proof:
        head = (f"Automatic confirmation: identifier in inspected namespace '{proof['namespace']}' is exact, "
                "unique on both sides, with no geography conflict and no competing campus candidate.")
    else:
        head = ("Retrieval candidate only; not an identity decision. "
                f"Retrieved by {candidate['retrieval_reason']}, rank {candidate['rank']} of "
                f"{candidate['candidates_found_for_base']} for this base row; "
                f"{candidate['other_bases_for_external']} other base row(s) retrieved this external record.")
    tail = f" Flags: {', '.join(sorted(candidate['flags']))}." if candidate["flags"] else ""
    return f"{head} {_phrase(s)}{tail}"


def build(candidates, bases, externals, policy, identifier_base=None):
    """Return (match rows, review rows, enriched candidates).

    `identifier_base` is the full list of original base rows when `bases` is
    only part of it. Identifier uniqueness is then counted across the whole
    base, as D's validator counts it.
    """
    base_rows = {b["id"]: b["row"] for b in bases}
    external_rows = {e["id"]: e["row"] for e in externals}
    counted = bases if identifier_base is None else [{"row": row} for row in identifier_base]
    counts = identifier_counts(counted, externals, policy)
    matches, reviews = [], []
    for c in candidates:
        proof, blocked = auto_confirmation(c, base_rows[c["facility_id"]], external_rows[c["external_facility_id"]],
                                           policy, counts)
        match_id = stable_id(MATCH_NS, c["facility_id"], c["external_facility_id"])
        c["match_id"] = match_id
        c["auto_confirmed"] = proof is not None
        matches.append({
            "match_id": match_id, "facility_id": c["facility_id"],
            "external_facility_id": c["external_facility_id"],
            "status": "confirmed" if proof else "candidate",
            "method": "shared_identifier" if proof else "candidate_generation",
            "rationale": rationale(c, proof), "shared_identifier": proof,
            "reviewer": None, "reviewed_at": None,
        })
        reason = None if proof else primary_reason(c, blocked)
        c["review_reason"] = reason
        if reason:
            severity, action = REASON_INDEX[reason]
            reviews.append({
                "review_id": stable_id(REVIEW_NS, reason, match_id), "facility_id": c["facility_id"],
                "external_facility_id": c["external_facility_id"], "evidence_id": None, "match_id": match_id,
                "reason_code": reason, "severity": severity, "status": "open",
                "next_action": action, "resolution": None,
            })
    matches.sort(key=lambda r: r["match_id"])
    reviews.sort(key=lambda r: r["review_id"])
    return matches, reviews, candidates
