"""Reconcile a national VF pharmacy cohort with a private outlet directory and reviewed links."""

import argparse
from collections import Counter, defaultdict
import csv
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from research.matching.normalize import fold, state_key


GENERIC = set(
    (
        "district general government govt civil city hospital hospitals healthcare health care centre center "
        "medical college research institute university nursing home community public private limited super "
        "specialty speciality multispeciality multispecialty trust branch maternity clinic clinics teaching "
        "eye child childrens women and the of for state national municipal central dental new"
    ).split()
)
FACILITY = {"hospital", "clinic", "centre", "college", "institute", "home"}
ALIASES = {
    "hospitals": "hospital",
    "hosp": "hospital",
    "clinics": "clinic",
    "center": "centre",
    "centers": "centre",
    "centres": "centre",
    "govt": "government",
    "pvt": "private",
    "ltd": "limited",
    "rd": "road",
    "opp": "opposite",
    "nr": "near",
    "sant": "saint",
    "st": "saint",
}
NEAR = r"(?:near(?:by)?|next to|opposite(?: to)?|opposit(?:e)?|opp(?:osite)? to|across from|beside|adjacent to|outside|behind|in front of)"
INSIDE = r"(?:inside|within|in|at|campus of|premises of)"
END_NEAR = re.compile(r"\b" + NEAR + r"(?: the)?$")
END_INSIDE = re.compile(r"\b" + INSIDE + r"(?: the)?$")
DISPOSITIONS = {"on_premises", "nearby", "ambiguous", "different_facility"}
BRAND_STOP = GENERIC | set(
    (
        "shri sri sree sai central charitable memorial international specialized foundation cancer "
        "kidney heart skin diagnostic diagnostics blood bank pharmacy orthopaedic orthopedic doctor "
        "dr advance advanced ayurveda ayurvedic womens emergency"
    ).split()
)


def normalized(text):
    raw = fold(text) or ""
    raw = re.sub(r"\b(?:[a-z] ){1,}[a-z]\b", lambda m: m[0].replace(" ", ""), raw)
    return " ".join(ALIASES.get(t, t) for t in raw.split())


def name_forms(raw):
    full = normalized(raw)
    parts = []
    for val in (full, normalized(re.split(r"[,|(]|\s[-–—]\s", raw or "", maxsplit=1)[0])):
        if val and val not in parts:
            parts.append(val)
        tokens = val.split()
        for i, token in enumerate(tokens):
            if token in FACILITY and i:
                short = " ".join(tokens[: i + 1])
                if short not in parts:
                    parts.append(short)
                break
    return [
        p
        for p in parts
        if len(p) >= 7
        and len(p.split()) >= 2
        and any(t not in GENERIC and len(t) >= 3 and not t.isnumeric() for t in p.split())
    ]


def classify_words(before, after):
    before, after = before.strip(), after.strip()
    if re.match(r"^(?:road|street|lane|marg)\b", after):
        return "name_only"
    # An address can be near one institution and inside another. Require the cue to attach to this name.
    if (
        END_NEAR.search(before)
        or re.search(r"\b(back side|oppo|besides)\s*$", before)
        or re.search(
            r"\b(?:beside|besides|near) the (?:radiology|emergency) (?:dept|department) of (?:the )?$",
            before + " ",
        )
        or re.match(r"^(?:ke samne|ke saamne|opposite side|ke paas|ke pass)\b", after)
    ):
        return "nearby"
    if END_INSIDE.search(before) or re.match(
        r"^(?:campus|premises|compound|ipd block|(?:shop (?:at |on )?)?ground floor)\b", after
    ):
        return "on_premises"
    return "name_only"


