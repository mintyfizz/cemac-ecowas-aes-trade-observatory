#!/usr/bin/env python3
"""Extract Trading Economics trade partner tables without an API key.

This is a "tedata-style" public-page fallback: it requests the visible
Trading Economics exports/imports-by-country pages and parses the HTML table
that appears in the browser. It is useful for diagnostics or spot checks when
official APIs are unavailable, but it is not the canonical dashboard source.

Each JSONL line is one reporter and one flow:
  {
    "source": "tradingeconomics_public_page",
    "method": "tedata_style_html_table_scrape",
    "reporter_iso3": "COG",
    "flow_type": "export",
    "source_url": "https://tradingeconomics.com/republic-of-the-congo/exports-by-country",
    "payload": [
      {"partner_name": "China", "value_usd": 5150000000.0, "year": 2023, ...}
    ]
  }

Typical usage:
    python3 extraction/extract/tradingeconomics_trade_page_extract.py \
        --reporter-codes COG \
        --flows export import \
        --out data/raw/tradingeconomics/cog_te_trade_pages_latest.jsonl

    python3 extraction/extract/tradingeconomics_trade_page_extract.py \
        --all-cemac-ecowas \
        --out data/raw/tradingeconomics/cemac_ecowas_te_trade_pages_latest.jsonl
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

import requests


@dataclass(frozen=True)
class ProjectCountry:
    iso3: str
    name: str
    slug: str
    bloc: str


CEMAC = [
    ProjectCountry("CMR", "Cameroon", "cameroon", "CEMAC"),
    ProjectCountry("CAF", "Central African Republic", "central-african-republic", "CEMAC"),
    ProjectCountry("TCD", "Chad", "chad", "CEMAC"),
    ProjectCountry("COG", "Republic of the Congo", "republic-of-the-congo", "CEMAC"),
    ProjectCountry("GNQ", "Equatorial Guinea", "equatorial-guinea", "CEMAC"),
    ProjectCountry("GAB", "Gabon", "gabon", "CEMAC"),
]

ECOWAS = [
    ProjectCountry("BEN", "Benin", "benin", "ECOWAS"),
    ProjectCountry("BFA", "Burkina Faso", "burkina-faso", "ECOWAS"),
    ProjectCountry("CPV", "Cabo Verde", "cape-verde", "ECOWAS"),
    ProjectCountry("CIV", "Cote d'Ivoire", "ivory-coast", "ECOWAS"),
    ProjectCountry("GMB", "Gambia", "gambia", "ECOWAS"),
    ProjectCountry("GHA", "Ghana", "ghana", "ECOWAS"),
    ProjectCountry("GIN", "Guinea", "guinea", "ECOWAS"),
    ProjectCountry("GNB", "Guinea-Bissau", "guinea-bissau", "ECOWAS"),
    ProjectCountry("LBR", "Liberia", "liberia", "ECOWAS"),
    ProjectCountry("MLI", "Mali", "mali", "ECOWAS"),
    ProjectCountry("NER", "Niger", "niger", "ECOWAS"),
    ProjectCountry("NGA", "Nigeria", "nigeria", "ECOWAS"),
    ProjectCountry("SEN", "Senegal", "senegal", "ECOWAS"),
    ProjectCountry("SLE", "Sierra Leone", "sierra-leone", "ECOWAS"),
    ProjectCountry("TGO", "Togo", "togo", "ECOWAS"),
]

ALL_COUNTRIES = CEMAC + ECOWAS
COUNTRY_BY_ISO3 = {country.iso3: country for country in ALL_COUNTRIES}

ISO2_TO_ISO3 = {
    "CM": "CMR", "CF": "CAF", "TD": "TCD", "CG": "COG", "GQ": "GNQ", "GA": "GAB",
    "BJ": "BEN", "BF": "BFA", "CV": "CPV", "CI": "CIV", "GM": "GMB", "GH": "GHA",
    "GN": "GIN", "GW": "GNB", "LR": "LBR", "ML": "MLI", "NE": "NER", "NG": "NGA",
    "SN": "SEN", "SL": "SLE", "TG": "TGO",
}

FLOW_TO_PAGE = {
    "export": "exports-by-country",
    "import": "imports-by-country",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class TradingEconomicsExtractError(Exception):
    """Raised when a Trading Economics page cannot be fetched or parsed."""


class TradingEconomicsMissingTableError(TradingEconomicsExtractError):
    """Raised when the page has no visible partner-by-country table."""


class SimpleTableParser(HTMLParser):
    """Collect plain-text cells for every HTML table in a document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_table and self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._in_table and self._in_cell and tag in {"td", "th"}:
            cell = normalize_space(" ".join(self._current_cell_parts))
            self._current_row.append(cell)
            self._current_cell_parts = []
            self._in_cell = False
        elif self._in_table and self._in_row and tag == "tr":
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []
            self._in_row = False
        elif self._in_table and tag == "table":
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_table and self._in_cell:
            self._current_cell_parts.append(data)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_money_to_usd(raw_value: str) -> float | None:
    value = normalize_space(raw_value)
    if not value or value.lower() in {"na", "n/a", "-", "--"}:
        return None

    negative = value.startswith("(") and value.endswith(")")
    cleaned = value.strip("()").replace(",", "").replace("$", "").strip()
    match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)([KMBT]?)", cleaned, re.IGNORECASE)
    if not match:
        return None

    number = Decimal(match.group(1))
    multiplier = {
        "": Decimal("1"),
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
        "B": Decimal("1000000000"),
        "T": Decimal("1000000000000"),
    }[match.group(2).upper()]
    result = number * multiplier
    if negative:
        result = -result
    return float(result)


