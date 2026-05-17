#!/usr/bin/env python3
"""Extract ACLED events locally for upload to Databricks.

Databricks Free Edition serverless can fail DNS resolution for
acleddata.com. This script runs from the local Mac, writes JSONL envelopes,
and the Databricks notebook reads those files from a Volume.

Credentials are read from ACLED_ACCESS_TOKEN, or from ACLED_USERNAME /
ACLED_PASSWORD, or prompted interactively. Do not pass the password as a
command-line argument.

Typical usage:

    python3 extraction/extract/acled_extract.py \\
      --all-cemac-ecowas \\
      --start-year 2010 --end-year 2026 \\
      --out data/raw/acled/cemac_ecowas_acled_2010_2026.jsonl
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
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
except ImportError:  # pragma: no cover - fallback for minimal Python installs
    certifi = None


TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_READ_URL = "https://acleddata.com/api/acled/read"

PROJECT_COUNTRIES = [
    {"iso": "120", "iso3": "CMR", "name": "Cameroon", "bloc_seed": "CEMAC"},
    {"iso": "140", "iso3": "CAF", "name": "Central African Republic", "bloc_seed": "CEMAC"},
    {"iso": "148", "iso3": "TCD", "name": "Chad", "bloc_seed": "CEMAC"},
    {"iso": "178", "iso3": "COG", "name": "Congo, Rep.", "bloc_seed": "CEMAC"},
    {"iso": "226", "iso3": "GNQ", "name": "Equatorial Guinea", "bloc_seed": "CEMAC"},
    {"iso": "266", "iso3": "GAB", "name": "Gabon", "bloc_seed": "CEMAC"},
    {"iso": "204", "iso3": "BEN", "name": "Benin", "bloc_seed": "ECOWAS"},
    {"iso": "854", "iso3": "BFA", "name": "Burkina Faso", "bloc_seed": "ECOWAS"},
    {"iso": "132", "iso3": "CPV", "name": "Cabo Verde", "bloc_seed": "ECOWAS"},
    {"iso": "384", "iso3": "CIV", "name": "Cote d'Ivoire", "bloc_seed": "ECOWAS"},
    {"iso": "270", "iso3": "GMB", "name": "Gambia", "bloc_seed": "ECOWAS"},
    {"iso": "288", "iso3": "GHA", "name": "Ghana", "bloc_seed": "ECOWAS"},
    {"iso": "324", "iso3": "GIN", "name": "Guinea", "bloc_seed": "ECOWAS"},
    {"iso": "624", "iso3": "GNB", "name": "Guinea-Bissau", "bloc_seed": "ECOWAS"},
    {"iso": "430", "iso3": "LBR", "name": "Liberia", "bloc_seed": "ECOWAS"},
    {"iso": "466", "iso3": "MLI", "name": "Mali", "bloc_seed": "ECOWAS"},
    {"iso": "562", "iso3": "NER", "name": "Niger", "bloc_seed": "ECOWAS"},
    {"iso": "566", "iso3": "NGA", "name": "Nigeria", "bloc_seed": "ECOWAS"},
    {"iso": "686", "iso3": "SEN", "name": "Senegal", "bloc_seed": "ECOWAS"},
    {"iso": "694", "iso3": "SLE", "name": "Sierra Leone", "bloc_seed": "ECOWAS"},
    {"iso": "768", "iso3": "TGO", "name": "Togo", "bloc_seed": "ECOWAS"},
]

FIELDS = [
    "event_id_cnty", "event_date", "year", "time_precision",
    "disorder_type", "event_type", "sub_event_type",
    "actor1", "assoc_actor_1", "inter1",
    "actor2", "assoc_actor_2", "inter2", "interaction",
    "civilian_targeting", "iso", "region", "country",
    "admin1", "admin2", "admin3", "location",
    "latitude", "longitude", "geo_precision",
    "source", "source_scale", "fatalities", "tags", "timestamp",
]


class AcledRequestError(Exception):
    """Raised when ACLED extraction cannot continue."""


def ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


SSL_CTX = ssl_context()


def load_dotenv() -> None:
    env_path = Path(__file__).parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract ACLED event rows locally for Databricks ingestion."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-cemac-ecowas", action="store_true")
    group.add_argument("--iso3-codes", nargs="+", metavar="ISO3")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--max-pages-per-country-year", type=int, default=50)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser.parse_args()


def credentials() -> tuple[str, str]:
    load_dotenv()
    username = os.environ.get("ACLED_USERNAME", "").strip()
    password = os.environ.get("ACLED_PASSWORD", "").strip()
    if username and password:
        return username, password

    if not username:
        username = input("ACLED email: ").strip()
    if not password:
        password = getpass.getpass("ACLED password: ").strip()
    if not username or not password:
        raise AcledRequestError("ACLED username and password are required.")
    return username, password


def env_access_token() -> str | None:
    load_dotenv()
    token = os.environ.get("ACLED_ACCESS_TOKEN", "").strip()
    return token or None


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as response:
        return json.loads(response.read())


def http_error_preview(exc: urllib.error.HTTPError) -> str:
    """Read a short, sanitized HTTP error body for diagnostics."""
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    if not body:
        return ""
    return body[:600].replace("\n", " ")


def get_access_token(username: str, password: str) -> str:
    body = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": "acled",
        "scope": "authenticated",
    }).encode("utf-8")
    try:
        payload = request_json(
            TOKEN_URL,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "cemac-ecowas-aes-trade-observatory/0.1",
            },
            data=body,
            timeout=60,
        )
    except urllib.error.HTTPError as exc:
        preview = http_error_preview(exc)
        detail = f" Response body: {preview}" if preview else ""
        raise AcledRequestError(
            f"ACLED OAuth failed with HTTP {exc.code}. Check your email/password, "
            f"account activation, and ACLED API permission.{detail}"
        ) from exc
    return str(payload["access_token"])


def acled_get(
    params: dict[str, str],
    access_token: str,
    *,
    max_retries: int,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{ACLED_READ_URL}?{query}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "cemac-ecowas-aes-trade-observatory/0.1",
    }
    for attempt in range(1, max_retries + 1):
        try:
            payload = request_json(url, headers=headers, timeout=180)
            if int(payload.get("status", 200)) != 200:
                raise AcledRequestError(f"ACLED payload status {payload.get('status')}")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = 10 * attempt
                print(f"    HTTP {exc.code}; retrying in {wait}s")
                time.sleep(wait)
                continue
            raise AcledRequestError(f"ACLED request failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if attempt < max_retries:
                wait = 10 * attempt
                print(f"    Network error; retrying in {wait}s")
                time.sleep(wait)
                continue
            raise AcledRequestError(f"ACLED network error: {exc.reason}") from exc
    raise AcledRequestError("ACLED request failed after retries")


def fetch_country_year(
    country: dict[str, str],
    year: int,
    access_token: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        params = {
            "_format": "json",
            "iso": country["iso"],
            "year": str(year),
            "fields": "|".join(FIELDS),
            "limit": str(args.limit),
            "page": str(page),
        }
        payload = acled_get(params, access_token, max_retries=args.max_retries)
        data = payload.get("data", []) or []
        rows.extend(data)
        print(f"    {country['iso3']} {year} page {page}: {len(data):,} rows")
        if len(data) < args.limit:
            break
        if page >= args.max_pages_per_country_year:
            raise AcledRequestError(
                f"Page guard reached for {country['iso3']} {year}; "
                "increase --max-pages-per-country-year."
            )
        page += 1
        time.sleep(args.sleep_seconds)
    return rows


def selected_countries(args: argparse.Namespace) -> list[dict[str, str]]:
    if args.all_cemac_ecowas:
        return PROJECT_COUNTRIES
    wanted = {code.upper() for code in args.iso3_codes}
    countries = [country for country in PROJECT_COUNTRIES if country["iso3"] in wanted]
    missing = wanted - {country["iso3"] for country in countries}
    if missing:
        raise AcledRequestError(f"Unknown project ISO3 code(s): {sorted(missing)}")
    return countries


def main() -> int:
    args = parse_args()
    countries = selected_countries(args)
    token = env_access_token()
    if token:
        print("Using ACLED_ACCESS_TOKEN from environment/.env.")
    else:
        username, password = credentials()
        token = get_access_token(username, password)
        print("ACLED OAuth token acquired.")

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done: set[tuple[str, int]] = set()
    if output_path.exists():
        with output_path.open(encoding="utf-8") as existing:
            for line in existing:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    done.add((str(record["reporter_iso3"]), int(record["query_year"])))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        if done:
            print(f"Resuming: {len(done)} country-year pair(s) already written.")

    failures = 0
    total_pairs = len(countries) * (args.end_year - args.start_year + 1)
    with output_path.open("a", encoding="utf-8") as out:
        for country in countries:
            print(f"Reporter {country['iso3']} ({country['name']}):")
            for year in range(args.start_year, args.end_year + 1):
                if (country["iso3"], year) in done:
                    continue
                try:
                    rows = fetch_country_year(country, year, token, args)
                except AcledRequestError as exc:
                    failures += 1
                    print(f"  FAILED {country['iso3']} {year}: {exc}", file=sys.stderr)
                    continue

                record = {
                    "source": "acled",
                    "reporter_iso": country["iso"],
                    "reporter_iso3": country["iso3"],
                    "reporter_name": country["name"],
                    "bloc_seed": country["bloc_seed"],
                    "query_year": year,
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "payload": rows,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                print(f"  OK {country['iso3']} {year}: {len(rows):,} rows")
                time.sleep(args.sleep_seconds)

    written_pairs = total_pairs - failures
    print(f"\nWrote {output_path} ({written_pairs}/{total_pairs} pairs attempted)")
    if failures:
        print(f"{failures} country-year request(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
