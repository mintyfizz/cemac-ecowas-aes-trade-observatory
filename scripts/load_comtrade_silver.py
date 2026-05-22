#!/usr/bin/env python3
"""
Populate silver.comtrade_hs2_annual and silver.comtrade_country_year_coverage
from the local JSONL file, then run the gold.product_trade_hs2 CTAS.

Usage:
    python scripts/load_comtrade_silver.py
"""

from __future__ import annotations

import collections
import configparser
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HOST = "dbc-7b56a3a7-18e9.cloud.databricks.com"
WH_ID = "9cd578d885df8799"
CAT = "cemac_ecowas_aes_trade"
JSONL_PATH = "data/raw/comtrade/cemac_ecowas_comtrade_annual_hs6_1990_2024.jsonl"

# Notebook constants (must match 10b_silver_comtrade_normalize.ipynb)
SPARSE_THRESHOLD = 500
COMTRADE_DARK = {"GNQ", "GNB", "LBR", "MLI", "NER", "NGA", "SEN", "SLE", "TGO"}
START_YEAR = 1990
END_YEAR = 2024

# HS2 chapter names (standard UN Comtrade descriptions, abbreviated)
HS2_NAMES: dict[str, str] = {
    "01": "Live animals",
    "02": "Meat and edible offal",
    "03": "Fish and crustaceans",
    "04": "Dairy produce; eggs; honey",
    "05": "Products of animal origin",
    "06": "Live trees and other plants",
    "07": "Edible vegetables and roots",
    "08": "Edible fruit and nuts",
    "09": "Coffee, tea and spices",
    "10": "Cereals",
    "11": "Milling industry products",
    "12": "Oil seeds and oleaginous fruits",
    "13": "Lac; gums and resins",
    "14": "Vegetable plaiting materials",
    "15": "Animal or vegetable fats and oils",
    "16": "Preparations of meat or fish",
    "17": "Sugars and confectionery",
    "18": "Cocoa and cocoa preparations",
    "19": "Preparations of cereals and flour",
    "20": "Preparations of vegetables and fruit",
    "21": "Miscellaneous edible preparations",
    "22": "Beverages, spirits and vinegar",
    "23": "Residues from food industries",
    "24": "Tobacco and substitutes",
    "25": "Salt; sulphur; earths and stone",
    "26": "Ores, slag and ash",
    "27": "Mineral fuels and oils",
    "28": "Inorganic chemicals",
    "29": "Organic chemicals",
    "30": "Pharmaceutical products",
    "31": "Fertilisers",
    "32": "Tanning and dyeing extracts",
    "33": "Essential oils and perfumery",
    "34": "Soap and lubricants",
    "35": "Albuminoidal substances and starches",
    "36": "Explosives and pyrotechnics",
    "37": "Photographic goods",
    "38": "Miscellaneous chemical products",
    "39": "Plastics and articles thereof",
    "40": "Rubber and articles thereof",
    "41": "Raw hides and skins",
    "42": "Articles of leather and travel goods",
    "43": "Furskins and artificial fur",
    "44": "Wood and articles of wood",
    "45": "Cork and articles of cork",
    "46": "Manufactures of straw or esparto",
    "47": "Pulp of wood",
    "48": "Paper and paperboard",
    "49": "Printed books and newspapers",
    "50": "Silk",
    "51": "Wool and animal hair",
    "52": "Cotton",
    "53": "Other vegetable textile fibres",
    "54": "Man-made filaments",
    "55": "Man-made staple fibres",
    "56": "Wadding, felt and nonwovens",
    "57": "Carpets and textile floor coverings",
    "58": "Special woven fabrics",
    "59": "Coated or laminated textile fabrics",
    "60": "Knitted or crocheted fabrics",
    "61": "Knitted apparel and clothing",
    "62": "Woven apparel and clothing",
    "63": "Other made-up textile articles",
    "64": "Footwear and gaiters",
    "65": "Headgear and parts thereof",
    "66": "Umbrellas and walking sticks",
    "67": "Prepared feathers and down",
    "68": "Articles of stone, plaster or cement",
    "69": "Ceramic products",
    "70": "Glass and glassware",
    "71": "Precious stones; jewellery",
    "72": "Iron and steel",
    "73": "Articles of iron or steel",
    "74": "Copper and articles thereof",
    "75": "Nickel and articles thereof",
    "76": "Aluminium and articles thereof",
    "78": "Lead and articles thereof",
    "79": "Zinc and articles thereof",
    "80": "Tin and articles thereof",
    "81": "Other base metals and cermets",
    "82": "Tools, cutlery and spoons",
    "83": "Miscellaneous articles of base metal",
    "84": "Nuclear reactors, boilers, machinery",
    "85": "Electrical machinery and equipment",
    "86": "Railway locomotives and rolling stock",
    "87": "Vehicles (not railway or tramway)",
    "88": "Aircraft and spacecraft",
    "89": "Ships and floating structures",
    "90": "Optical and measuring instruments",
    "91": "Clocks and watches",
    "92": "Musical instruments",
    "93": "Arms and ammunition",
    "94": "Furniture; bedding and mattresses",
    "95": "Toys, games and sports requisites",
    "96": "Miscellaneous manufactured articles",
    "97": "Works of art and antiques",
    "98": "Special classification provisions",
    "99": "Miscellaneous",
}

