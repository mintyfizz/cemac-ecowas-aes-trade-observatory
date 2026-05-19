"""Plotly chart builders for the CEMAC-ECOWAS-AES dashboard."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


COLORS = {
    "CEMAC": "#0F6E56",
    "ECOWAS": "#185FA5",
    "AES": "#BA7517",
    "exports": "#1D9E75",
    "imports": "#7F77DD",
    "danger": "#EF7668",
    "warning": "#F7D25D",
    "muted": "#AAA59A",
    "surface": "#2F302D",
    "grid": "#4A4B46",
    "text": "#F4F1E8",
}

TEMPLATE_LAYOUT = {
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": COLORS["text"], "family": "Inter, Arial, sans-serif"},
    "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    "margin": {"l": 10, "r": 10, "t": 28, "b": 28},
}


def _apply_theme(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(**TEMPLATE_LAYOUT, height=height)
    fig.update_xaxes(showgrid=True, gridcolor=COLORS["grid"], zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=COLORS["grid"], zeroline=False)
    return fig


def empty_figure(message: str, height: int = 280) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"color": COLORS["muted"], "size": 13},
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _apply_theme(fig, height=height)


def metric_map(df: pd.DataFrame, metric: str, title: str) -> go.Figure:
    if df.empty or metric not in df.columns:
        return empty_figure("No map data available.")

    fig = px.choropleth(
        df,
        locations="country_iso3",
        color=metric,
        hover_name="country_name",
        hover_data={
            "country_iso3": True,
            "analytical_bloc_code": True,
            metric: ":.2f",
        },
        color_continuous_scale=["#E1F5EE", "#9FE1CB", "#5DCAA5", "#1D9E75", "#0F6E56"],
        scope="africa",
        title=title,
    )
    fig.update_geos(
        bgcolor="rgba(0,0,0,0)",
        showframe=False,
        showcoastlines=False,
        showland=True,
        landcolor="#20211E",
        countrycolor="#5D5E58",
    )
    fig.update_coloraxes(colorbar={"title": ""})
    return _apply_theme(fig, height=560)


def line_chart(
    df: pd.DataFrame,
    x: str,
    y: str | list[str],
    color: str | None = None,
    title: str | None = None,
    y_title: str | None = None,
    height: int = 300,
) -> go.Figure:
    if df.empty:
        return empty_figure("No time-series data available.", height=height)

    if isinstance(y, list):
        fig = go.Figure()
        palette = [COLORS["exports"], COLORS["imports"], COLORS["warning"], COLORS["danger"], "#5DCAA5"]
        for idx, column in enumerate(y):
            if column in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df[x],
                        y=df[column],
                        mode="lines",
                        name=column.replace("_", " "),
                        line={"width": 2, "color": palette[idx % len(palette)]},
                    )
                )
    else:
        fig = px.line(
            df,
            x=x,
            y=y,
            color=color,
            color_discrete_map=COLORS,
            title=title,
            markers=False,
        )

    fig.update_layout(title=title or "", yaxis_title=y_title or "")
    return _apply_theme(fig, height=height)


def top_partner_bars(df: pd.DataFrame, height: int = 360) -> go.Figure:
    if df.empty:
        return empty_figure("No partner data available.", height=height)

    ordered = df.sort_values("partner_rank", ascending=True).copy()
    labels = ordered["counterpart_name"].astype(str)

    fig = go.Figure()
    fig.add_bar(
        y=labels,
        x=ordered["exports_billions_usd"],
        name="Exports",
        orientation="h",
        marker_color=COLORS["exports"],
    )
    fig.add_bar(
        y=labels,
        x=ordered["imports_billions_usd"],
        name="Imports",
        orientation="h",
        marker_color=COLORS["imports"],
    )
    fig.update_layout(barmode="stack", xaxis_title="USD billions", yaxis_title="", yaxis={"autorange": "reversed"})
    return _apply_theme(fig, height=height)


def conflict_hotspot_bars(df: pd.DataFrame, height: int = 360) -> go.Figure:
    if df.empty:
        return empty_figure("No conflict hotspot data available.", height=height)

    top = df.sort_values(["violent_events", "fatalities"], ascending=False).head(12)
    fig = go.Figure()
    fig.add_bar(
        y=top["admin1"].fillna("Unknown"),
        x=top["violent_events"],
        name="Violent events",
        orientation="h",
        marker_color=COLORS["danger"],
    )
    fig.add_bar(
        y=top["admin1"].fillna("Unknown"),
        x=top["fatalities"],
        name="Fatalities",
        orientation="h",
        marker_color=COLORS["warning"],
    )
    fig.update_layout(barmode="group", xaxis_title="Count", yaxis_title="", yaxis={"autorange": "reversed"})
    return _apply_theme(fig, height=height)


def fragility_components(row: pd.Series | None, height: int = 340) -> go.Figure:
    if row is None or row.empty:
        return empty_figure("No fragility component data available.", height=height)

    labels = ["Cohesion", "Economic", "Political", "Social/cross-cutting"]
    values = [
        row.get("cohesion_score"),
        row.get("economic_score"),
        row.get("political_score"),
        row.get("social_cross_cutting_score"),
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=values,
            marker_color=[COLORS["danger"], COLORS["warning"], COLORS["imports"], COLORS["exports"]],
            name="FSI category score",
        )
    )
    fig.update_layout(yaxis_title="Score", xaxis_title="")
    return _apply_theme(fig, height=height)


def risk_scatter(df: pd.DataFrame, height: int = 360) -> go.Figure:
    required = {"trade_openness_pct_gdp", "fatalities_per_million", "gdp_current_usd_billions"}
    if df.empty or not required.issubset(df.columns):
        return empty_figure("No risk scatter data available.", height=height)

    plot_df = df.dropna(subset=["trade_openness_pct_gdp", "fatalities_per_million"]).copy()
    if plot_df.empty:
        return empty_figure("No country has both trade and conflict metrics for this year.", height=height)
    plot_df["gdp_current_usd_billions"] = (
        pd.to_numeric(plot_df["gdp_current_usd_billions"], errors="coerce")
        .fillna(0.1)
        .clip(lower=0.1)
    )

    fig = px.scatter(
        plot_df,
        x="trade_openness_pct_gdp",
        y="fatalities_per_million",
        size="gdp_current_usd_billions",
        color="analytical_bloc_code",
        color_discrete_map=COLORS,
        hover_name="country_name",
        hover_data={
            "country_iso3": True,
            "gdp_current_usd_billions": ":.2f",
            "trade_openness_pct_gdp": ":.1f",
            "fatalities_per_million": ":.1f",
        },
    )
    fig.update_layout(xaxis_title="Trade openness (% GDP)", yaxis_title="Fatalities per million")
    return _apply_theme(fig, height=height)


def coverage_chart(summary: pd.DataFrame, height: int = 280) -> go.Figure:
    if summary.empty:
        return empty_figure("No coverage summary available.", height=height)

    fig = px.bar(
        summary.sort_values("source_name"),
        x="source_name",
        y="pct_country_years_covered",
        text="pct_country_years_covered",
        color="source_name",
        color_discrete_sequence=[COLORS["exports"], COLORS["imports"], COLORS["warning"], COLORS["danger"]],
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Country-year coverage (%)")
    return _apply_theme(fig, height=height)


def grouped_bar(df: pd.DataFrame, x: str, y_columns: Iterable[str], title: str, height: int = 320) -> go.Figure:
    if df.empty:
        return empty_figure("No comparison data available.", height=height)

    fig = go.Figure()
    palette = [COLORS["exports"], COLORS["imports"], COLORS["warning"], COLORS["danger"], "#5DCAA5"]
    for idx, column in enumerate(y_columns):
        if column in df.columns:
            fig.add_bar(x=df[x], y=df[column], name=column.replace("_", " "), marker_color=palette[idx % len(palette)])
    fig.update_layout(title=title, barmode="group")
    return _apply_theme(fig, height=height)


def multi_bloc_line(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    y_title: str = "",
    highlight_bloc: str | None = None,
    height: int = 320,
) -> go.Figure:
    """
    Line chart with one trace per analytical_bloc_code, coloured by COLORS dict.
    Optionally thickens the highlighted bloc's line.
    """
    if df.empty or y not in df.columns:
        return empty_figure("No data available.", height=height)

    fig = go.Figure()
    blocs = df["analytical_bloc_code"].unique()
    for bloc in sorted(blocs):
        sub = df[df["analytical_bloc_code"] == bloc].sort_values(x)
        width = 3 if bloc == highlight_bloc else 1.5
        opacity = 1.0 if bloc == highlight_bloc else 0.55
        fig.add_scatter(
            x=sub[x],
            y=sub[y],
            name=bloc,
            mode="lines",
            line={"color": COLORS.get(bloc, "#AAA59A"), "width": width},
            opacity=opacity,
        )
    fig.update_layout(title=title, yaxis_title=y_title)
    return _apply_theme(fig, height=height)


def partner_share_comparison(
    history_df: pd.DataFrame,
    partner1: str,
    partner2: str,
    height: int = 320,
) -> go.Figure:
    """
    Two-line chart comparing partner1 vs partner2 share of total trade over years.
    `history_df` must have columns: year, counterpart_iso3, share_pct.
    """
    if history_df.empty:
        return empty_figure("No partner history data.", height=height)

    fig = go.Figure()
    for partner, color in [(partner1, COLORS["exports"]), (partner2, COLORS["imports"])]:
        sub = history_df[history_df["counterpart_iso3"] == partner].sort_values("year")
        if not sub.empty:
            fig.add_scatter(
                x=sub["year"],
                y=sub["share_pct"],
                name=partner,
                mode="lines+markers",
                line={"color": color, "width": 2},
                marker={"size": 4},
            )
    fig.update_layout(
        title="Partner share of total trade (%)",
        yaxis_title="Share (%)",
    )
    return _apply_theme(fig, height=height)


def trade_growth_index(
    df: pd.DataFrame,
    highlight_countries: list[str] | None = None,
    height: int = 340,
) -> go.Figure:
    """
    Indexed trade growth chart (base year = 100) per country.
    `df` must have columns: country_iso3, country_name, year, index_value.
    """
    if df.empty:
        return empty_figure("No trade index data.", height=height)

    fig = go.Figure()
    countries = df["country_iso3"].unique()
    highlight_set = set(highlight_countries or [])

    for iso in sorted(countries):
        sub = df[df["country_iso3"] == iso].sort_values("year")
        name = sub["country_name"].iloc[0] if not sub.empty else iso
        is_hi = iso in highlight_set
        fig.add_scatter(
            x=sub["year"],
            y=sub["index_value"],
            name=name,
            mode="lines",
            line={"width": 2 if is_hi else 1, "color": "#1D9E75" if is_hi else "#4A4B46"},
            opacity=1.0 if is_hi else 0.4,
            showlegend=is_hi,
        )

    fig.add_hline(y=100, line_dash="dot", line_color=COLORS["muted"], line_width=1)
    fig.update_layout(title="Indexed trade growth (1990 = 100)", yaxis_title="Index (1990=100)")
    return _apply_theme(fig, height=height)
