#!/usr/bin/env python3
"""Export Databricks gold tables to static JSON files for GitHub Pages.

Usage:
    python scripts/export_static.py

Environment variables (same ones used by the FastAPI backend):
    DATABRICKS_HOST          e.g. dbc-xxxx.cloud.databricks.com
    DATABRICKS_HTTP_PATH     e.g. /sql/1.0/warehouses/xxxx
    DATABRICKS_TOKEN         Databricks personal access token
    DATABRICKS_CATALOG       (optional, default: cemac_ecowas_aes_trade)

Writes five JSON files to static/data/:
    country_timeseries.json
    top_trade_partners.json
    conflict_hotspots.json
    fragility_components.json
    bloc_comparison.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Reuse the existing db helper so connection logic stays in one place.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.db import query as dbq, CATALOG  # noqa: E402

OUT = ROOT / "static" / "data"
OUT.mkdir(parents=True, exist_ok=True)

TABLES: dict[str, str] = {
    "country_timeseries": f"SELECT * FROM {CATALOG}.gold.dashboard_country_timeseries",
    "top_trade_partners": f"SELECT * FROM {CATALOG}.gold.dashboard_top_trade_partners",
    "conflict_hotspots":  f"SELECT * FROM {CATALOG}.gold.dashboard_conflict_hotspots",
    "fragility_components": f"SELECT * FROM {CATALOG}.gold.dashboard_fragility_components",
    "bloc_comparison":    f"SELECT * FROM {CATALOG}.gold.dashboard_bloc_comparison",
}


def main() -> None:
    for name, sql in TABLES.items():
        print(f"Exporting {name}...", end=" ", flush=True)
        rows = dbq(sql)
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(rows, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"{len(rows):,} rows → {path.relative_to(ROOT)}")
    print("Done.")


if __name__ == "__main__":
    main()
