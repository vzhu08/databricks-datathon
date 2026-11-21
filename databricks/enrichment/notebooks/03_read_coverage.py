# Databricks notebook source
# MAGIC %md
# MAGIC Capture the completed pointer once; read all tables using its attempt ID and pinned versions.
# MAGIC Do not independently select the latest row/run from each physical table.

# COMMAND ----------
import json
import sys
for name in ("repo_root", "output_catalog", "output_schema"):
    dbutils.widgets.text(name, "")
repo_root = dbutils.widgets.get("repo_root")
assert repo_root.startswith("/Workspace/"), "Set the absolute Workspace Git folder path"
sys.path.insert(0, repo_root + "/databricks/enrichment")
from common import counts, require
from delta_store import DeltaStore
from publication import current
store = DeltaStore(spark, dbutils.widgets.get("output_catalog"), dbutils.widgets.get("output_schema"))
manifest, batch = current(store)
require(manifest is not None, "publication", "no completed run exists")
require(counts(batch) == manifest["counts"], "publication", "readback counts differ from manifest")
print(json.dumps({"run_id": manifest["run_id"], "revision": manifest["revision"],
                  "table_versions": manifest["table_versions"], "counts_verified": counts(batch),
                  "coverage": manifest["coverage"]}, indent=2))
