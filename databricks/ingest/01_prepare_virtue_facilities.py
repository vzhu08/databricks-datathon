# Databricks notebook source
# MAGIC %md
# MAGIC # DATA-01 · Prepare Virtue Foundation facilities
# MAGIC
# MAGIC Produces the prepared table defined in `docs/implementation/SEARCH_CONTRACT.md`.
# MAGIC This notebook intentionally preserves original evidence wording and source provenance.
# MAGIC It does **not** deduplicate facilities by name.

# COMMAND ----------

from functools import reduce
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
dbutils.widgets.text("OUTPUT_TABLE", "main.default.virtue_facilities_prepared", "Prepared Delta table")
dbutils.widgets.text("COLUMN_MAPPING_JSON", "{}", "Raw-column overrides as JSON")

SOURCE_TABLE = dbutils.widgets.get("SOURCE_TABLE").strip()
OUTPUT_TABLE = dbutils.widgets.get("OUTPUT_TABLE").strip()
COLUMN_MAPPING_JSON = dbutils.widgets.get("COLUMN_MAPPING_JSON").strip() or "{}"

if not SOURCE_TABLE:
    raise ValueError("SOURCE_TABLE is required. Set it to the fully-qualified Virtue Foundation Marketplace table.")

try:
    COLUMN_OVERRIDES = json.loads(COLUMN_MAPPING_JSON)
except json.JSONDecodeError as exc:
    raise ValueError(f"COLUMN_MAPPING_JSON must be valid JSON: {exc}") from exc

# COMMAND ----------

raw = spark.table(SOURCE_TABLE)
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

required = ["name", "description", "capabilities", "procedures"]
missing_required = [field for field in required if not mapping[field]]
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

def source_expr(target, cast_type="string"):
    source = mapping.get(target)
    if not source:
        return F.lit(None).cast(cast_type)
    return F.col(source).cast(cast_type)

# Deterministic content hash fallback for lineage.
raw_struct = F.struct(*[F.col(c).alias(c) for c in sorted(raw.columns)])
raw_hash = F.sha2(F.to_json(raw_struct, options={"ignoreNullFields": "false"}), 256)

if mapping["raw_row_ref"]:
    upstream_ref = F.col(mapping["raw_row_ref"]).cast("string")
    raw_row_ref_expr = F.when(
        upstream_ref.isNotNull() & (F.length(F.trim(upstream_ref)) > 0),
        upstream_ref
    ).otherwise(raw_hash)
else:
    raw_row_ref_expr = raw_hash

lat_raw = source_expr("latitude", "double")
lon_raw = source_expr("longitude", "double")

lat_valid = F.when(
    lat_raw.between(-90.0, 90.0) & ~(lat_raw == F.lit(0.0)),
    lat_raw
)
lon_valid = F.when(
    lon_raw.between(-180.0, 180.0) & ~(lon_raw == F.lit(0.0)),
    lon_raw
)

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

identity_material = F.concat_ws(
    "||",
    F.coalesce(F.col("raw_row_ref"), F.lit("")),
    F.coalesce(F.col("name"), F.lit("")),
    F.coalesce(F.col("city"), F.lit("")),
    F.coalesce(F.col("state"), F.lit("")),
    F.coalesce(F.col("pin"), F.lit("")),
    F.coalesce(F.col("latitude").cast("string"), F.lit("")),
    F.coalesce(F.col("longitude").cast("string"), F.lit("")),
)

prepared = base.withColumn("facility_id", F.sha2(identity_material, 256)).select(
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
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OUTPUT_TABLE)
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