def name_match(forms, addr):
    text = f" {addr} "
    for i, name in enumerate(forms):
        target = f" {name} "
        index = text.find(target)
        if index >= 0:
            before, after = text[:index], text[index + len(target) :]
            return ("full_name" if i == 0 else "short_name", name, classify_words(before, after))
    # A single small spelling difference can produce a review lead only when a facility word also matches.
    terms = addr.split()
    for name in forms:
        words = name.split()
        if len(words) > 7 or not (FACILITY & set(words)):
            continue
        n = len(words)
        for i in range(len(terms) - n + 1):
            part = terms[i : i + n]
            diffs = [(a, b) for a, b in zip(words, part) if a != b]
            if len(diffs) != 1 or not (FACILITY & set(words) & set(part)):
                continue
            a, b = diffs[0]
            if a in GENERIC or b in GENERIC or min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
                continue
            if SequenceMatcher(None, a, b, autojunk=False).ratio() < 0.84:
                continue
            return (
                "spelling_variant",
                " ".join(part),
                classify_words(" ".join(terms[:i]), " ".join(terms[i + n :])),
            )
    return None


def brand_match(stem, terms, frequency):
    if (
        not stem
        or not any(len(t) >= 4 and frequency[t] <= 15 for t in stem)
        or not set(stem) <= set(terms)
    ):
        return None
    positions = [i for i, t in enumerate(terms) if t in stem]
    first, last = min(positions), max(positions)
    nouns = [i for i in range(max(0, first - 3), min(len(terms), last + 4)) if terms[i] in FACILITY]
    if not nouns or last - first > 7:
        return None
    noun = min(nouns, key=lambda i: min(abs(i - j) for j in positions))
    start, end = min(first, noun), max(last, noun) + 1
    return (
        "distinctive_brand_and_institution",
        " ".join(terms[start:end]),
        classify_words(" ".join(terms[:start]), " ".join(terms[end:])),
    )


def pin(value):
    text = str(value or "").strip()
    return text if re.fullmatch(r"[1-9]\d{5}", text) else None


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read_lines(path):
    with path.open(encoding="utf-8-sig") as stream:
        yield from map(json.loads, stream)


def write_lines(path, rows):
    with path.open("w", encoding="utf8", newline="\n") as stream:
        for row in rows:
            print(json.dumps(row, sort_keys=True, ensure_ascii=False), file=stream)


def file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def edition_rows(vf_path, outlet_path, expected):
    if file_sha(outlet_path) != expected:
        raise ValueError(
            "The contact-filtered outlet projection did not match the expected edition"
        )
    vf = list(read_lines(vf_path))
    with outlet_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        allowed = {
            "kendra_code",
            "state_ut",
            "district",
            "pin",
            "address",
            "source_serial",
            "pdf_page",
        }
        if not {"kendra_code", "state_ut", "district", "pin", "address"} <= set(
            reader.fieldnames or []
        ):
            raise ValueError("Missing outlet columns")
        # Project only the approved location fields even if additional CSV columns exist.
        outlets = [{k: v for k, v in row.items() if k in allowed} for row in reader]
    if len({r["occurrence_key"] for r in vf}) != len(vf):
        raise ValueError("Repeated VF occurrence key")
    if not all(r["kendra_code"] for r in outlets) or len(
        {r["kendra_code"] for r in outlets}
    ) != len(outlets):
        raise ValueError("Missing or duplicated outlet code")
    return vf, outlets


