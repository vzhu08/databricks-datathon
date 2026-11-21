# Databricks notebook source
# MAGIC %md
# MAGIC Run in an authorized workspace. Inspect schema first, then enter observed column mappings.
# MAGIC No table names below imply that a source has been installed or inspected.

# COMMAND ----------
import json
import sys

for name, default in {
    "repo_root": "", "original_table": "", "postal_table": "", "source_version": "",
    "output_path": "", "mapping_json": "{}", "postal_mapping_json": "{}",
    "allow_surrogate": "false", "max_rows": "500000",
}.items():
    dbutils.widgets.text(name, default)
repo_root = dbutils.widgets.get("repo_root")
assert repo_root.startswith("/Workspace/"), "Set the absolute Workspace Git folder path"
sys.path.insert(0, repo_root + "/databricks/enrichment")
from common import canonical
from source_inspection import inspect_table, map_base, profile_rows, write_new_json

# COMMAND ----------
version_text = dbutils.widgets.get("source_version")
source_rows, source_metadata = inspect_table(
    spark, dbutils.widgets.get("original_table"),
    int(version_text) if version_text else None, int(dbutils.widgets.get("max_rows")))
print(json.dumps({"source_metadata": source_metadata,
                  "unmapped_profile": profile_rows(source_rows, {})}, indent=2))
# Inspect these schema/aggregate outputs, set mapping_json, and run the next cell.

# COMMAND ----------
mapping = json.loads(dbutils.widgets.get("mapping_json"))
assert mapping, "Enter observed mapping_json (e.g. id/name/state/type/pin/evidence column names)"
profile = profile_rows(source_rows, mapping)
base = map_base(source_rows, mapping.get("id"), source_metadata["original_table"],
                dbutils.widgets.get("allow_surrogate") == "true")
output = dbutils.widgets.get("output_path").rstrip("/")
source_metadata["mapping"] = mapping
source_metadata["source_profile"] = profile
source_metadata["base_artifact"] = output + "/base.json"
source_metadata["base_file_sha256"] = write_new_json(output + "/base.json", base)
write_new_json(output + "/source_metadata.json", source_metadata)
print(json.dumps({"base_rows": len(base), "profile": profile,
                  "metadata_artifact": output + "/source_metadata.json"}, indent=2))

# COMMAND ----------
postal_table = dbutils.widgets.get("postal_table")
if postal_table:
    postal_rows, postal_metadata = inspect_table(spark, postal_table,
                                                max_rows=int(dbutils.widgets.get("max_rows")))
    postal_mapping = json.loads(dbutils.widgets.get("postal_mapping_json"))
    postal_metadata["profile"] = profile_rows(postal_rows, postal_mapping)
    # Export stays in the approved Volume. No postal join can multiply base rows.
    from source_inspection import json_value
    postal_metadata["file_sha256"] = write_new_json(output + "/postal_rows.json", json_value(postal_rows))
    write_new_json(output + "/postal_metadata.json", postal_metadata)
    print(json.dumps(postal_metadata, indent=2))
