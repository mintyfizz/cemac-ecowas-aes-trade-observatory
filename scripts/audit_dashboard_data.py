#!/usr/bin/env python3
"""Audit dashboard data contracts and static JSON exports.

The script is read-only. It validates the exported GitHub Pages datasets and,
when Databricks credentials are available, cross-checks the gold tables that
feed those exports.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.databricks_sql import CATALOG, query as dbq
except Exception:  # pragma: no cover - import failure is reported at runtime
    CATALOG = os.getenv("DATABRICKS_CATALOG", "cemac_ecowas_aes_trade")
    dbq = None


REQUIRED_FILES = {
    "country_timeseries": "country_timeseries.json",
    "top_trade_partners": "top_trade_partners.json",
    "conflict_hotspots": "conflict_hotspots.json",
    "fragility_components": "fragility_components.json",
    "bloc_comparison": "bloc_comparison.json",
    "product_trade_hs2": "product_trade_hs2.json",
}

SOURCE_TABLES = {
    "country_timeseries": "gold.dashboard_country_timeseries",
    "top_trade_partners": "gold.dashboard_top_trade_partners",
    "conflict_hotspots": "gold.dashboard_conflict_hotspots",
    "fragility_components": "gold.dashboard_fragility_components",
    "bloc_comparison": "gold.dashboard_bloc_comparison",
    "product_trade_hs2": "gold.product_trade_hs2",
}

PANEL_MAPPING = [
    ("Overview cards", "country_timeseries, top_trade_partners, fragility_components", "Selected bloc/country and selected year."),
    ("Map", "country_timeseries", "Selected year only; metric selector changes the rendered value."),
    ("Top trading partners", "top_trade_partners", "ISO3 partners only; aggregate rows are filtered out of displayed outputs."),
    ("Two-partner comparison", "top_trade_partners", "Partner share uses full total trade denominator from country_timeseries."),
    ("Partner concentration", "country_timeseries, bloc_comparison", "HHI trend; selected country gets its own history."),
    ("Trade openness trend", "bloc_comparison", "Exports plus imports as percent of GDP."),
    ("Trade growth indexed to 1990", "country_timeseries", "Total trade rebased to 1990 = 100; nulls remain gaps."),
    ("Trade exposure profile", "country_timeseries", "Exports, imports, and balance as percent of GDP."),
    ("Product trade structure", "product_trade_hs2", "Selected year only; empty state when selected-year HS2 coverage is absent."),
    ("Conflict", "conflict_hotspots", "Bloc view shows countries; country drilldown shows admin1 hotspots."),
    ("Fragility", "fragility_components", "Latest available FSI components, not true 2024 coverage when 2024 source is absent."),
    ("Pipeline health", "all exported static JSON", "Row counts and coverage metadata from exported datasets."),
]


class Audit:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.sections: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    @property
    def status(self) -> str:
        if self.failures:
            return "FAIL"
        if self.warnings:
            return "WARN"
        return "PASS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-dir", default=str(ROOT / "static" / "data"))
    parser.add_argument("--report", default=str(ROOT / "docs" / "dashboard_data_audit.md"))
    parser.add_argument("--static-only", action="store_true", help="Skip live Databricks checks.")
    parser.add_argument("--check-only", action="store_true", help="Validate and exit without writing a report.")
    return parser.parse_args()


def read_static(static_dir: Path, audit: Audit) -> dict[str, list[dict[str, Any]]]:
    datasets: dict[str, list[dict[str, Any]]] = {}
    for name, filename in REQUIRED_FILES.items():
        path = static_dir / filename
        if not path.exists():
            audit.fail(f"Missing required static dataset: {path.relative_to(ROOT)}")
            datasets[name] = []
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            audit.fail(f"Invalid JSON in {path.relative_to(ROOT)}: {exc}")
            datasets[name] = []
            continue
        if not isinstance(data, list):
            audit.fail(f"{path.relative_to(ROOT)} must contain a JSON array.")
            datasets[name] = []
            continue
        datasets[name] = data
    return datasets


def year_range(rows: list[dict[str, Any]]) -> str:
    years = [
        int(row["year"])
        for row in rows
        if isinstance(row.get("year"), int | float) and not isinstance(row.get("year"), bool)
    ]
    return f"{min(years)}-{max(years)}" if years else "n/a"


def distinct(rows: list[dict[str, Any]], *keys: str) -> int:
    values: set[Any] = set()
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                values.add(value)
                break
    return len(values)


def num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def close(a: float | None, b: float | None, tolerance: float) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= tolerance


def validate_country_timeseries(rows: list[dict[str, Any]], audit: Audit) -> None:
    if not rows:
        audit.fail("country_timeseries has no rows.")
        return

    key_counts = Counter((row.get("country_iso3"), row.get("year")) for row in rows)
    duplicate_keys = [key for key, count in key_counts.items() if count > 1]
    if duplicate_keys:
        audit.fail(f"country_timeseries has duplicate (country_iso3, year) keys: {duplicate_keys[:5]}")

    if len(rows) != 735:
        audit.fail(f"country_timeseries expected 735 rows, found {len(rows)}.")
    if distinct(rows, "country_iso3") != 21:
        audit.fail(f"country_timeseries expected 21 countries, found {distinct(rows, 'country_iso3')}.")
    years = sorted({
        int(row["year"])
        for row in rows
        if isinstance(row.get("year"), int | float) and not isinstance(row.get("year"), bool)
    })
    if years[:1] != [1990] or years[-1:] != [2024]:
        audit.fail(f"country_timeseries expected years 1990-2024, found {year_range(rows)}.")

    formula_counts = Counter()
    for row in rows:
        exports = num(row.get("exports_billions_usd"))
        imports = num(row.get("imports_billions_usd"))
        total = num(row.get("total_trade_billions_usd"))
        balance = num(row.get("trade_balance_billions_usd"))
        gdp = num(row.get("gdp_current_usd_billions"))
        pop = num(row.get("population_millions"))
        openness = num(row.get("trade_openness_pct_gdp"))
        exports_pct = num(row.get("exports_pct_gdp"))
        imports_pct = num(row.get("imports_pct_gdp"))
        gdp_pc = num(row.get("gdp_per_capita_current_usd"))
        hhi = num(row.get("total_trade_partner_hhi"))

        if exports is not None and imports is not None and not close(total, exports + imports, 0.05):
            formula_counts["total_trade"] += 1
        if exports is not None and imports is not None and not close(balance, exports - imports, 0.05):
            formula_counts["trade_balance"] += 1
        if total is not None and gdp not in (None, 0) and not close(openness, total / gdp * 100, 0.2):
            formula_counts["openness"] += 1
        if exports is not None and gdp not in (None, 0) and not close(exports_pct, exports / gdp * 100, 0.2):
            formula_counts["exports_pct"] += 1
        if imports is not None and gdp not in (None, 0) and not close(imports_pct, imports / gdp * 100, 0.2):
            formula_counts["imports_pct"] += 1
        if gdp is not None and pop not in (None, 0) and not close(gdp_pc, gdp / pop * 1000, 5.0):
            formula_counts["gdp_per_capita"] += 1
        if hhi is not None and not (0 <= hhi <= 1):
            formula_counts["hhi_range"] += 1

    for formula, count in formula_counts.items():
        audit.fail(f"country_timeseries formula check failed for {formula}: {count} rows.")

    if not formula_counts:
        audit.note("country_timeseries formula checks passed.")


def validate_partners(rows: list[dict[str, Any]], audit: Audit) -> None:
    if not rows:
        audit.fail("top_trade_partners has no rows.")
        return
    aggregate_rows = [
        row for row in rows
        if not re.fullmatch(r"[A-Z]{3}", str(row.get("counterpart_iso3", "")))
    ]
    if aggregate_rows:
        audit.warn(
            f"top_trade_partners contains {len(aggregate_rows):,} raw aggregate/non-ISO partner rows; "
            "static rendering filters them from displayed partner panels."
        )

    bad_shares = [
        row for row in rows
        if (share := num(row.get("total_trade_partner_share_pct"))) is not None and not (0 <= share <= 100)
    ]
    if bad_shares:
        audit.fail(f"Partner share outside 0-100% in {len(bad_shares)} rows.")


def validate_fragility(rows: list[dict[str, Any]], audit: Audit) -> None:
    if not rows:
        audit.fail("fragility_components has no rows.")
        return
    if distinct(rows, "country_iso3") != 21:
        audit.fail(f"fragility_components expected 21 countries, found {distinct(rows, 'country_iso3')}.")
    years = [
        int(row["fsi_year"])
        for row in rows
        if isinstance(row.get("fsi_year"), int | float) and not isinstance(row.get("fsi_year"), bool)
    ]
    if years:
        latest = max(years)
        audit.note(f"Latest available FSI year in export: {latest}.")
        if latest < 2024:
            audit.warn("FSI is latest-available coverage, not true 2024 coverage.")


def validate_bloc(rows: list[dict[str, Any]], audit: Audit) -> None:
    if not rows:
        audit.fail("bloc_comparison has no rows.")
        return
    if distinct(rows, "analytical_bloc_code") != 3:
        audit.fail(f"bloc_comparison expected 3 blocs, found {distinct(rows, 'analytical_bloc_code')}.")
    if year_range(rows) == "n/a":
        audit.fail("bloc_comparison has no usable year coverage.")


def validate_products(rows: list[dict[str, Any]], audit: Audit) -> None:
    if not rows:
        audit.fail("product_trade_hs2 has no rows.")
        return
    bad_flows = sorted({row.get("flow_type") for row in rows if row.get("flow_type") not in {"export", "import"}})
    if bad_flows:
        audit.fail(f"product_trade_hs2 has invalid flow_type values: {bad_flows}.")
    bad_codes = [
        row.get("hs2_code") for row in rows
        if not re.fullmatch(r"[0-9]{2}", str(row.get("hs2_code", "")))
    ]
    if bad_codes:
        audit.fail(f"product_trade_hs2 has invalid HS2 codes in {len(bad_codes)} rows.")
    audit.note(
        "product_trade_hs2 coverage: "
        f"{len(rows):,} rows, {distinct(rows, 'reporter_iso3')} reporters, years {year_range(rows)}."
    )


def validate_static(datasets: dict[str, list[dict[str, Any]]], audit: Audit) -> None:
    validate_country_timeseries(datasets.get("country_timeseries", []), audit)
    validate_partners(datasets.get("top_trade_partners", []), audit)
    validate_fragility(datasets.get("fragility_components", []), audit)
    validate_bloc(datasets.get("bloc_comparison", []), audit)
    validate_products(datasets.get("product_trade_hs2", []), audit)


def databricks_creds_present() -> bool:
    return all(os.getenv(name) for name in ("DATABRICKS_HOST", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"))


def validate_live(audit: Audit) -> dict[str, int]:
    counts: dict[str, int] = {}
    if dbq is None:
        audit.fail("Cannot import scripts.databricks_sql query helper for live Databricks validation.")
        return counts
    for name, table in SOURCE_TABLES.items():
        result = dbq(f"SELECT COUNT(*) AS rows FROM {CATALOG}.{table}")
        counts[name] = int(result[0]["rows"])
    if counts.get("country_timeseries") != 735:
        audit.fail(f"Live country_timeseries expected 735 rows, found {counts.get('country_timeseries')}.")
    if counts.get("fragility_components") != 21:
        audit.fail(f"Live fragility_components expected 21 rows, found {counts.get('fragility_components')}.")
    if counts.get("product_trade_hs2", 0) <= 0:
        audit.fail("Live product_trade_hs2 has no rows.")
    return counts


def static_summary_table(datasets: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        "| Dataset | Source table | Rows | Years | Countries/reporters | Blocs |",
        "| --- | --- | ---: | --- | ---: | ---: |",
    ]
    for name, filename in REQUIRED_FILES.items():
        rows = datasets.get(name, [])
        lines.append(
            f"| `{filename}` | `{SOURCE_TABLES[name]}` | {len(rows):,} | {year_range(rows)} | "
            f"{distinct(rows, 'country_iso3', 'reporter_iso3')} | {distinct(rows, 'analytical_bloc_code')} |"
        )
    return "\n".join(lines)


def mapping_table() -> str:
    lines = [
        "| Panel | Data source | Interpretation rule |",
        "| --- | --- | --- |",
    ]
    for panel, source, rule in PANEL_MAPPING:
        lines.append(f"| {panel} | `{source}` | {rule} |")
    return "\n".join(lines)


def build_report(
    audit: Audit,
    datasets: dict[str, list[dict[str, Any]]],
    live_counts: dict[str, int],
    static_dir: Path,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    failure_list = "\n".join(f"- {item}" for item in audit.failures) or "- None"
    warning_list = "\n".join(f"- {item}" for item in audit.warnings) or "- None"
    note_list = "\n".join(f"- {item}" for item in audit.notes) or "- None"
    live_lines = "\n".join(
        f"- `{SOURCE_TABLES[name]}`: {count:,} rows" for name, count in live_counts.items()
    ) or "- Live Databricks validation was not run."

    return f"""# Dashboard Data Audit

