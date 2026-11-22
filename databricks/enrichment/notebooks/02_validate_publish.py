# Databricks notebook source
# MAGIC %md
# MAGIC Install `databricks/enrichment/requirements.txt` in the notebook environment first.
# MAGIC Bootstrap once with `initialize_only=true`; then publish with that flag false.
# MAGIC Five staged Delta writes are sequential. The single operational pointer update publishes the run.

# COMMAND ----------
import hashlib
import json
from copy import deepcopy
from pathlib import Path
import sys

for name, default in {
    "repo_root": "", "original_table": "", "output_catalog": "", "output_schema": "",
    "input_path": "", "batch_files_json": "[]", "contract_version": "1.0.0", "run_id": "",
    "as_of": "", "transitions_file": "", "identity_policy_file": "", "initialize_only": "true",
    "status_artifact_path": "", "status_artifact_sha256": "", "status_identity_rows_sha256": "",
}.items():
    dbutils.widgets.text(name, default)
repo_root = dbutils.widgets.get("repo_root")
assert repo_root.startswith("/Workspace/"), "Set the absolute Workspace Git folder path"
sys.path.insert(0, repo_root + "/databricks/enrichment")
from common import VERSION, load, require
from delta_store import DeltaStore, identifier, volume_path
from publication import publish
from source_inspection import verify_base_export

require(dbutils.widgets.get("contract_version") == VERSION, "contract_version", "unsupported contract")
original_table = dbutils.widgets.get("original_table")
identifier(original_table, 3)
output_catalog, output_schema = (dbutils.widgets.get(k) for k in ("output_catalog", "output_schema"))
# Separate source/output schemas prevent an original table from becoming a write target.
require(original_table.rsplit(".", 1)[0].lower() != (output_catalog + "." + output_schema).lower(),
        "output_schema", "use a dedicated writable enrichment schema separate from original sources")
store = DeltaStore(spark, output_catalog, output_schema)

# COMMAND ----------
if dbutils.widgets.get("initialize_only") == "true":
    store.initialize()
    dbutils.notebook.exit("Initialized five empty Delta tables plus operational publication state; no run published.")

# COMMAND ----------
input_path = dbutils.widgets.get("input_path").rstrip("/")
base_path = volume_path(input_path + "/base.json")
metadata = load(volume_path(input_path + "/source_metadata.json"))
input_metadata = deepcopy(metadata)
require(metadata["original_table"] == original_table, "original_table", "does not match inspected export")
require(hashlib.sha256(Path(base_path).read_bytes()).hexdigest() == metadata["base_file_sha256"],
        "base", "base file hash differs from inspected export")
base = load(base_path)
verify_base_export(base, metadata)
files = json.loads(dbutils.widgets.get("batch_files_json"))
require(isinstance(files, list) and files and all(isinstance(f, str) for f in files),
        "batch_files_json", "nonempty list of full Volume JSON paths required")
batches = [load(volume_path(path)) for path in files]
optional = lambda name: load(volume_path(dbutils.widgets.get(name))) if dbutils.widgets.get(name) else None
metadata["producer_artifacts"] = [{"path": volume_path(path),
    "sha256": hashlib.sha256(Path(volume_path(path)).read_bytes()).hexdigest()} for path in files]
status_path, status_sha, identity_sha = (dbutils.widgets.get(k) for k in
    ("status_artifact_path", "status_artifact_sha256", "status_identity_rows_sha256"))
require(bool(status_path) == bool(status_sha) and (bool(status_path) or not identity_sha),
        "service_status", "provide artifact path and accepted hash together; identity pin is optional")
status_spec = {"path": status_path, "sha256": status_sha,
               "identity_rows_sha256": identity_sha or None, "input_metadata": input_metadata} if status_path else None
manifest = publish(store, batches, base, dbutils.widgets.get("run_id"), dbutils.widgets.get("as_of"),
                   transitions=optional("transitions_file"), identity_policy=optional("identity_policy_file"),
                   source_metadata=metadata, status_artifact=status_spec)
print(json.dumps({key: manifest[key] for key in ("run_id", "revision", "status", "attempt_id",
    "completed_at", "parent_run", "table_versions", "counts", "base_rows", "base_sha256", "coverage")}, indent=2))
