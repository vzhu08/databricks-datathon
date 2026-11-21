"""Run the baseline Databricks notebook against synthetic local Spark/Delta tables."""
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace

from pyspark.sql import SparkSession

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "databricks/ingest/01_prepare_virtue_facilities.py"


def run_notebook(spark, source, destination):
    params = {"SOURCE_TABLE": f"spark_catalog.default.{source}",
              "OUTPUT_TABLE": f"spark_catalog.default.{destination}", "repo_root": str(ROOT)}
    widgets = SimpleNamespace(text=lambda name, default, label: params.setdefault(name, default),
                              get=params.__getitem__)
    runpy.run_path(str(NOTEBOOK), init_globals={
        "spark": spark, "dbutils": SimpleNamespace(widgets=widgets), "display": lambda frame: None,
    })


def expect_refusal(spark, source, destination, message):
    try:
        run_notebook(spark, source, destination)
    except ValueError as error:
        assert message in str(error), error
    else:
        raise AssertionError(f"Expected refusal for {source} -> {destination}")


def verify(spark):
    schema = "id string, name string, city string, latitude string, longitude string, procedures array<string>, source_urls array<string>"
    rows = [("001", "Example", "Jaipur", "0", "75", ["Dialysis."], ["https://example.invalid/a"]),
            ("002", "Example", "Jaipur", "bad", "75", ["MRI."], [])]
    spark.createDataFrame(rows, schema).write.saveAsTable("input_facilities")
    run_notebook(spark, "input_facilities", "prepared")
    result = {r.facility_id: r for r in spark.table("prepared").collect()}
    assert set(result) == {"001", "002"}
    assert result["001"].raw_row_ref == "001" and result["001"].latitude == 0
    assert result["001"].procedures == ["Dialysis."] and result["001"].record_source_urls == rows[0][-1]
    assert result["002"].latitude is None and result["002"].longitude is None
    expect_refusal(spark, "input_facilities", "prepared", "already exists")
    expect_refusal(spark, "input_facilities", "INPUT_FACILITIES", "distinct")
    source = spark.table("input_facilities")
    assert {tuple(r[:5]) for r in source.collect()} == {r[:5] for r in rows}
    source.drop("id").write.saveAsTable("without_ids")
    run_notebook(spark, "without_ids", "with_surrogates")
    from source_inspection import map_base
    source_rows = [r.asDict(recursive=True) for r in spark.table("without_ids").collect()]
    expected = map_base(source_rows, None, "spark_catalog.default.without_ids", allow_surrogate=True)
    assert {r.facility_id for r in spark.table("with_surrogates").collect()} == {r["facility_id"] for r in expected}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as warehouse:
        spark = (SparkSession.builder.master("local[2]").appName("synthetic-baseline-prep")
                 .config("spark.sql.warehouse.dir", warehouse)
                 .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
                 .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
                 .config("spark.sql.ansi.enabled", "true")
                 .config("spark.sql.shuffle.partitions", "2")
                 .config("spark.databricks.delta.snapshotPartitions", "2")
                 .config("spark.ui.enabled", "false").getOrCreate())
        try:
            verify(spark)
            print("Synthetic Spark/Delta smoke passed.")
        finally:
            spark.stop()
