# Databricks notebook source
# MAGIC %md
# MAGIC Capture the completed pointer once; read all tables using its attempt ID and pinned versions.
# MAGIC Do not independently select the latest row/run from each physical table.

# COMMAND ----------
import json
import sys
for name in ("repo_root", "output_catalog", "output_schema", "input_path"):
    dbutils.widgets.text(name, "")
repo_root = dbutils.widgets.get("repo_root")
assert repo_root.startswith("/Workspace/"), "Set the absolute Workspace Git folder path"
sys.path.insert(0, repo_root + "/databricks/enrichment")
from common import counts, load, require
from delta_store import DeltaStore, volume_path
from publication import current
from status_artifact import read_status_artifact
store = DeltaStore(spark, dbutils.widgets.get("output_catalog"), dbutils.widgets.get("output_schema"))
manifest, batch = current(store)
require(manifest is not None, "publication", "no completed run exists")
require(counts(batch) == manifest["counts"], "publication", "readback counts differ from manifest")
if "service_status_artifact" in manifest["source_metadata"]:
    input_path = dbutils.widgets.get("input_path").rstrip("/")
    status = read_status_artifact(manifest, load(volume_path(input_path + "/base.json")),
                                  load(volume_path(input_path + "/source_metadata.json")))
    print(json.dumps({"status_artifact_sha256": manifest["source_metadata"]["service_status_artifact"]["sha256"],
                      "status_decisions_verified": status["decision_count"]}))
print(json.dumps({"run_id": manifest["run_id"], "revision": manifest["revision"],
                  "table_versions": manifest["table_versions"], "counts_verified": counts(batch),
                  "coverage": manifest["coverage"]}, indent=2))
