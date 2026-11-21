# Databricks notebook source
# MAGIC %md
# MAGIC # DATA-01 · Prepare Virtue Foundation facilities
# MAGIC
# MAGIC Produces the prepared table defined in `docs/implementation/SEARCH_CONTRACT.md`.
# MAGIC This notebook intentionally preserves original evidence wording and source provenance.
# MAGIC It does **not** deduplicate facilities by name.

# COMMAND ----------

from pathlib import Path
import sys
import json

from pyspark.sql import functions as F
from pyspark.sql import types as T

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC Set the Marketplace source and destination table names.
# MAGIC `COLUMN_MAPPING_JSON` is optional; use it when the real Marketplace schema does not
# MAGIC match one of the candidate names below. Example:
# MAGIC
# MAGIC ```json
# MAGIC {"name":"hospital_name","city":"town","latitude":"lat","longitude":"lng"}
# MAGIC ```

# COMMAND ----------

dbutils.widgets.text("SOURCE_TABLE", "", "Virtue Marketplace source table")
dbutils.widgets.text("repo_root", "", "Workspace Git folder")
dbutils.widgets.text("OUTPUT_TABLE", "", "Prepared Delta table")
dbutils.widgets.text("COLUMN_MAPPING_JSON", "{}", "Raw-column overrides as JSON")

SOURCE_TABLE = dbutils.widgets.get("SOURCE_TABLE").strip()
OUTPUT_TABLE = dbutils.widgets.get("OUTPUT_TABLE").strip()
COLUMN_MAPPING_JSON = dbutils.widgets.get("COLUMN_MAPPING_JSON").strip() or "{}"

root = Path(dbutils.widgets.get("repo_root") or ".").resolve()
sys.path.insert(0, str(root / "databricks/enrichment"))
from delta_store import identifier
from source_inspection import json_value
from common import stable_id

source_name = identifier(SOURCE_TABLE, 3)
output_name = identifier(OUTPUT_TABLE, 3)
if source_name.casefold() == output_name.casefold():
    raise ValueError("Choose a new prepared table distinct from the Marketplace source.")
if spark.catalog.tableExists(output_name):
    raise ValueError("Prepared table already exists. Choose a new versioned output name.")

try:
    COLUMN_OVERRIDES = json.loads(COLUMN_MAPPING_JSON)
except json.JSONDecodeError as exc:
    raise ValueError(f"COLUMN_MAPPING_JSON must be valid JSON: {exc}") from exc

# COMMAND ----------

raw = spark.table(source_name)
print(f"Source table: {SOURCE_TABLE}")
print(f"Rows: {raw.count():,}")
print(f"Columns ({len(raw.columns)}):")
for field in raw.schema.fields:
    print(f"  {field.name}: {field.dataType.simpleString()}")

display(raw.limit(20))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Resolve the real Marketplace schema
# MAGIC Candidate names are deliberately conservative. If a field is not found, provide an
# MAGIC explicit override rather than guessing.

# COMMAND ----------

CANDIDATES = {
    "raw_row_ref": [
        "facility_id", "id", "record_id", "hospital_id", "uuid", "source_id"
    ],
    "name": [
        "name", "facility_name", "hospital_name", "healthcare_facility_name", "facility"
    ],
    "city": [
        "city", "town", "locality", "district_city"
    ],
    "state": [
        "state", "state_name", "province", "region"
    ],
    "pin": [
        "pin", "pincode", "pin_code", "postal_code", "postcode", "zip"
    ],
    "latitude": [
        "latitude", "lat", "facility_latitude"
    ],
    "longitude": [
        "longitude", "lon", "lng", "long", "facility_longitude"
    ],
    "description": [
        "description", "facility_description", "about", "overview"
    ],
    "capabilities": [
        "capabilities", "capability", "services", "service_capabilities"
    ],
    "procedures": [
        "procedures", "procedure", "treatments"
    ],
    "equipment": [
        "equipment", "medical_equipment", "equipments"
    ],
    "record_source_urls": [
        "record_source_urls", "source_urls", "source_url", "sources", "urls", "url"
    ],
}

lower_to_actual = {c.lower(): c for c in raw.columns}

def resolve_column(target):
    override = COLUMN_OVERRIDES.get(target)
    if override:
        if override not in raw.columns:
            raise ValueError(f"Override for {target!r} points to missing column {override!r}.")
        return override
    for candidate in CANDIDATES[target]:
        if candidate.lower() in lower_to_actual:
            return lower_to_actual[candidate.lower()]
    return None

