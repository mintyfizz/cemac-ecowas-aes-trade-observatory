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
from dotenv import load_dotenv

# Resolve .env from the project root (two levels above this file).
_DOTENV_PATH = Path(__file__).parents[2] / ".env"
_API_KEY_PRESET_IN_ENV = "COMTRADE_API_KEY" in os.environ
load_dotenv(_DOTENV_PATH, override=False)

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
    if _DOTENV_PATH.exists():
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
    parser.add_argument(
        "--max-calls",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N successful API calls (quota guard). Rerun to resume.",
    )
    return parser.parse_args()


_PLACEHOLDERS = {"your-key", "your-rotated-key", "paste_your_key_here"}


def read_api_keys() -> list[str]:
    """Return all configured API keys (COMTRADE_API_KEY, COMTRADE_API_KEY_2, …)."""
    keys: list[str] = []
    for var in ("COMTRADE_API_KEY", "COMTRADE_API_KEY_2", "COMTRADE_API_KEY_3"):
        val = (os.environ.get(var) or "").strip()
        if val and val.lower() not in _PLACEHOLDERS:
            keys.append(val)
    if not keys:
        raise ComtradeAuthError(
            "No valid COMTRADE_API_KEY found. Set it in .env from the UN Comtrade "
            "developer portal before running the extractor."
        )
    return keys


def build_request(
    api_key: str,
    reporter_code: str,
    year: int,
) -> urllib.request.Request:
    qs = urllib.parse.urlencode({
        "reporterCode": reporter_code,
        "period": str(year),
        # Request every partner row for this reporter-year.
        # The Databricks notebook filters partnerCode == 0 (World aggregate).
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


def _parse_retry_after(exc: urllib.error.HTTPError) -> str:
    """Return a human-readable wait hint from the Retry-After header, if present."""
    retry_after = exc.headers.get("Retry-After", "")
    if retry_after.isdigit():
        secs = int(retry_after)
        h, m = divmod(secs // 60, 60)
        return f" Quota resets in {h}h {m}m (Retry-After: {retry_after}s)."
    return ""


def _check_quota_exceeded(exc: urllib.error.HTTPError) -> bool:
    """Return True if the 403 body indicates a quota / volume limit error."""
    try:
        body = exc.read().decode("utf-8", errors="replace").lower()
        return "quota" in body or "call volume" in body or "rate limit" in body
    except Exception:
        return False


def validate_api_key(api_key: str) -> None:
    """Validate the subscription key once before the full extraction loop."""
    req = build_request(api_key=api_key, reporter_code="120", year=2010)
    try:
        read_comtrade_json(req)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ComtradeAuthError(
                f"UN Comtrade rejected COMTRADE_API_KEY with HTTP 401 (Unauthorized). "
                f"The script is reading the key from {api_key_source()}. "
                "The key is missing, invalid, or not subscribed to the comtrade-v1 "
                "product on comtradedeveloper.un.org."
            ) from exc
        if exc.code == 403:
            if _check_quota_exceeded(exc):
                raise ComtradeRequestError(
                    f"UN Comtrade daily call quota is exhausted (HTTP 403).{_parse_retry_after(exc)} "
                    "Wait for the quota to reset, then rerun."
                ) from exc
            raise ComtradeAuthError(
                f"UN Comtrade rejected COMTRADE_API_KEY with HTTP 403 (Forbidden). "
                f"The script is reading the key from {api_key_source()}. "
                "Check that the key is subscribed to the comtrade-v1 product."
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
            if exc.code == 401:
                raise ComtradeAuthError(
                    f"UN Comtrade rejected COMTRADE_API_KEY with HTTP 401 (Unauthorized). "
                    f"The script is reading the key from {api_key_source()}."
                ) from exc
            if exc.code == 403:
                if _check_quota_exceeded(exc):
                    raise ComtradeRequestError(
                        f"UN Comtrade daily call quota is exhausted (HTTP 403).{_parse_retry_after(exc)} "
                        "Wait for the quota to reset, then rerun."
                    ) from exc
                raise ComtradeAuthError(
                    f"UN Comtrade rejected COMTRADE_API_KEY with HTTP 403 (Forbidden). "
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
        api_keys = read_api_keys()
    except ComtradeAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    api_key = api_keys[0]
    key_index = 0
    print(f"Using key {key_index + 1}/{len(api_keys)}")

    if not args.skip_auth_check:
        try:
            validate_api_key(api_key)
        except ComtradeAuthError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except ComtradeRequestError as exc:
            # quota on key 1 — try next key
            if len(api_keys) > 1:
                key_index = 1
                api_key = api_keys[key_index]
                print(f"Key 1 quota exhausted. Switching to key {key_index + 1}/{len(api_keys)}")
                try:
                    validate_api_key(api_key)
                except (ComtradeAuthError, ComtradeRequestError) as exc2:
                    print(str(exc2), file=sys.stderr)
                    return 1
            else:
                print(str(exc), file=sys.stderr)
                return 1

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Resume: find (reporter_code, year) pairs already written ---
    done: set[tuple[str, int]] = set()
    if output_path.exists():
        with output_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done.add((str(rec["reporter_code"]), int(rec["period"])))
                except (json.JSONDecodeError, KeyError):
                    pass
        if done:
            print(f"Resuming: {len(done)} pair(s) already in {output_path}, skipping them.")

    all_pairs = [
        (rc, yr)
        for rc in reporter_codes
        for yr in range(args.start_year, args.end_year + 1)
        if (rc, yr) not in done
    ]
    total_remaining = len(all_pairs)
    total_overall = len(reporter_codes) * (args.end_year - args.start_year + 1)
    calls_this_run = 0
    request_failures = 0
    empty_responses = 0

    with output_path.open("a", encoding="utf-8") as out:
        for idx, (reporter_code, year) in enumerate(all_pairs, start=1):
            if args.max_calls is not None and calls_this_run >= args.max_calls:
                print(
                    f"\n--max-calls {args.max_calls} reached after {calls_this_run} call(s). "
                    f"{total_remaining - idx + 1} pair(s) remaining. Rerun to resume."
                )
                break

            try:
                record = fetch_comtrade(api_key, reporter_code, year)
            except ComtradeAuthError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            except ComtradeRequestError as exc:
                # If quota exhausted, rotate to next key
                if "quota" in str(exc).lower() and key_index + 1 < len(api_keys):
                    key_index += 1
                    api_key = api_keys[key_index]
                    print(f"\nKey quota exhausted. Switching to key {key_index + 1}/{len(api_keys)}")
                    try:
                        record = fetch_comtrade(api_key, reporter_code, year)
                    except (ComtradeAuthError, ComtradeRequestError) as exc2:
                        request_failures += 1
                        print(str(exc2), file=sys.stderr)
                        continue
                else:
                    request_failures += 1
                    print(str(exc), file=sys.stderr)
                    continue

            calls_this_run += 1
            n_obs = len(record["payload"])
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            status = "empty" if n_obs == 0 else "ok"
            if n_obs == 0:
                empty_responses += 1
            already = len(done)
            print(
                f"{already + idx}/{total_overall} {status} "
                f"reporter={reporter_code} year={year} obs={n_obs}"
            )
            time.sleep(args.sleep_seconds)

    print(f"\nWrote {output_path} ({len(done) + calls_this_run}/{total_overall} pairs total)")
    print(f"Empty successful responses this run: {empty_responses}")
    if request_failures:
        print(
            f"Completed with {request_failures} failed request(s).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
