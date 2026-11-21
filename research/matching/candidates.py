"""Deterministic candidate retrieval between base rows and external records.

Everything in this module proposes pairs for review. Thresholds are retrieval
heuristics chosen so that reviewers see plausible alternatives; they are not
identity probabilities and must not be reported as confidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from research.geography.distance import haversine_m
from .common import field_value, require
from .normalize import NON_HOSPITAL_TYPES, core, initials, name_evidence

LEVEL = {"none": 0, "weak": 1, "moderate": 2, "strong": 3}

DEFAULTS = {
    "top_k": 5,                  # candidates kept per base row (identifier hits are never cut)
    "max_token_df": 2000,        # a name token on more records than this cannot block alone
    "max_block": 5000,           # a PIN / grid cell larger than this cannot block alone
    "cell_deg": 0.02,            # grid cell for proximity blocking (~2 km)
    "same_site_m": 150.0,
    "near_m": 1000.0,
    "area_m": 5000.0,
    "far_m": 25000.0,
    "proximity_only_m": 100.0,   # 0 disables proximity-only candidates
    "switchboard_min": 3,        # a phone on this many records per side is a switchboard
}


def settings(overrides=None):
    config = dict(DEFAULTS)
    for key, value in (overrides or {}).items():
        require(key in DEFAULTS, "config", "unknown setting")
        require(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0,
                f"config.{key}", "non-negative number required")
        config[key] = value
    return config


def _windows(token_list):
    out = set()
    for size in range(2, 7):
        for start in range(0, len(token_list) - size + 1):
            window = token_list[start:start + size]
            if all(len(w) > 1 for w in window):
                out.add(initials(window))
    return out


def _cell(coord, deg):
    return (int(coord["lat"] // deg), int(coord["lon"] // deg))


class ExternalIndex:
    def __init__(self, externals, policy, config):
        self.externals, self.config = externals, config
        self.token, self.token_state = defaultdict(list), defaultdict(list)
        self.nospace, self.window = defaultdict(list), defaultdict(list)
        self.pin, self.cell, self.phone = defaultdict(list), defaultdict(list), defaultdict(list)
        self.ident = defaultdict(list)
        for i, e in enumerate(externals):
            seen_tokens, seen_windows = set(), set()
            for name in e["names"]:
                c = core(name)
                seen_tokens.update(c)
                if c:
                    self.nospace["".join(c)].append(i)
                seen_windows.update(_windows(name))
            for t in sorted(seen_tokens):
                self.token[t].append(i)
                if e["state"]:
                    self.token_state[(t, e["state"])].append(i)
            for w in sorted(seen_windows):
                self.window[w].append(i)
            if e["pin"]:
                self.pin[e["pin"]].append(i)
            if e["coord"]["usable"]:
                self.cell[_cell(e["coord"], config["cell_deg"])].append(i)
            for p in sorted(e["phones"]):
                self.phone[p].append(i)
            for namespace in sorted(policy):
                binding = policy[namespace]
                value = field_value(e["row"], binding["external_field"])
                if value is not None and e["source_key"] in binding["source_keys"]:
                    self.ident[(namespace, str(value))].append(i)

    def block(self, b, policy):
        """Indexes of externals worth scoring against base view b."""
        cfg, found = self.config, set()
        for name in b["names"]:
            c = core(name)
            if c:
                found.update(self.nospace.get("".join(c), ()))
            for t in set(c):
                hits = self.token.get(t, ())
                if len(hits) <= cfg["max_token_df"]:
                    found.update(hits)
                elif b["state"]:
                    hits = self.token_state.get((t, b["state"]), ())
                    if len(hits) <= cfg["max_token_df"]:
                        found.update(hits)
                if 2 <= len(t) <= 6 and t.isalpha():
                    hits = self.window.get(t, ())
                    if len(hits) <= cfg["max_token_df"]:
                        found.update(hits)
            for w in _windows(name):
                hits = self.token.get(w, ())
                if len(hits) <= cfg["max_token_df"]:
                    found.update(hits)
        if b["pin"] and len(self.pin.get(b["pin"], ())) <= cfg["max_block"]:
            found.update(self.pin.get(b["pin"], ()))
        if b["coord"]["usable"]:
            row, col = _cell(b["coord"], cfg["cell_deg"])
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    hits = self.cell.get((row + dr, col + dc), ())
                    if len(hits) <= cfg["max_block"]:
                        found.update(hits)
        for p in b["phones"]:
            found.update(self.phone.get(p, ()))
        for namespace in policy:
            value = field_value(b["row"], policy[namespace]["base_field"])
            if value is not None:
                found.update(self.ident.get((namespace, str(value)), ()))
        return sorted(found)


def _agreement(a, b):
    if a is None or b is None:
        return "unknown"
    return "agree" if a == b else "conflict"


def _place(b, e):
    """City/district comparison. A city on one side equal to the district on the
    other counts as agreement: sources disagree about which level they record."""
    b_places = {p for p in (b["city"], b["district"]) if p}
    e_places = {p for p in (e["city"], e["district"]) if p}
    if not b_places or not e_places:
        return "unknown"
    return "agree" if b_places & e_places else "conflict"


def _best_name(b, e):
    best = ("none", "name_missing", False)
    for bi, b_name in enumerate(b["names"]):
        for ei, e_name in enumerate(e["names"]):
            level, detail = name_evidence(b_name, e_name)
            via_alias = bi > 0 or ei > 0
            if (LEVEL[level], not via_alias) > (LEVEL[best[0]], not best[2]):
                best = (level, detail, via_alias)
    return best


def pair_signals(b, e, policy, phone_counts, config):
    level, detail, via_alias = _best_name(b, e)
    signals = {
        "name_level": level, "name_detail": detail, "name_via_alias": via_alias,
        "state": _agreement(b["state"], e["state"]), "place": _place(b, e),
        "pin": _agreement(b["pin"], e["pin"]),
        "distance_m": None, "distance_band": "unknown", "distance_if_base_axes_swapped_m": None,
        "address_shared_tokens": len(b["address"] & e["address"]),
        "address_jaccard": None, "address": "unknown", "phone_match": False, "phone_switchboard": False,
        "identifiers": [], "identifier_disagrees": [],
        "external_type": e["type"], "external_source_key": e["source_key"],
        "non_hospital_type": e["type"] in NON_HOSPITAL_TYPES,
    }
    if b["address"] and e["address"]:
        signals["address_jaccard"] = round(len(b["address"] & e["address"]) / len(b["address"] | e["address"]), 3)
        # Agreement only; a different address wording is not treated as a conflict.
        if signals["address_shared_tokens"] >= 2 and signals["address_jaccard"] >= 0.8:
            signals["address"] = "agree"
    if b["coord"]["usable"] and e["coord"]["usable"]:
        d = haversine_m(b["coord"]["lat"], b["coord"]["lon"], e["coord"]["lat"], e["coord"]["lon"])
        signals["distance_m"] = round(d, 1)
        signals["distance_band"] = ("same_site" if d <= config["same_site_m"] else "near" if d <= config["near_m"]
                                    else "area" if d <= config["area_m"] else "far" if d > config["far_m"] else "region")
    proposed = b["coord"]["proposed"]
    if proposed and e["coord"]["usable"]:
        signals["distance_if_base_axes_swapped_m"] = round(
            haversine_m(proposed["latitude"], proposed["longitude"], e["coord"]["lat"], e["coord"]["lon"]), 1)
    shared_phones = b["phones"] & e["phones"]
    if shared_phones:
        signals["phone_match"] = True
        signals["phone_switchboard"] = any(
            phone_counts["base"][p] >= config["switchboard_min"] or phone_counts["external"][p] >= config["switchboard_min"]
            for p in shared_phones)
    for namespace in sorted(policy):
        binding = policy[namespace]
        if e["source_key"] not in binding["source_keys"]:
            continue
        bv, ev = field_value(b["row"], binding["base_field"]), field_value(e["row"], binding["external_field"])
        if bv is None or ev is None:
            continue
        (signals["identifiers"] if str(bv) == str(ev) else signals["identifier_disagrees"]).append(namespace)
    return signals


def retained(signals, config):
    """The retrieval rule: is this pair worth showing to a reviewer?"""
    s = signals
    geo_support = (s["pin"] == "agree" or s["place"] == "agree" or s["address"] == "agree"
                   or s["distance_band"] in ("same_site", "near"))
    close = s["distance_band"] in ("same_site", "near", "area")
    if s["identifiers"]:
        return "identifier"
    if s["phone_match"] and not s["phone_switchboard"]:
        return "phone"
    level = LEVEL[s["name_level"]]
    if level >= 2:
        if s["state"] == "conflict" and not (s["pin"] == "agree" or close):
            return None
        return "name"
    if level == 1 and geo_support:
        return "weak_name_with_geography"
    if s["phone_match"] and level >= 1:
        return "switchboard_with_name"
    if (config["proximity_only_m"] > 0 and s["distance_m"] is not None
            and s["distance_m"] <= config["proximity_only_m"]):
        return "proximity_only"
    return None


def flags_for(signals, reason):
    s, flags = signals, []
    if reason == "proximity_only":
        flags.append("proximity_only")
    if s["name_detail"] == "acronym_only":
        flags.append("acronym_only")
    if s["name_detail"] in ("generic_name_equal", "generic_name"):
        flags.append("generic_name")
    if s["name_via_alias"]:
        flags.append("matched_via_alias")
    geo_known = [s[k] for k in ("state", "place", "pin", "address")]
    if all(v == "unknown" for v in geo_known) and s["distance_m"] is None:
        flags.append("geography_unknown")
    if s["distance_m"] is None:
        flags.append("distance_unavailable")
    if s["state"] == "conflict":
        flags.append("state_conflict")
    if s["place"] == "conflict":
        flags.append("place_conflict")
    if s["pin"] == "conflict":
        flags.append("pin_conflict")
    if s["distance_band"] == "far":
        flags.append("coordinates_far_apart")
    if s["phone_match"]:
        flags.append("shared_switchboard" if s["phone_switchboard"] else "phone_match")
    if s["identifier_disagrees"]:
        flags.append("identifier_disagrees")
    if s["non_hospital_type"]:
        flags.append("non_hospital_type")
    if LEVEL[s["name_level"]] >= 2 and "geography_unknown" in flags:
        flags.append("name_only")
    return flags


def rank_key(candidate):
    s = candidate["signals"]
    conflicts = sum(s[k] == "conflict" for k in ("state", "place", "pin")) + (s["distance_band"] == "far")
    agreements = sum(s[k] == "agree" for k in ("state", "place", "pin", "address"))
    return (-len(s["identifiers"]), -LEVEL[s["name_level"]], conflicts, -agreements,
            s["distance_m"] if s["distance_m"] is not None else float("inf"),
            -(s["address_shared_tokens"]), candidate["external_facility_id"])


def generate(bases, externals, policy=None, config=None):
    """Return candidates sorted by (facility_id, rank). Deterministic for a given input."""
    policy, config = policy or {}, settings(config)
    index = ExternalIndex(externals, policy, config)
    phone_counts = {"base": Counter(p for b in bases for p in b["phones"]),
                    "external": Counter(p for e in externals for p in e["phones"])}
    per_base, external_bases, external_serious = {}, defaultdict(set), defaultdict(set)
    for b in sorted(bases, key=lambda v: v["id"]):
        found = []
        for i in index.block(b, policy):
            e = externals[i]
            signals = pair_signals(b, e, policy, phone_counts, config)
            reason = retained(signals, config)
            if reason is None:
                continue
            found.append({"facility_id": b["id"], "external_facility_id": e["id"], "signals": signals,
                          "retrieval_reason": reason, "flags": flags_for(signals, reason)})
        found.sort(key=rank_key)
        serious = [c for c in found if _serious(c)]
        for c in found:
            external_bases[c["external_facility_id"]].add(b["id"])
            if _serious(c):
                external_serious[c["external_facility_id"]].add(b["id"])
        kept = [c for position, c in enumerate(found) if position < config["top_k"] or c["signals"]["identifiers"]]
        for position, c in enumerate(kept):
            c["rank"] = position + 1
            c["candidates_found_for_base"] = len(found)
            c["candidates_kept_for_base"] = len(kept)
            c["other_candidates_for_base"] = len(found) - 1
            c["other_serious_candidates_for_base"] = len(serious) - (1 if _serious(c) else 0)
        per_base[b["id"]] = kept
    out = []
    for fid in sorted(per_base):
        for c in per_base[fid]:
            # Counted before the per-base cut, so a hidden competing campus still blocks auto-confirmation.
            ext = c["external_facility_id"]
            c["other_bases_for_external"] = len(external_bases[ext]) - 1
            c["other_serious_bases_for_external"] = len(external_serious[ext] - {fid})
            if _serious(c) and (c["other_serious_candidates_for_base"] or c["other_serious_bases_for_external"]):
                c["flags"].append("ambiguous_campus")
            out.append(c)
    return out


def _serious(candidate):
    """A candidate that could plausibly be the same campus by name, identifier or direct phone."""
    s = candidate["signals"]
    return bool(s["identifiers"]) or LEVEL[s["name_level"]] >= 2 or (s["phone_match"] and not s["phone_switchboard"])
