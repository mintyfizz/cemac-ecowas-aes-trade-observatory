#!/usr/bin/env python3
"""Extract annual total imports/exports from UN Comtrade.

The subscription key is sent in the Ocp-Apim-Subscription-Key HTTP header so
it never appears in URLs, query strings, or error messages. SSL verification
uses the certifi CA bundle.

Typical usage for all 21 CEMAC + ECOWAS countries:

    export COMTRADE_API_KEY="your-key"
    python3 extraction/extract/comtrade_totals.py \\
        --all-cemac-ecowas \\
        --start-year 2010 \\
        --end-year 2023 \\
        --out data/raw/comtrade/cemac_ecowas_totals_2010_2023.jsonl

Then upload the JSONL to your Databricks Volume and run 04_bronze_comtrade_extract.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ssl
import urllib.error
import urllib.parse
import urllib.request

import certifi
from dotenv import find_dotenv, load_dotenv

_API_KEY_PRESET_IN_ENV = "COMTRADE_API_KEY" in os.environ
_DOTENV_PATH = find_dotenv(usecwd=True)
load_dotenv(_DOTENV_PATH or None, override=False)

BASE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# M49 numeric codes for the 21 project countries.
_CEMAC = ["120", "140", "148", "178", "226", "266"]
_ECOWAS = [
    "204", "854", "132", "384", "270", "288",
    "324", "624", "430", "466", "562", "566",
    "686", "694", "768",
]
_ALL_CEMAC_ECOWAS = _CEMAC + _ECOWAS


class ComtradeAuthError(Exception):
    """Raised when UN Comtrade rejects the configured subscription key."""


class ComtradeRequestError(Exception):
    """Raised when a Comtrade request fails after retryable attempts."""


def api_key_source() -> str:
    if _API_KEY_PRESET_IN_ENV:
        return "the COMTRADE_API_KEY environment variable"
    if _DOTENV_PATH:
        return f"the .env file at {_DOTENV_PATH}"
    return "COMTRADE_API_KEY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract UN Comtrade annual TOTAL imports/exports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--reporter-codes",
        nargs="+",
        metavar="CODE",
        help="M49 numeric reporter codes, e.g. 120 for Cameroon.",
    )
    group.add_argument(
        "--all-cemac-ecowas",
        action="store_true",
        help="Shorthand for all 21 CEMAC + ECOWAS countries.",
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSONL path, e.g. data/raw/comtrade/cemac_ecowas_totals.jsonl.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=2.0,
        help="Delay between API calls to stay within rate limits (default: 2).",
    )
    parser.add_argument(
        "--skip-auth-check",
        action="store_true",
        help="Skip the one-request API key validation check before extraction.",
    )
    return parser.parse_args()


def read_api_key() -> str:
    api_key = (os.environ.get("COMTRADE_API_KEY") or "").strip()
    if not api_key:
        raise ComtradeAuthError(
            "COMTRADE_API_KEY is not set. Set it from your rotated UN Comtrade "
            "subscription key before running the extractor."
        )
    if api_key.lower() in {"your-key", "your-rotated-key", "paste_your_key_here"}:
        raise ComtradeAuthError(
            f"{api_key_source()} still contains a placeholder value. Replace it "
            "with the rotated UN Comtrade subscription key from your password "
            "manager."
        )
    return api_key


def build_request(
    api_key: str,
    reporter_code: str,
    year: int,
) -> urllib.request.Request:
    qs = urllib.parse.urlencode({
        "reporterCode": reporter_code,
        "period": str(year),
        "partnerCode": "all",
        "cmdCode": "TOTAL",
        "flowCode": "M,X",
        "breakdownMode": "classic",
        "includeDesc": "false",
    })
    url = f"{BASE_URL}?{qs}"

    hdr = {
        "Cache-Control": "no-cache",
        "Ocp-Apim-Subscription-Key": api_key,
        "User-Agent": "cemac-ecowas-aes-trade-observatory/0.1",
    }
    req = urllib.request.Request(url, headers=hdr)
    req.get_method = lambda: "GET"
    return req


def read_comtrade_json(req: urllib.request.Request) -> dict:
    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as response:
        return json.loads(response.read())


def validate_api_key(api_key: str) -> None:
    """Validate the subscription key once before the full extraction loop."""
    req = build_request(api_key=api_key, reporter_code="120", year=2010)
    try:
        read_comtrade_json(req)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise ComtradeAuthError(
                f"UN Comtrade rejected COMTRADE_API_KEY with HTTP {exc.code}. "
                f"The script is reading the key from {api_key_source()}. "
                "The key is missing, invalid, inactive, expired, or not "
                "subscribed to the API product. Rotate or copy the key again "
                "from the UN Comtrade developer portal, then rerun the command."
            ) from exc
        raise ComtradeRequestError(
            f"UN Comtrade API key check failed with HTTP {exc.code}."
        ) from exc
    except urllib.error.URLError as exc:
        raise ComtradeRequestError(
            f"Could not reach UN Comtrade during API key check: {exc.reason}"
        ) from exc

    print("UN Comtrade API key check passed.")


def fetch_comtrade(
    api_key: str,
    reporter_code: str,
    year: int,
    max_retries: int = 3,
    retry_delay: float = 10.0,
) -> dict:
    """Fetch one reporter-year combination from Comtrade.

    The subscription key goes in the Ocp-Apim-Subscription-Key header only,
    never in the URL or query string.
    """
    req = build_request(api_key=api_key, reporter_code=reporter_code, year=year)

    for attempt in range(1, max_retries + 1):
        try:
            observations = read_comtrade_json(req).get("data", []) or []
            return {
                "source": "un_comtrade",
                "reporter_code": reporter_code,
                "period": year,
                "cmd_code": "TOTAL",
                "flow_code": "M,X",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "payload": observations,
            }
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ComtradeAuthError(
                    f"UN Comtrade rejected COMTRADE_API_KEY with HTTP {exc.code}. "
                    f"The script is reading the key from {api_key_source()}."
                ) from exc
            if exc.code == 429:
                wait = retry_delay * attempt
                print(f"    Rate limited — waiting {wait:.0f}s (attempt {attempt}/{max_retries})")
                time.sleep(wait)
            elif exc.code >= 500:
                print(f"    HTTP {exc.code} reporter={reporter_code} year={year} (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(retry_delay)
            else:
                print(f"    HTTP {exc.code} reporter={reporter_code} year={year} (attempt {attempt}/{max_retries})")
                break
        except Exception as exc:
            print(f"    Error (attempt {attempt}/{max_retries}): {type(exc).__name__}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    raise ComtradeRequestError(
        f"Failed reporter={reporter_code} year={year} after {max_retries} attempt(s)."
    )


def main() -> int:
    args = parse_args()
    reporter_codes = _ALL_CEMAC_ECOWAS if args.all_cemac_ecowas else args.reporter_codes

    try:
        api_key = read_api_key()
        if not args.skip_auth_check:
            validate_api_key(api_key)
    except ComtradeAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ComtradeRequestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_requests = len(reporter_codes) * (args.end_year - args.start_year + 1)
    completed = 0
    request_failures = 0
    empty_responses = 0

    with output_path.open("w", encoding="utf-8") as out:
        for reporter_code in reporter_codes:
            for year in range(args.start_year, args.end_year + 1):
                completed += 1
                try:
                    record = fetch_comtrade(api_key, reporter_code, year)
                except ComtradeAuthError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
                except ComtradeRequestError as exc:
                    request_failures += 1
                    print(str(exc), file=sys.stderr)
                    continue

                n_obs = len(record["payload"])
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                if n_obs == 0:
                    empty_responses += 1
                    status = "empty"
                else:
                    status = "ok"
                print(
                    f"{completed}/{total_requests} {status} "
                    f"reporter={reporter_code} year={year} obs={n_obs}"
                )
                time.sleep(args.sleep_seconds)

    print(f"\nWrote {output_path}")
    print(f"Empty successful responses: {empty_responses}")
    if request_failures:
        print(
            f"Completed with {request_failures} failed request(s) out of {total_requests}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
