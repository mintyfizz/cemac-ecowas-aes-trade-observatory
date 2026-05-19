"""CEMAC-ECOWAS-AES Trade Observatory – Streamlit dashboard.

Layout matches the HTML prototype. Data loaded from local JSONL files.
Comtrade-dependent features (product treemap, mirror gap) are removed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import data_local as dl
from charts import (
    COLORS,
    conflict_hotspot_bars,
    empty_figure,
    fragility_components,
    grouped_bar,
    metric_map,
    multi_bloc_line,
    partner_share_comparison,
    top_partner_bars,
    trade_growth_index,
)

st.set_page_config(
    page_title="CEMAC-ECOWAS-AES Trade Observatory",
    page_icon="\U0001f30d",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BLOCS = ["CEMAC", "ECOWAS", "AES"]
BLOC_SIZES = {"CEMAC": 6, "ECOWAS": 15, "AES": 3}
MAP_METRICS = {
    "Trade openness (% GDP)": "trade_openness_pct_gdp",
    "Total trade (USD B)": "total_trade_billions_usd",
    "Partner HHI": "total_trade_partner_hhi",
    "GDP (USD B)": "gdp_current_usd_billions",
    "Fragility (FSI)": "fsi_total_score",
    "Conflict fatalities": "fatalities",
}
YEARS = list(range(2024, 1989, -1))


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def inject_css() -> None:
    st.markdown(
        """
