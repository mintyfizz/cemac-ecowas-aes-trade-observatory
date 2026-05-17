#!/usr/bin/env python3
"""Extract IMF World Economic Outlook indicators for the project countries.

The script uses the IMF SDMX 2.1 API and writes one JSON object per
country-indicator-year observation. No API key is required.

Typical usage:

    python3 extraction/extract/imf_weo_extract.py \\
      --all-cemac-ecowas \\
      --start-year 1990 --end-year 2024 \\
      --out data/raw/weo/cemac_ecowas_weo_1990_2024.jsonl
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - fallback for minimal Python installs
    certifi = None


BASE_URL = "https://api.imf.org/external/sdmx/2.1/data/WEO"

CEMAC = ["CMR", "CAF", "TCD", "COG", "GNQ", "GAB"]
ECOWAS = [
    "BEN", "BFA", "CPV", "CIV", "GMB", "GHA", "GIN",
    "GNB", "LBR", "MLI", "NER", "NGA", "SEN", "SLE", "TGO",
]
ALL_COUNTRIES = CEMAC + ECOWAS

COUNTRY_NAMES = {
    "BEN": "Benin",
    "BFA": "Burkina Faso",
    "CAF": "Central African Republic",
    "CIV": "Cote d'Ivoire",
    "CMR": "Cameroon",
    "COG": "Congo, Rep.",
    "CPV": "Cabo Verde",
    "GAB": "Gabon",
    "GHA": "Ghana",
    "GIN": "Guinea",
    "GMB": "Gambia",
    "GNB": "Guinea-Bissau",
    "GNQ": "Equatorial Guinea",
    "LBR": "Liberia",
    "MLI": "Mali",
    "NER": "Niger",
    "NGA": "Nigeria",
    "SEN": "Senegal",
    "SLE": "Sierra Leone",
    "TCD": "Chad",
    "TGO": "Togo",
}

INDICATORS = {
    "GGXWDG_NGDP": {
        "name": "Gross debt, General government, Percent of GDP",
        "unit": "percent_of_gdp",
        "topic": "fiscal",
    },
    "GGR_NGDP": {
        "name": "Revenue, General government, Percent of GDP",
        "unit": "percent_of_gdp",
        "topic": "fiscal",
    },
    "GGX_NGDP": {
        "name": "Expenditure, General government, Percent of GDP",
        "unit": "percent_of_gdp",
        "topic": "fiscal",
    },
    "GGXCNL_NGDP": {
        "name": "Net lending (+) / net borrowing (-), General government, Percent of GDP",
        "unit": "percent_of_gdp",
        "topic": "fiscal",
    },
    "BCA_NGDPD": {
        "name": "Current account balance, Percent of GDP",
        "unit": "percent_of_gdp",
        "topic": "external",
    },
    "NGDP_RPCH": {
        "name": "Gross domestic product, constant prices, Percent change",
        "unit": "annual_percent_change",
        "topic": "macro",
    },
    "PCPIPCH": {
        "name": "Consumer price index, period average, Percent change",
        "unit": "annual_percent_change",
        "topic": "macro",
    },
    "NGDPD": {
        "name": "Gross domestic product, current prices, US dollars",
        "unit": "current_usd",
        "topic": "macro",
    },
}


class WeoRequestError(Exception):
    """Raised when an IMF WEO request fails."""


def ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


SSL_CTX = ssl_context()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract IMF WEO observations for CEMAC + ECOWAS countries."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-cemac-ecowas", action="store_true")
    group.add_argument("--iso3-codes", nargs="+", metavar="ISO3")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--indicators",
        nargs="+",
        default=list(INDICATORS),
        choices=sorted(INDICATORS),
        help="WEO indicator codes to extract.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def selected_countries(args: argparse.Namespace) -> list[str]:
    if args.all_cemac_ecowas:
        return ALL_COUNTRIES
    countries = [code.upper() for code in args.iso3_codes]
    unknown = sorted(set(countries) - set(ALL_COUNTRIES))
    if unknown:
        raise WeoRequestError(f"Unknown project ISO3 code(s): {unknown}")
    return countries


def fetch_weo_xml(
    countries: list[str],
    indicator_code: str,
    start_year: int,
    end_year: int,
    max_retries: int,
) -> str:
    country_key = "+".join(countries)
    key = f"{country_key}.{indicator_code}.A"
    url = f"{BASE_URL}/{key}?startPeriod={start_year}&endPeriod={end_year}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "cemac-ecowas-aes-trade-observatory/0.1"},
    )

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=180, context=SSL_CTX) as response:
                return response.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            if attempt < max_retries:
                wait = 10 * attempt
                print(f"  {indicator_code}: request failed ({type(exc).__name__}); retrying in {wait}s")
                time.sleep(wait)
                continue
            raise WeoRequestError(f"{indicator_code}: failed after {max_retries} attempts: {exc}") from exc

    raise WeoRequestError(f"{indicator_code}: failed after {max_retries} attempts")


def parse_weo_xml(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    extracted_at = datetime.now(timezone.utc).isoformat()

    for series in root.iter():
        if local_name(series.tag) != "Series":
            continue

        attrs = dict(series.attrib)
        country_iso3 = attrs.get("COUNTRY", "")
        indicator_code = attrs.get("INDICATOR", "")
        indicator = INDICATORS.get(indicator_code)
        if indicator is None:
            continue

        for obs in series:
            if local_name(obs.tag) != "Obs":
                continue
            raw_value = obs.attrib.get("OBS_VALUE")
            records.append({
                "source": "imf_weo",
                "dataset": "WEO",
                "frequency": attrs.get("FREQUENCY"),
                "country_iso3": country_iso3,
                "country_name": COUNTRY_NAMES.get(country_iso3, country_iso3),
                "indicator_code": indicator_code,
                "indicator_name": indicator["name"],
                "topic": indicator["topic"],
                "unit": indicator["unit"],
                "year": int(obs.attrib["TIME_PERIOD"]),
                "value": float(raw_value) if raw_value not in (None, "") else None,
                "scale": attrs.get("SCALE"),
                "decimals_displayed": attrs.get("DECIMALS_DISPLAYED"),
                "country_update_date": attrs.get("COUNTRY_UPDATE_DATE"),
                "overlap": attrs.get("OVERLAP"),
                "extracted_at": extracted_at,
            })

    return records


def main() -> int:
    args = parse_args()
    countries = selected_countries(args)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_records: list[dict[str, Any]] = []
    for indicator_code in args.indicators:
        print(f"Fetching {indicator_code} for {len(countries)} countries...")
        xml_text = fetch_weo_xml(
            countries=countries,
            indicator_code=indicator_code,
            start_year=args.start_year,
            end_year=args.end_year,
            max_retries=args.max_retries,
        )
        records = parse_weo_xml(xml_text)
        all_records.extend(records)
        print(f"  {indicator_code}: {len(records):,} observations")
        time.sleep(args.sleep_seconds)

    with output_path.open("w", encoding="utf-8") as out:
        for record in all_records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    countries_seen = {record["country_iso3"] for record in all_records}
    indicators_seen = {record["indicator_code"] for record in all_records}
    print(f"\nWrote {output_path}")
    print(f"Rows: {len(all_records):,}")
    print(f"Countries: {len(countries_seen)}")
    print(f"Indicators: {len(indicators_seen)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WeoRequestError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