Generated: {generated}

Status: **{audit.status}**

This audit covers the GitHub Pages static dashboard. The browser reads only
local files under `{static_dir.relative_to(ROOT)}`; Databricks remains the
source of truth for those exported files.

## Failures

{failure_list}

## Warnings

{warning_list}

## Notes

{note_list}

## Static Export Coverage

{static_summary_table(datasets)}

## Live Databricks Counts

{live_lines}

## Panel To Source Mapping

{mapping_table()}

## Formula Checks

Validated where source columns are available:

- `total_trade = exports + imports`
- `trade_balance = exports - imports`
- `trade_openness_pct_gdp = total_trade / GDP * 100`
- `exports_pct_gdp = exports / GDP * 100`
- `imports_pct_gdp = imports / GDP * 100`
- `gdp_per_capita = GDP billions / population millions * 1000`
- `total_trade_partner_hhi` is constrained to `[0, 1]`

Missing inputs remain null. They must not be rendered as zero.

## Known Gaps And Interpretation Notes

- FSI should be read as latest-available coverage. If 2024 FSI is missing,
  the dashboard must not imply a true 2024 FSI release.
- ACLED hotspot panels use the latest loaded 3-year window, not necessarily a
  single selected calendar year.
- Product sectors use `gold.product_trade_hs2` only where selected-year HS2
  coverage exists. Missing product years are displayed as gaps.
