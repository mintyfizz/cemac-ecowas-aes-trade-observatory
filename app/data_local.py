"""
Local JSONL data layer – computes dashboard metrics directly from raw extracts
when Databricks gold tables are not yet available.

All public functions are decorated with @st.cache_data so they only run once
per Streamlit session.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

CEMAC: frozenset[str] = frozenset(["CMR", "CAF", "TCD", "COG", "GNQ", "GAB"])
ECOWAS_FULL: frozenset[str] = frozenset([
    "BEN", "BFA", "CPV", "CIV", "GMB", "GHA", "GIN", "GNB",
    "LBR", "MLI", "NER", "NGA", "SEN", "SLE", "TGO",
])
AES: frozenset[str] = frozenset(["MLI", "BFA", "NER"])  # from 2025 onwards
ALL_COUNTRIES: frozenset[str] = CEMAC | ECOWAS_FULL

COUNTRY_NAMES: dict[str, str] = {
    "CMR": "Cameroon",
    "CAF": "Central African Republic",
    "TCD": "Chad",
    "COG": "Congo",
    "GNQ": "Equatorial Guinea",
    "GAB": "Gabon",
    "BEN": "Benin",
    "BFA": "Burkina Faso",
    "CPV": "Cabo Verde",
    "CIV": "Côte d'Ivoire",
    "GMB": "Gambia",
    "GHA": "Ghana",
    "GIN": "Guinea",
    "GNB": "Guinea-Bissau",
    "LBR": "Liberia",
    "MLI": "Mali",
    "NER": "Niger",
    "NGA": "Nigeria",
    "SEN": "Senegal",
    "SLE": "Sierra Leone",
    "TGO": "Togo",
}

BLOC_MEMBERS: dict[str, list[str]] = {
    "CEMAC": [iso for iso in COUNTRY_NAMES if iso in CEMAC],
    "ECOWAS": [iso for iso in COUNTRY_NAMES if iso in ECOWAS_FULL],
    "AES": list(AES),
}

WEO_INDICATORS: dict[str, str] = {
    "NGDPD": "gdp_current_usd_billions",
    "NGDP_RPCH": "gdp_growth_pct",
    "PCPIPCH": "inflation_cpi_pct",
    "GGXWDG_NGDP": "gross_debt_pct_gdp",
    "BCA_NGDPD": "current_account_pct_gdp",
    "GGXCNL_NGDP": "net_lending_borrowing_pct_gdp",
    "GGR_NGDP": "gov_revenue_pct_gdp",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bloc(iso3: str, year: int | None = None) -> str:
    if iso3 in CEMAC:
        return "CEMAC"
    if iso3 in AES and (year or 0) >= 2025:
        return "AES"
    return "ECOWAS"


def _load_flat(path: Path) -> list[dict[str, Any]]:
    """Load a flat JSONL file (one JSON object per line)."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _load_enveloped(path: Path) -> list[dict[str, Any]]:
    """Load an enveloped JSONL (one envelope per reporter, payload=list of obs)."""
    if not path.exists():
        return []
    obs: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                env = json.loads(line)
                for item in env.get("payload", []):
                    obs.append(item)
            except json.JSONDecodeError:
                pass
    return obs


def _load_acled(path: Path) -> list[dict[str, Any]]:
    """Load ACLED enveloped JSONL; inject reporter_iso3 into each payload row."""
    if not path.exists():
        return []
    obs: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                env = json.loads(line)
                iso3 = env.get("reporter_iso3", "")
                for item in env.get("payload", []):
                    item["country_iso3"] = iso3
                    obs.append(item)
            except json.JSONDecodeError:
                pass
    return obs


