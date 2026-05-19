#!/usr/bin/env python3
"""Extract IMF IMTS bilateral trade data for CEMAC + ECOWAS countries.

No API key required.  Uses the IMF SDMX 2.1 REST API at api.imf.org —
publicly accessible from any network.  The IMTS dataflow (International
Merchandise Trade Statistics) replaces the retired DOTS service which was
decommissioned November 2025.

Each JSONL line is one reporter with all counterpart areas and years:
  {"source": "imf_imts", "reporter_iso3": "CMR", "extracted_at": "...",
   "payload": [{"reporter_iso3": "CMR", "counterpart_iso3": "W00",
                "indicator": "XG_FOB_USD", "year": 2010,
                "value_usd": 2345678901.0}, ...]}

Indicators in the new API:
    XG_FOB_USD  -- Exports of goods, FOB  (was TXG_FOB_USD in old DOTS)
    MG_CIF_USD  -- Imports of goods, CIF  (was TMG_CIF_USD in old DOTS)

Typical usage:
    pip install -r extraction/requirements.txt
    python3 extraction/extract/imf_dots_extract.py \
        --all-cemac-ecowas \
        --start-year 2010 --end-year 2023 \
        --out data/raw/imts/cemac_ecowas_imts_2010_2023.jsonl

Then upload to the Databricks Volume and run 04_bronze_imts_extract.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import sdmx  # sdmx1 package

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_INDICATORS = "XG_FOB_USD+MG_CIF_USD"   # exports FOB + imports CIF

# ISO 3-letter codes for the 21 project countries
# (The IMF IMTS API uses ISO3 codes, not ISO2)
_CEMAC_ISO3  = ["CMR", "CAF", "TCD", "COG", "GNQ", "GAB"]
_ECOWAS_ISO3 = ["BEN", "BFA", "CPV", "CIV", "GMB", "GHA",
                "GIN", "GNB", "LBR", "MLI", "NER", "NGA",
                "SEN", "SLE", "TGO"]
_ALL_ISO3 = _CEMAC_ISO3 + _ECOWAS_ISO3

# ISO2 -> ISO3 lookup (so --reporter-codes accepts either format)
_ISO2_TO_ISO3: dict[str, str] = {
    "CM": "CMR", "CF": "CAF", "TD": "TCD", "CG": "COG", "GQ": "GNQ", "GA": "GAB",
    "BJ": "BEN", "BF": "BFA", "CV": "CPV", "CI": "CIV", "GM": "GMB", "GH": "GHA",
    "GN": "GIN", "GW": "GNB", "LR": "LBR", "ML": "MLI", "NE": "NER", "NG": "NGA",
    "SN": "SEN", "SL": "SLE", "TG": "TGO",
}


class ImtsRequestError(Exception):
    """Raised when an IMF IMTS request fails."""


# ---------------------------------------------------------------------------
# Fetch via sdmx1 library
# ---------------------------------------------------------------------------

def fetch_imts(
    reporter_iso3: str,
    start_year: int,
    end_year: int,
    max_retries: int = 3,
    retry_delay: float = 15.0,
) -> dict:
    """Fetch all years and counterpart areas for one reporter.

    Returns a JSONL-envelope dict ready to be serialised.
    """
    client = sdmx.Client("IMF_DATA")

    for attempt in range(1, max_retries + 1):
        try:
            msg = client.data(
                "IMTS",
                key={
                    "COUNTRY":   reporter_iso3,
                    "FREQUENCY": "A",
                    "INDICATOR": _INDICATORS,
                },
                params={
                    "startPeriod": str(start_year),
                    "endPeriod":   str(end_year),
                },
            )
            break  # success
        except Exception as exc:
            msg_text = str(exc)
            if "429" in msg_text or "rate" in msg_text.lower():
                wait = retry_delay * attempt
                print(f"    Rate limited -- waiting {wait:.0f}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
            elif attempt < max_retries:
                print(f"    Error (attempt {attempt}/{max_retries}): {type(exc).__name__}: {exc}")
                time.sleep(retry_delay)
            else:
                raise ImtsRequestError(
                    f"reporter={reporter_iso3}: {type(exc).__name__}: {exc}"
                ) from exc
    else:
        raise ImtsRequestError(
            f"Failed reporter={reporter_iso3} after {max_retries} attempt(s)."
        )

    # Flatten observations from the sdmx1 DataMessage
    observations: list[dict] = []
    for dataset in msg.data:
        for series_key, obs_list in dataset.series.items():
            key_vals = {
                str(k): str(v).split("=", 1)[-1]
                for k, v in series_key.values.items()
            }
            counterpart = key_vals.get("COUNTERPART_COUNTRY", "")
            indicator   = key_vals.get("INDICATOR", "")

            for obs in obs_list:
                # obs.dimension renders as "(TIME_PERIOD=2022)"
                time_str = str(obs.dimension).strip("()")
                year_str = time_str.split("=")[-1]
                try:
                    year = int(year_str)
                except ValueError:
                    continue

                observations.append({
                    "reporter_iso3":    reporter_iso3,
                    "counterpart_iso3": counterpart,
                    "indicator":        indicator,
                    "year":             year,
                    "value_usd":        float(obs.value) if obs.value is not None else None,
                })

    return {
        "source":        "imf_imts",
        "reporter_iso3": reporter_iso3,
        "extracted_at":  datetime.now(timezone.utc).isoformat(),
        "payload":       observations,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract IMF IMTS bilateral trade data for CEMAC + ECOWAS countries."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--reporter-codes",
        nargs="+",
        metavar="ISO3",
        help="ISO 3-letter reporter codes, e.g. CMR for Cameroon. "
             "ISO 2-letter codes are also accepted.",
    )
    group.add_argument(
        "--all-cemac-ecowas",
        action="store_true",
        help="Shorthand for all 21 CEMAC + ECOWAS countries.",
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year",   type=int, required=True)
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSONL path, e.g. data/raw/imts/cemac_ecowas_imts.jsonl",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Delay between API calls (default: 1).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.all_cemac_ecowas:
        reporters = _ALL_ISO3
    else:
        reporters = [_ISO2_TO_ISO3.get(c.upper(), c.upper()) for c in args.reporter_codes]

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume: skip reporters already written
    done: set[str] = set()
    if output_path.exists():
        with output_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done.add(rec["reporter_iso3"])
                except (json.JSONDecodeError, KeyError):
                    pass
        if done:
            print(f"Resuming: {len(done)} reporter(s) already in {output_path}, skipping.")

    remaining = [r for r in reporters if r not in done]
    failures  = 0
    total_reporters = len(reporters)

    with output_path.open("a", encoding="utf-8") as out:
        for idx, reporter in enumerate(remaining, start=len(done) + 1):
            print(f"{idx}/{total_reporters} Fetching reporter={reporter} "
                  f"years={args.start_year}\u2013{args.end_year} \u2026")
            try:
                record = fetch_imts(reporter, args.start_year, args.end_year)
            except ImtsRequestError as exc:
                failures += 1
                print(f"  FAILED: {exc}", file=sys.stderr)
                continue

            n_obs = len(record["payload"])
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  OK  obs={n_obs:,}")
            time.sleep(args.sleep_seconds)

    total_written = total_reporters - failures
    print(f"\nWrote {output_path} ({total_written}/{total_reporters} reporters)")
    if failures:
        print(f"{failures} reporter(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
