#!/usr/bin/env python3
"""Exact-identity contract checks for static/data.

Fails (exit 1) on any violation. These checks test identities, not plausible
ranges, so internally consistent but wrongly scaled data still fails when a
raw snapshot is supplied.

Usage:
    python scripts/check_static_contract.py                 # static identities only
    python scripts/check_static_contract.py --raw-dir DIR   # also recompute from raw snapshots

With --raw-dir the script rebuilds into a temporary directory and requires the
committed files to be byte-identical (reproducibility), then checks headline
values against independent raw recounts.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import observatory_definitions as D  # noqa: E402

DATA = D.ROOT / "static" / "data"
FAILURES: list[str] = []
CHECKS = collections.Counter()


def fail(msg: str) -> None:
    FAILURES.append(msg)


def check(cond: bool, msg: str) -> None:
    CHECKS["run"] += 1
    if not cond:
        fail(msg)


def close(a, b, rel=1e-12, abs_=1e-9) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def static_checks() -> None:
    ct = load("country_timeseries.json")
    tp = load("top_trade_partners.json")
    bc = load("bloc_comparison.json")
    bp = load("bloc_trade_partners.json")
    hs = load("conflict_hotspots.json")
    fr = load("fragility_components.json")
    pr = load("product_trade_hs2.json")
    prov = load("provenance.json")
    fsi_flagged = {(f["country_iso3"], f["year"]) for f in prov.get("fsi_source_inconsistencies", [])}
    roles = D.load_counterpart_roles()

    # Keys and coverage
    keys = [(r["country_iso3"], r["year"]) for r in ct]
    check(len(keys) == len(set(keys)), "country_timeseries: duplicate country-year keys")
    check(len(ct) == len(D.COUNTRIES) * (D.END_YEAR - D.START_YEAR + 1), "country_timeseries: expected 21 x 35 rows")

    for r in ct:
        k = (r["country_iso3"], r["year"])
        # Membership
        bloc, basis = D.analytical_bloc(*k)
        check(r["analytical_bloc_code"] == bloc and r["membership_basis"] == basis, f"{k}: membership rule mismatch")
        # Population identity
        if r["population_persons"] is None or r["population_millions"] is None:
            check(r["population_persons"] is None and r["population_millions"] is None, f"{k}: population null mismatch")
        else:
            check(close(r["population_millions"] * 1e6, r["population_persons"], rel=1e-12), f"{k}: population_millions*1e6 != population_persons")
            check(1e5 < r["population_persons"] < 1e9, f"{k}: population_persons not in persons scale")
        # Rates = counts / population_millions, nulls propagate
        for cnt, rate in (("total_events", "events_per_million"), ("violent_events", "violent_events_per_million"), ("fatalities", "fatalities_per_million")):
            exp = D.per_million(r[cnt], r["population_millions"])
            check(close(r[rate], exp), f"{k}: {rate} != {cnt}/population_millions")
        if not r["acled_covered"]:
            check(r["total_events"] is None and r["fatalities"] is None, f"{k}: ACLED counts must be null before coverage")
        # Trade identities
        check(close(r["total_trade_billions_usd"], None if r["exports_billions_usd"] is None or r["imports_billions_usd"] is None else r["exports_billions_usd"] + r["imports_billions_usd"]), f"{k}: total != exports+imports")
        if r["total_trade_billions_usd"] is not None and r["gdp_current_usd_billions"]:
            check(close(r["trade_openness_pct_gdp"], r["total_trade_billions_usd"] / r["gdp_current_usd_billions"] * 100), f"{k}: openness identity")
        if r["trade_balance_billions_usd"] is not None and r["gdp_current_usd_billions"]:
            check(close(r["trade_balance_pct_gdp"], r["trade_balance_billions_usd"] / r["gdp_current_usd_billions"] * 100, rel=1e-12), f"{k}: balance % GDP identity")
        if r["named_total_trade_billions_usd"] is not None and r["total_trade_billions_usd"] is not None:
            check(close(r["world_minus_named_total_trade_billions_usd"], r["total_trade_billions_usd"] - r["named_total_trade_billions_usd"], abs_=1e-9), f"{k}: world-minus-named identity")
        check(r["top_partner_iso3"] is None or roles.get(r["top_partner_iso3"], {}).get("role") == "named_partner", f"{k}: top partner is not a named economy")
        h = r["total_trade_partner_hhi"]
        check(h is None or 0 < h <= 1, f"{k}: HHI out of [0,1]")
        # FSI: this-year only
        if r["fsi_total_score"] is not None:
            parts = [r[c] for c in ("cohesion_score", "economic_score", "political_score", "social_cross_cutting_score")]
            if None not in parts:
                # FFP publishes the total and the 12 indicators each rounded to 0.1, so
                # the indicator sum may differ from the published total by up to ~0.1.
                # Larger gaps are source inconsistencies and must be disclosed in provenance.
                if not close(sum(parts), r["fsi_total_score"], abs_=0.1501):
                    check(k in fsi_flagged, f"{k}: FSI pillars do not sum to total and the gap is not disclosed")
        else:
            check(all(r[c] is None for c in ("cohesion_score", "economic_score", "political_score", "social_cross_cutting_score")), f"{k}: FSI pillars present without total (look-ahead?)")

    # Partners: named only, dense ranks, top-N, shares consistent
    by_cy = {(r["country_iso3"], r["year"]): r for r in ct}
    groups = collections.defaultdict(list)
    for p in tp:
        groups[(p["country_iso3"], p["year"])].append(p)
        check(roles.get(p["counterpart_code"], {}).get("role") == "named_partner", f"partner {p['counterpart_code']} is not a named economy")
        check(p["counterpart_code"] != p["country_iso3"], f"self-trade partner row {p['country_iso3']} {p['year']}")
    for k, rows in groups.items():
        ranks = sorted(p["partner_rank"] for p in rows)
        check(ranks == list(range(1, len(rows) + 1)), f"{k}: partner ranks not dense 1..n")
        check(len(rows) == min(D.TOP_N_PARTNERS, by_cy[k]["named_partner_count"]), f"{k}: partner row count != min(top N, named count)")
        tt = by_cy[k]["total_trade_billions_usd"]
        for p in rows:
            if tt:
                check(close(p["share_of_world_total_pct"], p["total_trade_billions_usd"] / tt * 100, rel=1e-9), f"{k}: share_of_world identity")
        top = min(rows, key=lambda p: p["partner_rank"])
        check(top["counterpart_code"] == by_cy[k]["top_partner_iso3"], f"{k}: top partner mismatch between files")
        tv = [p["total_trade_billions_usd"] for p in sorted(rows, key=lambda p: p["partner_rank"])]
        check(all(a >= b for a, b in zip(tv, tv[1:])), f"{k}: partner ranks not ordered by trade")

    # Bloc rows: single definitions, recomputable from country rows
    for b in bc:
        k = (b["analytical_bloc_code"], b["year"])
        members = D.bloc_members(*k)
        check(b["members"] == members, f"{k}: bloc members mismatch")
        rows = [by_cy[(c, b["year"])] for c in members]
        tt = [r["total_trade_billions_usd"] for r in rows if r["total_trade_billions_usd"] is not None]
        check(b["trade_reporting"] == len(tt), f"{k}: trade_reporting count")
        check(close(b["total_trade_billions_usd"], sum(tt) if tt else None, rel=1e-12), f"{k}: bloc total != sum of member World totals")
        # Contributor lists must match the values they claim and the counts shown.
        for col_list, cols in (("trade_members", ("total_trade_billions_usd",)), ("gdp_members", ("gdp_current_usd_billions",)),
                               ("population_members", ("population_millions",))):
            exp_members = [r["country_iso3"] for r in rows if all(r[c] is not None for c in cols)]
            check(b[col_list] == exp_members, f"{k}: {col_list} mismatch")
        check(b["trade_reporting"] == len(b["trade_members"]) and b["gdp_reporting"] == len(b["gdp_members"]), f"{k}: reporting counts != contributor lists")
        both = [r for r in rows if r["total_trade_billions_usd"] is not None and r["gdp_current_usd_billions"]]
        check(b["openness_members"] == [r["country_iso3"] for r in both] and b["openness_countries"] == len(both), f"{k}: openness contributors")
        if both:
            den = math.fsum(r["gdp_current_usd_billions"] for r in both)
            for col, src in (("exports_pct_gdp", "exports_billions_usd"), ("imports_pct_gdp", "imports_billions_usd"), ("trade_balance_pct_gdp", "trade_balance_billions_usd")):
                check(close(b[col], math.fsum(r[src] for r in both) / den * 100, rel=1e-12), f"{k}: {col} not matched to openness contributors")
            check(close(b["trade_balance_pct_gdp"], b["exports_pct_gdp"] - b["imports_pct_gdp"], rel=1e-9, abs_=1e-9), f"{k}: balance % GDP != exports % GDP - imports % GDP")
        conf = [r for r in rows if r["fatalities"] is not None and r["population_millions"]]
        check(b["conflict_members"] == [r["country_iso3"] for r in conf], f"{k}: conflict contributors")
        if conf:
            check(close(b["fatalities_per_million"], sum(r["fatalities"] for r in conf) / sum(r["population_millions"] for r in conf)), f"{k}: bloc fatalities rate identity")
        fsi = [r["fsi_total_score"] for r in rows if r["fsi_total_score"] is not None]
        check(b["fsi_reporting"] == len(fsi), f"{k}: bloc FSI count must use same-year values only")
        check(b["bloc_partner_hhi"] is None or 0 < b["bloc_partner_hhi"] <= 1, f"{k}: bloc HHI out of range")
    # Regression (Nov 2026 review R5): ECOWAS 1990 has trade for 15 members but GDP for 14.
    # The balance must use the same 14 contributors as exports/imports % of GDP.
    e90 = next(b for b in bc if b["analytical_bloc_code"] == "ECOWAS" and b["year"] == 1990)
    check(e90["openness_countries"] == 14 and e90["trade_reporting"] == 15, "ECOWAS 1990 contributor counts changed; review the R5 regression")
    check(close(e90["trade_balance_pct_gdp"], 2.7212514678007, rel=1e-9), "ECOWAS 1990 matched balance % GDP regression")

    # Historical/successor overlap flags must match provenance.
    ov = {(o["reporter_iso3"], o["year"]) for o in prov["imts"].get("historical_successor_overlaps", [])}
    for r in ct:
        check(r["historical_successor_overlap"] == ((r["country_iso3"], r["year"]) in ov), f"{(r['country_iso3'], r['year'])}: overlap flag mismatch")

    bgroups = collections.defaultdict(list)
    for p in bp:
        bgroups[(p["analytical_bloc_code"], p["year"])].append(p)
        check(roles.get(p["counterpart_code"], {}).get("role") == "named_partner", f"bloc partner {p['counterpart_code']} not a named economy")
    for k, rows in bgroups.items():
        check(sorted(p["partner_rank"] for p in rows) == list(range(1, len(rows) + 1)), f"{k}: bloc partner ranks not dense")

    # Hotspots: unique, fixed window, totals preserved
    hk = [(h["country_iso3"], h["admin1"]) for h in hs]
    check(len(hk) == len(set(hk)), "hotspots: duplicate country x admin1 rows")
    check(all((h["window_start_year"], h["window_end_year"]) == D.HOTSPOT_WINDOW for h in hs), "hotspots: window not fixed")
    check(all("per_million" not in key for h in hs for key in h), "hotspots: admin1 per-capita fields must not be published")
    for c in D.COUNTRIES:
        hrows = [h for h in hs if h["country_iso3"] == c]
        ranks = sorted(h["hotspot_rank"] for h in hrows)
        check(ranks == list(range(1, len(hrows) + 1)), f"hotspots {c}: ranks not dense")
        for col in ("total_events", "violent_events", "fatalities"):
            yrs = [by_cy[(c, y)][col] for y in range(D.HOTSPOT_WINDOW[0], D.HOTSPOT_WINDOW[1] + 1)]
            if None not in yrs:
                check(sum(h[col] for h in hrows) == sum(yrs), f"hotspots {c}: {col} not preserved vs country-year sums")

    # Fragility: one latest row per country, dated
    check(len({f["country_iso3"] for f in fr}) == len(fr), "fragility: duplicate countries")
    for f in fr:
        k = (f["country_iso3"], f["fsi_year"])
        check(k in by_cy and close(by_cy[k]["fsi_total_score"], f["fsi_total_score"]), f"fragility {k}: does not match its dated country-year")

    # Products: quarantined, no values
    check(isinstance(pr, dict) and pr.get("status") == "quarantined" and pr.get("rows") == [], "products must remain quarantined with no values")


def raw_checks(raw_dir: Path) -> None:
    import offline_rebuild as R

    with tempfile.TemporaryDirectory() as tmp:
        R.build(raw_dir, Path(tmp))
        for f in sorted(Path(tmp).iterdir()):
            committed = DATA / f.name
            check(committed.exists() and committed.read_bytes() == f.read_bytes(), f"reproducibility: {f.name} differs from a fresh rebuild")

    ct = {(r["country_iso3"], r["year"]): r for r in load("country_timeseries.json")}
    # Independent raw recounts (no shared aggregation code)
    world = collections.defaultdict(float)
    for line in (raw_dir / R.RAW_FILES["imts"]).open():
        env = json.loads(line)
        for o in env["payload"]:
            if o["counterpart_iso3"] == "G001" and o["value_usd"] is not None and D.START_YEAR <= o["year"] <= D.END_YEAR:
                world[(o["reporter_iso3"], o["year"], o["indicator"])] = o["value_usd"]
    for (c, y), r in ct.items():
        x, m = world.get((c, y, D.EXPORT_INDICATOR)), world.get((c, y, D.IMPORT_INDICATOR))
        check(close(r["exports_billions_usd"], None if x is None else x / 1e9), f"raw: {c} {y} exports != G001")
        check(close(r["imports_billions_usd"], None if m is None else m / 1e9), f"raw: {c} {y} imports != G001")
    counts = collections.Counter()
    fats = collections.Counter()
    for line in (raw_dir / R.RAW_FILES["acled"]).open():
        env = json.loads(line)
        for e in env["payload"]:
            counts[(env["reporter_iso3"], int(e["year"]))] += 1
            fats[(env["reporter_iso3"], int(e["year"]))] += int(e["fatalities"] or 0)
    for k, n in counts.items():
        if k in ct:
            check(ct[k]["total_events"] == n and ct[k]["fatalities"] == fats[k], f"raw: ACLED recount mismatch {k}")
    pops = {}
    for line in (raw_dir / R.RAW_FILES["weo"]).open():
        r = json.loads(line)
        if r["indicator_code"] == "LP":
            pops[(r["country_iso3"], int(r["year"]))] = r["value"]
    for k, v in pops.items():
        if k in ct:
            check(ct[k]["population_persons"] == v, f"raw: population mismatch {k}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path)
    args = ap.parse_args()
    static_checks()
    if args.raw_dir:
        raw_checks(args.raw_dir)
    print(f"checks run: {CHECKS['run']:,}; failures: {len(FAILURES)}")
    for f in FAILURES[:50]:
        print("FAIL:", f)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
