#!/usr/bin/env python3
"""
Local recovery path for bronze.imf_weo_raw and silver.fact_macro_annual.

Notebook 06 -> notebook 09 is the canonical WEO path. This script is only
for local recovery from the JSONL extract and must preserve the same scale
contract as notebook 09: gdp_current_usd is actual USD and
gdp_current_usd_billions is the dashboard display column.

Usage:
    python scripts/load_weo_silver.py

Reads Databricks config from environment variables first, then
~/.databrickscfg [cemac-project].
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from _dbx_config import dbx_config, require_dbx_config

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DBX = dbx_config()
HOST = DBX["host"]
WH_ID = DBX["warehouse"]
CAT = DBX["catalog"]
JSONL_PATH = "data/raw/weo/cemac_ecowas_weo_1990_2024.jsonl"
MACRO_SCALE_MIN_USD = 1e11
MACRO_SCALE_MAX_USD = 1e12

# WEO indicator code → silver column name
INDICATOR_COLUMNS: dict[str, str] = {
    "NGDPD":       "gdp_current_usd_billions",
    "LP":          "population_millions",
    "NGDPDPC":     "gdp_per_capita_current_usd",
    "NGDP_RPCH":   "real_gdp_growth_pct_imf",
    "PCPIPCH":     "inflation_cpi_pct",
    "GGXWDG_NGDP": "gross_debt_pct_gdp_imf",
    "GGR_NGDP":    "government_revenue_pct_gdp_imf",
    "GGX_NGDP":    "government_expenditure_pct_gdp_imf",
    "GGXCNL_NGDP": "net_lending_borrowing_pct_gdp_imf",
    "BCA_NGDPD":   "current_account_balance_pct_gdp_imf",
}

# ---------------------------------------------------------------------------
# Databricks SQL helpers (same pattern as load_comtrade_silver.py)
# ---------------------------------------------------------------------------

def _get_pat() -> str:
    return DBX["token"]


def _headers(pat: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pat}", "Content-Type": "application/json"}


def run_sql(pat: str, statement: str, timeout_s: int = 50) -> dict:
    """Submit a SQL statement and poll until finished."""
    url = f"https://{HOST}/api/2.0/sql/statements"
    payload = {
        "warehouse_id": WH_ID,
        "catalog": CAT,
        "wait_timeout": f"{min(timeout_s, 50)}s",
        "statement": statement,
    }
    resp = requests.post(url, headers=_headers(pat), json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    sid = data.get("statement_id")
    for _ in range(120):
        state = data.get("status", {}).get("state", "")
        if state == "SUCCEEDED":
            return data
        if state in ("FAILED", "CANCELED", "CLOSED"):
            err = data.get("status", {}).get("error", {})
            raise RuntimeError(f"SQL {state}: {err.get('message', data)}")
        if state in ("PENDING", "RUNNING") and sid:
            time.sleep(5)
            r = requests.get(
                f"https://{HOST}/api/2.0/sql/statements/{sid}",
                headers=_headers(pat),
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        else:
            break
    raise RuntimeError(f"SQL did not finish: {data}")


def rows_from(response: dict) -> list[list]:
    return response.get("result", {}).get("data_array", []) or []


def _escape(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def insert_batches(
    pat: str,
    full_table: str,
    columns: list[str],
    records: list[dict],
    batch_size: int = 200,
) -> None:
    total = len(records)
    for start in range(0, total, batch_size):
        batch = records[start : start + batch_size]
        vals = []
        for rec in batch:
            row = ", ".join(_escape(rec.get(c)) for c in columns)
            vals.append(f"({row})")
        stmt = f"INSERT INTO {full_table} ({', '.join(columns)}) VALUES {', '.join(vals)}"
        run_sql(pat, stmt)
        pct = min(start + batch_size, total)
        print(f"\r  {pct:,}/{total:,} ({pct*100//total}%)", end="", flush=True)
    print()


# ---------------------------------------------------------------------------
# Step 1: Load and pivot JSONL locally
# ---------------------------------------------------------------------------

def load_and_pivot(jsonl_path: str):
    """
    Read the WEO JSONL and pivot to one dict per (country_iso3, year).

    Scale contract, matching notebook 09:
      - gdp_current_usd stays at actual USD scale
      - population stays at persons scale
      - *_billions and *_millions columns are dashboard display columns
      - %GDP / growth / per-capita indicators are stored as published

    Returns (bronze_records, silver_records).
    """
    bronze_records = []
    # Store raw values per (iso3, year, indicator_code) before scaling
    raw_pivot: dict[tuple, dict] = {}  # (iso3, year) → {indicator_code: raw_value}

    print(f"Reading {jsonl_path} ...")
    with open(jsonl_path) as fh:
        for line in fh:
            row = json.loads(line)
            bronze_records.append(row)

            iso3 = row.get("country_iso3", "").upper().strip()
            year = int(row.get("year", 0))
            code = row.get("indicator_code", "").upper().strip()
            value = row.get("value")

            if not iso3 or not year or code not in INDICATOR_COLUMNS:
                continue

            key = (iso3, year)
            if key not in raw_pivot:
                raw_pivot[key] = {"country_iso3": iso3, "year": year}
            raw_pivot[key][code] = float(value) if value is not None else None

    # Derive display columns without rescaling the base facts.
    silver_records = []
    for (iso3, year), raw in sorted(raw_pivot.items()):
        ngdpd_raw = raw.get("NGDPD")        # actual USD
        lp_raw = raw.get("LP")              # persons
        debt_pct = raw.get("GGXWDG_NGDP")  # already % GDP (scale=0)

        gdp_b = ngdpd_raw / 1e9 if ngdpd_raw is not None else None  # USD billions
        pop_m = lp_raw / 1e6 if lp_raw is not None else None         # millions of persons
        gdp_usd = ngdpd_raw if ngdpd_raw is not None else None        # raw USD
        pop_raw = lp_raw if lp_raw is not None else None              # raw persons

        row = {
            "country_iso3": iso3,
            "year": year,
            # Scaled headline metrics
            "gdp_current_usd_billions":            gdp_b,
            "gdp_current_usd":                     gdp_usd,
            "gdp_per_capita_current_usd":          raw.get("NGDPDPC"),  # scale=0, USD
            "population_millions":                 pop_m,
            "population":                          pop_raw,
            # %GDP fiscal indicators — all scale=0, store as-is
            "real_gdp_growth_pct_imf":             raw.get("NGDP_RPCH"),
            "inflation_cpi_pct":                   raw.get("PCPIPCH"),
            "gross_debt_pct_gdp_imf":              debt_pct,
            "gross_debt_usd": (
                debt_pct / 100.0 * gdp_usd
                if debt_pct is not None and gdp_usd is not None else None
            ),
            "government_revenue_pct_gdp_imf":      raw.get("GGR_NGDP"),
            "government_expenditure_pct_gdp_imf":  raw.get("GGX_NGDP"),
            "net_lending_borrowing_pct_gdp_imf":   raw.get("GGXCNL_NGDP"),
            "current_account_balance_pct_gdp_imf": raw.get("BCA_NGDPD"),
        }
        silver_records.append(row)

    reporters = sorted({r.get("country_iso3", "") for r in bronze_records})
    indicators = sorted({r.get("indicator_code", "") for r in bronze_records})
    print(f"  Bronze records: {len(bronze_records):,}")
    print(f"  Reporters: {reporters}")
    print(f"  Indicators: {indicators}")
    print(f"  Silver rows (country×year): {len(silver_records):,}")
    nga_rows = [
        r for r in silver_records
        if r["country_iso3"] == "NGA" and r.get("gdp_current_usd") is not None
    ]
    sample = max(nga_rows, key=lambda r: r["year"], default=None)
    if sample:
        gdp_usd = sample.get("gdp_current_usd")
        if not (MACRO_SCALE_MIN_USD < gdp_usd < MACRO_SCALE_MAX_USD):
            raise ValueError(
                f"NGDPD scale assumption looks wrong: NGA GDP came out as {gdp_usd}. "
                "Expected 1e11-1e12 USD."
            )
        print(f"  NGA {sample['year']} sample: gdp_billions={sample.get('gdp_current_usd_billions'):.1f}"
              f"  pop_millions={sample.get('population_millions'):.1f}"
              f"  gdp_per_capita={sample.get('gdp_per_capita_current_usd')}")
    return bronze_records, silver_records


# ---------------------------------------------------------------------------
# Step 2a: Rebuild bronze.imf_weo_raw
# ---------------------------------------------------------------------------
BRONZE_COLUMNS = [
    "source", "dataset", "frequency", "country_iso3", "country_name",
    "indicator_code", "indicator_name", "topic", "unit", "year", "value",
    "scale", "decimals_displayed", "country_update_date", "overlap",
    "extracted_at",
]

BRONZE_DDL = f"""
CREATE OR REPLACE TABLE {CAT}.bronze.imf_weo_raw (
    source                 STRING,
    dataset                STRING,
    frequency              STRING,
    country_iso3           STRING,
    country_name           STRING,
    indicator_code         STRING,
    indicator_name         STRING,
    topic                  STRING,
    unit                   STRING,
    year                   INT,
    value                  DOUBLE,
    scale                  STRING,
    decimals_displayed     STRING,
    country_update_date    STRING,
    overlap                STRING,
    extracted_at           STRING
)
USING DELTA
"""

# ---------------------------------------------------------------------------
# Step 2b: Rebuild silver.fact_macro_annual
# ---------------------------------------------------------------------------
SILVER_COLUMNS = [
    "country_iso3", "year",
    "gdp_current_usd_billions", "gdp_current_usd",
    "gdp_per_capita_current_usd",
    "population_millions", "population",
    "real_gdp_growth_pct_imf", "inflation_cpi_pct",
    "gross_debt_pct_gdp_imf", "gross_debt_usd",
    "government_revenue_pct_gdp_imf", "government_expenditure_pct_gdp_imf",
    "net_lending_borrowing_pct_gdp_imf", "current_account_balance_pct_gdp_imf",
]

SILVER_DDL = f"""
CREATE OR REPLACE TABLE {CAT}.silver.fact_macro_annual (
    country_iso3                         STRING,
    year                                 INT,
    gdp_current_usd_billions             DOUBLE,
    gdp_current_usd                      DOUBLE,
    gdp_per_capita_current_usd           DOUBLE,
    population_millions                  DOUBLE,
    population                           DOUBLE,
    real_gdp_growth_pct_imf              DOUBLE,
    inflation_cpi_pct                    DOUBLE,
    gross_debt_pct_gdp_imf               DOUBLE,
    gross_debt_usd                       DOUBLE,
    government_revenue_pct_gdp_imf       DOUBLE,
    government_expenditure_pct_gdp_imf   DOUBLE,
    net_lending_borrowing_pct_gdp_imf    DOUBLE,
    current_account_balance_pct_gdp_imf  DOUBLE
)
USING DELTA
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    require_dbx_config(DBX, "host", "warehouse", "token")
    pat = _get_pat()
    print(f"PAT loaded (ends ...{pat[-6:]})\n")

    bronze_records, silver_records = load_and_pivot(JSONL_PATH)

    # --- Bronze ---
    print("\n[Step 2a] Rebuilding bronze.imf_weo_raw ...")
    run_sql(pat, BRONZE_DDL)
    print(f"  Inserting {len(bronze_records):,} rows into bronze.imf_weo_raw (batch=200) ...")
    insert_batches(pat, f"{CAT}.bronze.imf_weo_raw", BRONZE_COLUMNS, bronze_records, batch_size=200)

    r = run_sql(pat, f"SELECT COUNT(*) FROM {CAT}.bronze.imf_weo_raw")
    count = rows_from(r)[0][0]
    print(f"  ✓ bronze.imf_weo_raw: {count} rows")

    # --- Silver ---
    print("\n[Step 2b] Rebuilding silver.fact_macro_annual ...")
    run_sql(pat, SILVER_DDL)
    print(f"  Inserting {len(silver_records):,} rows into silver.fact_macro_annual (batch=200) ...")
    insert_batches(pat, f"{CAT}.silver.fact_macro_annual", SILVER_COLUMNS, silver_records, batch_size=200)

    r = run_sql(pat, f"SELECT COUNT(*) FROM {CAT}.silver.fact_macro_annual")
    count = rows_from(r)[0][0]
    print(f"  ✓ silver.fact_macro_annual: {count} rows")

    # --- Quick sanity check ---
    print("\n[Step 3] Sanity check ...")
    r = run_sql(pat, f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(population_millions) AS rows_with_population,
            COUNT(gdp_current_usd_billions) AS rows_with_gdp,
            MIN(year) AS min_year,
            MAX(year) AS max_year
        FROM {CAT}.silver.fact_macro_annual
    """)
    header = [c["name"] for c in r.get("manifest", {}).get("schema", {}).get("columns", [])]
    data = rows_from(r)
    if header and data:
        for col, val in zip(header, data[0]):
            print(f"  {col}: {val}")

    print("\nDone. Next steps:")
    print("  1. Re-run notebooks 14 + 15 on Databricks to rebuild the gold dashboard tables.")
    print("     (or run: python scripts/rebuild_gold_dashboard.py)")


if __name__ == "__main__":
    main()
