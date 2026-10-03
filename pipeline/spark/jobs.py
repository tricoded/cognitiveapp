"""
PySpark jobs for the layered AI-usage warehouse.

    raw JSONL ──► ODS ──► DWD ──► DWS ──► ADS (features, CDI)
                  typed   clean    user×day  rolling 7d / model-ready

Every table is Parquet, partitioned Hive-style by `dt`, and written with
dynamic partition overwrite, so re-running a date range is idempotent.
The transformation logic lives in ./sql/*.sql; this module only wires
inputs/outputs.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

SQL_DIR = Path(__file__).parent / "sql"

# Contract for raw events. Includes the drifted column name so a schema change
# is *absorbed and reported* instead of silently turning msg_len into NULL.
RAW_SCHEMA = T.StructType([
    T.StructField("event_id", T.StringType()),
    T.StructField("user_id", T.StringType()),
    T.StructField("device_id", T.StringType()),
    T.StructField("platform", T.StringType()),
    T.StructField("event_type", T.StringType()),
    T.StructField("event_ts", T.StringType()),
    T.StructField("client_ts", T.StringType()),
    T.StructField("tz_offset", T.IntegerType()),
    T.StructField("session_id", T.StringType()),
    T.StructField("msg_len", T.IntegerType()),
    T.StructField("message_length", T.IntegerType()),   # v1.1 name
    T.StructField("has_code", T.BooleanType()),
    T.StructField("is_question", T.BooleanType()),
    T.StructField("is_reask", T.BooleanType()),
    T.StructField("prompt_kind", T.StringType()),
    T.StructField("category", T.StringType()),
    T.StructField("app_version", T.StringType()),
])


def get_spark(app_name: str = "cognitive-warehouse") -> SparkSession:
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    return (
        SparkSession.builder
        .appName(app_name)
        .master(os.getenv("SPARK_MASTER", "local[*]"))
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", os.getenv("SPARK_SHUFFLE_PARTITIONS", "16"))
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "3g"))
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def date_range(start: str, end: str) -> list[str]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


class Warehouse:
    def __init__(self, spark: SparkSession, root: str | Path):
        self.spark = spark
        self.root = Path(root)
        self.raw = self.root / "raw" / "events"
        self.wh = self.root / "warehouse"

    # ── io helpers ──────────────────────────────────────────────────────────
    def path(self, table: str) -> str:
        return str(self.wh / table)

    def read(self, table: str, start: str | None = None, end: str | None = None) -> DataFrame:
        # Spark infers `dt=2026-06-01` partitions as DATE; keep dt a string everywhere
        df = self.spark.read.parquet(self.path(table)).withColumn("dt", F.col("dt").cast("string"))
        if start:
            df = df.where(F.col("dt") >= start)
        if end:
            df = df.where(F.col("dt") <= end)
        return df

    def write(self, df: DataFrame, table: str) -> int:
        df = df.withColumn("dt", F.col("dt").cast("string"))
        df.write.mode("overwrite").partitionBy("dt").parquet(self.path(table))
        return self.read(table).where(F.col("dt").isin(
            [r.dt for r in df.select("dt").distinct().collect()]
        )).count()

    def run_sql(self, name: str) -> DataFrame:
        return self.spark.sql((SQL_DIR / f"{name}.sql").read_text(encoding="utf-8"))

    # ── layers ──────────────────────────────────────────────────────────────
    def build_ods(self, start: str, end: str) -> int:
        paths = [str(self.raw / f"dt={d}") for d in date_range(start, end) if (self.raw / f"dt={d}").exists()]
        raw = (
            self.spark.read.schema(RAW_SCHEMA)
            .option("basePath", str(self.raw))
            .json(paths)
        )
        # dt comes from the partition directory
        raw = raw.withColumn("dt", F.regexp_extract(F.input_file_name(), r"dt=(\d{4}-\d{2}-\d{2})", 1))
        ods = raw.select(
            "event_id", "user_id", "device_id", "platform", "event_type",
            F.to_timestamp("event_ts").alias("event_ts"),
            F.to_timestamp("client_ts").alias("client_ts"),
            "tz_offset", "session_id",
            F.coalesce("msg_len", "message_length").alias("msg_len"),
            "has_code", "is_question", "is_reask", "prompt_kind", "category",
            F.coalesce("app_version", F.lit("unknown")).alias("app_version"),
            "dt",
        )
        return self.write(ods, "ods_ai_events")

    def build_dwd(self, start: str, end: str) -> int:
        ods = self.read("ods_ai_events", start, end)
        ods.createOrReplaceTempView("ods_ai_events")
        # quarantine rather than silently drop — DQ reports on it
        quarantine = ods.where(F.col("user_id").isNull() | F.col("event_ts").isNull())
        self.write(quarantine, "dwd_ai_events_quarantine")
        return self.write(self.run_sql("dwd_ai_events_di"), "dwd_ai_events_di")

    def build_dws(self, start: str, end: str) -> int:
        self.read("dwd_ai_events_di", start, end).createOrReplaceTempView("dwd_ai_events_di")
        return self.write(self.run_sql("dws_user_ai_1d"), "dws_user_ai_1d")

    def build_ads(self, start: str, end: str) -> int:
        lookback = (date.fromisoformat(start) - timedelta(days=6)).isoformat()
        self.read("dws_user_ai_1d", lookback, end).createOrReplaceTempView("dws_user_ai_1d")
        feats = self.run_sql("ads_user_features_1d").where(F.col("dt") >= start)
        n = self.write(feats, "ads_user_features_1d")

        self.read("ads_user_features_1d", start, end).createOrReplaceTempView("ads_user_features_1d")
        self.write(self.run_sql("ads_user_cdi_1d"), "ads_user_cdi_1d")
        return n
