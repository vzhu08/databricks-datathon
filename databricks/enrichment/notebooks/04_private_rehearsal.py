# Databricks notebook source
# MAGIC %md
# MAGIC Explicit operator-only rehearsal in a new private validation schema.
# MAGIC Creates five additive tables plus completed-run state. Retains interrupted attempts.
# MAGIC Does not load a service-status artifact, change grants or publish patient information.

# COMMAND ----------
import hashlib
import json
from pathlib import Path
import sys

existing_widgets = dbutils.widgets.getAll()
for name in ("repo_root", "output_catalog", "output_schema", "confirm_private_rehearsal", "input_path",
             "batch_files_json", "identity_rows_path", "expected_base_sha256", "expected_identity_sha256",
             "expected_batch_sha256", "run_id", "as_of", "receipt_path"):
    if name not in existing_widgets:
        dbutils.widgets.text(name, "")
repo_root = Path(dbutils.widgets.get("repo_root"))
assert repo_root.is_absolute() and (repo_root / "contracts/enrichment/schema.json").is_file()
sys.path.insert(0, str(repo_root / "databricks/enrichment"))
from common import IDS, canonical, digest, load, require
from delta_store import DeltaStore, identifier, volume_path
from merge import plan_merge
from rehearsal import rehearse
from source_inspection import verify_base_export

catalog, schema = (dbutils.widgets.get(k) for k in ("output_catalog", "output_schema"))
identifier(catalog)
identifier(schema)
require(schema.endswith("_validation") and dbutils.widgets.get("confirm_private_rehearsal") == catalog + "." + schema,
        "rehearsal", "explicit confirmation of a dedicated validation schema required")
input_path = volume_path(dbutils.widgets.get("input_path").rstrip("/") + "/base.json")
metadata = load(str(Path(input_path).with_name("source_metadata.json")))
require(metadata["original_table"].rsplit(".", 1)[0].lower() != (catalog + "." + schema).lower(),
        "rehearsal", "output schema must differ from source")
base_hash = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
require(base_hash == dbutils.widgets.get("expected_base_sha256") == metadata["base_file_sha256"],
        "base", "base file differs from accepted pin")
base = load(input_path)
verify_base_export(base, metadata)
identity_path = volume_path(dbutils.widgets.get("identity_rows_path"))
identity_hash = hashlib.sha256(Path(identity_path).read_bytes()).hexdigest()
require(identity_hash == dbutils.widgets.get("expected_identity_sha256"), "identity", "frozen frame hash differs")
identity_rows = load(identity_path)
require(len(identity_rows) == len(base) and {r["facility_id"] for r in identity_rows} == {r["facility_id"] for r in base},
        "identity", "frozen frame must cover every original occurrence exactly")
files = json.loads(dbutils.widgets.get("batch_files_json"))
require(isinstance(files, list) and files, "batches", "accepted producer paths required")
batches = [load(volume_path(path)) for path in files]
plan = plan_merge(batches, base)
require(digest(plan["batch"]) == dbutils.widgets.get("expected_batch_sha256"), "batch", "combined batch pin differs")
require(not plan["batch"]["facility_evidence"] and not any(r["status"] == "confirmed" for r in plan["batch"]["facility_matches"]),
        "rehearsal", "this retrieval-only rehearsal excludes clinical evidence and confirmed identities")
metadata["producer_artifacts"] = [{"path": volume_path(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                                  for path in files]
metadata["identity_frame"] = {"path": identity_path, "sha256": identity_hash}
metadata["release_scope"] = "private retrieval-only engineering rehearsal"
receipt_path = Path(volume_path(dbutils.widgets.get("receipt_path")))
require(not receipt_path.exists(), "receipt", "receipt already exists; inspect before any replay")
store = DeltaStore(spark, catalog, schema)
require(spark.sql(f"SHOW TABLES IN {store.prefix}").count() == 0, "rehearsal", "schema must contain no existing tables")
store.initialize()

def versions():
    names = {table: store.table(table) for table in IDS}
    names["enrichment_publication"] = store.state_table
    return {key: int(spark.sql(f"DESCRIBE HISTORY {name} LIMIT 1").first()["version"]) for key, name in names.items()}

receipt = rehearse(store, batches, base, dbutils.widgets.get("run_id"), dbutils.widgets.get("as_of"), metadata, versions)
receipt.update(output_schema=catalog + "." + schema, spark_version=spark.version,
               base_file_sha256=base_hash, identity_rows_sha256=identity_hash,
               clinical_release=False, submission=False)
receipt_path.parent.mkdir(parents=True, exist_ok=True)
with receipt_path.open("x", encoding="utf-8") as stream:
    stream.write(canonical(receipt) + "\n")
dbutils.notebook.exit(canonical({"receipt_path": str(receipt_path),
    "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    "checks": receipt["checks"], "table_versions": receipt["recovery_manifest"]["table_versions"]}))