# ---------------------------------------------------------------------------
# Databricks REST helpers
# ---------------------------------------------------------------------------

def _get_pat() -> str:
    cfg_path = os.path.expanduser("~/.databrickscfg")
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path)
    return cfg["cemac-project"]["token"]


def _headers(pat: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pat}", "Content-Type": "application/json"}


def run_sql(pat: str, statement: str, timeout_s: int = 50) -> dict:
    """Submit a SQL statement and poll until finished. Returns the full response."""
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

    # Poll if still running
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


# ---------------------------------------------------------------------------
# Step 1: Aggregate locally from JSONL
# ---------------------------------------------------------------------------

def load_and_aggregate(jsonl_path: str):
    """
    Returns (hs2_records, coverage_records).

    hs2_records: list of dicts with keys matching silver.comtrade_hs2_annual
    coverage_records: list of dicts matching silver.comtrade_country_year_coverage
    """
    print(f"Reading {jsonl_path} ...")

    # hs2_agg[(reporter, year, flow_type, hs2_code)] → {usd, hs6s}
    hs2_agg: dict = collections.defaultdict(
        lambda: {"usd": 0.0, "hs6s": set()}
    )
    # coverage_raw[(reporter, year)] → count of non-aggregate rows
    coverage_raw: dict = collections.defaultdict(int)
    reporters: set[str] = set()

    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            d = json.loads(line)
            reporter = d["reporter_iso3"]
            year = d["year"]
            reporters.add(reporter)

            for row in d.get("payload", []):
                # All rows in this file are W00 (world-total), which is what the
                # HS2 product-structure chart needs. The Comtrade API changed its
                # is_aggregate flag for W00 rows between extractions: 1993-2016
                # records have is_aggregate=False, 2017+ have is_aggregate=True.
                # We skip the is_aggregate check entirely since there are no
                # bilateral (non-W00) rows in this file to accidentally include.

                coverage_raw[(reporter, year)] += 1

                cmd_code = str(row.get("cmd_code", "")).zfill(6)
                hs2_code = cmd_code[:2]
                flow = row.get("flow", "")
                flow_type = (
                    "export" if flow == "X" else "import" if flow == "M" else "other"
                )
                value_usd = float(row.get("value_usd") or 0)

                key = (reporter, year, flow_type, hs2_code)
                hs2_agg[key]["usd"] += value_usd
                hs2_agg[key]["hs6s"].add(cmd_code)

    print(f"  Reporters: {sorted(reporters)}")
    print(f"  HS2 aggregation keys: {len(hs2_agg):,}")
    print(f"  Coverage (reporter×year) keys: {len(coverage_raw):,}")

    loaded_at = datetime.now(timezone.utc).isoformat()

    # Build hs2_annual records
    hs2_records = []
    for (reporter, year, flow_type, hs2_code), vals in hs2_agg.items():
        hs2_records.append({
            "reporter_iso3": reporter,
            "year": year,
            "flow_type": flow_type,
            "hs2_code": hs2_code,
            "hs2_description": HS2_NAMES.get(hs2_code, f"HS {hs2_code}"),
            "trade_value_usd": vals["usd"],
            "distinct_hs6_products": len(vals["hs6s"]),
            "distinct_partners": 1,  # world-total rows only; 1 partner (World)
            "created_at": loaded_at,
        })

    # Build coverage records
    # Build full grid: reporters × years
    all_years = list(range(START_YEAR, END_YEAR + 1))
    coverage_records = []
    for reporter in reporters:
        for year in all_years:
            n = coverage_raw.get((reporter, year), 0)
            has_data = n > 0

            # comtrade_status
            if n == 0:
                comtrade_status = "missing"
            elif n < SPARSE_THRESHOLD:
                comtrade_status = "sparse"
            else:
                comtrade_status = "good"

            # quality_flag (same logic as notebook)
            if reporter == "GHA" and year == 2004 and n <= 2:
                quality_flag = "data_integrity_anomaly"
            elif reporter == "CAF" and year == 2006 and n < SPARSE_THRESHOLD:
                quality_flag = "partial_submission"
            elif year == END_YEAR and n == 0:
                quality_flag = "late_release"
            elif reporter in COMTRADE_DARK and n == 0:
                quality_flag = "comtrade_dark"
            else:
                quality_flag = comtrade_status

            # recommended_action
            action_map = {
                "good": "use_direct_comtrade",
                "sparse": "flag_or_fallback",
                "partial_submission": "exclude_or_fallback",
                "data_integrity_anomaly": "exclude_from_default_gold",
                "late_release": "treat_as_not_yet_available",
                "comtrade_dark": "use_imts_mirror_only",
                "missing": "use_imts_or_mirror",
            }
            recommended_action = action_map.get(quality_flag, "use_imts_or_mirror")

            coverage_records.append({
                "country_iso3": reporter,
                "year": year,
                "comtrade_row_count": n,
                "distinct_partners": 0,      # not computed (only in hs6_normalized)
                "distinct_hs6_products": 0,  # not computed
                "has_comtrade_data": has_data,
                "comtrade_status": comtrade_status,
                "quality_flag": quality_flag,
                "recommended_action": recommended_action,
                "created_at": loaded_at,
            })

    print(f"  HS2 records: {len(hs2_records):,}")
    print(f"  Coverage records: {len(coverage_records):,}")
    good_cov = sum(1 for r in coverage_records if r["quality_flag"] == "good")
    print(f"  Coverage 'good' rows: {good_cov}")

    return hs2_records, coverage_records


