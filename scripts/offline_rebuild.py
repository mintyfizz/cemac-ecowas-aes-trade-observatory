#!/usr/bin/env python3
"""Deterministic offline rebuild of the static dashboard data from preserved raw snapshots.

Reads the original extractor JSONL files (never modifies them) and writes
static/data/*.json plus static/data/provenance.json. No network, no Databricks.

Usage:
    python scripts/offline_rebuild.py --raw-dir /path/to/raw-readonly [--out static/data]

Expected raw files (names as produced by extraction/extract/*):
    cemac_ecowas_imts_1990_2024.jsonl   IMF IMTS bilateral goods trade
    cemac_ecowas_weo_1990_2024.jsonl    IMF World Economic Outlook indicators
    cemac_ecowas_acled_1990_2024.jsonl  ACLED events, one envelope per country-year query
    cemac_ecowas_fsi_1990_2024.jsonl    Fund for Peace Fragile States Index

Same inputs -> byte-identical outputs (no wall-clock timestamps are written).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import observatory_definitions as D  # noqa: E402

RAW_FILES = {
    "imts": "cemac_ecowas_imts_1990_2024.jsonl",
    "weo": "cemac_ecowas_weo_1990_2024.jsonl",
    "acled": "cemac_ecowas_acled_1990_2024.jsonl",
    "fsi": "cemac_ecowas_fsi_1990_2024.jsonl",
}

YEARS = range(D.START_YEAR, D.END_YEAR + 1)


class BuildError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def bn(v):
    return None if v is None else v / 1e9


def pct(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den * 100.0


def add(a, b):
    return None if a is None or b is None else a + b


def sub(a, b):
    return None if a is None or b is None else a - b


# ---------------------------------------------------------------------------
# IMF IMTS
# ---------------------------------------------------------------------------
def load_imts(path: Path):
    roles = D.load_counterpart_roles()
    obs: dict[tuple, float] = {}
    seen_codes: collections.Counter = collections.Counter()
    extracted = set()
    negatives = 0
    for env in jsonl(path):
        extracted.add(env.get("extracted_at"))
        for o in env["payload"]:
            rep, cp, ind, yr = o["reporter_iso3"], o["counterpart_iso3"], o["indicator"], int(o["year"])
            if ind not in (D.EXPORT_INDICATOR, D.IMPORT_INDICATOR) or not (D.START_YEAR <= yr <= D.END_YEAR):
                continue
            key = (rep, cp, ind, yr)
            if key in obs:
                raise BuildError(f"Duplicate IMTS observation {key}; refusing to sum duplicates.")
            if o["value_usd"] is None:
                continue
            if o["value_usd"] < 0:
                negatives += 1
            obs[key] = float(o["value_usd"])
            seen_codes[cp] += 1
    unknown = sorted(c for c in seen_codes if c not in roles)
    if unknown:
        raise BuildError(f"IMTS counterpart codes not in config/imts_counterpart_roles.csv: {unknown}")
    if negatives:
        raise BuildError(f"{negatives} negative IMTS values found; review before building.")

    # Per reporter-year aggregates
    world = collections.defaultdict(dict)        # (rep, yr) -> {ind: value}
    named = collections.defaultdict(lambda: collections.defaultdict(lambda: [None, None]))  # (rep,yr)->{cp:[x,m]}
    unalloc = collections.defaultdict(lambda: [0.0, 0.0, False])
    for (rep, cp, ind, yr), v in obs.items():
        role = roles[cp]["role"]
        i = 0 if ind == D.EXPORT_INDICATOR else 1
        if role == "world":
            world[(rep, yr)][ind] = v
        elif role == "named_partner":
            if cp == rep:
                continue  # self-trade is not a partner
            named[(rep, yr)][cp][i] = v
        elif role == "unallocated":
            unalloc[(rep, yr)][i] += v
            unalloc[(rep, yr)][2] = True
    audit = collections.Counter()
    for cp, n in seen_codes.items():
        audit[roles[cp]["role"]] += n
    meta = {
        "observations": len(obs),
        "counterpart_codes_seen": len(seen_codes),
        "observations_by_role": dict(sorted(audit.items())),
        "non_named_codes_seen": [
            {"code": c, "name": roles[c]["name_en"], "role": roles[c]["role"], "observations": n}
            for c, n in sorted(seen_codes.items()) if roles[c]["role"] != "named_partner"
        ],
        "historical_or_combined_named_codes_seen": sorted(
            c for c in seen_codes if roles[c]["historical_or_combined"] == "yes"
        ),
        "extracted_at": sorted(e for e in extracted if e),
    }
    return world, named, unalloc, roles, meta


def partner_rows(named_cp: dict, roles):
    rows = []
    for cp, (x, m) in named_cp.items():
        tot = (x or 0.0) + (m or 0.0)
        rows.append({
            "code": cp,
            "name": roles[cp]["name_en"],
            "historical": roles[cp]["historical_or_combined"] == "yes",
            "x": x, "m": m, "t": tot,
        })
    rows.sort(key=lambda r: (-r["t"], r["code"]))
    return rows


# ---------------------------------------------------------------------------
# WEO
# ---------------------------------------------------------------------------
def load_weo(path: Path):
    vals: dict[tuple, dict] = collections.defaultdict(dict)
    seen = set()
    meta_ind = {}
    cud = collections.defaultdict(set)
    extracted = set()
    for r in jsonl(path):
        code = r["indicator_code"]
        if code not in D.WEO_COLUMNS:
            continue
        key = (r["country_iso3"], code, int(r["year"]))
        if key in seen:
            raise BuildError(f"Duplicate WEO observation {key}")
        seen.add(key)
        vals[(r["country_iso3"], int(r["year"]))][D.WEO_COLUMNS[code]] = r["value"]
        meta_ind[code] = {"name": r.get("indicator_name"), "unit_label": r.get("unit"), "source_scale": r.get("scale")}
        cud[r["country_iso3"]].add(r.get("country_update_date"))
        extracted.add(r.get("extracted_at"))
    meta = {
        "indicators": dict(sorted(meta_ind.items())),
        "extracted_at": sorted(e for e in extracted if e),
        "country_update_date_by_country": {k: sorted(v) for k, v in sorted(cud.items())},
        "release_vintage": "not recorded in the snapshot",
        "value_scale_note": "Extractor applied the SDMX SCALE attribute: NGDPD is in USD and LP is in persons, although unit_label says millions_of_persons.",
        "observed_vs_estimate": "not available in the snapshot; latest years may be IMF staff estimates",
    }
    return vals, meta


# ---------------------------------------------------------------------------
# ACLED
# ---------------------------------------------------------------------------
def load_acled(path: Path):
    queried = set()
    events = {}
    extracted = set()
    for env in jsonl(path):
        iso3, qy = env["reporter_iso3"], int(env["query_year"])
        if (iso3, qy) in queried:
            raise BuildError(f"Duplicate ACLED envelope {(iso3, qy)}")
        queried.add((iso3, qy))
        extracted.add(env.get("extracted_at"))
        for e in env["payload"]:
            eid = e["event_id_cnty"]
            if eid in events:
                if events[eid] != (iso3, e):
                    raise BuildError(f"Conflicting duplicate ACLED event id {eid}")
                continue
            events[eid] = (iso3, e)
    cy = collections.defaultdict(lambda: collections.Counter())
    hot = collections.defaultdict(lambda: collections.Counter())
    for eid, (iso3, e) in events.items():
        yr = int(e["year"])
        fat = int(e["fatalities"]) if e.get("fatalities") not in (None, "") else 0
        et = e["event_type"]
        c = cy[(iso3, yr)]
        c["total_events"] += 1
        c["fatalities"] += fat
        if et in D.VIOLENT_EVENT_TYPES:
            c["violent_events"] += 1
        c[f"type::{et}"] += 1
        if D.HOTSPOT_WINDOW[0] <= yr <= D.HOTSPOT_WINDOW[1]:
            h = hot[(iso3, e.get("admin1") or "(admin1 not recorded)")]
            h["total_events"] += 1
            h["fatalities"] += fat
            if et in D.VIOLENT_EVENT_TYPES:
                h["violent_events"] += 1
            h[f"type::{et}"] += 1
    first_year = {}
    for (iso3, yr) in cy:
        first_year[iso3] = min(yr, first_year.get(iso3, 9999))
    meta = {
        "events": len(events),
        "country_year_queries": len(queried),
        "extracted_at_range": [min(e for e in extracted if e), max(e for e in extracted if e)],
        "coverage_start_by_country": dict(sorted(first_year.items())),
        "coverage_rule": (
            "A country-year is treated as covered from the first year in which ACLED returned any "
            "event for that country. Covered years whose query returned no events are recorded as "
            "0 events; earlier years are null (not covered or unknown), never 0."
        ),
        "violent_event_types": list(D.VIOLENT_EVENT_TYPES),
    }
    return cy, hot, queried, first_year, meta


# ---------------------------------------------------------------------------
# FSI
# ---------------------------------------------------------------------------
def load_fsi(path: Path):
    vals = collections.defaultdict(dict)
    rank = {}
    seen = set()
    urls = set()
    extracted = set()
    for r in jsonl(path):
        code = r["indicator_code"]
        if code not in D.FSI_COLUMNS:
            continue
        key = (r["country_iso3"], int(r["year"]), code)
        if key in seen:
            raise BuildError(f"Duplicate FSI observation {key}")
        seen.add(key)
        vals[(r["country_iso3"], int(r["year"]))][code] = r["value"]
        if code == "TOTAL":
            rank[(r["country_iso3"], int(r["year"]))] = r.get("rank")
        urls.add(r.get("source_url"))
        extracted.add(r.get("extracted_at"))
    years = sorted({y for (_, y) in vals})
    meta = {
        "years": [years[0], years[-1]] if years else None,
        "latest_year_loaded": years[-1] if years else None,
        "extracted_at": sorted(e for e in extracted if e),
        "source_files": len(urls),
        "note": "FSI 2024 (published Feb 2025) is not in this snapshot; latest loaded edition is shown with its year.",
    }
    return vals, rank, meta


def fsi_record(v: dict) -> dict:
    out = {col: v.get(code) for code, col in D.FSI_COLUMNS.items()}
    for pillar, codes in D.FSI_PILLARS.items():
        parts = [v.get(c) for c in codes]
        out[pillar] = None if any(p is None for p in parts) else round(sum(parts), 6)
    return out


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build(raw_dir: Path, out_dir: Path) -> dict:
    paths = {k: raw_dir / name for k, name in RAW_FILES.items()}
    for k, p in paths.items():
        if not p.exists():
            raise BuildError(f"Missing raw file for {k}: {p}")

    world, named, unalloc, roles, imts_meta = load_imts(paths["imts"])
    weo, weo_meta = load_weo(paths["weo"])
    acled_cy, acled_hot, acled_queried, acled_first, acled_meta = load_acled(paths["acled"])
    fsi_vals, fsi_rank, fsi_meta = load_fsi(paths["fsi"])

    country_rows = []
    partner_out = []
    named_by_cy = {}
    for iso3, (name, region, _) in sorted(D.COUNTRIES.items()):
        for yr in YEARS:
            bloc, basis = D.analytical_bloc(iso3, yr)
            w = weo.get((iso3, yr), {})
            gdp = w.get("gdp_current_usd")
            pop_persons = w.get("population_persons")
            pop_m = None if pop_persons is None else pop_persons / 1e6

            wx = world.get((iso3, yr), {}).get(D.EXPORT_INDICATOR)
            wm = world.get((iso3, yr), {}).get(D.IMPORT_INDICATOR)
            wt = add(wx, wm)
            prow = partner_rows(named.get((iso3, yr), {}), roles)
            named_by_cy[(iso3, yr)] = prow
            nx = sum(r["x"] or 0.0 for r in prow) if prow else None
            nm = sum(r["m"] or 0.0 for r in prow) if prow else None
            nt = add(nx, nm)
            ua = unalloc.get((iso3, yr))
            top = prow[0] if prow else None
            top3 = sum(r["t"] for r in prow[:3]) if prow else None

            covered = iso3 in acled_first and yr >= acled_first[iso3]
            c = acled_cy.get((iso3, yr))
            if covered:
                if (iso3, yr) not in acled_queried:
                    raise BuildError(f"ACLED covered year without a query envelope: {(iso3, yr)}")
                c = c or collections.Counter()
                ev, vev, fat = c["total_events"], c["violent_events"], c["fatalities"]
            else:
                if c:
                    raise BuildError(f"ACLED events before coverage start: {(iso3, yr)}")
                ev = vev = fat = None

            f = fsi_vals.get((iso3, yr))
            frec = fsi_record(f) if f else {col: None for col in list(D.FSI_COLUMNS.values()) + list(D.FSI_PILLARS)}

            row = {
                "country_iso3": iso3,
                "country_name": name,
                "project_region": region,
                "analytical_bloc_code": bloc,
                "analytical_bloc_name": D.BLOC_NAMES[bloc],
                "membership_basis": basis,
                "year": yr,
                # WEO
                "gdp_current_usd_billions": bn(gdp),
                "gdp_per_capita_current_usd": w.get("gdp_per_capita_current_usd"),
                "population_persons": pop_persons,
                "population_millions": pop_m,
                "real_gdp_growth_pct_imf": w.get("real_gdp_growth_pct_imf"),
                "inflation_cpi_pct": w.get("inflation_cpi_pct"),
                "gross_debt_pct_gdp_imf": w.get("gross_debt_pct_gdp_imf"),
                "government_revenue_pct_gdp_imf": w.get("government_revenue_pct_gdp_imf"),
                "government_expenditure_pct_gdp_imf": w.get("government_expenditure_pct_gdp_imf"),
                "net_lending_borrowing_pct_gdp_imf": w.get("net_lending_borrowing_pct_gdp_imf"),
                "current_account_balance_pct_gdp_imf": w.get("current_account_balance_pct_gdp_imf"),
                # IMTS: headline = IMF World (G001)
                "exports_billions_usd": bn(wx),
                "imports_billions_usd": bn(wm),
                "total_trade_billions_usd": bn(wt),
                "trade_balance_billions_usd": bn(sub(wx, wm)),
                "trade_openness_pct_gdp": pct(wt, gdp),
                "exports_pct_gdp": pct(wx, gdp),
                "imports_pct_gdp": pct(wm, gdp),
                # Named-partner universe (disjoint from World and aggregates)
                "named_partner_count": len(prow),
                "named_exports_billions_usd": bn(nx),
                "named_imports_billions_usd": bn(nm),
                "named_total_trade_billions_usd": bn(nt),
                "world_minus_named_total_trade_billions_usd": bn(sub(wt, nt)),
                "named_partner_coverage_pct": pct(nt, wt),
                "unallocated_total_trade_billions_usd": bn(ua[0] + ua[1]) if ua and ua[2] else None,
                "total_trade_partner_hhi": D.hhi(r["t"] for r in prow),
                "top_partner_iso3": top["code"] if top else None,
                "top_partner_name": top["name"] if top else None,
                "top_partner_share_of_world_pct": pct(top["t"], wt) if top else None,
                "top3_partner_share_of_world_pct": pct(top3, wt) if prow else None,
                # ACLED
                "acled_covered": covered,
                "total_events": ev,
                "violent_events": vev,
                "fatalities": fat,
                "events_per_million": D.per_million(ev, pop_m),
                "violent_events_per_million": D.per_million(vev, pop_m),
                "fatalities_per_million": D.per_million(fat, pop_m),
                # FSI: this year only (no carry-forward)
                "fsi_rank": fsi_rank.get((iso3, yr)),
                **frec,
            }
            country_rows.append(row)

            for rank_i, r in enumerate(prow[: D.TOP_N_PARTNERS], start=1):
                partner_out.append({
                    "country_iso3": iso3,
                    "analytical_bloc_code": bloc,
                    "year": yr,
                    "partner_rank": rank_i,
                    "counterpart_code": r["code"],
                    "counterpart_name": r["name"],
                    "counterpart_is_project_country": r["code"] in D.COUNTRIES,
                    "counterpart_historical_or_combined": r["historical"],
                    "exports_billions_usd": bn(r["x"]),
                    "imports_billions_usd": bn(r["m"]),
                    "total_trade_billions_usd": bn(r["t"]),
                    "share_of_world_total_pct": pct(r["t"], wt),
                    "share_of_named_total_pct": pct(r["t"], nt),
                })

    by_cy = {(r["country_iso3"], r["year"]): r for r in country_rows}

    # ---------------- Bloc-year aggregates (single definition) ----------------
    bloc_rows, bloc_partner_out = [], []
    for bloc in D.BLOC_NAMES:
        for yr in YEARS:
            members = D.bloc_members(bloc, yr)
            if not members:
                continue
            rows = [by_cy[(c, yr)] for c in members]

            def ssum(col, rs=rows):
                vals = [r[col] for r in rs if r[col] is not None]
                return (sum(vals) if vals else None), len(vals)

            gdp, n_gdp = ssum("gdp_current_usd_billions")
            popm, n_pop = ssum("population_millions")
            tx, n_tx = ssum("exports_billions_usd")
            tm, _ = ssum("imports_billions_usd")
            tt, n_tt = ssum("total_trade_billions_usd")
            both = [r for r in rows if r["total_trade_billions_usd"] is not None and r["gdp_current_usd_billions"]]
            open_num = sum(r["total_trade_billions_usd"] for r in both)
            open_den = sum(r["gdp_current_usd_billions"] for r in both)

            def gdp_weighted(col):
                rs = [r for r in rows if r[col] is not None and r["gdp_current_usd_billions"]]
                den = sum(r["gdp_current_usd_billions"] for r in rs)
                return (sum(r[col] * r["gdp_current_usd_billions"] for r in rs) / den if den else None), len(rs)

            debt, n_debt = gdp_weighted("gross_debt_pct_gdp_imf")
            growth, n_growth = gdp_weighted("real_gdp_growth_pct_imf")
            infl, n_infl = gdp_weighted("inflation_cpi_pct")
            fiscal, n_fiscal = gdp_weighted("net_lending_borrowing_pct_gdp_imf")
            ca, n_ca = gdp_weighted("current_account_balance_pct_gdp_imf")

            conf = [r for r in rows if r["fatalities"] is not None and r["population_millions"]]
            fat = sum(r["fatalities"] for r in conf) if conf else None
            vev = sum(r["violent_events"] for r in conf) if conf else None
            ev = sum(r["total_events"] for r in conf) if conf else None
            conf_pop = sum(r["population_millions"] for r in conf) if conf else None

            fsi = [r["fsi_total_score"] for r in rows if r["fsi_total_score"] is not None]

            # Bloc partner distribution: aggregate the FULL named universe of members.
            agg = collections.defaultdict(lambda: [0.0, 0.0, "", False])
            for c in members:
                for p in named_by_cy[(c, yr)]:
                    a = agg[p["code"]]
                    a[0] += p["x"] or 0.0
                    a[1] += p["m"] or 0.0
                    a[2] = p["name"]
                    a[3] = p["historical"]
            plist = sorted(
                ({"code": k, "name": v[2], "historical": v[3], "x": v[0], "m": v[1], "t": v[0] + v[1]} for k, v in agg.items()),
                key=lambda r: (-r["t"], r["code"]),
            )
            named_total = sum(p["t"] for p in plist) if plist else None
            tt_usd = None if tt is None else tt * 1e9
            for rank_i, p in enumerate(plist[: D.TOP_N_PARTNERS], start=1):
                bloc_partner_out.append({
                    "analytical_bloc_code": bloc,
                    "year": yr,
                    "partner_rank": rank_i,
                    "counterpart_code": p["code"],
                    "counterpart_name": p["name"],
                    "counterpart_is_project_country": p["code"] in D.COUNTRIES,
                    "counterpart_in_same_bloc": p["code"] in members,
                    "counterpart_historical_or_combined": p["historical"],
                    "exports_billions_usd": bn(p["x"]),
                    "imports_billions_usd": bn(p["m"]),
                    "total_trade_billions_usd": bn(p["t"]),
                    "share_of_world_total_pct": pct(p["t"], tt_usd) if n_tt == len(members) else None,
                    "share_of_named_total_pct": pct(p["t"], named_total),
                })
            top = plist[0] if plist else None
            complete_trade = n_tt == len(members)
            bloc_rows.append({
                "analytical_bloc_code": bloc,
                "analytical_bloc_name": D.BLOC_NAMES[bloc],
                "year": yr,
                "members": members,
                "member_count": len(members),
                "gdp_reporting": n_gdp,
                "trade_reporting": n_tt,
                "population_reporting": n_pop,
                "gdp_current_usd_billions": gdp,
                "population_millions": popm,
                "gdp_per_capita_current_usd": (gdp * 1e9 / (popm * 1e6)) if (gdp is not None and popm and n_gdp == n_pop) else None,
                "exports_billions_usd": tx,
                "imports_billions_usd": tm,
                "total_trade_billions_usd": tt,
                "trade_balance_billions_usd": sub(tx, tm),
                "trade_openness_pct_gdp": pct(open_num, open_den) if both else None,
                "openness_countries": len(both),
                "exports_pct_gdp": pct(sum(r["exports_billions_usd"] for r in both), open_den) if both else None,
                "imports_pct_gdp": pct(sum(r["imports_billions_usd"] for r in both), open_den) if both else None,
                "named_total_trade_billions_usd": bn(named_total),
                "named_partner_coverage_pct": pct(bn(named_total), tt) if complete_trade else None,
                "bloc_partner_hhi": D.hhi(p["t"] for p in plist),
                "top_partner_code": top["code"] if top else None,
                "top_partner_name": top["name"] if top else None,
                "top_partner_share_of_world_pct": pct(top["t"], tt_usd) if (top and complete_trade) else None,
                "top3_partner_share_of_world_pct": pct(sum(p["t"] for p in plist[:3]), tt_usd) if (plist and complete_trade) else None,
                "gross_debt_pct_gdp_weighted": debt, "gross_debt_reporting": n_debt,
                "real_gdp_growth_pct_weighted": growth, "growth_reporting": n_growth,
                "inflation_pct_weighted": infl, "inflation_reporting": n_infl,
                "net_lending_borrowing_pct_gdp_weighted": fiscal, "fiscal_reporting": n_fiscal,
                "current_account_pct_gdp_weighted": ca, "current_account_reporting": n_ca,
                "conflict_reporting": len(conf),
                "total_events": ev,
                "violent_events": vev,
                "fatalities": fat,
                "events_per_million": D.per_million(ev, conf_pop),
                "violent_events_per_million": D.per_million(vev, conf_pop),
                "fatalities_per_million": D.per_million(fat, conf_pop),
                "fsi_reporting": len(fsi),
                "fsi_total_score_mean": (sum(fsi) / len(fsi)) if fsi else None,
            })

    # ---------------- Hotspots: fixed window, one row per country x admin1 ----------------
    hot_rows = []
    for iso3 in sorted(D.COUNTRIES):
        items = [(a, h) for (c, a), h in acled_hot.items() if c == iso3]
        items.sort(key=lambda t: (-t[1]["violent_events"], -t[1]["fatalities"], t[0]))
        for rank_i, (admin1, h) in enumerate(items, start=1):
            hot_rows.append({
                "country_iso3": iso3,
                "country_name": D.COUNTRIES[iso3][0],
                "current_analytical_bloc_code": D.COUNTRIES[iso3][2],
                "admin1": admin1,
                "window_start_year": D.HOTSPOT_WINDOW[0],
                "window_end_year": D.HOTSPOT_WINDOW[1],
                "total_events": h["total_events"],
                "violent_events": h["violent_events"],
                "fatalities": h["fatalities"],
                "battle_events": h["type::Battles"],
                "violence_against_civilians_events": h["type::Violence against civilians"],
                "explosions_remote_violence_events": h["type::Explosions/Remote violence"],
                "riot_events": h["type::Riots"],
                "protest_events": h["type::Protests"],
                "hotspot_rank": rank_i,
            })

    # ---------------- Fragility: latest loaded edition, explicitly dated ----------------
    frag_rows = []
    for iso3 in sorted(D.COUNTRIES):
        years = sorted(y for (c, y) in fsi_vals if c == iso3)
        if not years:
            continue
        y = years[-1]
        frag_rows.append({
            "country_iso3": iso3,
            "country_name": D.COUNTRIES[iso3][0],
            "current_analytical_bloc_code": D.COUNTRIES[iso3][2],
            "fsi_year": y,
            "fsi_rank": fsi_rank.get((iso3, y)),
            **fsi_record(fsi_vals[(iso3, y)]),
        })

    # ---------------- Products: quarantined ----------------
    products = {
        "status": "quarantined",
        "rows": [],
        "reason": (
            "UN Comtrade HS2 values in the previous export were summed across customs-procedure, "
            "mode-of-transport and second-partner breakdown slices. Ghana 2023 HS2 exports summed to "
            "$67.5B against a same-provider UN Comtrade TOTAL of $16.8B (partner=World, partner2=World, "
            "customs=C00, mode=0). No trustworthy raw Comtrade snapshot is available, so no product "
            "values or shares are published until a matched re-extraction is validated."
        ),
        "revalidation": [
            "Re-extract with extraction/extract/comtrade_extract.py (pins partner2=0, customs=C00, mot=0).",
            "Load with scripts/load_comtrade_silver.py (rejects unpinned slices and duplicate keys).",
            "Reconcile each reporter-year HS2 sum to UN Comtrade TOTAL with identical dimensions; use IMF IMTS only as a cross-source warning.",
        ],
    }

    # ---------------- Source outliers (flagged, never altered) ----------------
    outliers = []
    for r in country_rows:
        if r["trade_openness_pct_gdp"] is not None and r["trade_openness_pct_gdp"] > 200:
            outliers.append({"country_iso3": r["country_iso3"], "year": r["year"], "flag": "trade_openness_above_200pct",
                             "value": r["trade_openness_pct_gdp"]})
    fsi_inconsistent = []
    for (iso3, yr), v in sorted(fsi_vals.items()):
        parts = [v.get(c) for c in D.FSI_COLUMNS if c != "TOTAL"]
        if v.get("TOTAL") is not None and None not in parts and abs(sum(parts) - v["TOTAL"]) > 0.15:
            fsi_inconsistent.append({"country_iso3": iso3, "year": yr, "published_total": v["TOTAL"],
                                     "indicator_sum": round(sum(parts), 4)})
    low_cov = [
        {"country_iso3": r["country_iso3"], "year": r["year"], "named_partner_coverage_pct": r["named_partner_coverage_pct"]}
        for r in country_rows
        if r["named_partner_coverage_pct"] is not None and abs(r["named_partner_coverage_pct"] - 100) > 2
    ]

    provenance = {
        "schema_version": 2,
        "builder": "scripts/offline_rebuild.py",
        "raw_inputs": {k: {"file": RAW_FILES[k], "sha256": sha256(p), "bytes": p.stat().st_size} for k, p in paths.items()},
        "years": [D.START_YEAR, D.END_YEAR],
        "membership_rule": D.MEMBERSHIP_RULE,
        "imts": {
            **imts_meta,
            "codelist": "IMF.STA:CL_IMTS_COUNTRY 1.0.0 (config/imf_cl_imts_country_1.0.0.tsv), roles in config/imts_counterpart_roles.csv",
            "headline_rule": "Exports, imports and total trade are the IMF World (G001) rows. Partner rows are named economies only; aggregates are excluded; 'not specified' areas are counted as unallocated.",
            "share_rule": "Partner shares are partner trade divided by World total trade. HHI is computed on the full named-partner distribution before any top-N cut, so it is conditional on named-partner coverage.",
            "world_minus_named_note": "World minus named-partner sum can be positive or negative; it is reported as a difference, not as unallocated trade.",
            "country_years_named_coverage_off_by_more_than_2pct": len(low_cov),
        },
        "weo": weo_meta,
        "acled": {**acled_meta, "hotspot_window": list(D.HOTSPOT_WINDOW),
                  "hotspot_rule": "One row per country x admin1 over the fixed window; ranked by violent events, then fatalities, then name. No admin1 per-capita rates (no admin1 population source)."},
        "fsi": fsi_meta,
        "products": {"status": "quarantined", "reason": products["reason"]},
        "source_outliers": outliers,
        "fsi_source_inconsistencies": fsi_inconsistent,
    }

    outputs = {
        "country_timeseries.json": country_rows,
        "top_trade_partners.json": partner_out,
        "bloc_comparison.json": bloc_rows,
        "bloc_trade_partners.json": bloc_partner_out,
        "conflict_hotspots.json": hot_rows,
        "fragility_components.json": frag_rows,
        "product_trade_hs2.json": products,
        "provenance.json": provenance,
        "trade_named_coverage.json": low_cov,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in outputs.items():
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return {name: (len(obj) if isinstance(obj, list) else "object") for name, obj in outputs.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=D.ROOT / "static" / "data")
    args = ap.parse_args()
    try:
        summary = build(args.raw_dir, args.out)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