<style>
:root {
  --bg:#0b0c0a; --surface:#1c1d1a; --surface-2:#232420; --surface-3:#2a2b27;
  --border:#3a3b36; --text:#f4f1e8; --muted:#9a9590;
  --success:#1d9e75; --danger:#ef7668; --warning:#f7d25d;
  --cemac:#0f6e56; --ecowas:#185fa5; --aes:#ba7517;
}
.stApp { background:var(--bg); color:var(--text);
  font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
[data-testid="stHeader"] { background:rgba(0,0,0,0); }
[data-testid="stToolbar"] { visibility:hidden; }
.block-container { max-width:1440px; padding-top:1rem; padding-bottom:2rem; }
.dash-title { font-size:1.3rem; font-weight:700; letter-spacing:-.01em;
  color:var(--text); margin-bottom:2px; }
.dash-subtitle { font-size:.78rem; color:var(--muted); margin-bottom:8px; }
.section-divider { height:1px; background:var(--border); margin:26px 0 16px; }
.section-label { color:var(--muted); font-size:10px; letter-spacing:.1em;
  text-transform:uppercase; font-weight:700; margin-bottom:12px; }
.crumb-bar { background:#141510; border:1px solid #2c2d28; border-radius:8px;
  padding:9px 14px; color:#b8b4a8; font-size:.82rem; margin:8px 0 18px; }
.crumb-sep { color:#4a4b46; margin:0 4px; }
.crumb-val { color:var(--text); font-weight:600; }
.kpi-tile { background:var(--surface-2); border:1px solid var(--border);
  border-radius:10px; padding:14px 16px 12px; }
.kpi-label { color:var(--muted); font-size:.6rem; text-transform:uppercase;
  letter-spacing:.08em; margin-bottom:6px; font-weight:700; }
.kpi-value { color:var(--text); font-size:1.35rem; font-weight:700; line-height:1.15; }
.kpi-note { color:var(--muted); font-size:.67rem; margin-top:4px; }
.econ-section-label { color:var(--muted); font-size:9px; text-transform:uppercase;
  letter-spacing:.1em; font-weight:700; margin:16px 0 8px; }
.econ-card { background:var(--surface-3); border:1px solid var(--border);
  border-radius:8px; padding:10px 12px; }
.econ-label { color:var(--muted); font-size:.57rem; text-transform:uppercase;
  letter-spacing:.07em; margin-bottom:4px; font-weight:700; }
.econ-value { color:var(--text); font-size:1.05rem; font-weight:700; line-height:1.2; }
.econ-unit { color:var(--muted); font-size:.63rem; margin-top:2px; }
</style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt(val, decimals=1, suffix=""):
    if val is None:
        return "\u2014"
    try:
        f = float(val)
        if f != f:  # nan check
            return "\u2014"
        return f"{f:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "\u2014"


def fmt_bn(val):    return _fmt(val, 1, "\xa0B")
def fmt_pct(val):   return _fmt(val, 1, "%")
def fmt_num(val, d=3): return _fmt(val, d)


def kpi_tile(label, value, note=""):
    note_html = f'<div class="kpi-note">{note}</div>' if note else ""
    return (
        f'<div class="kpi-tile">' +
        f'<div class="kpi-label">{label}</div>' +
        f'<div class="kpi-value">{value}</div>' +
        note_html +
        '</div>'
    )


def econ_card(label, value, unit=""):
    unit_html = f'<div class="econ-unit">{unit}</div>' if unit else ""
    return (
        f'<div class="econ-card">' +
        f'<div class="econ-label">{label}</div>' +
        f'<div class="econ-value">{value}</div>' +
        unit_html +
        '</div>'
    )


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def _members(bloc):
    return dl.BLOC_MEMBERS.get(bloc, [])


def _scope_ts(ts, bloc, country):
    if country:
        return ts[ts["country_iso3"] == country]
    return ts[ts["analytical_bloc_code"] == bloc]


def _latest_row(ts, bloc, country):
    scoped = _scope_ts(ts, bloc, country)
    if scoped.empty:
        return None
    sub = scoped.dropna(subset=["total_trade_billions_usd"])
    if sub.empty:
        return None
    if country:
        return sub.sort_values("year").iloc[-1]
    last_yr = sub["year"].max()
    yr = sub[sub["year"] == last_yr]
    row = {"year": last_yr, "analytical_bloc_code": bloc}
    for col in ["exports_billions_usd", "imports_billions_usd", "total_trade_billions_usd"]:
        row[col] = yr[col].sum() if col in yr.columns else None
    for col in ["total_trade_partner_hhi", "fsi_total_score", "gdp_current_usd_billions",
                "gdp_growth_pct", "inflation_cpi_pct", "gross_debt_pct_gdp",
                "current_account_pct_gdp", "gov_revenue_pct_gdp",
                "trade_openness_pct_gdp", "top_partner_share_pct"]:
        if col in yr.columns:
            row[col] = pd.to_numeric(yr[col], errors="coerce").mean()
    return pd.Series(row)


def _top_partners_for_scope(partners_df, bloc, year, country):
    if partners_df.empty:
        return pd.DataFrame()
    if country:
        return partners_df[
            (partners_df["country_iso3"] == country) & (partners_df["year"] == year)
        ]
    df = partners_df[
        (partners_df["analytical_bloc_code"] == bloc) & (partners_df["year"] == year)
    ]
    if df.empty:
        return df
    df = (
        df.groupby("counterpart_iso3", as_index=False)
        .agg(
            exports_billions_usd=("exports_billions_usd", "sum"),
            imports_billions_usd=("imports_billions_usd", "sum"),
            total_trade_billions_usd=("total_trade_billions_usd", "sum"),
            total_trade_partner_share_pct=("total_trade_partner_share_pct", "mean"),
        )
        .sort_values("total_trade_billions_usd", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )
    df["counterpart_name"] = df["counterpart_iso3"].map(dl.COUNTRY_NAMES).fillna(df["counterpart_iso3"])
    df["partner_rank"] = range(1, len(df) + 1)
    return df


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_overview(ts, weo, fsi, map_df, bloc, year, country, map_metric):
    row = _latest_row(ts, bloc, country)

    left, right = st.columns([5, 7])

    with left:
        st.markdown('<div class="section-label">Key indicators</div>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        yr_str = str(int(row["year"])) if row is not None and row.get("year") is not None else "—"
        with c1:
            v = fmt_bn(row.get("total_trade_billions_usd") if row is not None else None)
            st.markdown(kpi_tile("Total trade", v, f"USD, {yr_str}"), unsafe_allow_html=True)
        with c2:
            v = fmt_pct(row.get("top_partner_share_pct") if row is not None else None)
            st.markdown(kpi_tile("Top partner share", v, "% of total trade"), unsafe_allow_html=True)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        c3, c4 = st.columns(2)
        with c3:
            v = fmt_num(row.get("total_trade_partner_hhi") if row is not None else None)
            st.markdown(kpi_tile("Concentration (HHI)", v, "0\u2009=\u2009dispersed · 1\u2009=\u2009monopoly"), unsafe_allow_html=True)
        with c4:
            v = fmt_num(row.get("fsi_total_score") if row is not None else None, 1)
            st.markdown(kpi_tile("Fragility (FSI)", v, "Fund for Peace index"), unsafe_allow_html=True)

        # Econ cards (WEO)
        st.markdown('<div class="econ-section-label">Economic context (IMF WEO)</div>', unsafe_allow_html=True)

        if country:
            weo_sub = weo[weo["country_iso3"] == country]
        else:
            weo_sub = weo[weo["country_iso3"].isin(_members(bloc))]

        if not weo_sub.empty:
            lw = weo_sub[weo_sub["year"] == weo_sub["year"].max()]
            def _w(col): return pd.to_numeric(lw.get(col, pd.Series()), errors="coerce")
            _gdp    = fmt_bn(_w("gdp_current_usd_billions").sum() if not country else _w("gdp_current_usd_billions").mean())
            _growth = fmt_pct(_w("gdp_growth_pct").mean())
            _infl   = fmt_pct(_w("inflation_cpi_pct").mean())
            _debt   = fmt_pct(_w("gross_debt_pct_gdp").mean())
            _ca     = fmt_pct(_w("current_account_pct_gdp").mean())
            _rev    = fmt_pct(_w("gov_revenue_pct_gdp").mean())
        else:
            _gdp = _growth = _infl = _debt = _ca = _rev = "\u2014"

        e1, e2 = st.columns(2)
        with e1:
            st.markdown(econ_card("GDP", _gdp, "current USD B"), unsafe_allow_html=True)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(econ_card("Inflation", _infl, "CPI % change"), unsafe_allow_html=True)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(econ_card("Current account", _ca, "% of GDP"), unsafe_allow_html=True)
        with e2:
            st.markdown(econ_card("GDP growth", _growth, "real % change"), unsafe_allow_html=True)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(econ_card("Gross debt", _debt, "% of GDP"), unsafe_allow_html=True)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(econ_card("Gov. revenue", _rev, "% of GDP"), unsafe_allow_html=True)

    with right:
        st.markdown('<div class="section-label">Map · ' + map_metric + '</div>', unsafe_allow_html=True)
        col_name = MAP_METRICS.get(map_metric, "total_trade_billions_usd")
        if not map_df.empty:
            st.plotly_chart(metric_map(map_df, col_name, map_metric), use_container_width=True)
        else:
            st.info("Map data not available.")


def render_trading_partners(partners_df, ts, bloc, year, country):
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Trading partners</div>', unsafe_allow_html=True)

    scoped = _top_partners_for_scope(partners_df, bloc, year, country)

    bar_col, trend_col = st.columns(2)

    with bar_col:
        st.plotly_chart(top_partner_bars(scoped), use_container_width=True)

    with trend_col:
        opts = []
        if not scoped.empty and "counterpart_iso3" in scoped.columns:
            opts = (
                scoped.sort_values("total_trade_billions_usd", ascending=False)
                ["counterpart_iso3"].dropna().unique().tolist()
            )
        if len(opts) >= 2:
            pc1, pc2 = st.columns(2)
            with pc1:
                p1 = st.selectbox("Partner 1", opts, index=0, key="p1")
            with pc2:
                p2 = st.selectbox("Partner 2", opts, index=min(1, len(opts)-1), key="p2")
            history = dl.partner_share_history(country, bloc)
            st.plotly_chart(partner_share_comparison(history, p1, p2), use_container_width=True)
        else:
            st.plotly_chart(empty_figure("No partner data for selected scope / year."), use_container_width=True)


def render_concentration(ts, intra, hhi_df, bloc, country):
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Concentration and regional integration</div>', unsafe_allow_html=True)

    hhi_col, intra_col = st.columns(2)

    with hhi_col:
        if country:
            c_hhi = ts[ts["country_iso3"] == country][["year", "total_trade_partner_hhi"]].copy()
            c_hhi["analytical_bloc_code"] = bloc
            fig = multi_bloc_line(c_hhi, "year", "total_trade_partner_hhi",
                                  "Partner concentration (HHI)", "HHI", highlight_bloc=bloc)
        else:
            fig = multi_bloc_line(hhi_df, "year", "total_trade_partner_hhi",
                                  "Partner concentration (HHI)", "HHI", highlight_bloc=bloc)
        st.plotly_chart(fig, use_container_width=True)

    with intra_col:
        fig = multi_bloc_line(intra, "year", "intra_share_pct",
                              "Intra-bloc trade share", "% of total trade", highlight_bloc=bloc)
        st.plotly_chart(fig, use_container_width=True)


def render_growth(ts, growth_df, bloc, country):
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Growth and trade structure</div>', unsafe_allow_html=True)

    highlight = [country] if country else _members(bloc)
    st.plotly_chart(trade_growth_index(growth_df, highlight_countries=highlight), use_container_width=True)

    st.markdown(
        '<p style="color:#55564f;font-size:.73rem;margin-top:-8px;">' +
        "Product composition chart not available — Comtrade data pending." +
        "</p>",
        unsafe_allow_html=True,
    )


def render_operational_context(fsi, acled, ts, bloc, year, country):
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Operational context</div>', unsafe_allow_html=True)

    conflict_col, fragility_col = st.columns(2)

    with conflict_col:
        if country:
            hotspot = acled[acled["country_iso3"] == country]
        else:
            hotspot = acled[acled["analytical_bloc_code"] == bloc]
        st.plotly_chart(conflict_hotspot_bars(hotspot), use_container_width=True)

    with fragility_col:
        if country:
            frag = fsi[fsi["country_iso3"] == country].sort_values("year")
            row_frag = frag.iloc[-1] if not frag.empty else None
            st.plotly_chart(fragility_components(row_frag), use_container_width=True)
        else:
            frag = (
                fsi[fsi["analytical_bloc_code"] == bloc]
                .sort_values("year", ascending=False)
                .drop_duplicates("country_iso3")
                .sort_values("fsi_total_score", ascending=False)
            )
            st.plotly_chart(
                grouped_bar(
                    frag, "country_iso3",
                    ["cohesion_score", "economic_score", "political_score", "social_cross_cutting_score"],
                    "Fragility components (latest FSI)",
                ),
                use_container_width=True,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    inject_css()

    st.markdown(
        '<div class="dash-title">CEMAC · ECOWAS · AES Trade Observatory</div>' +
        '<div class="dash-subtitle">Regional trade, macro-fiscal and operational risk monitor' +
        ' · IMF IMTS &amp; WEO · ACLED · Fund for Peace FSI · Comtrade pending</div>',
        unsafe_allow_html=True,
    )

    # Toolbar
    t_bloc, t_year, t_country, t_metric = st.columns([3, 1, 2, 2])
    with t_bloc:
        bloc = st.radio(
            "Bloc", BLOCS,
            format_func=lambda b: b + (" 🆕" if b == "AES" else ""),
            horizontal=True, label_visibility="collapsed",
        )
    with t_year:
        year = st.selectbox("Year", YEARS, index=0, label_visibility="collapsed")
    with t_country:
        members = dl.BLOC_MEMBERS.get(bloc, [])
        iso_by_name = {dl.COUNTRY_NAMES.get(m, m): m for m in members}
        opts_c = ["All " + bloc + " countries"] + list(iso_by_name.keys())
        c_label = st.selectbox("Country", opts_c, index=0, label_visibility="collapsed")
        country = iso_by_name.get(c_label) if c_label.startswith("All") is False else None
    with t_metric:
        map_metric = st.selectbox("Map metric", list(MAP_METRICS.keys()), label_visibility="collapsed")

    # Crumb
    if country:
        crumb = (
            '<div class="crumb-bar">\U0001f30d ' +
            '<span class="crumb-sep">›</span> ' +
            f'<span class="crumb-val">{bloc}</span> ' +
            '<span class="crumb-sep">›</span> ' +
            f'<span class="crumb-val">{dl.COUNTRY_NAMES.get(country, country)}</span> ' +
            f'<span class="crumb-sep">·</span> {year}</div>'
        )
    else:
        n = BLOC_SIZES.get(bloc, len(members))
        crumb = (
            '<div class="crumb-bar">\U0001f30d Viewing ' +
            f'<span class="crumb-val">{bloc}</span> bloc ' +
            f'<span class="crumb-sep">·</span> <span class="crumb-val">{year}</span> ' +
            f'<span class="crumb-sep">·</span> {n} members</div>'
        )
    st.markdown(crumb, unsafe_allow_html=True)

    # Load data
    with st.spinner("Loading data…"):
        ts      = dl.country_timeseries()
        weo     = dl.weo_annual()
        fsi     = dl.fsi_annual()
        acled   = dl.acled_annual()
        partners = dl.top_partners()
        intra   = dl.intra_bloc_share()
        hhi     = dl.hhi_trend()
        growth  = dl.indexed_trade_growth()

    if ts.empty and weo.empty:
        st.error(
            "⚠️ No local data found. Ensure JSONL extracts are present in "
            "`data/raw/imts/`, `data/raw/weo/`, `data/raw/fsi/`, `data/raw/acled/`."
        )
        return

    map_df = pd.DataFrame()
    if not ts.empty:
        map_df = (
            ts.dropna(subset=["total_trade_billions_usd"])
            .sort_values("year")
            .groupby("country_iso3", as_index=False)
            .last()
        )

    render_overview(ts, weo, fsi, map_df, bloc, year, country, map_metric)
    render_trading_partners(partners, ts, bloc, year, country)
    render_concentration(ts, intra, hhi, bloc, country)
    render_growth(ts, growth, bloc, country)
    render_operational_context(fsi, acled, ts, bloc, year, country)

    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    st.markdown(
        '<p style="color:#3a3b36;font-size:.68rem;text-align:center;">' +
        "CEMAC-ECOWAS-AES Trade Observatory · IMF IMTS 1990–2024 · IMF WEO · ACLED · FSI</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
