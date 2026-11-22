"""Hash-bound observations; equipment and operator totals are never service decisions."""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import re

from bs4 import BeautifulSoup

from research.acquisition.common import canonical, digest, envelope, file_digest, publish_json_directory
from research.mri.maharashtra.inventory import compile_inventory, find_inventory, inventory_date, value
from . import VERSION

KINDS = {"equipment_count", "commissioned", "onsite_reported", "planned", "reporting_only",
         "offsite", "unavailable", "closed", "aggregate_capacity", "unknown"}
MODALITIES = {"mri", "ct", "ct_mri", "reporting", "unknown"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def norm(text):
    return " ".join(text.split())


def stable(kind, *parts):
    return "imaging-" + kind + ":" + digest(canonical(parts))


def local(root, name):
    require(isinstance(name, str), "relative source path required")
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts, "source path escapes root")
    path = (Path(root) / relative).resolve()
    require(Path(root).resolve() in path.parents and path.is_file(), "source missing or outside root")
    return path


def checked_source(root, source):
    require(source["status"] == "ok", "failed source cannot emit observations")
    for key in ("key", "publisher", "source_family", "geography", "reuse_reason", "pursue_or_stop"):
        require(isinstance(source.get(key), str) and bool(source[key]), "missing source field: " + key)
    require(source["sharing_status"] in {"permitted_private", "restricted", "pending_review"}, "reuse disposition required")
    stamp = source["retrieved_at"]
    require(stamp.endswith("Z") and datetime.fromisoformat(stamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0,
            "UTC retrieval timestamp required")
    path = local(root, source["path"])
    require(file_digest(path) == source["sha256"], "raw source hash mismatch")
    return path


def snapshot(source):
    return dict(snapshot_id=stable("snapshot", source["key"], source["sha256"]),
                source_key=source["key"], publisher=source["publisher"], source_family=source["source_family"],
                url=source["url"], retrieved_at=source["retrieved_at"], published_date=source.get("published_date"),
                license=source["reuse_reason"], attribution=source["publisher"], sha256=source["sha256"],
                artifact_uri="urn:sha256:" + source["sha256"], parser_version=VERSION,
                independence_status="unassessed")


def bound_text(path, locator):
    if path.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(path) as doc:
            page = locator.get("page")
            require(type(page) is int and 1 <= page <= len(doc), "invalid PDF page")
            return norm(doc[page - 1].get_text())
    selector = locator.get("selector")
    require(isinstance(selector, str) and bool(selector), "HTML selector required")
    nodes = BeautifulSoup(path.read_bytes(), "html.parser").select(selector)
    require(len(nodes) == 1, "HTML locator must identify exactly one element")
    return norm(nodes[0].get_text(" ", strip=True))


def annotation_row(source, path, annotation):
    require(annotation["kind"] in KINDS and annotation["modality"] in MODALITIES, "unknown observation kind/modality")
    require(annotation["grain"] in {"campus", "campus_group", "operator_network", "jurisdiction"}, "unknown grain")
    require(annotation["subject"] and annotation["period"] and annotation["series_key"], "subject/period/series required")
    excerpt = norm(annotation["excerpt"])
    require(bool(excerpt) and excerpt in bound_text(path, annotation["locator"]), "excerpt not found at source locator")
    # A reviewed interpretation, not an automatic semantic assertion. Exact text
    # binding prevents invented citations; it cannot establish the interpretation.
    require(annotation.get("interpretation_reviewer") and annotation.get("interpretation_note"), "interpretation review required")
    sid = snapshot(source)["snapshot_id"]
    return {**annotation, "excerpt": excerpt, "observation_id": stable("observation", sid, annotation["key"]),
            "snapshot_id": sid, "source_key": source["key"], "source_sha256": source["sha256"],
            "source_family": source["source_family"], "originating_organization": source["publisher"],
            "lineage_status": "same_publisher_repeated_editions_not_independent",
            "published_date": source.get("published_date"), "retrieved_at": source["retrieved_at"],
            "sharing_status": source["sharing_status"], "vf_campus_join": "unreviewed",
            "current_service_decision": "unconfirmed"}


def campus_records(row, source):
    sid = row["snapshot_id"]
    xid = stable("external", sid, row["subject"], row["key"])
    loc = norm(str(row["locator"]))
    flags = ["unlinked_source_identity", "clinical_status_requires_campus_and_date_review", *row.get("flags", [])]
    ext = dict(external_facility_id=xid, snapshot_id=sid, source_record_id=row["key"], record_locator=loc,
               name_original=row["subject"], name_normalized=row["subject"].casefold(),
               address_original=row.get("address"), facility_type=row["grain"], city=row.get("city"),
               state=row.get("state"), pin=None, latitude=None, longitude=None, coordinate_method=None,
               quality_flags=flags)
    # The shared v1 contract has MRI, dialysis and trauma only. CT stays in the
    # observation ledger and contributes identity evidence, never trauma.
    service = "mri" if row["modality"] == "mri" else None
    ev = dict(evidence_id=stable("evidence", row["observation_id"]), external_facility_id=xid,
              snapshot_id=sid, facility_id=None, match_id=None, claim_type="service" if service else "identity",
              service=service, polarity="inconclusive", assertion=row["interpretation_note"],
              excerpt=row["excerpt"], observation=None, locator=loc, source_url=source["url"],
              effective_date=row.get("effective_date"), valid_until=row.get("valid_until"),
              temporal_status="historical" if row.get("effective_date") else "undated",
              reviewer=None, reviewed_at=None)
    review = dict(review_id=stable("review", row["observation_id"]), facility_id=None,
                  external_facility_id=xid, evidence_id=ev["evidence_id"], match_id=None,
                  reason_code="campus_date_modality_review", severity="medium", status="open", resolution=None,
                  next_action="Review the named campus, dates, modality and negation before any service decision.")
    return ext, ev, review


def dmer_rows(raw, receipt, batch):
    result = compile_inventory(raw, receipt)
    for table in batch:
        if isinstance(batch[table], list):
            batch[table].extend(result["batch.json"][table])
    soup = BeautifulSoup(raw, "html.parser")
    ti, table, trs, hi, labels, ni, _, _ = find_inventory(soup)
    ct = [i for i, x in enumerate(labels) if x in {"ct", "ct scan", "ct scan facility", "ct count"}]
    require(len(ct) == 1, "one CT equipment column required")
    observations = []
    for original, tr in zip(result["rows.json"], trs[hi + 1:]):
        # Compile_inventory handles malformed and repeated rows. Resolve by its
        # physical row locator rather than silently shifting those rows here.
        number = int(re.search(r"physical tr (\d+)", original["locator"])[1])
        cells = trs[number - 1].find_all(["td", "th"], recursive=False)
        aligned = len(cells) == len(labels) and all(c.get("rowspan", "1") == "1" and c.get("colspan", "1") == "1" for c in cells)
        raw_ct = value(cells[ct[0]]) if aligned else None
        count_ct = int(raw_ct) if raw_ct is not None and re.fullmatch(r"[0-9]+", raw_ct) else None
        for modality, count, raw_value in (("mri", original["count"], original["raw_value"]), ("ct", count_ct, raw_ct)):
            observations.append(dict(observation_id=stable("dmer-observation", receipt["sha256"], original["locator"], modality),
                source_key=receipt["key"], source_sha256=receipt["sha256"], source_family=receipt["source_family"],
                originating_organization=receipt["publisher"], lineage_status="publisher_inventory_origin_unassessed",
                subject=original["name"], grain="campus_group" if "group_institution" in original["flags"] else "campus",
                state="Maharashtra", city=None, modality=modality, kind="equipment_count", reported_value=count,
                units="equipment_units", raw_value=raw_value, locator=original["locator"], flags=original["flags"],
                period="undated inventory", effective_date=inventory_date(table), published_date=result["report.json"]["published_date"],
                retrieved_at=receipt["retrieved_at"], series_key="dmer_equipment", sharing_status=receipt["sharing_status"],
                external_facility_id=original["external_facility_id"], vf_campus_join="unreviewed",
                current_service_decision="unconfirmed", negation="equipment_zero_not_service_absence" if count == 0 else None))
    return observations


def summarize(observations, attempts):
    families = sorted({r["source_family"] for r in observations})
    exact_units = {(r["source_family"], r["subject"], r["modality"]) for r in observations if r["grain"] == "campus"}
    series = defaultdict(list)
    for row in observations:
        key = (row["source_family"], row["series_key"], row["subject"], row["modality"], row["period"], row["kind"])
        series[key].append(row)
    conflicting = sum(len({canonical(r.get("reported_value")) for r in rows}) > 1 for rows in series.values())
    return dict(raw_observations=len(observations), campus_service_literal_keys=len(exact_units),
                unique_reviewed_campuses=None, independently_verified_campus_service_pairs=0,
                origin_families=families, independent_origins=None,
                repeated_series_period_groups=sum(len(v) > 1 for v in series.values()),
                conflicting_series_period_values=conflicting,
                by_modality=dict(Counter(r["modality"] for r in observations)),
                by_kind=dict(Counter(r["kind"] for r in observations)),
                by_grain=dict(Counter(r["grain"] for r in observations)),
                by_source_family=dict(Counter(r["source_family"] for r in observations)),
                by_state=dict(Counter(r.get("state") or "UNKNOWN_OR_NETWORK" for r in observations)),
                attempts=dict(Counter(r["status"] for r in attempts)),
                limitation="Literal campus keys are not deduplicated real campuses. Publisher families are not verified independent origins. No observation establishes current service availability.")


def collect(root, manifest, annotations):
    sources = manifest["sources"]
    require(len({s["key"] for s in sources}) == len(sources), "duplicate source key")
    by_key = {s["key"]: s for s in sources}
    paths = {s["key"]: checked_source(root, s) for s in sources if s["status"] == "ok"}
    require(len({(a["source_key"], a["key"]) for a in annotations}) == len(annotations), "duplicate annotation key")
    batch, rows = envelope(), []
    for source in sources:
        if source.get("parser") == "dmer" and source["status"] == "ok":
            rows.extend(dmer_rows(paths[source["key"]].read_bytes(), source, batch))
    for annotation in annotations:
        source = by_key[annotation["source_key"]]
        require(source["key"] in paths, "annotation references failed source")
        row = annotation_row(source, paths[source["key"]], annotation)
        rows.append(row)
        if row["grain"] in {"campus", "campus_group"}:
            snap = snapshot(source)
            if snap not in batch["source_snapshots"]:
                batch["source_snapshots"].append(snap)
            ext, ev, review = campus_records(row, source)
            batch["external_facilities"].append(ext)
            batch["facility_evidence"].append(ev)
            batch["review_queue"].append(review)
    return {"batch.json": batch, "observations.json": rows, "source_attempts.json": sources,
            "summary.json": summarize(rows, sources)}


def publish(output, payloads):
    hashes = {name: digest(canonical(value) + b"\n") for name, value in payloads.items()}
    publish_json_directory(output, {**payloads, "hashes.json": hashes}, "existing imaging release differs")
    return hashes