# ---------------------------------------------------------------------------
# Raw loaders (cached)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _imts_raw() -> pd.DataFrame:
    obs = _load_enveloped(RAW / "imts" / "cemac_ecowas_imts_1990_2024.jsonl")
    df = pd.DataFrame(obs)
    if df.empty:
        return df
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value_usd"] = pd.to_numeric(df["value_usd"], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def _weo_raw() -> pd.DataFrame:
    rows = _load_flat(RAW / "weo" / "cemac_ecowas_weo_1990_2024.jsonl")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def _fsi_raw() -> pd.DataFrame:
    rows = _load_flat(RAW / "fsi" / "cemac_ecowas_fsi_1990_2024.jsonl")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def _acled_raw() -> pd.DataFrame:
    obs = _load_acled(RAW / "acled" / "cemac_ecowas_acled_1990_2024.jsonl")
    df = pd.DataFrame(obs)
    if df.empty:
        return df
    df["year"] = pd.to_numeric(df.get("year", pd.Series(dtype=float)), errors="coerce").astype("Int64")
    df["fatalities"] = pd.to_numeric(df.get("fatalities", pd.Series(dtype=float)), errors="coerce").fillna(0)
    return df


# ---------------------------------------------------------------------------
# Computed tables (cached)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def trade_annual() -> pd.DataFrame:
    """
    Per-country per-year trade aggregates plus HHI and top-partner metrics.

    Columns:
        country_iso3, year, exports_usd, imports_usd, total_usd,
        exports_billions_usd, imports_billions_usd, total_trade_billions_usd,
        total_trade_partner_hhi, top_partner_iso3, top_partner_share_pct,
        country_name, analytical_bloc_code
    """
    df = _imts_raw()
    if df.empty:
        return pd.DataFrame()

    # Volumes
    exp = df[df["indicator"] == "XG_FOB_USD"].groupby(
        ["reporter_iso3", "year"], as_index=False
    )["value_usd"].sum().rename(columns={"value_usd": "exports_usd"})
    imp = df[df["indicator"] == "MG_CIF_USD"].groupby(
        ["reporter_iso3", "year"], as_index=False
    )["value_usd"].sum().rename(columns={"value_usd": "imports_usd"})
    base = exp.merge(imp, on=["reporter_iso3", "year"], how="outer").fillna(0)
    base["total_usd"] = base["exports_usd"] + base["imports_usd"]

    # Partner-level aggregation for HHI + top partner
    by_partner = df.groupby(
        ["reporter_iso3", "year", "counterpart_iso3"], as_index=False
    )["value_usd"].sum()

    grand = (
        by_partner.groupby(["reporter_iso3", "year"], as_index=False)["value_usd"]
        .sum()
        .rename(columns={"value_usd": "grand_total"})
    )
    by_partner = by_partner.merge(grand, on=["reporter_iso3", "year"])
    by_partner["sq_share"] = (
        by_partner["value_usd"] / by_partner["grand_total"].clip(lower=1)
    ) ** 2

    hhi = (
        by_partner.groupby(["reporter_iso3", "year"], as_index=False)["sq_share"]
        .sum()
        .rename(columns={"sq_share": "total_trade_partner_hhi"})
    )

    top = (
        by_partner.sort_values("value_usd", ascending=False)
        .groupby(["reporter_iso3", "year"], as_index=False)
        .first()[["reporter_iso3", "year", "counterpart_iso3", "value_usd", "grand_total"]]
        .rename(columns={"counterpart_iso3": "top_partner_iso3"})
    )
    top["top_partner_share_pct"] = (
        top["value_usd"] / top["grand_total"].clip(lower=1)
    ) * 100

    result = (
        base.merge(hhi, on=["reporter_iso3", "year"], how="left")
        .merge(
            top[["reporter_iso3", "year", "top_partner_iso3", "top_partner_share_pct"]],
            on=["reporter_iso3", "year"],
            how="left",
        )
    )
    result["exports_billions_usd"] = result["exports_usd"] / 1e9
    result["imports_billions_usd"] = result["imports_usd"] / 1e9
    result["total_trade_billions_usd"] = result["total_usd"] / 1e9
    result = result.rename(columns={"reporter_iso3": "country_iso3"})
    result["country_name"] = result["country_iso3"].map(COUNTRY_NAMES)
    result["analytical_bloc_code"] = [
        _bloc(iso, int(yr)) for iso, yr in zip(result["country_iso3"], result["year"])
    ]
    return result


