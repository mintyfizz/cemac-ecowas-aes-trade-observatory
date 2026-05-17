#!/usr/bin/env python3
"""Extract Fragile States Index data for CEMAC + ECOWAS countries.

The Fund for Peace publishes annual FSI Excel downloads. The official Excel
download page currently exposes 2006-2023 files. If a wider date range is
requested, the script extracts the available years and prints the missing
requested years.

Typical usage:

    python3 extraction/extract/fsi_extract.py \\
      --all-cemac-ecowas \\
      --start-year 1990 --end-year 2024 \\
      --out data/raw/fsi/cemac_ecowas_fsi_1990_2024.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

try:
    import certifi
except ImportError:  # pragma: no cover - fallback for minimal Python installs
    certifi = None


EXCEL_PAGE_URL = "https://fragilestatesindex.org/excel/"

CEMAC = ["CMR", "CAF", "TCD", "COG", "GNQ", "GAB"]
ECOWAS = [
    "BEN", "BFA", "CPV", "CIV", "GMB", "GHA", "GIN",
    "GNB", "LBR", "MLI", "NER", "NGA", "SEN", "SLE", "TGO",
]
ALL_COUNTRIES = CEMAC + ECOWAS

COUNTRY_NAME_TO_ISO3 = {
    "Benin": "BEN",
    "Burkina Faso": "BFA",
    "Cameroon": "CMR",
    "Cabo Verde": "CPV",
    "Cape Verde": "CPV",
    "Central African Republic": "CAF",
    "Chad": "TCD",
    "Congo Republic": "COG",
    "Cote d'Ivoire": "CIV",
    "Equatorial Guinea": "GNQ",
    "Gabon": "GAB",
    "Gambia": "GMB",
    "Ghana": "GHA",
    "Guinea": "GIN",
    "Guinea Bissau": "GNB",
    "Liberia": "LBR",
    "Mali": "MLI",
    "Niger": "NER",
    "Nigeria": "NGA",
    "Senegal": "SEN",
    "Sierra Leone": "SLE",
    "Togo": "TGO",
}

ISO3_TO_COUNTRY_NAME = {
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

INDICATOR_META = {
    "TOTAL": ("Total score", "composite"),
    "C1": ("Security Apparatus", "cohesion"),
    "C2": ("Factionalized Elites", "cohesion"),
    "C3": ("Group Grievance", "cohesion"),
    "E1": ("Economy", "economic"),
    "E2": ("Economic Inequality", "economic"),
    "E3": ("Human Flight and Brain Drain", "economic"),
    "P1": ("State Legitimacy", "political"),
    "P2": ("Public Services", "political"),
    "P3": ("Human Rights", "political"),
    "S1": ("Demographic Pressures", "social"),
    "S2": ("Refugees and IDPs", "social"),
    "X1": ("External Intervention", "cross_cutting"),
}


class FsiExtractError(Exception):
    """Raised when FSI extraction cannot continue."""


def ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


SSL_CTX = ssl_context()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Fragile States Index rows for CEMAC + ECOWAS countries."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-cemac-ecowas", action="store_true")
    group.add_argument("--iso3-codes", nargs="+", metavar="ISO3")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    return parser.parse_args()


def selected_countries(args: argparse.Namespace) -> set[str]:
    if args.all_cemac_ecowas:
        return set(ALL_COUNTRIES)
    countries = {code.upper() for code in args.iso3_codes}
    unknown = sorted(countries - set(ALL_COUNTRIES))
    if unknown:
        raise FsiExtractError(f"Unknown project ISO3 code(s): {unknown}")
    return countries


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as response:
        return response.read()


def discover_downloads() -> dict[int, str]:
    html = http_get(EXCEL_PAGE_URL).decode("utf-8", errors="replace")
    urls = sorted(set(re.findall(r"https?://[^\"']+?\.xlsx", html)))
    downloads: dict[int, str] = {}
    for url in urls:
        match = re.search(r"(20\d{2})", url)
        if not match:
            continue
        year = int(match.group(1))
        # Prefer direct annual files if duplicates exist.
        downloads[year] = url
    if not downloads:
        raise FsiExtractError("No FSI Excel download links found.")
    return downloads


def column_index(ref: str) -> int:
    match = re.match(r"([A-Z]+)", ref)
    if not match:
        return 0
    idx = 0
    for char in match.group(1):
        idx = idx * 26 + ord(char) - 64
    return idx - 1


def read_xlsx_first_sheet(data: bytes) -> list[list[Any]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(PathBytes(data)) as workbook:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                text = "".join(
                    (t.text or "")
                    for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                )
                shared_strings.append(text)

        sheet_names = [
            name for name in workbook.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        ]
        if not sheet_names:
            raise FsiExtractError("No worksheets found in FSI Excel file.")
        root = ET.fromstring(workbook.read(sorted(sheet_names)[0]))

        rows: list[list[Any]] = []
        for row in root.findall(".//a:sheetData/a:row", ns):
            values: list[Any] = []
            for cell in row.findall("a:c", ns):
                idx = column_index(cell.attrib.get("r", ""))
                while len(values) <= idx:
                    values.append(None)

                value_node = cell.find("a:v", ns)
                value = None if value_node is None else value_node.text
                if cell.attrib.get("t") == "s" and value is not None:
                    value = shared_strings[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    inline = cell.find(".//a:t", ns)
                    value = inline.text if inline is not None else None
                values[idx] = value
            rows.append(values)
        return rows


class PathBytes:
    """Small adapter so ZipFile can read bytes without importing io at call sites."""

    def __init__(self, data: bytes):
        import io

        self._buffer = io.BytesIO(data)

    def seek(self, *args):
        return self._buffer.seek(*args)

    def read(self, *args):
        return self._buffer.read(*args)

    def tell(self):
        return self._buffer.tell()

    def seekable(self):
        return True


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_rank(value: Any) -> int | None:
    if value in (None, ""):
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def normalize_country_name(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def indicator_from_header(header: str) -> tuple[str, str]:
    if header == "Total":
        return "TOTAL", INDICATOR_META["TOTAL"][0]
    match = re.match(r"([A-Z]\d):\s*(.+)", header)
    if match:
        return match.group(1), match.group(2).strip()
    raise FsiExtractError(f"Unrecognized FSI indicator header: {header}")


def parse_year_file(year: int, url: str, wanted_iso3: set[str]) -> list[dict[str, Any]]:
    data = http_get(url)
    rows = read_xlsx_first_sheet(data)
    if not rows:
        return []

    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    header_index = {name: idx for idx, name in enumerate(headers) if name}
    required = {"Country", "Year", "Rank", "Total"}
    missing = required - set(header_index)
    if missing:
        raise FsiExtractError(f"{year}: missing expected columns {sorted(missing)}")

    indicator_columns: list[tuple[int, str, str, str]] = []
    for idx, header in enumerate(headers):
        if header == "Total" or re.match(r"^[A-Z]\d:", header):
            indicator_code, default_name = indicator_from_header(header)
            meta_name, category = INDICATOR_META.get(indicator_code, (default_name, "unknown"))
            indicator_columns.append((idx, indicator_code, meta_name, category))

    records: list[dict[str, Any]] = []
    extracted_at = datetime.now(timezone.utc).isoformat()
    for row in rows[1:]:
        if not row or len(row) <= header_index["Country"]:
            continue
        country_source = row[header_index["Country"]]
        if country_source in (None, ""):
            continue
        country_source = str(country_source).strip()
        iso3 = COUNTRY_NAME_TO_ISO3.get(normalize_country_name(country_source))
        if iso3 not in wanted_iso3:
            continue

        # Some annual files store the Year cell as an Excel date serial.
        # The file URL year is the reliable annual key for these downloads.
        row_year = year
        rank = parse_rank(row[header_index["Rank"]])
        for idx, indicator_code, indicator_name, category in indicator_columns:
            if idx >= len(row):
                continue
            value = parse_float(row[idx])
            if value is None:
                continue
            records.append({
                "source": "fragile_states_index",
                "dataset": "FSI",
                "country_iso3": iso3,
                "country_name": ISO3_TO_COUNTRY_NAME[iso3],
                "country_name_source": country_source,
                "year": row_year,
                "rank": rank,
                "indicator_code": indicator_code,
                "indicator_name": indicator_name,
                "category": category,
                "value": value,
                "source_url": url,
                "extracted_at": extracted_at,
            })
    return records


def main() -> int:
    args = parse_args()
    wanted_iso3 = selected_countries(args)
    downloads = discover_downloads()
    requested_years = set(range(args.start_year, args.end_year + 1))
    available_years = sorted(year for year in requested_years if year in downloads)
    missing_years = sorted(requested_years - set(available_years))

    if missing_years:
        print(
            "Official FSI Excel downloads are not available for requested year(s): "
            + ", ".join(str(year) for year in missing_years),
            file=sys.stderr,
        )
    if not available_years:
        raise FsiExtractError("No requested years are available from official FSI Excel downloads.")

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_records: list[dict[str, Any]] = []
    for year in available_years:
        print(f"Fetching FSI {year}...")
        records = parse_year_file(year, downloads[year], wanted_iso3)
        all_records.extend(records)
        countries = {record["country_iso3"] for record in records}
        print(f"  {year}: {len(records):,} rows, {len(countries)} project countries")
        time.sleep(args.sleep_seconds)

    with output_path.open("w", encoding="utf-8") as out:
        for record in all_records:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nWrote {output_path}")
    print(f"Rows: {len(all_records):,}")
    print(f"Countries: {len({record['country_iso3'] for record in all_records})}")
    print(f"Years: {min(record['year'] for record in all_records)}-{max(record['year'] for record in all_records)}")
    print(f"Indicators: {len({record['indicator_code'] for record in all_records})}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FsiExtractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