def candidate_rows(vf, outlets):
    by_pin = defaultdict(list)
    frequency = Counter()
    for outlet in outlets:
        p = pin(outlet["pin"])
        if p:
            addr = normalized(outlet["address"])
            terms = addr.split()
            by_pin[state_key(outlet["state_ut"]), p].append((outlet, addr, terms))
            frequency.update(set(terms))
    postal = set()
    leads = []
    for occ in vf:
        raw = occ["original_payload"]
        key = occ["occurrence_key"]
        state = state_key(occ["state"])
        p = pin(raw.get("address_zipOrPostcode"))
        block = by_pin.get((state, p), ())
        if block:
            postal.add(key)
        forms = name_forms(raw.get("name"))
        stop = (
            BRAND_STOP
            | set(normalized(raw.get("address_city")).split())
            | set(normalized(occ["state"]).split())
        )
        stem = [
            t
            for t in normalized(raw.get("name")).split()
            if len(t) >= 3 and not t.isnumeric() and t not in stop
        ]
        for outlet, addr, terms in block:
            match = name_match(forms, addr) or brand_match(stem, terms, frequency)
            if not match:
                continue
            variant, alias, cue = match
            record = {
                "occurrence_key": key,
                "outlet_code": outlet["kendra_code"],
                "vf_name": raw.get("name"),
                "vf_city": raw.get("address_city"),
                "vf_address": [raw.get(f"address_line{i}") for i in (1, 2, 3)],
                "outlet_district": outlet["district"],
                "outlet_address": outlet["address"],
                "same_state_and_pin": True,
                "alias_basis": variant,
                "matched_words": alias,
                "wording": cue,
            }
            record["review_key"] = sha(
                json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
            )
            leads.append(record)
    if len({r["review_key"] for r in leads}) != len(leads):
        raise ValueError("Duplicate candidate key")
    return postal, leads


