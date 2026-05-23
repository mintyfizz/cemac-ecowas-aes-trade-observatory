#!/usr/bin/env python3
"""Export Databricks gold tables to static JSON files for GitHub Pages.

Usage:
    python scripts/export_static.py

Environment variables:
    DATABRICKS_HOST          e.g. dbc-xxxx.cloud.databricks.com
    DATABRICKS_HTTP_PATH     e.g. /sql/1.0/warehouses/xxxx
    DATABRICKS_TOKEN         Databricks personal access token
    DATABRICKS_CATALOG       optional, default: cemac_ecowas_aes_trade

Writes six JSON files to static/data/:
    country_timeseries.json
    top_trade_partners.json
    conflict_hotspots.json
    fragility_components.json
    bloc_comparison.json
    product_trade_hs2.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.databricks_sql import CATALOG, query as dbq  # noqa: E402

OUT = ROOT / "static" / "data"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ExportSpec:
    source_table: str
    sql: str


TABLES: dict[str, ExportSpec] = {
    "country_timeseries": ExportSpec(
        source_table="gold.dashboard_country_timeseries",
        sql=f"SELECT * FROM {CATALOG}.gold.dashboard_country_timeseries",
    ),
    "top_trade_partners": ExportSpec(
        source_table="gold.dashboard_top_trade_partners",
        sql=f"""
            SELECT *
            FROM {CATALOG}.gold.dashboard_top_trade_partners
            WHERE counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
        """,
    ),
    "conflict_hotspots": ExportSpec(
        source_table="gold.dashboard_conflict_hotspots",
        sql=f"SELECT * FROM {CATALOG}.gold.dashboard_conflict_hotspots",
    ),
    "fragility_components": ExportSpec(
        source_table="gold.dashboard_fragility_components",
        sql=f"SELECT * FROM {CATALOG}.gold.dashboard_fragility_components",
    ),
    "bloc_comparison": ExportSpec(
        source_table="gold.dashboard_bloc_comparison",
        sql=f"SELECT * FROM {CATALOG}.gold.dashboard_bloc_comparison",
    ),
    "product_trade_hs2": ExportSpec(
        source_table="gold.product_trade_hs2",
        sql=f"SELECT * FROM {CATALOG}.gold.product_trade_hs2 WHERE flow_type IN ('export', 'import')",
    ),
}


def _year_range(rows: list[dict[str, Any]]) -> str:
    years = [row.get("year") for row in rows if isinstance(row.get("year"), int)]
    return f"{min(years)}-{max(years)}" if years else "n/a"


def _distinct(rows: list[dict[str, Any]], *keys: str) -> int | None:
    values: set[Any] = set()
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                values.add(value)
                break
    return len(values) if values else None


def _summary(name: str, spec: ExportSpec, rows: list[dict[str, Any]], path: Path) -> str:
    country_count = _distinct(rows, "country_iso3", "reporter_iso3")
    bloc_count = _distinct(rows, "analytical_bloc_code")
    parts = [
        f"{name}: {len(rows):,} rows",
        f"source={spec.source_table}",
        f"years={_year_range(rows)}",
    ]
    if country_count is not None:
        parts.append(f"countries/reporters={country_count}")
    if bloc_count is not None:
        parts.append(f"blocs={bloc_count}")
    parts.append(f"file={path.relative_to(ROOT)}")
    return " | ".join(parts)


def main() -> None:
    print("Exporting Databricks gold tables for static dashboard...")
    for name, spec in TABLES.items():
        rows = dbq(spec.sql)
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(rows, default=str, ensure_ascii=False), encoding="utf-8")
        print(_summary(name, spec, rows, path))
    print("Static export complete.")


if __name__ == "__main__":
    main()
