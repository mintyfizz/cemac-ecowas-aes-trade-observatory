"""Validate the hosted dashboard's Databricks data contract.

Requires Databricks environment variables:
  DATABRICKS_HOST
  DATABRICKS_HTTP_PATH
  DATABRICKS_TOKEN
  DATABRICKS_CATALOG
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.databricks_sql import CATALOG, query


EXPECTED_COUNTS = {
    "gold.dashboard_country_timeseries": 735,
    "gold.dashboard_fragility_components": 21,
    "gold.dashboard_bloc_comparison": 71,
}

REQUIRED_NONZERO = [
    "gold.dashboard_top_trade_partners",
    "gold.dashboard_conflict_hotspots",
    "gold.product_trade_hs2",
]

MACRO_SCALE_MIN_USD = 1e11
MACRO_SCALE_MAX_USD = 1e12


def table_count(table_name: str) -> int:
    rows = query(f"SELECT COUNT(*) AS rows FROM {CATALOG}.{table_name}")
    return int(rows[0]["rows"])


def main() -> int:
    failures: list[str] = []

    for table_name, expected in EXPECTED_COUNTS.items():
        actual = table_count(table_name)
        print(f"{table_name}: {actual} rows")
        if actual != expected:
            failures.append(f"{table_name}: expected {expected}, got {actual}")

    for table_name in REQUIRED_NONZERO:
        actual = table_count(table_name)
        print(f"{table_name}: {actual} rows")
        if actual <= 0:
            failures.append(f"{table_name}: expected nonzero rows, got {actual}")

    coverage = query(
        f"""
        SELECT
          COUNT(DISTINCT country_iso3) AS countries,
          MIN(year) AS min_year,
          MAX(year) AS max_year,
          COUNT(*) AS rows
        FROM {CATALOG}.gold.dashboard_country_timeseries
        """
    )[0]
    print(
        "country timeseries coverage: "
        f"{coverage['countries']} countries, "
        f"{coverage['min_year']}-{coverage['max_year']}, "
        f"{coverage['rows']} rows"
    )

    aggregate_partners = query(
        f"""
        SELECT COUNT(*) AS rows
        FROM {CATALOG}.gold.dashboard_top_trade_partners
        WHERE counterpart_iso3 NOT RLIKE '^[A-Z]{{3}}$'
        """
    )[0]["rows"]
    print(f"aggregate partner rows present in raw top-partner mart: {aggregate_partners}")
    print("Static export filters aggregate partner rows out of public top-partner panels.")

    macro_anchor = query(
        f"""
        SELECT year, gdp_current_usd
        FROM {CATALOG}.silver.fact_macro_annual
        WHERE country_iso3 = 'NGA'
          AND gdp_current_usd IS NOT NULL
        ORDER BY year DESC
        LIMIT 1
        """
    )
    if not macro_anchor:
        failures.append("silver.fact_macro_annual: missing NGA GDP scale anchor row")
    else:
        anchor = macro_anchor[0]
        gdp_usd = float(anchor["gdp_current_usd"])
        print(f"NGA GDP scale anchor: {anchor['year']} = {gdp_usd / 1e9:,.0f}B USD")
        if not (MACRO_SCALE_MIN_USD < gdp_usd < MACRO_SCALE_MAX_USD):
            failures.append(
                "silver.fact_macro_annual: NGA gdp_current_usd scale looks wrong "
                f"({gdp_usd}; expected 1e11-1e12 USD)"
            )

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nDashboard data contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
