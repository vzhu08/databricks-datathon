"""Freeze issuer-derived lookup strings and screen the frozen sample offline."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import zipfile

from .sample import name_key, sha


def evaluate(base_bytes, sample_bytes, archive_bytes, manifest_bytes):
    import io

    sample = json.loads(sample_bytes)
    expected = sample["summary"]
    if sha(base_bytes) != expected["base_sha256"]:
        raise ValueError("base differs from the frozen sample")
    manifest = json.loads(manifest_bytes)
    if sha(archive_bytes) != manifest["archive"]["sha256"]:
        raise ValueError("archive differs from the publisher edition manifest")
    member = "facility-locators.jsonl.gz"
    spec = next(item for item in manifest["members"] if item["filename"] == member)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
        content = z.read(member)
    if sha(content) != spec["sha256"]:
        raise ValueError("locator ledger differs from manifest")
    records = [json.loads(line) for line in gzip.decompress(content).splitlines()]
    if len(records) != spec["count"]:
        raise ValueError("locator ledger count differs from manifest")

    index = defaultdict(list)
    freeze = []
    gaps = Counter()
    for record in records:
        name = record["Hospital_Name"]
        pin = record["Pincode"]
        locator = record["official_locator"]
        locality = record["Town"] or record["Subdistrict"] or record["District"]
        if not name_key(name) or not pin or not re.fullmatch(r"[1-9][0-9]{5}", pin) or not locator:
            gaps["missing_name_pin_or_official_locator"] += 1
            continue
        entry = {"name": name, "pin": pin, "locator": locator, "sr_no": record["sr_no"],
                 "locality": locality, "premises": record["Address_Original_First_Line"],
                 "state": record["State"], "town": record["Town"], "date": None,
                 "query": " ".join((name, locality)) if locality else None}
        freeze.append(entry)
        index[name_key(name), pin].append(entry)
    original = {row["facility_id"]: row["source_row"] for row in json.loads(base_bytes)}
    selected = sample["sample_private"]
    if len(selected) != 24 or len({r["occurrence"] for r in selected}) != 24:
        raise ValueError("expected the 24 frozen sample slots")
    results = []
    for row in selected:
        source = original[row["occurrence"]]
        matches = index.get((name_key(source.get("name")), str(source.get("address_zipOrPostcode")).strip()), [])
        if not matches:
            status = "no_exact_name_pin"
        elif len(matches) != 1:
            status = "ambiguous_issuer_records"
        elif not all(matches[0][field] for field in ("query", "premises", "state")):
            status = "missing_locality_premises_or_state"
        else:
            status = "needs_branch_review"
        results.append({"occurrence": row["occurrence"], "stratum": row["stratum"],
                        "status": status, "issuer_records": [m["sr_no"] for m in matches]})
    return {"summary": {"manifest_sha256": sha(manifest_bytes), "source_records": len(records),
                         "indexable_records": len(freeze), "source_gaps": dict(gaps),
                         "town_missing": sum(not r["town"] for r in freeze),
                         "premises_missing": sum(not r["premises"] for r in freeze),
                         "dated_branch_records": 0,
                         "sample_sha256": sha(sample_bytes),
                         "by_stratum": {s: dict(Counter(r["status"] for r in results if r["stratum"] == s))
                                        for s in sorted({r["stratum"] for r in results})}},
            "publisher_freeze": freeze, "private_results": results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "sample", "archive", "manifest", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    result = evaluate(*[getattr(args, name).read_bytes() for name in ("base", "sample", "archive", "manifest")])
    with args.output.open("x") as f:
        json.dump(result, f, ensure_ascii=False, sort_keys=True)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