def build(vf, prior, postal, candidates, reviews):
    keys = {r["occurrence_key"] for r in vf}
    if len(prior) != len(keys) or set(prior) != keys:
        raise ValueError("Pharmacy baseline and VF keys differ")
    decisions = {}
    for r in reviews:
        if (
            r["review_key"] in decisions
            or r["disposition"] not in DISPOSITIONS
            or not r.get("reason")
        ):
            raise ValueError("Invalid or duplicate reviewed link")
        decisions[r["review_key"]] = r
    if set(decisions) - {r["review_key"] for r in candidates}:
        raise ValueError("Reviewed link differs from the current evidence")
    links = defaultdict(set)
    operator = set()
    premises = set()
    for r in candidates:
        decision = decisions.get(r["review_key"], {})
        d = decision.get("disposition", "ambiguous")
        primary = (
            decision.get("onsite_basis") == "named_premises_and_operator_pharmacy"
            and str(decision.get("operator_url", "")).startswith("https://")
            and r["wording"] == "name_only"
        )
        cited = normalized(decision.get("shared_civic_phrase"))
        shared_address = (
            r["wording"] == "name_only"
            and len(cited.split()) >= 3
            and re.search(r"\b\d+\b", cited)
            and f" {cited} " in f" {normalized(r['outlet_address'])} "
            and any(f" {cited} " in f" {normalized(v)} " for v in r["vf_address"])
        )
        clause = normalized(decision.get("premises_clause"))
        branch_terms = set(normalized(r["vf_name"]).split()) - GENERIC
        premises_clause = (
            r["wording"] == "name_only"
            and len(clause.split()) >= 4
            and branch_terms.intersection(clause.split())
            and re.search(r"\b(?:inside|campus|premises|shop at ground floor)\b", clause)
            and not re.search(r"\b(?:near|opposite|beside|on the road)\b", clause)
            and f" {clause} " in f" {normalized(r['outlet_address'])} "
        )
        if (d == "nearby" and r["wording"] != "nearby") or (
            d == "on_premises"
            and r["wording"] != "on_premises"
            and not (primary or shared_address or premises_clause)
        ):
            raise ValueError("Positive review requires explicit wording about this hospital")
        if primary and d == "on_premises":
            operator.add(r["occurrence_key"])
        if (shared_address or premises_clause) and d == "on_premises":
            premises.add(r["occurrence_key"])
        links[r["occurrence_key"]].add(d)
    rows = []
    for r in vf:
        k = r["occurrence_key"]
        ds = links[k]
        b = prior[k]
        onsite = []
        if b["previous_external_pharmacy_support"]:
            onsite.append("prior_external_pharmacy")
        if "on_premises" in ds:
            onsite.append(
                "reviewed_named_outlet_and_operator"
                if k in operator
                else (
                    "reviewed_matching_named_premises"
                    if k in premises
                    else "reviewed_outlet_on_premises"
                )
            )
        near = ["reviewed_outlet_nearby"] if "nearby" in ds else []
        families = set(b.get("prior_source_families", []))
        if not b["previous_external_pharmacy_support"] and families:
            raise ValueError("Unexpected baseline source")
        if set(ds) & {"on_premises", "nearby"}:
            families.add("pmbi")
        if k in operator:
            families.add("hospital_operator")
        rows.append(
            {
                "occurrence_key": k,
                "upstream_id": r["upstream_id"],
                "vf_mentions_pharmacy": b["vf_mentions_pharmacy"],
                "onsite_supported": bool(onsite),
                "nearby_supported": bool(near),
                "ambiguous": "ambiguous" in ds or bool(b.get("prior_branch_unresolved")),
                "onsite_basis": onsite,
                "nearby_basis": near,
                "source_families": sorted(families),
                "postal_area_only": k in postal and not (onsite or near),
            }
        )

    def totals(scope):
        return {
            "occurrences": len(scope),
            "onsite": sum(r["onsite_supported"] for r in scope),
            "nearby": sum(r["nearby_supported"] for r in scope),
            "both": sum(r["onsite_supported"] and r["nearby_supported"] for r in scope),
            "either": sum(r["onsite_supported"] or r["nearby_supported"] for r in scope),
            "ambiguous": sum(r["ambiguous"] for r in scope),
            "postal_area_only": sum(r["postal_area_only"] for r in scope),
        }

    return rows, {
        "all": totals(rows),
        "pharmacy_mentions": totals([r for r in rows if r["vf_mentions_pharmacy"]]),
        "distinct_upstream_ids": len({r["upstream_id"] for r in rows}),
        "reviewed_pairs": dict(
            sorted(Counter(r["disposition"] for r in decisions.values()).items())
        ),
        "unreviewed_candidate_pairs": len(candidates) - len(decisions),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("candidates", "build"))
    for arg in ("vf", "outlets", "output"):
        p.add_argument("--" + arg, type=Path, required=True)
    p.add_argument(
        "--prior", type=Path, help="Previous pharmacy evidence for each VF occurrence (build mode)"
    )
    p.add_argument("--outlet-sha256", required=True)
    p.add_argument("--reviews", type=Path)
    a = p.parse_args()
    if a.mode == "build" and not a.prior:
        p.error("--prior is required to build the national occurrence output")
    if a.output.exists():
        raise FileExistsError(a.output)
    vf, outlets = edition_rows(a.vf, a.outlets, a.outlet_sha256)
    postal, candidates = candidate_rows(vf, outlets)
    with TemporaryDirectory(dir=a.output.parent) as staging:
        temp = Path(staging) / "edition"
        temp.mkdir()
        if a.mode == "candidates":
            write_lines(temp / "candidates.jsonl", candidates)
        else:
            prior_rows = list(read_lines(a.prior))
            prior = {r["occurrence_key"]: r for r in prior_rows}
            if len(prior) != len(prior_rows):
                raise ValueError("Duplicate occurrence in prior")
            rows, summary = build(
                vf, prior, postal, candidates, read_lines(a.reviews) if a.reviews else []
            )
            write_lines(temp / "occurrences.jsonl", rows)
            summary["input_sha256"] = {
                k: file_sha(v)
                for k, v in vars(a).items()
                if k in {"vf", "outlets", "prior", "reviews"} and v
            }
            summary["occurrences_sha256"] = file_sha(temp / "occurrences.jsonl")
            (temp / "summary.json").write_text(
                json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf8"
            )
        if a.output.exists():
            raise FileExistsError(a.output)
        temp.rename(a.output)


if __name__ == "__main__":
    main()
