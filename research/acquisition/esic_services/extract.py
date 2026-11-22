"""Extract a complete, pinned five-column hospital/service annexure.

This is a research sidecar, not a service decision producer. It preserves raw
cells and source spans; it neither confirms identity nor infers current care.
Run with --help. Source-specific names and dates belong in the private edition
configuration, not in synthetic tests or the public repository.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

VERSION = "esic-services-1.0.1"


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   indent=2, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fold(text):
    return re.sub(r"\s+", " ", text or "").strip()


def stitch(pages, expected_rows):
    """Accept (one-based PDF page, table rows); fail closed on layout drift.

    The last service cell can continue on the next page. State headings are
    merged across five columns. Neither a heading nor a blank continuation
    creates a hospital, and all original cell fragments remain available.
    """
    records, state = [], None
    for page, table in pages:
        for cells in table:
            if len(cells) != 5:
                raise ValueError("Expected exactly five columns")
            first = fold(cells[0])
            if first in {"Sl. No.", "Sl.No."}:
                continue
            if first and all(v is None for v in cells[1:]):
                state = first
                continue
            if re.fullmatch(r"\d+\.?", first):
                serial = int(first.rstrip("."))
                if serial != len(records) + 1 or not state:
                    raise ValueError("Missing, repeated, out-of-order row or missing state")
                if not all(isinstance(v, str) and v.strip() for v in cells):
                    raise ValueError("Required source cell missing")
                if not re.fullmatch(r"\d+", cells[2]) or not re.fullmatch(r"\d+(?:\.\d+)?", cells[3]):
                    raise ValueError("Unrecognised capacity or occupancy cell")
                records.append({"serial": serial, "state_original": state,
                                "name_original": cells[1],
                                "sanctioned_beds_original": cells[2],
                                "occupancy_original": cells[3],
                                "fragments": [{"pdf_page": page, "cells": cells}],
                                "services_original": cells[4]})
            elif all(not fold(v) for v in cells[:4]) and fold(cells[4]):
                if not records:
                    raise ValueError("Orphan continuation")
                records[-1]["fragments"].append({"pdf_page": page, "cells": cells})
                records[-1]["services_original"] += "\n" + cells[4]
            else:
                raise ValueError("Unrecognised table row; inspect PDF before continuing")
    if len(records) != expected_rows:
        raise ValueError("Annexure row count differs from declared scope")
    return records


# These are literal lexical observations. In particular MRI is not inferred
# from Radiology, dialysis from Nephrology, or trauma care from ICU/orthopaedics.
PATTERNS = {
    "dialysis": r"\b(?:ha?emodialysis|dialysis)\b",
    "mri": r"\bMRI\b|\bmagnetic\s+resonance(?:\s+imaging)?\b",
    "trauma_mention": r"\btrauma(?:\s*(?:&|and)\s*emergency)?\b",
    "ct": r"\bCT(?:\s+Scan)?\b|\bcomputed\s+tomography\b",
    "emergency": r"\b(?:emergency(?:\s+(?:medicine|services))?|casualty|causality)\b",
    "emergency_surgery": r"\bemergency\s+(?:surgery|OT)\b",
    "orthopaedics": r"\b(?:orthop(?:ae|e)dic\w*|ortho)\b",
    "neurosurgery": r"\bneuro[ -]?surgery\b",
    "icu": r"\b(?:(?:medical|surgical|respiratory|emergency)\s+)?[MSR]?ICU\b|\bcritical\s+care\b",
    "neonatal_icu": r"\bNICU\b|\bneonatal\s+(?:ICU|intensive\s+care)\b",
    "paediatric_icu": r"\bPICU\b|\bpa?ediatric\s+(?:ICU|intensive\s+care)\b",
    "hdu": r"\bHDU\b|\bhigh\s+dependency\s+unit\b",
    "ventilation": r"\b(?:ventilator\w*|ventilation)\b",
    "blood_bank": r"\bblood\s*(?:bank|cent(?:er|re))\b",
    "blood_storage": r"\bblood\s+storage(?:\s+(?:unit|facility))?\b",
    "transfusion_medicine": r"\btransfusion\s+medicine\b",
    "burns": r"\bburns?\b",
    "paediatrics": r"\bpa?ediatrics?\b",
    "paediatric_surgery": r"\bpa?ediatric\s+surgery\b",
    "transfer_referral": r"\b(?:referral(?:\s+services)?|ambulance(?:\s+services)?)\b",
    "operation_theatre": r"\b(?:OT|O\.T\.?|operation\s+theat(?:re|er)s?|operating\s+theat(?:re|er)s?)\b",
    "general_surgery": r"\b(?:general|gen\.?)\s+surgery\b",
    "cathlab": r"\bcath[ -]?lab\b",
    "nephrology": r"\bnephrology\b",
    "urology": r"\burology\b",
    "neurology": r"\bneurology\b",
    "cardiology": r"\bcardiology\b",
    "plastic_surgery": r"\bplastic(?:\s+and\s+reconstructive)?\s+surgery\b",
    "oncology": r"\b(?:oncology|oncosurgery|chemotherapy)\b",
    "radiology_unspecified": r"\b(?:radiology|radio[ -]?diagnosis|radiodiagnosis)\b",
}


def observe(record):
    """Return every lexical hit with exact offsets, keeping repeats auditable."""
    text = record["services_original"]
    observations = []
    for service, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text, re.I):
            # Comma/semicolon boundaries limit qualifiers to the printed item.
            left = max(text.rfind(",", 0, match.start()), text.rfind(";", 0, match.start())) + 1
            ends = [pos for sep in (",", ";") if (pos := text.find(sep, match.end())) >= 0]
            right = min(ends, default=len(text))
            context = text[left:right]
            planned = bool(re.search(r"\b(?:planned|proposed|required|tender|to be set up)\b", context, re.I))
            referral_only = bool(re.search(r"\b(?:referred|referral|tie[ -]?up)\b", context, re.I))
            ppp = bool(re.search(r"\bPPP\b", context))
            # A lexical mention cannot establish onsite provision when negated.
            negated = bool(re.search(r"\b(?:no|not|unavailable|without|excluded)\b", context, re.I))
            # An exception introduces the following mentions in the same item.
            excluded = bool(re.search(r"\b(?:except(?:ing)?|excluding|other\s+than)\b",
                                      text[left:match.start()], re.I))
            status = "planned" if planned else "negation_review" if negated or excluded else "referral_review" if referral_only else "reported_available"
            onsite = "source_table_reports_in_hospital" if status == "reported_available" else "not_established"
            observations.append({"observation_id": f"{record['record_id']}:{service}:{match.start()}",
                "record_id": record["record_id"], "service": service,
                "mention_original": match.group(), "start": match.start(), "end": match.end(),
                "context_original": context, "context_start": left, "context_end": right,
                "availability": status,
                "operator": "PPP_partner_unspecified" if ppp else "not_separately_specified",
                "onsite": onsite,
                "quantity": None, "unit": None,
                "quantity_reason": "No equipment count inferred from service wording or other columns",
                "current_service_decision": "unconfirmed",
                "source_family": record["source_family"],
                "publication_date": record["publication_date"],
                "service_observation_date": None,
                "date_basis": "service field undated within dated return",
                "temporal_status": "historical_report",
                "locator": record["locator"]})
    return sorted(observations, key=lambda row: (row["start"], row["service"]))


def extract(pdf_path, config, output):
    import pdfplumber  # Optional dependency only for the PDF acquisition lane.
    if sha(pdf_path) != config["sha256"]:
        raise ValueError("PDF digest differs from pinned edition")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite an existing edition")
    with pdfplumber.open(pdf_path) as pdf:
        pages = []
        for number in config["pdf_pages"]:
            tables = pdf.pages[number - 1].extract_tables()
            if len(tables) != 1:
                raise ValueError("Expected one table per annexure page")
            pages.append((number, tables[0]))
    records = stitch(pages, config["expected_rows"])
    names = config["normalized_names"]
    if set(names) != {str(row["serial"]) for row in records}:
        raise ValueError("Name normalization must cover exactly the annexure rows")
    observations, mentions = [], []
    for row in records:
        serial = str(row["serial"])
        row.update(record_id=f"{config['edition_id']}:row-{serial}",
                   name_normalized=names[serial],
                   normalization_method="reviewed PDF line-wrap repair; source name retained",
                   state_normalized=config.get("state_aliases", {}).get(row["state_original"], row["state_original"]),
                   source_family=config["source_family"], source_url=config["url"],
                   publication_date=config["publication_date"],
                   sanctioned_beds_date=config["sanctioned_beds_date"],
                   occupancy_period=config["occupancy_period"],
                   address_original=None, city=None, pin=None, latitude=None, longitude=None,
                   campus_id=None, reuse_status=config["reuse_status"],
                   locator={"annexure": config["annexure"], "serial": row["serial"],
                            "pdf_pages": [part["pdf_page"] for part in row["fragments"]]})
        # Keep all source wording, including vocabulary outside PATTERNS. These
        # are delimiter fragments, NOT a claim that each fragment is one service.
        for match in re.finditer(r"[^,;]+", row["services_original"]):
            if match.group().strip():
                mentions.append({"record_id": row["record_id"], "start": match.start(),
                                 "end": match.end(), "text_original": match.group()})
        observations.extend(observe(row))
    report = {"parser_version": VERSION, "edition_id": config["edition_id"],
              "source_rows": len(records), "states": dict(Counter(r["state_normalized"] for r in records)),
              "cross_page_rows": sum(len(r["fragments"]) > 1 for r in records),
              "raw_service_cells": len(records), "raw_delimiter_fragments": len(mentions),
              "recognized_mentions": len(observations),
              "unique_row_service_pairs": len({(r["record_id"], r["service"]) for r in observations}),
              "by_service_mentions": dict(Counter(r["service"] for r in observations)),
              "by_service_rows": {s: len({r["record_id"] for r in observations if r["service"] == s}) for s in PATTERNS},
              "independent_families": 1, "source_editions": 1,
              "approved_campus_service_pairs": 0, "current_yes": 0, "current_no": 0,
              "reuse_status": config["reuse_status"]}
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("records", records), ("mentions", mentions), ("observations", observations),
                        ("report", report), ("edition", config)):
        dump(output / f"{name}.json", value)
    dump(output / "manifest.json", {"parser_version": VERSION, "source_sha256": sha(pdf_path),
         "files": [{"path": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
                   for p in sorted(output.glob("*.json"))]})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = extract(args.pdf, json.loads(args.config.read_text()), args.output)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