def trading_economics_url(country: ProjectCountry, flow_type: str) -> str:
    return f"https://tradingeconomics.com/{country.slug}/{FLOW_TO_PAGE[flow_type]}"


def fetch_html(url: str, timeout: int, max_retries: int, retry_delay: float) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries:
                wait = retry_delay * attempt
                print(f"    request failed ({attempt}/{max_retries}): {exc}; retrying in {wait:.1f}s")
                time.sleep(wait)
    raise TradingEconomicsExtractError(f"failed to fetch {url}: {last_error}")


def find_partner_table(document_html: str, flow_type: str) -> list[list[str]]:
    parser = SimpleTableParser()
    parser.feed(document_html)

    expected_phrase = f"{flow_type}s by country"
    for table in parser.tables:
        if not table:
            continue
        header = " ".join(table[0]).lower()
        if expected_phrase in header and "value" in header and "year" in header:
            return table

    raise TradingEconomicsMissingTableError(
        f"could not find a Trading Economics '{expected_phrase}' table"
    )


def parse_partner_rows(table: list[list[str]]) -> list[dict]:
    rows: list[dict] = []
    for raw_row in table[1:]:
        if len(raw_row) < 3:
            continue
        partner_name, raw_value, raw_year = raw_row[:3]
        year_match = re.search(r"\d{4}", raw_year)
        rows.append({
            "partner_name": partner_name,
            "partner_iso3": "W00" if partner_name.lower() == "total" else None,
            "value_usd": parse_money_to_usd(raw_value),
            "year": int(year_match.group(0)) if year_match else None,
            "raw_value": raw_value,
            "raw_year": raw_year,
            "is_total": partner_name.lower() == "total",
        })
    return rows


def fetch_trade_page(
    country: ProjectCountry,
    flow_type: str,
    timeout: int,
    max_retries: int,
    retry_delay: float,
) -> dict:
    url = trading_economics_url(country, flow_type)
    document_html = fetch_html(url, timeout, max_retries, retry_delay)
    try:
        table = find_partner_table(document_html, flow_type)
    except TradingEconomicsMissingTableError as exc:
        return {
            "source": "tradingeconomics_public_page",
            "method": "tedata_style_html_table_scrape",
            "status": "no_partner_table",
            "error": str(exc),
            "reporter_iso3": country.iso3,
            "reporter_name": country.name,
            "reporter_slug": country.slug,
            "primary_bloc": country.bloc,
            "flow_type": flow_type,
            "source_url": url,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "row_count": 0,
            "years_present": [],
            "payload": [],
        }

    payload = parse_partner_rows(table)
    years = sorted({row["year"] for row in payload if row["year"] is not None})

    return {
        "source": "tradingeconomics_public_page",
        "method": "tedata_style_html_table_scrape",
        "status": "ok",
        "reporter_iso3": country.iso3,
        "reporter_name": country.name,
        "reporter_slug": country.slug,
        "primary_bloc": country.bloc,
        "flow_type": flow_type,
        "source_url": url,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(payload),
        "years_present": years,
        "payload": payload,
    }


