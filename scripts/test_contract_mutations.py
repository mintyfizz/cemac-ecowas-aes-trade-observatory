#!/usr/bin/env python3
"""Prove the contract checks catch the defects found in the Nov 2026 review.

Each mutation re-introduces one known defect into a temporary copy of
static/data and asserts that scripts/check_static_contract.py fails on it.

Usage:
    python scripts/test_contract_mutations.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_static_contract as C  # noqa: E402
import observatory_definitions as D  # noqa: E402


def mutate_population(data):
    r = data["country_timeseries.json"][100]
    r["population_persons"] *= 1e6  # persons x 1e6, as in the old gold table


def mutate_rate_scale(data):
    for r in data["country_timeseries.json"]:
        if r["fatalities_per_million"]:
            r["fatalities_per_million"] /= 1e6
            return


def mutate_aggregate_partner(data):
    p = data["top_trade_partners.json"][0]
    p["counterpart_code"] = "G001"


def mutate_sparse_ranks(data):
    for p in data["top_trade_partners.json"]:
        if p["partner_rank"] == 1:
            p["partner_rank"] = 8  # ranks left sparse after filtering aggregates
            return


def mutate_duplicate_hotspot(data):
    h = dict(data["conflict_hotspots.json"][0])
    data["conflict_hotspots.json"].append(h)


def mutate_hotspot_window(data):
    data["conflict_hotspots.json"][0]["window_start_year"] = 2024


def mutate_fsi_lookahead(data):
    for r in data["country_timeseries.json"]:
        if r["year"] == 1990:
            r["fsi_total_score"] = 90.0
            r["cohesion_score"] = 20.0
            return


def mutate_products_unquarantined(data):
    data["product_trade_hs2.json"] = {"status": "ok", "rows": [{"reporter_iso3": "GHA"}]}


def mutate_inflated_total(data):
    r = data["country_timeseries.json"][5]
    r["exports_billions_usd"] *= 4.7
    r["total_trade_billions_usd"] = r["exports_billions_usd"] + r["imports_billions_usd"]


MUTATIONS = [
    mutate_population,
    mutate_rate_scale,
    mutate_aggregate_partner,
    mutate_sparse_ranks,
    mutate_duplicate_hotspot,
    mutate_hotspot_window,
    mutate_fsi_lookahead,
    mutate_products_unquarantined,
    mutate_inflated_total,
]


def run(mutation) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for f in C.DATA.iterdir():
            shutil.copy(f, tmp / f.name)
        data = {f.name: json.loads(f.read_text()) for f in tmp.iterdir()}
        mutation(data)
        for name, obj in data.items():
            (tmp / name).write_text(json.dumps(obj))
        C.DATA = tmp
        C.FAILURES.clear()
        try:
            C.static_checks()
        except (KeyError, TypeError) as exc:  # a structural break also counts as caught
            C.FAILURES.append(f"structural: {exc!r}")
        return len(C.FAILURES)


def main() -> int:
    original = C.DATA
    missed = []
    for m in MUTATIONS:
        n = run(m)
        C.DATA = original
        status = "caught" if n else "MISSED"
        print(f"{m.__name__:34s} {status} ({n} failures)")
        if not n:
            missed.append(m.__name__)
    # An inflated World total is caught here through the partner-share and bloc
    # identities; check_static_contract.py --raw-dir additionally compares every
    # headline total with the raw G001 rows.
    if missed:
        print("MISSED:", missed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
