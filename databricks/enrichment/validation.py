"""Schema validation and checkable semantics, not a natural-language truth oracle."""
import re
from collections import Counter, defaultdict
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker

from common import IDS, ROOT, VERSION, Invalid, finite, load, require


@lru_cache(maxsize=1)
def validator():
    schema = load(ROOT / "contracts/enrichment/schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_check(batch, label="batch"):
    finite(batch, label)
    require(isinstance(batch, dict), label, "expected a contract envelope object")
    require(batch.get("contract_version") == VERSION, f"{label}.contract_version",
            f"supported version is {VERSION}")
    errors = sorted(validator().iter_errors(batch), key=lambda e: str(list(e.path)))
    if errors:
        # Do not echo arbitrary instance values (possibly restricted source text).
        messages = []
        for error in errors[:20]:
            path = ".".join(str(p) for p in error.absolute_path) or "$"
            messages.append(f"{label}.{path}: violates schema {error.validator}")
        raise Invalid("\n".join(messages))
    for table in IDS:
        for index, row in enumerate(batch[table]):
            for key, value in row.items():
                if isinstance(value, str):
                    require(bool(value.strip()), f"{label}.{table}[{index}].{key}",
                            "blank strings are not usable values; use null where allowed")


def base_check(base):
    finite(base, "base")
    require(isinstance(base, list), "base", "expected an array of original rows")
    result = {}
    for index, row in enumerate(base):
        path = f"base[{index}].facility_id"
        require(isinstance(row, dict), path, "expected an object")
        fid = row.get("facility_id")
        require(isinstance(fid, str) and bool(fid.strip()), path, "nonempty text ID required")
        require(fid not in result, path, "duplicate base ID; do not collapse original rows")
        result[fid] = row
    return result


def reviewed(row, path, mandatory=False):
    actor, at = row["reviewer"], row["reviewed_at"]
    require((actor is None) == (at is None), path, "reviewer and reviewed_at must appear together")
    if mandatory:
        require(actor is not None and at is not None, path, "reviewer and UTC reviewed_at required")


def field_value(row, path):
    """Policy field selectors support preserved source_row.<column> values."""
    if path in row:
        return row[path]
    value = row
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def semantic_check(batch, base, identity_policy=None):
    """Validate a deduplicated combined dataset. policy binds verified ID namespaces."""
    schema_check(batch)
    bases = base_check(base)
    indexes = {}
    for table, key in IDS.items():
        indexes[table] = {row[key]: row for row in batch[table]}
        require(len(indexes[table]) == len(batch[table]), table, "duplicate IDs require merge planning")

    def ref(table, value, path, nullable=False):
        if nullable and value is None:
            return None
        target = bases if table == "base" else indexes[table]
        require(value in target, path, f"reference not found in combined {table}")
        return target[value]

    policy = identity_policy or {}
    require(isinstance(policy, dict), "identity_policy", "expected namespace mapping")
    for ns, binding in policy.items():
        require(isinstance(ns, str) and ns.strip() and isinstance(binding, dict),
                "identity_policy", "invalid namespace binding")
        require(set(binding) == {"base_field", "external_field", "source_keys"},
                "identity_policy", "binding needs base_field, external_field, source_keys")
        require(all(isinstance(binding[k], str) and binding[k].strip()
                    for k in ("base_field", "external_field")), "identity_policy", "blank field")
        require(isinstance(binding["source_keys"], list) and binding["source_keys"]
                and all(isinstance(s, str) and s.strip() for s in binding["source_keys"]),
                "identity_policy", "nonempty allowed source_keys required")

    for index, row in enumerate(batch["external_facilities"]):
        path = f"external_facilities[{index}]"
        ref("source_snapshots", row["snapshot_id"], path + ".snapshot_id")
        require((row["latitude"] is None) == (row["longitude"] is None), path,
                "coordinates must be a complete pair or both null")
        if row["latitude"] is not None:
            require(row["coordinate_method"] is not None, path + ".coordinate_method", "required with coordinates")
        if row["name_original"] is None:
            require(row["name_normalized"] is None and bool(row["quality_flags"]), path,
                    "missing original name must remain null with quality flags")

    confirmed = defaultdict(set)
    active = defaultdict(set)
    for row in batch["facility_matches"]:
        if row["status"] == "confirmed":
            confirmed[row["external_facility_id"]].add(row["facility_id"])
        if row["status"] != "rejected":
            active[row["external_facility_id"]].add(row["facility_id"])
    # Cache uniqueness indexes once; national batches must not need O(rows^2) scans.
    uniqueness = {}
    for ns, binding in policy.items():
        bc = Counter(str(field_value(r, binding["base_field"])) for r in base
                     if field_value(r, binding["base_field"]) is not None)
        ec = Counter(str(field_value(r, binding["external_field"])) for r in batch["external_facilities"]
                     if field_value(r, binding["external_field"]) is not None
                     and indexes["source_snapshots"][r["snapshot_id"]]["source_key"] in binding["source_keys"])
        uniqueness[ns] = (bc, ec)

    for index, row in enumerate(batch["facility_matches"]):
        path = f"facility_matches[{index}]"
        b = ref("base", row["facility_id"], path + ".facility_id")
        ext = ref("external_facilities", row["external_facility_id"], path + ".external_facility_id")
        reviewed(row, path, row["status"] in ("rejected", "conflict") or
                 (row["status"] == "confirmed" and row["method"] != "shared_identifier"))
        require(len(confirmed[row["external_facility_id"]]) <= 1, path,
                "one external campus cannot confirm multiple base IDs")
        if row["status"] != "confirmed":
            continue
        require(row["method"] != "candidate_generation", path + ".method", "candidate generation cannot confirm")
        if row["method"] == "shared_identifier":
            proof = row["shared_identifier"]
            require(proof is not None, path + ".shared_identifier", "proof required")
            binding = policy.get(proof["namespace"])
            require(binding is not None, path + ".shared_identifier.namespace",
                    "unverified namespace; supply inspected identity_policy or manual review")
            require(all(proof[k] == binding[k] for k in ("base_field", "external_field")),
                    path + ".shared_identifier", "fields disagree with namespace policy")
            source = indexes["source_snapshots"][ext["snapshot_id"]]["source_key"]
            require(source in binding["source_keys"], path, "source not authorized for this ID namespace")
            require(field_value(b, proof["base_field"]) == proof["value"] and
                    field_value(ext, proof["external_field"]) == proof["value"], path,
                    "shared identifier value not verifiable exactly in both inputs")
            bc, ec = uniqueness[proof["namespace"]]
            require(bc[proof["value"]] == ec[proof["value"]] == 1 and
                    len(active[row["external_facility_id"]]) == 1, path,
                    "shared identifier is ambiguous or competing campus candidates remain")

    for index, row in enumerate(batch["facility_evidence"]):
        path = f"facility_evidence[{index}]"
        ext = ref("external_facilities", row["external_facility_id"], path + ".external_facility_id")
        ref("source_snapshots", row["snapshot_id"], path + ".snapshot_id")
        require((row["facility_id"] is None) == (row["match_id"] is None), path,
                "base and match links must both be null or both populated")
        if row["facility_id"] is not None:
            ref("base", row["facility_id"], path + ".facility_id")
            match = ref("facility_matches", row["match_id"], path + ".match_id")
            require(match["status"] == "confirmed" and match["facility_id"] == row["facility_id"]
                    and match["external_facility_id"] == row["external_facility_id"], path + ".match_id",
                    "linked evidence requires a confirmed match with identical base/external IDs")
        cross_source = row["snapshot_id"] != ext["snapshot_id"]
        clinical = row["claim_type"] == "service"
        decisive = row["polarity"] in ("supports", "contradicts")
        reviewed(row, path, cross_source or (clinical and decisive))
        require((row["service"] is not None) == clinical, path + ".service",
                "service is required only for service claims")
        if row["observation"] is not None:
            ob = row["observation"]
            require((ob["latitude"] is None) == (ob["longitude"] is None), path + ".observation",
                    "observation coordinates must be a complete pair or both null")
        if row["effective_date"] and row["valid_until"]:
            require(row["effective_date"] <= row["valid_until"], path + ".valid_until", "expiry precedes effective date")
        if row["temporal_status"] == "undated":
            require(row["effective_date"] is None and row["valid_until"] is None, path,
                    "undated evidence cannot have effective/expiry dates")
        if row["temporal_status"] == "dated":
            require(row["effective_date"] is not None, path + ".effective_date", "dated evidence requires date")
        if row["temporal_status"] == "expired":
            require(row["valid_until"] is not None, path + ".valid_until", "expired evidence requires expiry date")
        if clinical and row["polarity"] == "supports":
            excerpt = (row["excerpt"] or "").lower()
            token = {"trauma_care": r"\btrauma\b", "dialysis": r"\bdialysis\b", "mri": r"\bmri\b"}[row["service"]]
            require(re.search(token, excerpt) is not None, path + ".excerpt",
                    "affirmative service evidence needs an explicit service mention plus human review")
            require(not re.search(r"\b(planned|proposed|referral[ -]only|unavailable|not available|no trauma|non[ -]functional)\b", excerpt),
                    path + ".polarity", "planned/referral/unavailable excerpt cannot support capability")
        # These conservative checks catch known invalid upgrades only. A reviewer
        # must still verify source/excerpt, campus, negation, scope and historical wording.

    for index, row in enumerate(batch["review_queue"]):
        path = f"review_queue[{index}]"
        for key, table in (("facility_id", "base"), ("external_facility_id", "external_facilities"),
                           ("evidence_id", "facility_evidence"), ("match_id", "facility_matches")):
            ref(table, row[key], path + "." + key, nullable=True)
        require((row["status"] == "resolved") == bool(row["resolution"]), path + ".resolution",
                "resolved needs a resolution; open must have null resolution")
        for table, key in (("facility_matches", "match_id"), ("facility_evidence", "evidence_id")):
            if row[key] is None:
                continue
            target = indexes[table][row[key]]
            for field in ("facility_id", "external_facility_id"):
                require(row[field] is None or target[field] is None or row[field] == target[field], path,
                        f"review references disagree on {field}")
        if row["match_id"] is not None and row["evidence_id"] is not None:
            match = indexes["facility_matches"][row["match_id"]]
            evidence = indexes["facility_evidence"][row["evidence_id"]]
            for field in ("facility_id", "external_facility_id"):
                require(evidence[field] is None or match[field] == evidence[field], path,
                        "match and evidence references describe different facilities")
    return batch