- Macro-fiscal pressure is a normalized dashboard diagnostic, not an official
  credit rating, sovereign rating, or debt sustainability assessment.
- Partner panels filter non-ISO aggregate partner rows from displayed outputs.

## Fix Priorities

1. Keep `static/index.html`, `static/css/styles.css`, `static/js/charts.js`,
   and `static/js/app_static.js` aligned before every GitHub Pages deployment.
2. Re-run `scripts/export_static.py` after gold tables change.
3. Re-run this audit before publishing and investigate any failure.
"""


def main() -> int:
    args = parse_args()
    audit = Audit()
    static_dir = Path(args.static_dir).resolve()
    report_path = Path(args.report).resolve()

    datasets = read_static(static_dir, audit)
    validate_static(datasets, audit)

    live_counts: dict[str, int] = {}
    if args.static_only:
        audit.note("Live Databricks validation skipped by --static-only.")
    elif databricks_creds_present():
        try:
            live_counts = validate_live(audit)
        except Exception as exc:
            audit.fail(f"Live Databricks validation failed: {exc}")
    else:
        message = "Live Databricks validation skipped: DATABRICKS_HOST, DATABRICKS_HTTP_PATH, or DATABRICKS_TOKEN is missing."
        if args.check_only:
            audit.fail(message)
        else:
            audit.warn(message)

    report = build_report(audit, datasets, live_counts, static_dir)
    if not args.check_only:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"Wrote {report_path.relative_to(ROOT)}")

    print(f"Dashboard data audit status: {audit.status}")
    for failure in audit.failures:
        print(f"FAIL: {failure}")
    for warning in audit.warnings:
        print(f"WARN: {warning}")

    return 1 if audit.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
