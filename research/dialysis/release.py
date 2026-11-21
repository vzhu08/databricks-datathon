"""Compile a frozen documentary review into an unlinked v1.0.0 envelope."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
import pdfplumber


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def rid(kind, *parts):
    return "dialysis:" + kind + ":" + digest(encode(parts))


def compact(value):
    return " ".join(value.split())


def read_passage(path, claim):
    if claim["format"] == "html":
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for tag in soup.select("script, style, noscript, template"):
            tag.decompose()
        nodes = list(soup.stripped_strings)
        index = claim["segment"]
        if not isinstance(index, int) or not 0 <= index < len(nodes):
            raise ValueError("HTML segment outside document")
        passage = nodes[index]
    elif claim["format"] == "pdf":
        with pdfplumber.open(path) as doc:
            page = claim["page"]
            if not isinstance(page, int) or not 1 <= page <= len(doc.pages):
                raise ValueError("PDF page outside document")
            passage = doc.pages[page - 1].extract_text() or ""
    else:
        raise ValueError("Unsupported document format")
    quote = compact(claim["excerpt"])
    if not quote or quote not in compact(passage):
        raise ValueError("Quote does not match its original locator")
    return claim["excerpt"]


def compile_batch(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tables = {name: [] for name in ("source_snapshots", "external_facilities", "facility_matches",
                                    "facility_evidence", "review_queue")}
    root = manifest_path.parent.resolve()
    sources = {}
    for spec in manifest["sources"]:
        key = spec["key"]
        path = (root / spec["path"]).resolve()
        if not path.is_relative_to(root) or key in sources:
            raise ValueError("Duplicate source or invalid archive path")
        if digest(path.read_bytes()) != spec["sha256"]:
            raise ValueError("Source checksum mismatch")
        sid = rid("snapshot", spec["url"], spec["sha256"])
        sources[key] = sid, path, spec
        tables["source_snapshots"].append(dict(
            snapshot_id=sid, source_key=key, publisher=spec["publisher"], source_family=spec["family"],
            url=spec["url"], retrieved_at=spec["retrieved_at"], published_date=spec.get("published_date"),
            license=spec.get("license"), attribution=spec["publisher"], sha256=spec["sha256"],
            artifact_uri="urn:sha256:" + spec["sha256"], parser_version="b02-1",
            independence_status=spec["independence_status"]))
    externals, evidence = {}, {}
    ledger = []
    for claim in manifest["claims"]:
        sid, path, spec = sources[claim["source"]]
        quote = read_passage(path, claim)
        campus = claim["campus"]
        eid = rid("external", sid, campus)
        identity = dict(
            external_facility_id=eid, snapshot_id=sid, source_record_id=None,
            record_locator=claim["identity_locator"], name_original=campus["name"],
            name_normalized=compact(campus["name"]).casefold(), address_original=campus.get("address"),
            facility_type="hospital", city=campus["city"], state="Rajasthan", pin=campus.get("pin"),
            latitude=None, longitude=None, coordinate_method=None,
            quality_flags=["unlinked_source_identity", "coordinates_missing"])
        if eid in externals and externals[eid] != identity:
            raise ValueError("Conflicting locators for the same external identity")
        externals[eid] = identity
        rec = dict(external_facility_id=eid, snapshot_id=sid, facility_id=None, match_id=None,
                   claim_type="service", service="dialysis", polarity="inconclusive",
                   assertion=claim["assertion"], excerpt=quote, observation=None, locator=claim["locator"],
                   source_url=spec["url"], effective_date=None, valid_until=None,
                   temporal_status=claim["temporal_status"], reviewer=None, reviewed_at=None)
        claim_id = rid("evidence", rec)
        if claim_id in evidence:
            raise ValueError("Duplicate evidence claim")
        evidence[claim_id] = dict(evidence_id=claim_id, **rec)
        tables["review_queue"].append(dict(
            review_id=rid("review", claim_id), facility_id=None, external_facility_id=eid,
            evidence_id=claim_id, match_id=None, reason_code="service_scope_review",
            severity="medium", status="open", next_action=claim["next_action"], resolution=None))
        ledger.append(dict(evidence_id=claim_id, kind=claim["kind"], district=campus["district"],
                           ownership=campus["ownership"], family=spec["family"],
                           time_specific=claim["time_specific"], eligible_for_audit=True))
    tables["external_facilities"] = list(externals.values())
    tables["facility_evidence"] = list(evidence.values())
    for name, pk in (("source_snapshots", "snapshot_id"), ("external_facilities", "external_facility_id"),
                     ("facility_evidence", "evidence_id"), ("review_queue", "review_id")):
        tables[name].sort(key=lambda r: r[pk])
    return dict(contract_version="1.0.0", **tables), sorted(ledger, key=lambda r: r["evidence_id"])


def publish(manifest_path, output):
    batch, ledger = compile_batch(manifest_path)
    files = {"batch.json": encode(batch), "claim_ledger.json": encode(ledger)}
    files["sha256.json"] = encode({name: digest(data) for name, data in files.items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            staged = Path(tmp) / "release"
            staged.mkdir()
            for name, data in files.items():
                (staged / name).write_bytes(data)
            try:
                staged.rename(output)
                return
            except OSError:
                if not output.is_dir():
                    raise
    if not output.is_dir() or {p.name for p in output.iterdir()} != set(files):
        raise ValueError("Existing output is not a complete release")
    if any((output / name).read_bytes() != data for name, data in files.items()):
        raise ValueError("Frozen release differs; choose a new output directory")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    publish(args.manifest, args.out)


if __name__ == "__main__":
    main()
