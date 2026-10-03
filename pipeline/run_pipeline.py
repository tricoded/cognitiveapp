"""
Run the warehouse end to end for a date range.

    python -m pipeline.run_pipeline                       # whole simulated range
    python -m pipeline.run_pipeline --start 2026-06-10 --end 2026-06-20
    python -m pipeline.run_pipeline --layers dws,ads      # rebuild only some layers
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from pipeline.quality.checks import run_all
from pipeline.spark.jobs import Warehouse, date_range, get_spark

LAYERS = ["ods", "dwd", "dws", "ads", "dq"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="pipeline_data")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--layers", default=",".join(LAYERS))
    a = ap.parse_args()

    root = Path(a.root)
    manifest = json.loads((root / "raw" / "_manifest.json").read_text())
    all_dts = sorted(p.name[3:] for p in (root / "raw" / "events").glob("dt=*"))
    start = a.start or all_dts[0]
    end = a.end or all_dts[-1]
    layers = a.layers.split(",")

    spark = get_spark()
    spark.sparkContext.setLogLevel("WARN")
    wh = Warehouse(spark, root)
    print(f"Warehouse {root}/warehouse  range {start} -> {end}  layers {layers}")

    for layer in LAYERS:
        if layer not in layers:
            continue
        t0 = time.time()
        if layer == "dq":
            alerts = run_all(wh, all_dts[0], end, date_range(start, end), root / "reports")
            print(f"  [dq ] {len(alerts)} alerts  ({time.time() - t0:.1f}s)")
            for check, n in Counter(x.check for x in alerts).items():
                print(f"         {check:<16} {n}")
            injected = manifest.get("injected_defects", {})
            caught = {dt: kind for dt, kind in injected.items() if any(x.dt == dt for x in alerts)}
            print(f"         injected defects caught: {len(caught)}/{len(injected)}")
            continue
        n = getattr(wh, f"build_{layer}")(start, end)
        print(f"  [{layer}] {n:>10,} rows  ({time.time() - t0:.1f}s)")

    spark.stop()


if __name__ == "__main__":
    main()