def parse_reporters(args: argparse.Namespace) -> list[ProjectCountry]:
    if args.all_cemac_ecowas:
        reporters = list(ALL_COUNTRIES)
    else:
        reporters = []
        for code in args.reporter_codes:
            iso3 = ISO2_TO_ISO3.get(code.upper(), code.upper())
            if iso3 not in COUNTRY_BY_ISO3:
                raise SystemExit(f"Unknown project reporter code: {code}")
            reporters.append(COUNTRY_BY_ISO3[iso3])

    overrides = parse_slug_overrides(args.slug_override or [])
    if not overrides:
        return reporters

    return [
        ProjectCountry(
            country.iso3,
            country.name,
            overrides.get(country.iso3, country.slug),
            country.bloc,
        )
        for country in reporters
    ]


def parse_slug_overrides(values: Iterable[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --slug-override value '{value}'. Use ISO3=slug.")
        iso3, slug = value.split("=", 1)
        iso3 = ISO2_TO_ISO3.get(iso3.upper(), iso3.upper())
        if iso3 not in COUNTRY_BY_ISO3:
            raise SystemExit(f"Unknown override country code: {iso3}")
        overrides[iso3] = slug.strip().strip("/")
    return overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Trading Economics exports/imports-by-country public pages "
            "using a tedata-style HTML table scrape."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--reporter-codes",
        nargs="+",
        metavar="ISO3",
        help="Project reporter ISO3 codes, e.g. COG CMR. ISO2 is also accepted.",
    )
    group.add_argument(
        "--all-cemac-ecowas",
        action="store_true",
        help="Fetch all 21 CEMAC + ECOWAS project reporters.",
    )
    parser.add_argument(
        "--flows",
        nargs="+",
        choices=sorted(FLOW_TO_PAGE),
        default=["export", "import"],
        help="Flows to fetch. Default: export import.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSONL path, e.g. data/raw/tradingeconomics/latest.jsonl.",
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument(
        "--slug-override",
        action="append",
        help="Override a Trading Economics country slug, e.g. COG=republic-of-the-congo.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reporters = parse_reporters(args)
    flows = list(dict.fromkeys(args.flows))
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done: set[tuple[str, str]] = set()
    if output_path.exists():
        with output_path.open(encoding="utf-8") as existing:
            for line in existing:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    done.add((record["reporter_iso3"], record["flow_type"]))
                except (json.JSONDecodeError, KeyError):
                    pass
        if done:
            print(f"Resuming: {len(done)} reporter-flow pair(s) already in {output_path}.")

    expected_pairs = [(country, flow) for country in reporters for flow in flows]
    failures = 0

    with output_path.open("a", encoding="utf-8") as out:
        for idx, (country, flow) in enumerate(expected_pairs, start=1):
            if (country.iso3, flow) in done:
                continue

            print(f"{idx}/{len(expected_pairs)} Fetching {country.iso3} {flow} page...")
            try:
                record = fetch_trade_page(
                    country=country,
                    flow_type=flow,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    retry_delay=args.retry_delay,
                )
            except TradingEconomicsExtractError as exc:
                failures += 1
                print(f"  FAILED: {exc}", file=sys.stderr)
                continue

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            years = ",".join(str(year) for year in record["years_present"]) or "none"
            status = record.get("status", "ok")
            print(f"  OK status={status} rows={record['row_count']:,} years={years}")
            time.sleep(args.sleep_seconds)

    attempted = len(expected_pairs)
    written = attempted - failures
    print(f"\nWrote {output_path} ({written}/{attempted} reporter-flow pairs attempted)")
    if failures:
        print(f"{failures} reporter-flow pair(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
