#!/usr/bin/env python3
"""Extract annual total imports/exports from UN Comtrade.

This script is the local fallback for sources that Databricks Free Edition
serverless compute cannot reach directly. It intentionally keeps the
subscription key in an HTTP header instead of query parameters so failures do
not print secrets in URLs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


BASE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract UN Comtrade annual TOTAL imports/exports."
    )
    parser.add_argument(
        "--reporter-codes",
        nargs="+",
        required=True,
        help="UN Comtrade reporter codes, for example 120 for Cameroon.",
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSONL path, for example data/raw/comtrade/cemac.jsonl.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Delay between requests to avoid hammering the API.",
    )
    return parser.parse_args()


def request_comtrade(
    session: requests.Session,
    api_key: str,
    reporter_code: str,
    year: int,
) -> dict[str, Any]:
    params = {
        "reporterCode": reporter_code,
        "period": str(year),
        "partnerCode": "all",
        "cmdCode": "TOTAL",
        "flowCode": "M,X",
    }
    headers = {"Ocp-Apim-Subscription-Key": api_key}

    response = session.get(BASE_URL, params=params, headers=headers, timeout=60)
    response.raise_for_status()

    return {
        "source": "un_comtrade",
        "endpoint": BASE_URL,
        "reporter_code": reporter_code,
        "period": year,
        "partner_code": "all",
        "cmd_code": "TOTAL",
        "flow_code": "M,X",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "payload": response.json(),
    }


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("COMTRADE_API_KEY")
    if not api_key:
        print("COMTRADE_API_KEY is not set.", file=sys.stderr)
        return 2

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_requests = len(args.reporter_codes) * (args.end_year - args.start_year + 1)
    completed = 0
    failures = 0

    with requests.Session() as session, output_path.open("w", encoding="utf-8") as out:
        for reporter_code in args.reporter_codes:
            for year in range(args.start_year, args.end_year + 1):
                completed += 1
                try:
                    record = request_comtrade(session, api_key, reporter_code, year)
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
                    print(
                        f"{completed}/{total_requests} ok "
                        f"reporter={reporter_code} year={year}"
                    )
                except requests.RequestException as exc:
                    failures += 1
                    print(
                        f"{completed}/{total_requests} failed reporter={reporter_code} "
                        f"year={year}: {type(exc).__name__}",
                        file=sys.stderr,
                    )
                time.sleep(args.sleep_seconds)

    print(f"Wrote {output_path}")
    if failures:
        print(f"Completed with {failures} failed request(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