mapping = {target: resolve_column(target) for target in CANDIDATES}

required = ["name"]
missing_required = [field for field in required if not mapping[field]]
if not any(mapping[f] for f in ("description", "capabilities", "procedures", "equipment")):
    raise ValueError("Map at least one observed evidence column.")
if missing_required:
    raise ValueError(
        "Could not resolve required Marketplace columns: "
        + ", ".join(missing_required)
        + ". Inspect the schema above and set COLUMN_MAPPING_JSON explicitly."
    )

print("Resolved raw → prepared mapping")
for target, source in mapping.items():
    print(f"  {source or '[not present]'} -> {target}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build prepared rows
# MAGIC - Evidence fields remain verbatim strings.
# MAGIC - PIN is stored as text.
# MAGIC - Invalid/missing coordinates become null but the facility row is retained.
# MAGIC - Same-name facilities are never merged.
# MAGIC - Raw lineage is preserved using an upstream identifier where available, otherwise
# MAGIC   a deterministic SHA-256 hash of the complete raw row.

# COMMAND ----------

def quoted_column(name):
    return "`" + name.replace("`", "``") + "`"


def source_expr(target, cast_type="string"):
    source = mapping.get(target)
    if not source:
        return F.lit(None).cast(cast_type)
    name = quoted_column(source)
    if cast_type == "double":
        return F.expr(f"try_cast({name} as double)")
    if target in ("description", "capabilities", "procedures", "equipment", "record_source_urls"):
        data_type = raw.schema[source].dataType
        if isinstance(data_type, T.ArrayType) and isinstance(data_type.elementType, T.StringType):
            return F.col(name)
        if not isinstance(data_type, T.StringType):
            raise ValueError(f"Mapped {target} must contain text or an array of text.")
    return F.col(name).cast(cast_type)


if mapping["raw_row_ref"]:
    id_source = mapping["raw_row_ref"]
    if not isinstance(raw.schema[id_source].dataType, (T.StringType, T.IntegralType)):
        raise ValueError("Choose a source ID of text or integer type.")
    raw_row_ref_expr = F.col(quoted_column(id_source)).cast("string")
    if raw.where(raw_row_ref_expr.isNull() | (F.length(F.trim(raw_row_ref_expr)) == 0)).limit(1).count():
        raise ValueError("Mapped ID is empty on at least one row. Resolve identity before publication.")
else:
    # Use the same namespaced surrogate as enrichment, preserving Spark field types.
    # The bounded path fits the facility pilot and fails before collecting a larger table.
    rows = raw.limit(500001).collect()
    if len(rows) > 500000:
        raise ValueError("ID-less source exceeds the bounded export size.")
    surrogate_col = "__prepared_source_id"
    while surrogate_col in raw.columns:
        surrogate_col += "_"
    schema = T.StructType(raw.schema.fields + [T.StructField(surrogate_col, T.StringType(), False)])
    raw = spark.createDataFrame(
        [tuple(row) + (stable_id("base", SOURCE_TABLE, json_value(row.asDict(recursive=True))),)
         for row in rows], schema,
    )
    raw_row_ref_expr = F.col(surrogate_col)

lat_raw = source_expr("latitude", "double")
lon_raw = source_expr("longitude", "double")

point_valid = (lat_raw.between(-90.0, 90.0) & lon_raw.between(-180.0, 180.0)
               & ~((lat_raw == 0.0) & (lon_raw == 0.0)))
lat_valid = F.when(point_valid, lat_raw)
lon_valid = F.when(point_valid, lon_raw)

base = raw.select(
    raw_row_ref_expr.alias("raw_row_ref"),
    source_expr("name").alias("name"),
    source_expr("city").alias("city"),
    source_expr("state").alias("state"),
    source_expr("pin").alias("pin"),
    lat_valid.alias("latitude"),
    lon_valid.alias("longitude"),
    source_expr("description").alias("description"),
    source_expr("capabilities").alias("capabilities"),
    source_expr("procedures").alias("procedures"),
    source_expr("equipment").alias("equipment"),
    source_expr("record_source_urls").alias("record_source_urls"),
)

prepared = base.withColumn("facility_id", F.col("raw_row_ref")).select(
    "facility_id",
    "raw_row_ref",
    "name",
    "city",
    "state",
    "pin",
    "latitude",
    "longitude",
    "description",
    "capabilities",
    "procedures",
    "equipment",
    "record_source_urls",
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data-quality profile

# COMMAND ----------

profile_fields = [
    "name", "city", "state", "pin", "latitude", "longitude",
    "description", "capabilities", "procedures", "equipment", "record_source_urls"
]

total_rows = prepared.count()

profile_rows = []
for c in profile_fields:
    missing = prepared.where(
        F.col(c).isNull() |
        ((F.col(c).cast("string").isNotNull()) & (F.length(F.trim(F.col(c).cast("string"))) == 0))
    ).count()
    profile_rows.append((c, total_rows - missing, missing, (missing / total_rows if total_rows else None)))

profile = spark.createDataFrame(
    profile_rows,
    schema="field string, populated long, missing long, missing_fraction double"
)
display(profile.orderBy(F.desc("missing_fraction")))

# Re-check raw coordinates to quantify invalid values before normalization.
raw_lat = source_expr("latitude", "double") if mapping["latitude"] else F.lit(None).cast("double")
raw_lon = source_expr("longitude", "double") if mapping["longitude"] else F.lit(None).cast("double")

coordinate_profile = raw.select(
    F.sum(F.when(raw_lat.isNull(), 1).otherwise(0)).alias("missing_latitude"),
    F.sum(F.when(raw_lon.isNull(), 1).otherwise(0)).alias("missing_longitude"),
    F.sum(F.when(raw_lat.isNotNull() & ~raw_lat.between(-90.0, 90.0), 1).otherwise(0)).alias("out_of_range_latitude"),
    F.sum(F.when(raw_lon.isNotNull() & ~raw_lon.between(-180.0, 180.0), 1).otherwise(0)).alias("out_of_range_longitude"),
    F.sum(F.when((raw_lat == 0.0) & (raw_lon == 0.0), 1).otherwise(0)).alias("zero_zero_pairs"),
)
display(coordinate_profile)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Campus-preservation checks
# MAGIC Shared names are inspection candidates, **not** automatic duplicates.

# COMMAND ----------

same_name = (
    prepared
    .where(F.col("name").isNotNull())
    .groupBy(F.lower(F.trim("name")).alias("normalized_name"))
    .agg(
        F.count("*").alias("row_count"),
        F.countDistinct("facility_id").alias("facility_ids"),
        F.countDistinct(
            F.concat_ws(
                "|",
                F.coalesce(F.col("city"), F.lit("")),
                F.coalesce(F.col("state"), F.lit("")),
                F.coalesce(F.col("pin"), F.lit("")),
                F.coalesce(F.col("latitude").cast("string"), F.lit("")),
                F.coalesce(F.col("longitude").cast("string"), F.lit(""))
            )
        ).alias("distinct_location_signatures")
    )
    .where(F.col("row_count") > 1)
    .orderBy(F.desc("row_count"))
)

print("Repeated facility names (retained as separate rows):")
display(same_name.limit(50))

# Verify the transform itself has not collapsed rows.
if prepared.count() != raw.count():
    raise AssertionError("Preparation changed row count; DATA-01 must preserve one row per upstream record/campus candidate.")

if prepared.select("facility_id").distinct().count() != prepared.count():
    raise AssertionError(
        "facility_id collision detected. Inspect duplicate raw rows/campuses before handoff; do not silently deduplicate."
    )

print("PASS: row count preserved and facility_id is unique.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Jaipur smoke check
# MAGIC This checks that Jaipur facilities survive preparation. Service matching belongs to RANK-01.

# COMMAND ----------

jaipur = prepared.where(F.lower(F.trim(F.col("city"))) == "jaipur")
print(f"Prepared Jaipur rows: {jaipur.count():,}")
display(
    jaipur.select(
        "facility_id", "name", "city", "state", "pin",
        "latitude", "longitude", "description", "capabilities",
        "procedures", "equipment", "record_source_urls"
    ).limit(20)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write the prepared Delta table

# COMMAND ----------

(
    prepared.write
    .format("delta")
    .mode("errorifexists")
    .saveAsTable(output_name)
)

print(f"Wrote {prepared.count():,} rows to {OUTPUT_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Handoff summary
# MAGIC Copy this output into the DATA-01 PR for Vincent and Oliver.

# COMMAND ----------

summary = {
    "source_table": SOURCE_TABLE,
    "output_table": OUTPUT_TABLE,
    "row_count": prepared.count(),
    "jaipur_row_count": jaipur.count(),
    "mapping": mapping,
    "same_name_groups": same_name.count(),
}
print(json.dumps(summary, indent=2))
