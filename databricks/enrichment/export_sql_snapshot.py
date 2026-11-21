"""Read the two reviewed version-0 sources through an existing authenticated CLI.

Statement Execution JSON strings preserve source types via SQL to_json(struct(*))
with null fields retained. Every bucket must finish without truncation; original
rows stay in ignored local storage. No source or workspace mutation is issued.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from common import canonical, digest, load, require
from delta_store import identifier
from occurrence_keys import SOURCE
from prepare_local_export import local_output, parse_rows

POSTAL = SOURCE.rsplit(".", 1)[0] + ".india_post_pincode_directory"
EXPECTED = {"facilities": (SOURCE, "unique_id", 10088, 8),
            "postal": (POSTAL, "pincode", 165627, 16)}
RECEIPT_SHA = "538f3602e84526ef1df2492c78c5f9d22d55644195b7462f2f5f6f983f51dcf5"


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write(path, data):
    with Path(path).open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def verify_receipt(root):
    root = Path(root)
    require(hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() == RECEIPT_SHA,
            "receipt", "metadata packet differs from the reviewed operator receipt")
    for entry in load(root / "manifest.json")["files"]:
        require(Path(entry["file"]).name == entry["file"], "receipt", "unsafe packet filename")
        data = (root / entry["file"]).read_bytes()
        require(len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"],
                "receipt", "packet file hash or size differs")


def collect_chunks(response, get_chunk):
    """Validate a complete one-column JSON result before returning native rows."""
    require(response["status"]["state"] == "SUCCEEDED", "statement", "source query did not succeed")
    manifest = response["manifest"]
    require(manifest.get("truncated") is False, "statement", "truncated source result is forbidden")
    require(manifest["format"] == "JSON_ARRAY" and manifest["schema"]["column_count"] == 1,
            "statement", "expected one JSON source-row column")
    result, rows, seen = response["result"], [], set()
    while True:
        index = result["chunk_index"]
        require(index not in seen and index == len(seen), "statement", "repeated or nonsequential chunk")
        seen.add(index)
        values = result.get("data_array", [])
        require(result["row_offset"] == len(rows) and result["row_count"] == len(values),
                "statement", "chunk row count or offset mismatch")
        require(all(isinstance(r, list) and len(r) == 1 and isinstance(r[0], str) for r in values),
                "statement", "invalid serialized source-row result")
        rows.extend(r[0] for r in values)
        following = result.get("next_chunk_internal_link")
        if following is None:
            break
        require(following.startswith("/api/2.0/sql/statements/" + response["statement_id"] + "/result/chunks/"),
                "statement", "chunk link changed statement or endpoint")
        result = get_chunk(following)
    require(len(rows) == manifest["total_row_count"] and len(seen) == manifest["total_chunk_count"],
            "statement", "incomplete result chunks")
    return rows


class Cli:
    def __init__(self, binary, profile):
        self.binary, self.profile = binary, profile

    def call(self, method, path, request=None):
        args = [self.binary, "api", method, path, "--profile", self.profile, "-o", "json"]
        if request is not None:
            args += ["--json", "@" + str(Path(request).resolve())]
        done = subprocess.run(args, capture_output=True, text=True, timeout=90)
        require(done.returncode == 0, "databricks_cli", "API call failed; inspect authorized session without printing credentials/source rows")
        return json.loads(done.stdout)

    def statement(self, request):
        response = self.call("post", "/api/2.0/sql/statements", request)
        deadline = time.monotonic() + 300
        while response["status"]["state"] in ("PENDING", "RUNNING"):
            require(time.monotonic() < deadline, "statement", "query wait exceeded five minutes")
            time.sleep(1)
            response = self.call("get", "/api/2.0/sql/statements/" + response["statement_id"])
        return response


def export(root, receipt, binary, profile, warehouse):
    root, receipt = local_output(root), Path(receipt)
    verify_receipt(receipt)
    require(not root.exists(), "output", "capture already exists; choose a fresh run")
    root.mkdir(parents=True, mode=0o700)
    (root / "queries").mkdir(mode=0o700)
    (root / "raw").mkdir(mode=0o700)
    shutil.copytree(receipt, root / "source-receipt")
    client = Cli(binary, profile)
    capture = {"version": "vf-sql-snapshot-1.0.0", "started_at": utc_now(), "warehouse_id": warehouse,
               "source_receipt_manifest_sha256": RECEIPT_SHA, "sources": {}}
    for name, (table, key, expected, buckets) in EXPECTED.items():
        schema_name = "facilities-schema.json" if name == "facilities" else "india_post_pincode_directory-schema.json"
        schema = load(receipt / schema_name)
        require(schema["table"] == table, "schema", "unexpected source table")
        fields = {c["name"] for c in schema["columns"]}
        source = {"original_table": table, "observed_delta_version": 0, "schema": schema,
                  "expected_row_count": expected, "parts": []}
        all_rows = []
        for bucket in range(buckets):
            sql = ("SELECT to_json(struct(*), map('ignoreNullFields','false')) AS row_json FROM " + identifier(table, 3) +
                   " VERSION AS OF 0 WHERE pmod(xxhash64(`" + key + "`), " + str(buckets) + ") = " + str(bucket) +
                   " ORDER BY row_json")
            query_name = "queries/" + name + "-" + str(bucket) + ".json"
            request = {"warehouse_id": warehouse, "statement": sql, "format": "JSON_ARRAY", "disposition": "INLINE",
                       "wait_timeout": "10s", "on_wait_timeout": "CONTINUE", "row_limit": 100000}
            write(root / query_name, canonical(request).encode("utf-8"))
            response = client.statement(root / query_name)
            native = collect_chunks(response, lambda path: client.call("get", path))
            raw = ("\n".join(native) + ("\n" if native else "")).encode("utf-8")
            rows = parse_rows(raw, "jsonl") if native else []
            require(all(set(row) == fields for row in rows), "source", "source field/null-preservation mismatch")
            artifact = "raw/" + name + "-" + str(bucket) + ".jsonl"
            write(root / artifact, raw)
            source["parts"].append({"bucket": bucket, "bucket_count": buckets, "statement_id": response["statement_id"],
                "query": query_name, "query_sha256": hashlib.sha256((root / query_name).read_bytes()).hexdigest(),
                "artifact": artifact, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                "row_count": len(rows), "retrieved_at": utc_now(), "truncated": False})
            all_rows.extend(rows)
            print(json.dumps({"source": name, "bucket": bucket, "rows": len(rows), "accumulated": len(all_rows)}), flush=True)
        require(len(all_rows) == expected, "source", "row count differs from pinned operator/integration receipts")
        source.update(row_count=len(all_rows), source_rows_sha256=digest(sorted(all_rows, key=canonical)))
        capture["sources"][name] = source
    capture["completed_at"] = utc_now()
    write(root / "capture_manifest.json", canonical(capture).encode("utf-8"))
    return {"status": "captured", "source_rows": {k: v["row_count"] for k, v in capture["sources"].items()},
            "manifest_sha256": hashlib.sha256((root / "capture_manifest.json").read_bytes()).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("output-dir", "receipt-dir", "cli", "profile", "warehouse"):
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    print(json.dumps(export(args.output_dir, args.receipt_dir, args.cli, args.profile, args.warehouse), indent=2))


if __name__ == "__main__":
    main()
