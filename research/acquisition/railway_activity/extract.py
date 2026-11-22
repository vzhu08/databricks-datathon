"""Replay hash-bound PDF tables and reviewed spans without inferring services.

Profiles contain real source text and therefore belong in private storage.
Page numbers are one-based; row/column/span indexes are zero-based.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def compact(text):
    return " ".join(text.split())


def logical_rows(table, start, width):
    """Remove only PDF merged-cell placeholders, never empty source cells."""
    rows = [[cell for cell in row if cell is not None] for row in table[start:]]
    require(all(len(row) == width for row in rows), "table shape changed")
    return rows


def metric(raw, kind):
    if kind == "equipment_shortfall" and compact(raw) == "NS":
        return {"value": 0, "value_semantics": "no_shortfall", "unit": "equipment_shortfall_count"}
    require(bool(re.fullmatch(r"\d+", compact(raw))), "unrecognized numeric cell")
    require(kind in {"equipment_shortfall", "bed_inventory"}, "unsupported table metric")
    return {"value": int(compact(raw)), "value_semantics": kind,
            "unit": "equipment_shortfall_count" if kind == "equipment_shortfall" else "beds"}


def observation(source, locator, campus, zone, measure, raw, **details):
    require(set(details) <= {"value", "value_semantics", "unit", "scope_wording", "delivery_scope",
                            "clinical_service", "reported_period_raw", "quantity_uniqueness",
                            "aggregate_relationship", "condition"}, "unexpected observation override")
    require(details.get("clinical_service") in {None, "mri", "dialysis", "trauma_care"}, "unknown service")
    identity = [source["sha256"], locator, campus, measure]
    result = {"observation_id": "railway-observation:" + digest(canonical(identity)),
              "source_campus_key": "railway-campus:" + digest(canonical([source["sha256"], zone, campus])),
              "edition_id": source["edition_id"], "raw_sha256": source["sha256"],
              "source_url": source["url"], "source_family": source["source_family"],
              "upstream_origin_family": source["upstream_origin_family"],
              "published_date": source["published_date"], "report_period": source["report_period"],
              "observation_date": None, "record_locator": locator, "campus_raw": campus,
              "zone_raw": zone, "measure": measure, "raw_value_or_excerpt": raw,
              "temporal_status": "historical", "delivery_scope": "not_established",
              "clinical_service": None, "current_service_eligible": False,
              "vf_link_status": "unreviewed", "review_required": ["campus_link", "currentness", "clinical_scope"]}
    result.update(details)
    # This acquisition producer is deliberately unable to grant a current status.
    return result


def extract_profile(pdf_path, profile):
    import pdfplumber

    require(profile["parser"] == {"name": "pdfplumber", "version": pdfplumber.__version__}, "parser version changed")
    source = profile["source"]
    raw = Path(pdf_path).read_bytes()
    require(digest(raw) == source["sha256"], "PDF hash differs from reviewed edition")
    require(source["sharing_permission"] == "accurate_attributed_reproduction", "source terms not cleared")
    observations, cells = [], []
    with pdfplumber.open(pdf_path) as pdf:
        require(len(pdf.pages) == profile["page_count"], "PDF page count changed")
        for spec in profile.get("tables", []):
            page = pdf.pages[spec["page"] - 1]
            text = compact(page.extract_text() or "")
            require(all(anchor in text for anchor in spec["anchors"]), "table title/legend changed")
            table = page.extract_tables()[spec["table"]]
            rows = logical_rows(table, spec["start_row"], spec["width"])
            require(len(rows) == spec["row_count"], "table row count changed")
            for i, row in enumerate(rows):
                require(all(isinstance(v, str) for v in row), "invalid source cell")
                locator = f"pdf:page={spec['page']};table={spec['table']};row={spec['start_row'] + i}"
                zone = row[spec["zone_column"]]
                for m in spec["metrics"]:
                    raw_cell = row[m["column"]]
                    loc = locator + f";logical_column={m['column']}"
                    cells.append({"edition_id": source["edition_id"], "locator": loc, "zone_raw": zone,
                                  "raw_row": row, "raw_cell": raw_cell, "measure": m["measure"]})
                    if m["kind"] == "deficiency_list":
                        # NA and literal 0 describe this list, not service absence or presence.
                        if compact(raw_cell) in {"NA", "0"}:
                            continue
                        names = [name.strip() for name in raw_cell.split(",") if name.strip()]
                        require(names and all("/" in name for name in names), "ambiguous deficiency list")
                        for j, name in enumerate(names):
                            observations.append(observation(source, loc + f";mention={j}", name, zone,
                                m["measure"], raw_cell, value=None, value_semantics="scoped_deficiency",
                                unit=None, scope_wording=m["scope_wording"], delivery_scope=m["delivery_scope"]))
                    else:
                        campus = row[spec["campus_column"]]
                        observations.append(observation(source, loc, campus, zone, m["measure"], raw_cell,
                                                        **metric(raw_cell, m["kind"])))
        for spec in profile.get("spans", []):
            text = compact(pdf.pages[spec["page"] - 1].extract_text() or "")
            start, end = spec["start"], spec["end"]
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(text), "invalid span")
            require(text[start:end] == spec["excerpt"], "reviewed span changed")
            for i, item in enumerate(spec["observations"]):
                require(item["unit"] and item["measure"], "span requires unit and measure")
                require(type(item["value"]) is int and item["value"] >= 0, "invalid span quantity")
                # The reviewer supplies semantics; the numeric token must also occur in this exact span.
                token = item.get("value_token", str(item["value"]))
                require(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", spec["excerpt"]), "span quantity absent")
                details = {k: v for k, v in item.items() if k not in {"campus", "zone", "measure", "value_token"}}
                observations.append(observation(source,
                    f"pdf:page={spec['page']};normalized_span={start}:{end};measure={i}",
                    item["campus"], item["zone"], item["measure"], spec["excerpt"], **details))
    counts = dict(Counter(o["measure"] for o in observations))
    require(counts == profile["expected_measure_counts"], "observation census does not reconcile")
    require(len({o["observation_id"] for o in observations}) == len(observations), "duplicate observation locator")
    return {"source": source, "cells": cells, "observations": observations,
            "counts": {"source_cells": len(cells), "source_spans": len(profile.get("spans", [])),
                       "observations": len(observations), "by_measure": counts,
                       "source_campus_strings": len({o["source_campus_key"] for o in observations})}}