# ---------------------------------------------------------------------------
# Step 2: Insert records into Databricks via batched SQL
# ---------------------------------------------------------------------------

def _escape(v) -> str:
    """Format a Python value for SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    # string — escape single quotes
    s = str(v).replace("'", "''")
    return f"'{s}'"


def insert_batches(pat: str, full_table: str, columns: list[str], records: list[dict], batch_size: int = 200):
    """INSERT records into full_table in batches."""
    total = len(records)
    print(f"  Inserting {total:,} rows into {full_table} (batch={batch_size}) ...")
    col_list = ", ".join(columns)
    inserted = 0
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        value_rows = []
        for rec in batch:
            vals = ", ".join(_escape(rec[c]) for c in columns)
            value_rows.append(f"({vals})")
        stmt = f"INSERT INTO {full_table} ({col_list}) VALUES {', '.join(value_rows)}"
        run_sql(pat, stmt, timeout_s=50)
        inserted += len(batch)
        pct = inserted / total * 100
        print(f"    {inserted:,}/{total:,} ({pct:.0f}%)", end="\r", flush=True)
    print(f"    Done: {inserted:,} rows inserted.          ")


# ---------------------------------------------------------------------------
# Step 3: Gold CTAS
# ---------------------------------------------------------------------------

GOLD_CTAS = """
CREATE OR REPLACE TABLE gold.product_trade_hs2
PARTITIONED BY (reporter_iso3, year)
AS
WITH hs2 AS (
  SELECT * FROM silver.comtrade_hs2_annual
),
cov AS (
  SELECT country_iso3, year, quality_flag, recommended_action, comtrade_status
  FROM silver.comtrade_country_year_coverage
),
joined AS (
  SELECT
    h.reporter_iso3,
    h.year,
    h.flow_type,
    h.hs2_code,
    h.hs2_description,
    h.trade_value_usd,
    h.trade_value_usd / 1000000000.0 AS trade_value_billions_usd,
    h.distinct_hs6_products,
    h.distinct_partners,
    c.quality_flag,
    c.comtrade_status,
    current_timestamp() AS loaded_at,
    SUM(h.trade_value_usd) OVER (
      PARTITION BY h.reporter_iso3, h.year, h.flow_type
    ) AS reporter_year_flow_total_usd
  FROM hs2 h
  LEFT JOIN cov c ON h.reporter_iso3 = c.country_iso3 AND h.year = c.year
  WHERE c.quality_flag = 'good'
),
final AS (
  SELECT
    reporter_iso3,
    year,
    flow_type,
    hs2_code,
    hs2_description,
    trade_value_usd,
    trade_value_billions_usd,
    distinct_hs6_products,
    distinct_partners,
    CASE
      WHEN reporter_year_flow_total_usd > 0
      THEN trade_value_usd / reporter_year_flow_total_usd * 100.0
    END AS hs2_share_pct,
    reporter_year_flow_total_usd,
    quality_flag,
    comtrade_status,
    loaded_at
  FROM joined
)
SELECT * FROM final
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pat = _get_pat()
    print(f"PAT loaded (ends ...{pat[-6:]})\n")

    # --- Step 1: Aggregate locally ---
    hs2_records, coverage_records = load_and_aggregate(JSONL_PATH)

    # --- Step 2a: Rebuild silver.comtrade_hs2_annual ---
    print("\n[Step 2a] Rebuilding silver.comtrade_hs2_annual ...")
    run_sql(pat, "TRUNCATE TABLE silver.comtrade_hs2_annual")
    hs2_cols = [
        "reporter_iso3", "year", "flow_type", "hs2_code", "hs2_description",
        "trade_value_usd", "distinct_hs6_products", "distinct_partners", "created_at",
    ]
    insert_batches(pat, "silver.comtrade_hs2_annual", hs2_cols, hs2_records)

    # Verify
    resp = run_sql(pat, "SELECT COUNT(*) FROM silver.comtrade_hs2_annual")
    count = rows_from(resp)[0][0]
    print(f"  Verified: {count} rows in silver.comtrade_hs2_annual")

    # --- Step 2b: Rebuild silver.comtrade_country_year_coverage ---
    print("\n[Step 2b] Rebuilding silver.comtrade_country_year_coverage ...")
    run_sql(pat, "TRUNCATE TABLE silver.comtrade_country_year_coverage")
    cov_cols = [
        "country_iso3", "year", "comtrade_row_count", "distinct_partners",
        "distinct_hs6_products", "has_comtrade_data", "comtrade_status",
        "quality_flag", "recommended_action", "created_at",
    ]
    insert_batches(pat, "silver.comtrade_country_year_coverage", cov_cols, coverage_records, batch_size=300)

    # Verify
    resp = run_sql(pat, "SELECT quality_flag, COUNT(*) AS n FROM silver.comtrade_country_year_coverage GROUP BY quality_flag ORDER BY n DESC")
    print("  Coverage quality_flag distribution:")
    for row in rows_from(resp):
        print(f"    {row[0]}: {row[1]}")

    # --- Step 3: Gold CTAS ---
    print("\n[Step 3] Running gold.product_trade_hs2 CTAS ...")
    run_sql(pat, GOLD_CTAS.strip(), timeout_s=50)

    resp = run_sql(pat, "SELECT COUNT(*) FROM gold.product_trade_hs2")
    gold_count = rows_from(resp)[0][0]
    print(f"  gold.product_trade_hs2: {gold_count} rows")

    if int(gold_count) > 0:
        resp = run_sql(pat, "SELECT flow_type, COUNT(*) AS n FROM gold.product_trade_hs2 GROUP BY flow_type")
        print("  By flow_type:")
        for row in rows_from(resp):
            print(f"    {row[0]}: {row[1]}")

        resp = run_sql(pat, "SELECT reporter_iso3, year, hs2_code, hs2_description, ROUND(trade_value_billions_usd,3) AS bil FROM gold.product_trade_hs2 WHERE flow_type='export' ORDER BY trade_value_billions_usd DESC LIMIT 10")
        print("\n  Top 10 export sectors:")
        for row in rows_from(resp):
            print(f"    {row[0]} {row[1]}: HS{row[2]} {row[3]} ${row[4]}B")

    print("\nDone.")


if __name__ == "__main__":
    main()