@st.cache_data(show_spinner=False)
def top_partners(n: int = 10) -> pd.DataFrame:
    """
    Top N bilateral trade partners per country-year.

    Columns:
        country_iso3, year, counterpart_iso3, exports_billions_usd,
        imports_billions_usd, total_trade_billions_usd,
        total_trade_partner_share_pct, partner_rank,
        country_name, analytical_bloc_code
    """
    df = _imts_raw()
    if df.empty:
        return pd.DataFrame()

    by_partner = df.groupby(
        ["reporter_iso3", "year", "counterpart_iso3", "indicator"], as_index=False
    )["value_usd"].sum()

    pivot = by_partner.pivot_table(
        index=["reporter_iso3", "year", "counterpart_iso3"],
        columns="indicator",
        values="value_usd",
        aggfunc="first",
    ).reset_index().fillna(0)
    pivot.columns.name = None

    for col, rename in [("XG_FOB_USD", "exports_usd"), ("MG_CIF_USD", "imports_usd")]:
        pivot[rename] = pivot.get(col, pd.Series(0, index=pivot.index))

    pivot["total_usd"] = pivot["exports_usd"] + pivot["imports_usd"]

    year_total = (
        pivot.groupby(["reporter_iso3", "year"], as_index=False)["total_usd"]
        .sum()
        .rename(columns={"total_usd": "year_total"})
    )
    pivot = pivot.merge(year_total, on=["reporter_iso3", "year"])
    pivot["total_trade_partner_share_pct"] = (
        pivot["total_usd"] / pivot["year_total"].clip(lower=1)
    ) * 100

    pivot = pivot.sort_values(
        ["reporter_iso3", "year", "total_usd"], ascending=[True, True, False]
    )
    pivot["partner_rank"] = pivot.groupby(["reporter_iso3", "year"]).cumcount() + 1
    top = pivot[pivot["partner_rank"] <= n].copy()

    top["exports_billions_usd"] = top["exports_usd"] / 1e9
    top["imports_billions_usd"] = top["imports_usd"] / 1e9
    top["total_trade_billions_usd"] = top["total_usd"] / 1e9
    top = top.rename(columns={"reporter_iso3": "country_iso3"})
    top["country_name"] = top["country_iso3"].map(COUNTRY_NAMES)
    # counterpart_name: use COUNTRY_NAMES mapping, fall back to ISO3 code
    top["counterpart_name"] = top["counterpart_iso3"].map(COUNTRY_NAMES).fillna(top["counterpart_iso3"])
    top["analytical_bloc_code"] = [
        _bloc(iso, int(yr)) for iso, yr in zip(top["country_iso3"], top["year"])
    ]
    return top


@st.cache_data(show_spinner=False)
def weo_annual() -> pd.DataFrame:
    """
    WEO indicators pivoted wide per country-year.

    Columns: country_iso3, year, gdp_current_usd_billions, gdp_growth_pct,
             inflation_cpi_pct, gross_debt_pct_gdp, current_account_pct_gdp,
             net_lending_borrowing_pct_gdp, gov_revenue_pct_gdp,
             country_name, analytical_bloc_code
    """
    df = _weo_raw()
    if df.empty:
        return pd.DataFrame()

    relevant = df[df["indicator_code"].isin(WEO_INDICATORS)].copy()
    relevant["col"] = relevant["indicator_code"].map(WEO_INDICATORS)

    pivot = (
        relevant.pivot_table(
            index=["country_iso3", "year"],
            columns="col",
            values="value",
            aggfunc="first",
        )
        .reset_index()
    )
    pivot.columns.name = None
    pivot["country_name"] = pivot["country_iso3"].map(COUNTRY_NAMES)
    pivot["analytical_bloc_code"] = [
        _bloc(iso, int(yr)) for iso, yr in zip(pivot["country_iso3"], pivot["year"])
    ]
    return pivot


