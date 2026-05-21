#!/usr/bin/env python3
"""Extract UN Comtrade bilateral trade data locally for CEMAC + ECOWAS.

Runs outside Databricks (Databricks Free Edition serverless fails DNS for
comtradeapi.un.org).

With an API key (COMTRADE_API_KEY in .env or environment):
  - Uses the full authenticated dataset endpoint (no row-count limits)
  - Paginates automatically for large result sets
  - Supports HS commodity breakdown (--cmd-code AG2 for 2-digit chapters)
  - Supports monthly frequency (--freq M)
  - Includes re-exports and re-imports (flow codes X,M,RX,RM)
  - Falls back to the second key (COMTRADE_API_KEY_2) if the first is exhausted

Without an API key:
  - Falls back to the public preview endpoint (same parameters, no pagination,
    limited to ~500 rows per call)

Each JSONL line is one reporter × period (year or year-month):
  {
    "source":        "comtrade",
    "reporter_iso3": "CMR",
    "reporter_code": 120,
    "year":          2022,          # present for annual
    "period":        "2022",        # "YYYY" annual, "YYYYMM" monthly
    "cmd_code":      "TOTAL",       # commodity scope
    "freq":          "A",           # A=annual, M=monthly
    "extracted_at":  "...",
    "row_count":     328,
    "payload": [
      {
        "reporter_iso3":    "CMR",
        "partner_code":     276,
        "partner_iso3":     "DEU",
        "partner_name":     "Germany",
        "cmd_code":         "TOTAL",   # or e.g. "27" for mineral fuels
        "cmd_desc":         "",        # HS chapter description (when available)
        "flow":             "M",       # X=export M=import RX=re-export RM=re-import
        "period":           "2022",
        "value_usd":        1234567.89,
        "qty":              null,
        "qty_unit":         null,
        "is_reported":      false,
        "is_aggregate":     true,
        "is_intra_bloc":    false,     # true when partner is a project country
        "classification":   "H6"
      }, ...
    ]
  }

Typical usage:

  # Annual totals for all 21 countries (requires API key for full coverage):
  python3 extraction/extract/comtrade_extract.py \\
      --all-cemac-ecowas --start-year 1990 --end-year 2024 \\
      --out data/raw/comtrade/cemac_ecowas_comtrade_annual_total_1990_2024.jsonl

  # Annual HS-2 commodity breakdown, recent years:
  python3 extraction/extract/comtrade_extract.py \\
      --all-cemac-ecowas --start-year 2010 --end-year 2024 \\
      --cmd-code AG2 \\
      --out data/raw/comtrade/cemac_ecowas_comtrade_annual_ag2_2010_2024.jsonl

  # Monthly totals, recent years:
  python3 extraction/extract/comtrade_extract.py \\
      --all-cemac-ecowas --start-year 2015 --end-year 2024 \\
      --freq M \\
      --out data/raw/comtrade/cemac_ecowas_comtrade_monthly_total_2015_2024.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
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
# Load API keys from .env (python-dotenv not required — plain parse)
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — sets os.environ for keys not already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

_ROOT = Path(__file__).resolve().parents[2]
_load_dotenv(_ROOT / ".env")

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

# Set of M49 codes for quick intra-bloc detection
_PROJECT_CODES: set[int] = {c["code"] for c in PROJECT_COUNTRIES}

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

# Full authenticated endpoint (requires API key header)
_AUTH_BASE = "https://comtradeapi.un.org/data/v1/get/C/{freq}/HS"

# Public preview — no key, annual HS only, limited rows (~500)
_PREVIEW_BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"

# Reference area list
_REF_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"

# Page size for authenticated requests (Comtrade max is 250 000)
_PAGE_SIZE = 250_000


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
            ref[int(row["id"])] = {
                "iso3": row.get("PartnerCodeIsoAlpha3", ""),
                "name": row.get("text", ""),
            }
        except (KeyError, ValueError, TypeError):
            pass
    print(f"{len(ref)} areas loaded.")
    return ref


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

def _get_api_keys() -> list[str]:
    """Return available API keys in priority order."""
    keys = []
    for env_var in ("COMTRADE_API_KEY", "COMTRADE_API_KEY_2"):
        k = os.environ.get(env_var, "").strip()
        if k:
            keys.append(k)
    return keys


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get(url: str, params: dict, api_key: str | None, timeout: int = 120) -> Any:
    full = url + "?" + urllib.parse.urlencode(params)
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Ocp-Apim-Subscription-Key"] = api_key
    req = urllib.request.Request(full, headers=headers)
    kw: dict[str, Any] = {"context": _SSL_CONTEXT} if _SSL_CONTEXT else {}
    with urllib.request.urlopen(req, timeout=timeout, **kw) as r:
        return json.loads(r.read().decode())


def fetch_reporter_period(
    reporter_code: int,
    period: str,         # "YYYY" for annual, "YYYYMM" for monthly
    cmd_code: str,       # "TOTAL", "AG2", specific HS chapter e.g. "27"
    freq: str,           # "A" or "M"
    flow_codes: str,     # "X,M" or "X,M,RX,RM"
    api_keys: list[str],
    max_retries: int = 3,
    retry_delay: float = 15.0,
) -> list[dict]:
    """Fetch all partner rows for one reporter × period.

    Uses authenticated endpoint with pagination when an API key is available,
    falls back to the public preview otherwise.

    For authenticated calls:
    - partnerCode=0  → all partners; partner2Code holds the bilateral partner
    - Paginates using offset until all rows retrieved
    - Automatically rotates to the second key on 429

    For preview calls:
    - Single request, no pagination, same partner2Code convention
    """
    base_params: dict[str, Any] = {
        "reporterCode": reporter_code,
        "period":        period,
        "partnerCode":   0,      # 0 = all partners; partner2Code in response holds the bilateral partner
        "cmdCode":       cmd_code,
        "flowCode":      flow_codes,
    }

    keys = list(api_keys)  # copy so we can rotate

    if keys:
        # Authenticated — full dataset with pagination
        url = _AUTH_BASE.format(freq=freq)
        all_rows: list[dict] = []
        offset = 0
        while True:
            params = {**base_params, "pageSize": _PAGE_SIZE, "offset": offset}
            page = _auth_get_with_retry(url, params, keys, max_retries, retry_delay)
            batch = page.get("data", []) or []
            all_rows.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break  # last page
            offset += _PAGE_SIZE
        return all_rows
    else:
        # Public preview — single call, no pagination
        return _preview_get_with_retry(base_params, max_retries, retry_delay)


def _auth_get_with_retry(
    url: str, params: dict, keys: list[str],
    max_retries: int, retry_delay: float,
) -> dict:
    """GET with key rotation and exponential back-off on 429."""
    key_idx = 0
    for attempt in range(1, max_retries + 1):
        try:
            return _http_get(url, params, api_key=keys[key_idx])
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Try rotating to next key first
                next_idx = key_idx + 1
                if next_idx < len(keys):
                    print(f"\n    429 on key {key_idx+1} — rotating to key {next_idx+1}")
                    key_idx = next_idx
                else:
                    wait = retry_delay * attempt
                    print(f"\n    Rate-limited (429) all keys — waiting {wait:.0f}s ({attempt}/{max_retries})")
                    time.sleep(wait)
                    key_idx = 0  # reset to primary after wait
            elif exc.code in (401, 403):
                raise RuntimeError(f"API key rejected (HTTP {exc.code}) — check COMTRADE_API_KEY in .env") from exc
            else:
                raise
        except Exception as exc:
            if attempt < max_retries:
                print(f"\n    Error ({attempt}/{max_retries}): {type(exc).__name__}: {exc}")
                time.sleep(retry_delay)
            else:
                raise
    raise RuntimeError(f"Failed after {max_retries} attempts")


def _preview_get_with_retry(
    params: dict, max_retries: int, retry_delay: float,
) -> list[dict]:
    """GET the public preview endpoint with retry."""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return _http_get(_PREVIEW_BASE, params, api_key=None).get("data", [])
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
    raise RuntimeError(f"Preview failed after {max_retries} attempts") from last_exc


# ---------------------------------------------------------------------------
# Parse raw API records into clean dicts
# ---------------------------------------------------------------------------

def parse_records(
    raw: list[dict],
    reporter_iso3: str,
    period: str,
    cmd_code: str,
    partner_ref: dict[int, dict[str, str]],
) -> list[dict]:
    """Convert raw Comtrade API rows to clean payload records.

    Skips rows with no primaryValue.
    Adds is_intra_bloc flag when partner is one of the 21 project countries.
    """
    rows: list[dict] = []
    for rec in raw:
        value = rec.get("primaryValue")
        if value is None:
            continue
        # partner2Code holds the bilateral partner when partnerCode=0 is used
        partner_code = rec.get("partner2Code") or rec.get("partnerCode")
        if partner_code is None:
            continue
        pcode = int(partner_code)
        ref = partner_ref.get(pcode, {})
        # CIF value for imports, FOB for exports — take whichever is populated
        cif = rec.get("cifvalue")
        fob = rec.get("fobvalue")
        rows.append({
            "reporter_iso3":  reporter_iso3,
            "partner_code":   pcode,
            "partner_iso3":   ref.get("iso3", ""),
            "partner_name":   ref.get("name", str(pcode)),
            "cmd_code":       rec.get("cmdCode", cmd_code),
            "cmd_desc":       rec.get("cmdDesc", ""),
            "flow":           rec.get("flowCode", ""),
            "period":         str(rec.get("period", period)),
            "value_usd":      float(value),          # primaryValue (canonical)
            "cif_value_usd":  float(cif) if cif is not None else None,
            "fob_value_usd":  float(fob) if fob is not None else None,
            "net_wgt_kg":     rec.get("netWgt"),
            "gross_wgt_kg":   rec.get("grossWgt"),
            "qty":            rec.get("qty"),
            "qty_unit":       rec.get("qtyUnitAbbr"),
            "is_reported":    bool(rec.get("isReported", False)),
            "is_aggregate":   bool(rec.get("isAggregate", False)),
            "is_intra_bloc":  pcode in _PROJECT_CODES,
            "classification": rec.get("classificationCode", ""),
        })
    return rows


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------

def _periods_for(start_year: int, end_year: int, freq: str) -> list[str]:
    """Generate period strings: 'YYYY' for annual, 'YYYYMM' for monthly."""
    periods = []
    for year in range(start_year, end_year + 1):
        if freq == "A":
            periods.append(str(year))
        else:
            for month in range(1, 13):
                periods.append(f"{year}{month:02d}")
    return periods


def extract(
    reporters: list[dict],
    start_year: int,
    end_year: int,
    out_path: Path,
    cmd_code: str = "TOTAL",
    freq: str = "A",
    flow_codes: str = "X,M,RX,RM",
    pause: float = 1.0,
    api_keys: list[str] | None = None,
) -> None:
    if api_keys is None:
        api_keys = _get_api_keys()

    partner_ref = fetch_partner_reference()

    if api_keys:
        print(f"Using authenticated endpoint with {len(api_keys)} key(s).")
        endpoint_label = "full dataset"
    else:
        print("No API key found — using public preview endpoint (limited rows, annual only).")
        if freq == "M":
            print("WARNING: Monthly frequency requires an API key. Switching to annual.")
            freq = "A"
        if flow_codes == "X,M,RX,RM":
            flow_codes = "X,M"
        endpoint_label = "preview"

    periods = _periods_for(start_year, end_year, freq)
    total = len(reporters) * len(periods)
    done = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Mode: {freq} | cmd: {cmd_code} | flows: {flow_codes} | endpoint: {endpoint_label}")
    print(f"Reporters: {len(reporters)} | Periods: {len(periods)} | Total requests: {total}")

    with out_path.open("w", encoding="utf-8") as fh:
        for country in reporters:
            reporter_code = country["code"]
            reporter_iso3 = country["iso3"]

            for period in periods:
                done += 1
                year = int(period[:4])
                print(f"[{done:5d}/{total}] {reporter_iso3} ({reporter_code}) {period}",
                      end="  ", flush=True)
                try:
                    raw = fetch_reporter_period(
                        reporter_code=reporter_code,
                        period=period,
                        cmd_code=cmd_code,
                        freq=freq,
                        flow_codes=flow_codes,
                        api_keys=api_keys,
                    )
                    records = parse_records(raw, reporter_iso3, period, cmd_code, partner_ref)
                    intra = sum(1 for r in records if r["is_intra_bloc"])
                    print(f"{len(records)} rows  ({intra} intra-bloc)")
                    envelope: dict[str, Any] = {
                        "source":        "comtrade",
                        "reporter_iso3": reporter_iso3,
                        "reporter_code": reporter_code,
                        "year":          year,
                        "period":        period,
                        "cmd_code":      cmd_code,
                        "freq":          freq,
                        "extracted_at":  datetime.now(timezone.utc).isoformat(),
                        "row_count":     len(records),
                        "payload":       records,
                    }
                except Exception as exc:
                    print(f"ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
                    envelope = {
                        "source":        "comtrade",
                        "reporter_iso3": reporter_iso3,
                        "reporter_code": reporter_code,
                        "year":          year,
                        "period":        period,
                        "cmd_code":      cmd_code,
                        "freq":          freq,
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
        description=(
            "Extract UN Comtrade bilateral trade data for CEMAC + ECOWAS countries.\n"
            "Reads COMTRADE_API_KEY (and COMTRADE_API_KEY_2) from .env or environment.\n"
            "Falls back to the public preview endpoint when no key is set."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Reporter selection
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all-cemac-ecowas", action="store_true",
                   help="All 21 CEMAC + ECOWAS project countries.")
    g.add_argument("--reporter-codes", nargs="+", type=int, metavar="CODE",
                   help="Specific reporter codes (e.g. 120 for Cameroon).")

    # Time range
    p.add_argument("--start-year", type=int, default=1990)
    p.add_argument("--end-year",   type=int, default=2024)

    # Data dimensions
    p.add_argument(
        "--cmd-code", default="TOTAL", metavar="CODE",
        help=(
            "Commodity code: TOTAL (default), AG2 (HS 2-digit chapters), "
            "or a specific chapter e.g. 27 (mineral fuels). "
            "AG2 gives full commodity breakdown. Requires API key."
        ),
    )
    p.add_argument(
        "--freq", choices=["A", "M"], default="A",
        help="Frequency: A=annual (default), M=monthly. Monthly requires API key.",
    )
    p.add_argument(
        "--flow-codes", default="X,M,RX,RM", metavar="FLOWS",
        help=(
            "Comma-separated flow codes. Default: X,M,RX,RM "
            "(exports, imports, re-exports, re-imports). "
            "Public preview is limited to X,M."
        ),
    )

    # Output
    p.add_argument("--out", type=Path,
                   default=Path("data/raw/comtrade/cemac_ecowas_comtrade.jsonl"))
    p.add_argument("--pause", type=float, default=1.0,
                   help="Seconds to wait between requests (default 1.0).")
    p.add_argument("--no-key", action="store_true",
                   help="Force public preview endpoint even if API key is set.")
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

    api_keys = [] if args.no_key else _get_api_keys()
    if not api_keys:
        print("No API key — using public preview endpoint.")
    else:
        print(f"API key(s) loaded: {len(api_keys)}")

    print(f"Extracting {len(reporters)} reporter(s), "
          f"{args.start_year}–{args.end_year} -> {args.out}")

    extract(
        reporters=reporters,
        start_year=args.start_year,
        end_year=args.end_year,
        out_path=args.out,
        cmd_code=args.cmd_code,
        freq=args.freq,
        flow_codes=args.flow_codes,
        pause=args.pause,
        api_keys=api_keys,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
