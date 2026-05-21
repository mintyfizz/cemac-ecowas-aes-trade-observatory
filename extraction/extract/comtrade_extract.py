#!/usr/bin/env python3
"""Extract UN Comtrade bilateral trade data locally for CEMAC + ECOWAS.

Runs outside Databricks — the public Comtrade preview endpoint resolves fine
from a local machine (Databricks Free Edition serverless fails DNS for
comtradeapi.un.org).  No API key required.

Downloads annual total goods exports and imports by partner for all 21
project countries.  Partner descriptions are resolved from the Comtrade
reference area list fetched at startup.

Each JSONL line is one reporter x year:
  {"source": "comtrade", "reporter_iso3": "CMR", "reporter_code": 120,
   "year": 2022, "extracted_at": "...", "row_count": 163,
   "payload": [{"reporter_iso3": "CMR", "partner_code": 276,
                "partner_iso3": "DEU", "partner_name": "Germany",
                "flow": "M", "year": 2022, "value_usd": 123456.78,
                "is_reported": false, "is_aggregate": true,
                "classification": "H6"}, ...]}

Typical usage:
    python3 extraction/extract/comtrade_extract.py \
        --all-cemac-ecowas \
        --start-year 2010 --end-year 2023 \
        --out data/raw/comtrade/cemac_ecowas_comtrade_2010_2023.jsonl

Then upload the JSONL to a Databricks Volume and run a bronze ingest notebook.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import certifi
    _SSL_CONTEXT: Any = __import__("ssl").create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = None

# ---------------------------------------------------------------------------
# Project countries — numeric M49 codes match Comtrade reporter/partner codes
# ---------------------------------------------------------------------------

PROJECT_COUNTRIES = [
    {"code": 120, "iso3": "CMR", "name": "Cameroon",                 "bloc": "CEMAC"},
    {"code": 140, "iso3": "CAF", "name": "Central African Republic", "bloc": "CEMAC"},
    {"code": 148, "iso3": "TCD", "name": "Chad",                     "bloc": "CEMAC"},
    {"code": 178, "iso3": "COG", "name": "Congo",                    "bloc": "CEMAC"},
    {"code": 226, "iso3": "GNQ", "name": "Equatorial Guinea",        "bloc": "CEMAC"},
    {"code": 266, "iso3": "GAB", "name": "Gabon",                    "bloc": "CEMAC"},
    {"code": 204, "iso3": "BEN", "name": "Benin",                    "bloc": "ECOWAS"},
    {"code": 854, "iso3": "BFA", "name": "Burkina Faso",             "bloc": "ECOWAS"},
    {"code": 132, "iso3": "CPV", "name": "Cabo Verde",               "bloc": "ECOWAS"},
    {"code": 384, "iso3": "CIV", "name": "Cote d'Ivoire",            "bloc": "ECOWAS"},
    {"code": 270, "iso3": "GMB", "name": "Gambia",                   "bloc": "ECOWAS"},
    {"code": 288, "iso3": "GHA", "name": "Ghana",                    "bloc": "ECOWAS"},
    {"code": 324, "iso3": "GIN", "name": "Guinea",                   "bloc": "ECOWAS"},
    {"code": 624, "iso3": "GNB", "name": "Guinea-Bissau",            "bloc": "ECOWAS"},
    {"code": 430, "iso3": "LBR", "name": "Liberia",                  "bloc": "ECOWAS"},
    {"code": 466, "iso3": "MLI", "name": "Mali",                     "bloc": "ECOWAS"},
    {"code": 562, "iso3": "NER", "name": "Niger",                    "bloc": "ECOWAS"},
    {"code": 566, "iso3": "NGA", "name": "Nigeria",                  "bloc": "ECOWAS"},
    {"code": 686, "iso3": "SEN", "name": "Senegal",                  "bloc": "ECOWAS"},
    {"code": 694, "iso3": "SLE", "name": "Sierra Leone",             "bloc": "ECOWAS"},
    {"code": 768, "iso3": "TGO", "name": "Togo",                     "bloc": "ECOWAS"},
]

# Comtrade public preview endpoint (no API key required)
_BASE_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"

# Reference area list — maps numeric M49 code -> {iso3, name}
_REF_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"


# ---------------------------------------------------------------------------
# Reference area fetch (partner code -> ISO3 / name)
# ---------------------------------------------------------------------------

def fetch_partner_reference() -> dict[int, dict[str, str]]:
    """Fetch Comtrade partner area reference and return {code: {iso3, name}}."""
    print("Fetching Comtrade partner reference table...", end=" ", flush=True)
    try:
        req = urllib.request.Request(_REF_URL, headers={"Accept": "application/json"})
        kw: dict[str, Any] = {"context": _SSL_CONTEXT} if _SSL_CONTEXT else {}
        with urllib.request.urlopen(req, timeout=30, **kw) as r:
            data = json.loads(r.read().decode())
    except Exception as exc:
        print(f"WARNING: {exc}. Partner names will be numeric.")
        return {}
    ref: dict[int, dict[str, str]] = {}
    for row in data.get("results", []):
        try:
            ref[int(row["id"])] = {"iso3": row.get("iso3", ""), "name": row.get("text", "")}
        except (KeyError, ValueError, TypeError):
            pass
    print(f"{len(ref)} areas loaded.")
    return ref


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get(url: str, params: dict, timeout: int = 60) -> Any:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json"})
    kw: dict[str, Any] = {"context": _SSL_CONTEXT} if _SSL_CONTEXT else {}
    with urllib.request.urlopen(req, timeout=timeout, **kw) as r:
        return json.loads(r.read().decode())


def fetch_reporter_year(
    reporter_code: int,
    year: int,
    max_retries: int = 3,
    retry_delay: float = 10.0,
) -> list[dict]:
    """Fetch all partner rows (both flows) for one reporter x year.

    Notes:
    - partnerCode=0 returns rows where partner2Code holds the bilateral partner.
    - flowCode=X,M requests both exports and imports in one call.
    - primaryValue is the canonical trade value field.
    """
    params = {
        "reporterCode": reporter_code,
        "period":       year,
        "partnerCode":  0,       # 0 = all partners; partner2Code is the actual counterpart
        "cmdCode":      "TOTAL",
        "flowCode":     "X,M",   # exports and imports
    }
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return _http_get(_BASE_URL, params).get("data", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = retry_delay * attempt
                print(f"\n    Rate-limited (429) — waiting {wait:.0f}s ({attempt}/{max_retries})")
                time.sleep(wait)
                last_exc = exc
            else:
                raise
        except Exception as exc:
            if attempt < max_retries:
                print(f"\n    Error ({attempt}/{max_retries}): {type(exc).__name__}: {exc}")
                time.sleep(retry_delay)
                last_exc = exc
            else:
                raise
    raise RuntimeError(
        f"reporter={reporter_code} year={year} failed after {max_retries} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# Parse raw API records into clean dicts
# ---------------------------------------------------------------------------

def parse_records(
    raw: list[dict],
    reporter_iso3: str,
    year: int,
    partner_ref: dict[int, dict[str, str]],
) -> list[dict]:
    """Convert raw Comtrade API rows to clean payload records.

    Skips rows with no primaryValue.
    Maps partner2Code -> ISO3/name from the reference table; falls back to
    numeric code string when unmapped (e.g. aggregate regions like 'World').
    """
    rows: list[dict] = []
    for rec in raw:
        value = rec.get("primaryValue")
        if value is None:
            continue
        # When partnerCode=0 is passed, partner2Code holds the actual counterpart
        partner_code = rec.get("partner2Code") or rec.get("partnerCode")
        if partner_code is None:
            continue
        ref = partner_ref.get(int(partner_code), {})
        rows.append({
            "reporter_iso3":  reporter_iso3,
            "partner_code":   int(partner_code),
            "partner_iso3":   ref.get("iso3", ""),
            "partner_name":   ref.get("name", str(partner_code)),
            "flow":           rec.get("flowCode", ""),   # "X" = export, "M" = import
            "year":           int(rec.get("refYear", year)),
            "value_usd":      float(value),
            "is_reported":    bool(rec.get("isReported", False)),
            "is_aggregate":   bool(rec.get("isAggregate", False)),
            "classification": rec.get("classificationCode", ""),
        })
    return rows


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------

def extract(
    reporters: list[dict],
    start_year: int,
    end_year: int,
    out_path: Path,
    pause: float = 1.5,
) -> None:
    partner_ref = fetch_partner_reference()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(reporters) * (end_year - start_year + 1)
    done = 0

    with out_path.open("w", encoding="utf-8") as fh:
        for country in reporters:
            reporter_code = country["code"]
            reporter_iso3 = country["iso3"]

            for year in range(start_year, end_year + 1):
                done += 1
                print(f"[{done:4d}/{total}] {reporter_iso3} ({reporter_code}) {year}",
                      end="  ", flush=True)
                try:
                    raw = fetch_reporter_year(reporter_code, year)
                    records = parse_records(raw, reporter_iso3, year, partner_ref)
                    envelope = {
                        "source":        "comtrade",
                        "reporter_iso3": reporter_iso3,
                        "reporter_code": reporter_code,
                        "year":          year,
                        "extracted_at":  datetime.now(timezone.utc).isoformat(),
                        "row_count":     len(records),
                        "payload":       records,
                    }
                    print(f"{len(records)} rows")
                except Exception as exc:
                    print(f"ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
                    envelope = {
                        "source":        "comtrade",
                        "reporter_iso3": reporter_iso3,
                        "reporter_code": reporter_code,
                        "year":          year,
                        "extracted_at":  datetime.now(timezone.utc).isoformat(),
                        "row_count":     0,
                        "error":         f"{type(exc).__name__}: {exc}",
                        "payload":       [],
                    }
                fh.write(json.dumps(envelope, ensure_ascii=False) + "\n")
                time.sleep(pause)

    print(f"\nDone. Written to {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract UN Comtrade bilateral trade data (local run, no API key)."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all-cemac-ecowas", action="store_true",
                   help="Extract all 21 CEMAC + ECOWAS project countries.")
    g.add_argument("--reporter-codes", nargs="+", type=int, metavar="CODE",
                   help="One or more numeric Comtrade reporter codes (e.g. 120 for Cameroon).")
    p.add_argument("--start-year", type=int, default=2010)
    p.add_argument("--end-year",   type=int, default=2023)
    p.add_argument("--out", type=Path,
                   default=Path("data/raw/comtrade/cemac_ecowas_comtrade.jsonl"))
    p.add_argument("--pause", type=float, default=1.5,
                   help="Seconds to wait between requests (default 1.5).")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    if args.all_cemac_ecowas:
        reporters = PROJECT_COUNTRIES
    else:
        by_code = {c["code"]: c for c in PROJECT_COUNTRIES}
        reporters = []
        for code in args.reporter_codes:
            if code not in by_code:
                print(f"WARNING: code {code} not in project country list — skipping.")
            else:
                reporters.append(by_code[code])
    if not reporters:
        print("No valid reporters selected. Exiting.")
        return 1
    print(f"Extracting {len(reporters)} reporter(s), "
          f"{args.start_year}–{args.end_year} -> {args.out}")
    extract(reporters, args.start_year, args.end_year, args.out, pause=args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