@st.cache_data(show_spinner=False)
def fsi_annual() -> pd.DataFrame:
    """
    FSI scores per country-year (total + component averages).

    Columns: country_iso3, year, fsi_total_score, rank,
             cohesion_score, economic_score, political_score,
             social_cross_cutting_score, country_name, analytical_bloc_code
    """
    df = _fsi_raw()
    if df.empty:
        return pd.DataFrame()

    rank_col = [c for c in df.columns if c == "rank"]
    total = df[df["indicator_code"] == "TOTAL"][
        ["country_iso3", "year", "value"] + rank_col
    ].rename(columns={"value": "fsi_total_score"})

    for prefix, col in [("C", "cohesion_score"), ("E", "economic_score"),
                         ("P", "political_score"), ("S", "social_cross_cutting_score")]:
        sub = (
            df[df["indicator_code"].str.startswith(prefix)]
            .groupby(["country_iso3", "year"], as_index=False)["value"]
            .mean()
            .rename(columns={"value": col})
        )
        total = total.merge(sub, on=["country_iso3", "year"], how="left")

    total["country_name"] = total["country_iso3"].map(COUNTRY_NAMES)
    total["analytical_bloc_code"] = [
        _bloc(iso, int(yr)) for iso, yr in zip(total["country_iso3"], total["year"])
    ]
    return total


@st.cache_data(show_spinner=False)
def acled_annual() -> pd.DataFrame:
    """
    ACLED events and fatalities per country-year.

    Columns: country_iso3, year, violent_events, fatalities,
             country_name, analytical_bloc_code
    """
    df = _acled_raw()
    if df.empty:
        return pd.DataFrame()

    agg = df.groupby(["country_iso3", "year"], as_index=False).agg(
        violent_events=("fatalities", "count"),
        fatalities=("fatalities", "sum"),
    )
    agg["country_name"] = agg["country_iso3"].map(COUNTRY_NAMES)
    agg["analytical_bloc_code"] = [
        _bloc(iso, int(yr)) for iso, yr in zip(agg["country_iso3"], agg["year"])
    ]
    return agg


@st.cache_data(show_spinner=False)
def country_timeseries() -> pd.DataFrame:
    """
    Merged per-country per-year DataFrame combining trade, WEO, FSI, ACLED.
    Also computes trade_openness_pct_gdp.
    """
    trade = trade_annual()
    weo = weo_annual()
    fsi = fsi_annual()[
        ["country_iso3", "year", "fsi_total_score",
         "cohesion_score", "economic_score", "political_score", "social_cross_cutting_score"]
    ]
    acled = acled_annual()[["country_iso3", "year", "violent_events", "fatalities"]]

    if trade.empty and weo.empty:
        return pd.DataFrame()

    if trade.empty:
        base = weo.copy()
    elif weo.empty:
        base = trade.copy()
    else:
        drop = [c for c in ["country_name", "analytical_bloc_code"] if c in weo.columns]
        base = trade.merge(
            weo.drop(columns=drop, errors="ignore"),
            on=["country_iso3", "year"],
            how="outer",
        )
        base["country_name"] = base["country_iso3"].map(COUNTRY_NAMES)
        base["analytical_bloc_code"] = [
            _bloc(iso, int(yr)) for iso, yr in zip(base["country_iso3"], base["year"])
        ]

    for extra in [fsi, acled]:
        if not extra.empty:
            base = base.merge(extra, on=["country_iso3", "year"], how="left")

    if "total_trade_billions_usd" in base.columns and "gdp_current_usd_billions" in base.columns:
        gdp = pd.to_numeric(base["gdp_current_usd_billions"], errors="coerce")
        gdp = gdp.where(gdp > 0)
        base["trade_openness_pct_gdp"] = (
            base["total_trade_billions_usd"] / gdp
        ) * 100

    return base


@st.cache_data(show_spinner=False)
def country_latest() -> pd.DataFrame:
    """Latest available year per country (cross all sources)."""
    ts = country_timeseries()
    if ts.empty:
        return pd.DataFrame()
    # Keep the last year per country that has trade data
    ts_trade = ts.dropna(subset=["total_trade_billions_usd"])
    latest_year = (
        ts_trade.groupby("country_iso3")["year"].max().reset_index()
        .rename(columns={"year": "latest_year"})
    )
    return ts_trade.merge(latest_year, on="country_iso3").query("year == latest_year").drop(columns="latest_year")


