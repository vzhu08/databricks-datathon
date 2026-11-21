"""Keep original intervals and unresolved identities instead of guessing dates/NINs."""
from collections import Counter, defaultdict
from datetime import date, datetime
import re

from .common import FAMILY, identity


def parse_date(raw):
    result = {"raw": raw, "status": "invalid", "iso": None, "candidates": []}
    value = raw.strip()
    if value.casefold() in {"", "na", "n/a", "-", "not available"}:
        result["status"] = "missing"
        return result
    candidates = set()
    numeric = re.fullmatch(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})", value)
    if numeric:
        a, b, c = numeric.groups()
        orders = [(int(a), int(b), int(c))] if len(a) == 4 else (
            [(int(c), int(b), int(a)), (int(c), int(a), int(b))] if len(c) == 4 else [])
        for year, month, day in orders:
            try:
                candidates.add(date(year, month, day).isoformat())
            except ValueError:
                pass
    else:
        for fmt in ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y"):
            try:
                candidates.add(datetime.strptime(value, fmt).date().isoformat())
            except ValueError:
                pass
    result["candidates"] = sorted(candidates)
    if len(candidates) == 1:
        result.update(status="exact", iso=next(iter(candidates)))
    elif candidates:
        result["status"] = "ambiguous"
    return result


def episode(row, document, as_of):
    date.fromisoformat(as_of)
    start, end = parse_date(row["valid_from_raw"]), parse_date(row["valid_until_raw"])
    reasons = [field + "_" + value["status"] for field, value in (("start", start), ("end", end))
               if value["status"] != "exact"]
    coherent = not (start["candidates"] and end["candidates"]) or any(
        a <= b for a in start["candidates"] for b in end["candidates"])
    if not coherent:
        reasons.append("interval_conflict")
    expiration = "unknown"
    if end["candidates"]:
        expiration = ("expired_under_all_parses" if max(end["candidates"]) < as_of else
                      "not_expired_under_all_parses" if min(end["candidates"]) >= as_of else "ambiguous_at_as_of")
    if row["nin"] is None:
        reasons.append("nin_not_exposed")
    if row["category"] is None:
        reasons.append("category_not_exposed")
    if not row["district"]:
        reasons.append("district_missing")
    # A source row locator is not a campus ID. Never group episodes by this ID.
    eid = identity("nqas-episode", FAMILY, row["mode"], row["display_cells"], row["nin"], row["category"])
    return {**row, "episode_id": eid, "source_family": FAMILY, "snapshot_sha256": document["sha256"],
            "source_locator": row["source_url"] + "#view=" + row["view_id"] +
                              ";tbody-row=" + str(row["row_index"]) + ";serial=" + row["serial"],
            "start": start, "end": end, "interval_coherent": coherent, "as_of": as_of,
            "expiration": expiration, "review_reasons": reasons,
            "intended_use": "held_out_accreditation_audit", "matching_feature_use": "excluded"}


def relate(episodes):
    """Verified same-programme IDs plus coherent exact intervals; never name-only links."""
    by_nin = defaultdict(list)
    names = Counter((e["facility"].casefold(), e["district"].casefold()) for e in episodes)
    for item in episodes:
        if item["nin"] is not None:
            by_nin[(item["source_family"], item["nin"])].append(item)
    links, conflicts = [], []
    for (family, nin), group in sorted(by_nin.items()):
        for index, a in enumerate(sorted(group, key=lambda e: e["episode_id"])):
            for b in sorted(group, key=lambda e: e["episode_id"])[index + 1:]:
                pair = {"source_family": family, "nin": nin, "episodes": [a["episode_id"], b["episode_id"]]}
                if a["facility"].casefold() != b["facility"].casefold() or a["district"].casefold() != b["district"].casefold():
                    conflicts.append({**pair, "reason": "same_nin_incompatible_campus_labels"})
                    continue
                if not all(e["interval_coherent"] and e["start"]["iso"] and e["end"]["iso"] for e in (a, b)):
                    conflicts.append({**pair, "reason": "same_nin_unresolved_interval"})
                    continue
                if a["end"]["iso"] < b["start"]["iso"] or b["end"]["iso"] < a["start"]["iso"]:
                    links.append({**pair, "relation": "same_programme_nin_nonoverlapping_episodes",
                                  "formal_renewal_not_asserted": True})
                else:
                    conflicts.append({**pair, "reason": "same_nin_overlapping_intervals_preserved"})
    return {"verified_identifier_relations": links, "identifier_conflicts": conflicts,
            "repeated_name_district_groups_without_verified_identity": sum(n > 1 for n in names.values()),
            "warning": "Repeated names alone do not establish a shared campus or renewal."}


def sample(episodes, limit=20):
    """Deterministic documentary challenge sample, not a population accuracy sample."""
    names = Counter((e["facility"].casefold(), e["district"].casefold()) for e in episodes)
    strata = {}
    for item in episodes:
        key = (item["mode"], item["expiration"], names[(item["facility"].casefold(), item["district"].casefold())] > 1,
               item["start"]["status"] == "ambiguous" or item["end"]["status"] == "ambiguous")
        strata.setdefault(key, []).append(item)
    groups = [sorted(rows, key=lambda e: e["episode_id"]) for _, rows in sorted(strata.items())]
    selected = []
    while groups and len(selected) < limit:
        remaining = []
        for group in groups:
            if len(selected) < limit:
                selected.append(group.pop(0))
            if group:
                remaining.append(group)
        groups = remaining
    return selected
