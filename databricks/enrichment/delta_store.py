"""Databricks adapter. Imports Spark only when used on supported compute."""
import json
import re

from common import IDS, canonical, digest, empty, require
from validation import validator


def identifier(value, parts=1):
    require(isinstance(value, str), "identifier", "string required")
    pieces = value.split(".")
    require(len(pieces) == parts and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p) for p in pieces),
            "identifier", f"expected {parts} simple catalog/schema/table identifier components")
    return ".".join(f"`{p}`" for p in pieces)


def volume_path(value):
    from pathlib import PurePosixPath
    require(isinstance(value, str) and value.startswith("/Volumes/") and "\\" not in value
            and "\x00" not in value and ".." not in value.split("/"), "path", "absolute Unity Catalog Volume path required")
    path = PurePosixPath(value)
    require(len(path.parts) >= 6, "path", "expected /Volumes/catalog/schema/volume/file")
    for part in path.parts[2:5]:
        identifier(part)
    return str(path)


def spark_type(spec, definitions):
    from pyspark.sql import types as T
    if "$ref" in spec:
        return spark_type(definitions[spec["$ref"].split("/")[-1]], definitions)
    if "anyOf" in spec:
        return spark_type(next(s for s in spec["anyOf"] if s.get("type") != "null"), definitions)
    kind = spec.get("type", "string")
    if kind == "object":
        return T.StructType([T.StructField(k, spark_type(v, definitions), True) for k, v in spec["properties"].items()])
    if kind == "array":
        return T.ArrayType(spark_type(spec["items"], definitions), False)
    return T.DoubleType() if kind == "number" else T.StringType()


def table_schema(table):
    from pyspark.sql import types as T
    schema = validator().schema
    row_spec = schema["properties"][table]["items"]
    result = spark_type(row_spec, schema["$defs"])
    return T.StructType([T.StructField("_attempt_id", T.StringType(), False),
                         T.StructField("_payload_json", T.StringType(), False)] + result.fields)


def spark_value(value, data_type):
    from pyspark.sql import types as T
    if value is None:
        return None
    if isinstance(data_type, T.DoubleType):
        return float(value)
    if isinstance(data_type, T.StructType):
        return {f.name: spark_value(value[f.name], f.dataType) for f in data_type.fields}
    if isinstance(data_type, T.ArrayType):
        return [spark_value(v, data_type.elementType) for v in value]
    return value


class DeltaStore:
    def __init__(self, spark, catalog, schema):
        self.spark = spark
        self.prefix = identifier(catalog) + "." + identifier(schema)
        self.state_table = self.prefix + ".`enrichment_publication`"

    def table(self, name):
        require(name in IDS, "table", "unknown evidence table")
        return self.prefix + "." + identifier(name)

    def initialize(self):
        """Bootstrap once before concurrent publishers. Never touches source tables."""
        for table in IDS:
            # Creating an empty Delta table is schema-explicit, including null-only arrays.
            self.spark.createDataFrame([], table_schema(table)).write.format("delta").mode("ignore").saveAsTable(self.table(table))
        self.spark.sql(f"CREATE TABLE IF NOT EXISTS {self.state_table} (singleton INT, revision BIGINT, state_json STRING) USING DELTA")
        # Bootstrap is an operator-serialized step. A second call leaves state intact.
        if self.spark.table(self.state_table).count() == 0:
            self.spark.sql(f"INSERT INTO {self.state_table} VALUES (1, 0, :state)",
                           args={"state": canonical({"current_run": None, "runs": {}})})
        self.read_state()  # Fail closed if bootstrap was mistakenly run concurrently.

    def read_state(self):
        rows = self.spark.table(self.state_table).collect()
        require(len(rows) == 1 and rows[0]["singleton"] == 1, "publication",
                "expected exactly one operational state row; initialize once, never concurrently")
        return rows[0]["revision"], json.loads(rows[0]["state_json"])

    def write_stage(self, table, attempt, rows):
        schema = table_schema(table)
        data = [{"_attempt_id": attempt, "_payload_json": canonical(row), **row} for row in rows]
        data = [spark_value(row, schema) for row in data]
        self.spark.createDataFrame(data, schema).write.format("delta").mode("append").saveAsTable(self.table(table))
        return int(self.spark.sql(f"DESCRIBE HISTORY {self.table(table)} LIMIT 1").first()["version"])

    def read_completed(self, manifest):
        from pyspark.sql import functions as F
        result = empty()
        for table, key in IDS.items():
            frame = self.spark.read.option("versionAsOf", int(manifest["table_versions"][table])).table(self.table(table))
            rows = frame.where(F.col("_attempt_id") == F.lit(manifest["attempt_id"])).collect()
            for row in rows:
                payload = json.loads(row["_payload_json"])
                typed = row.asDict(recursive=True)
                require(all(typed[k] == v for k, v in payload.items()), table,
                        "typed columns disagree with lossless payload")
                result[table].append(payload)
            result[table].sort(key=lambda row: row[key])
        if "batch_sha256" in manifest:
            require(digest(result) == manifest["batch_sha256"], "publication", "completed table payload/hash mismatch")
        return result

    def compare_and_swap(self, revision, state):
        # Values are bound. Only validated/quoted table names enter SQL text.
        self.spark.sql(f"UPDATE {self.state_table} SET revision = :new_revision, state_json = :state "
                       "WHERE singleton = 1 AND revision = :expected_revision",
                       args={"new_revision": revision + 1, "expected_revision": revision, "state": canonical(state)})
        _, observed = self.read_state()
        run_id = state["current_run"]
        # A later successful publication may already have advanced the pointer.
        return observed["runs"].get(run_id) == state["runs"][run_id]