@st.cache_data(show_spinner=False)
def intra_bloc_share() -> pd.DataFrame:
    """
    Intra-bloc trade share (%) per bloc per year.

    Columns: analytical_bloc_code, year, intra_usd, total_usd, intra_share_pct
    """
    df = _imts_raw()
    if df.empty:
        return pd.DataFrame()

    by_partner = df.groupby(
        ["reporter_iso3", "year", "counterpart_iso3"], as_index=False
    )["value_usd"].sum()

    by_partner["reporter_bloc"] = [
        _bloc(iso, int(yr)) for iso, yr in zip(by_partner["reporter_iso3"], by_partner["year"])
    ]
    by_partner["counterpart_bloc"] = [
        _bloc(iso, int(yr)) if iso in ALL_COUNTRIES else "ROW"
        for iso, yr in zip(by_partner["counterpart_iso3"], by_partner["year"])
    ]
    by_partner["is_intra"] = by_partner["reporter_bloc"] == by_partner["counterpart_bloc"]

    intra = (
        by_partner[by_partner["is_intra"]]
        .groupby(["reporter_iso3", "year", "reporter_bloc"], as_index=False)["value_usd"]
        .sum()
        .rename(columns={"value_usd": "intra_usd"})
    )
    total = (
        by_partner.groupby(["reporter_iso3", "year", "reporter_bloc"], as_index=False)["value_usd"]
        .sum()
        .rename(columns={"value_usd": "total_usd"})
    )
    country_level = intra.merge(total, on=["reporter_iso3", "year", "reporter_bloc"], how="outer").fillna(0)

    bloc_level = (
        country_level.groupby(["reporter_bloc", "year"], as_index=False)
        .agg(intra_usd=("intra_usd", "sum"), total_usd=("total_usd", "sum"))
    )
    bloc_level["intra_share_pct"] = (
        bloc_level["intra_usd"] / bloc_level["total_usd"].clip(lower=1)
    ) * 100
    bloc_level = bloc_level.rename(columns={"reporter_bloc": "analytical_bloc_code"})
    return bloc_level


@st.cache_data(show_spinner=False)
def partner_share_history(
    selected_country: str | None,
    bloc: str,
) -> pd.DataFrame:
    """
    For each year, return the share of total trade that each counterpart represents,
    averaged across all reporters in the selected country or bloc.

    Columns: year, counterpart_iso3, share_pct
    """
    df = _imts_raw()
    if df.empty:
        return pd.DataFrame()

    if selected_country:
        reporters = [selected_country]
    else:
        reporters = [iso for iso in COUNTRY_NAMES if _bloc(iso, 2024) == bloc]

    sub = df[df["reporter_iso3"].isin(reporters)].copy()

    by_partner = sub.groupby(["year", "counterpart_iso3"], as_index=False)["value_usd"].sum()
    year_total = (
        sub.groupby("year", as_index=False)["value_usd"]
        .sum()
        .rename(columns={"value_usd": "total"})
    )
    by_partner = by_partner.merge(year_total, on="year")
    by_partner["share_pct"] = (
        by_partner["value_usd"] / by_partner["total"].clip(lower=1)
    ) * 100
    return by_partner[["year", "counterpart_iso3", "share_pct"]]


@st.cache_data(show_spinner=False)
def hhi_trend() -> pd.DataFrame:
    """HHI aggregated at bloc level per year (mean across member countries)."""
    ts = country_timeseries()
    if ts.empty or "total_trade_partner_hhi" not in ts.columns:
        return pd.DataFrame()
    return (
        ts.groupby(["analytical_bloc_code", "year"], as_index=False)["total_trade_partner_hhi"]
        .mean()
    )


@st.cache_data(show_spinner=False)
def indexed_trade_growth() -> pd.DataFrame:
    """
    Trade volume indexed to 1990=100 per country, for the 'growth chart'.
    Columns: country_iso3, country_name, year, index_value
    """
    ts = country_timeseries()
    if ts.empty or "total_trade_billions_usd" not in ts.columns:
        return pd.DataFrame()

    ts = ts.dropna(subset=["total_trade_billions_usd"])
    base = (
        ts[ts["year"] == 1990][["country_iso3", "total_trade_billions_usd"]]
        .rename(columns={"total_trade_billions_usd": "base_val"})
    )
    merged = ts.merge(base, on="country_iso3", how="inner")
    merged["index_value"] = (merged["total_trade_billions_usd"] / merged["base_val"].clip(lower=1e-9)) * 100
    return merged[["country_iso3", "country_name", "analytical_bloc_code", "year", "index_value"]]
