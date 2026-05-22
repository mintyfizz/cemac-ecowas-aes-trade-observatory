"""
CEMAC-ECOWAS-AES Trade Observatory – FastAPI backend.

User-supplied query parameters are validated before reaching Databricks SQL.
The API helper converts `?` placeholders to Databricks named parameters.

Environment variables required (set in Vercel dashboard):
  DATABRICKS_HOST          e.g. dbc-xxxx.cloud.databricks.com
  DATABRICKS_HTTP_PATH     e.g. /sql/1.0/warehouses/xxxx
  DATABRICKS_TOKEN         Databricks personal access token
  DATABRICKS_CATALOG       (optional, default: cemac_ecowas_aes_trade)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum

# Allow importing api.db both as a module and directly
_here = Path(__file__).resolve().parent
if str(_here.parent) not in sys.path:
    sys.path.insert(0, str(_here.parent))
PUBLIC_DIR = _here.parent / "public"

from api.db import query as dbq, CATALOG

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CEMAC-ECOWAS-AES Trade Observatory",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your Vercel domain in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

if PUBLIC_DIR.exists():
    app.mount("/css", StaticFiles(directory=PUBLIC_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=PUBLIC_DIR / "js"), name="js")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


# Mangum adapter for Vercel / AWS Lambda serverless
handler = Mangum(app, lifespan="off")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCS: dict[str, list[str]] = {
    "CEMAC":  ["CMR", "CAF", "TCD", "COG", "GNQ", "GAB"],
    "ECOWAS": ["BEN", "BFA", "CPV", "CIV", "GMB", "GHA", "GIN", "GNB",
               "LBR", "MLI", "NER", "NGA", "SEN", "SLE", "TGO"],
    "AES":    ["MLI", "BFA", "NER"],
}

COUNTRY_NAMES: dict[str, str] = {
    "CMR": "Cameroon", "CAF": "Central African Republic", "TCD": "Chad",
    "COG": "Congo", "GNQ": "Equatorial Guinea", "GAB": "Gabon",
    "BEN": "Benin", "BFA": "Burkina Faso", "CPV": "Cabo Verde",
    "CIV": "Côte d'Ivoire", "GMB": "Gambia", "GHA": "Ghana",
    "GIN": "Guinea", "GNB": "Guinea-Bissau", "LBR": "Liberia",
    "MLI": "Mali", "NER": "Niger", "NGA": "Nigeria",
    "SEN": "Senegal", "SLE": "Sierra Leone", "TGO": "Togo",
}

MAP_METRICS: dict[str, str] = {
    "total_trade": "total_trade_billions_usd",
    "trade_openness": "trade_openness_pct_gdp",
    "hhi": "total_trade_partner_hhi",
    "gdp": "gdp_current_usd_billions",
    "fragility": "fsi_total_score",
    "conflict": "fatalities_per_million",
}

VALID_BLOCS = set(BLOCS.keys())
VALID_COUNTRIES = set(COUNTRY_NAMES.keys())
VALID_METRICS = set(MAP_METRICS.keys())

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_bloc(bloc: str) -> str:
    if bloc not in VALID_BLOCS:
        raise HTTPException(400, f"Invalid bloc '{bloc}'. Must be one of {sorted(VALID_BLOCS)}.")
    return bloc


def _validate_country(country: str | None) -> str | None:
    if country and country not in VALID_COUNTRIES:
        raise HTTPException(400, f"Unknown country ISO3 '{country}'.")
    return country


def _validate_year(year: int) -> int:
    if not (1990 <= year <= 2024):
        raise HTTPException(400, "Year must be between 1990 and 2024.")
    return year


def _validate_partner(partner: str) -> str:
    if not re.fullmatch(r"[A-Z0-9_]{2,12}", partner):
        raise HTTPException(400, f"Invalid partner ISO/code '{partner}'.")
    return partner


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/meta")
async def get_meta() -> dict:
    """Return blocs, member countries, and available years."""
    return {
        "blocs": BLOCS,
        "country_names": COUNTRY_NAMES,
        "years": list(range(2024, 1989, -1)),
        "map_metrics": [
            {"value": "trade_openness", "label": "Trade openness (% GDP)"},
            {"value": "hhi", "label": "Partner concentration (HHI)"},
            {"value": "total_trade", "label": "Total trade (USD B)"},
            {"value": "gdp", "label": "GDP (USD B)"},
            {"value": "fragility", "label": "Fragility score"},
            {"value": "conflict", "label": "Fatalities per million"},
        ],
    }


@app.get("/api/overview")
async def get_overview(
    bloc: str = Query("CEMAC"),
    year: int = Query(2024),
    country: str | None = Query(None),
) -> dict:
    """KPI tiles and WEO econ cards for the selected scope."""
    _validate_bloc(bloc)
    _validate_country(country)
    _validate_year(year)

    try:
        if country:
            rows = dbq(
                f"""
                WITH base AS (
                    SELECT *
                    FROM {CATALOG}.gold.dashboard_country_timeseries
                    WHERE country_iso3 = ? AND year = ?
                    LIMIT 1
                ),
                valid_partners AS (
                    SELECT *
                    FROM {CATALOG}.gold.dashboard_top_trade_partners
                    WHERE country_iso3 = ? AND year = ?
                      AND counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
                ),
                top_partner AS (
                    SELECT
                        counterpart_iso3,
                        counterpart_name,
                        total_trade_billions_usd AS partner_trade_billions_usd
                    FROM valid_partners
                    ORDER BY partner_rank
                    LIMIT 1
                ),
                latest_fsi AS (
                    SELECT country_iso3, fsi_total_score
                    FROM {CATALOG}.gold.dashboard_fragility_components
                    WHERE country_iso3 = ?
                    LIMIT 1
                )
                SELECT
                    b.total_trade_billions_usd, b.exports_billions_usd, b.imports_billions_usd,
                    b.total_trade_partner_hhi AS hhi,
                    (SELECT counterpart_iso3 FROM top_partner) AS main_partner_iso3,
                    (SELECT counterpart_name FROM top_partner) AS main_partner_name,
                    (SELECT partner_trade_billions_usd FROM top_partner) AS main_partner_trade_billions_usd,
                    (SELECT partner_trade_billions_usd FROM top_partner)
                        / NULLIF(b.total_trade_billions_usd, 0) * 100
                        AS top_partner_share_pct,
                    b.gdp_current_usd_billions,
                    b.gdp_per_capita_current_usd AS gdp_per_capita_usd,
                    b.population_millions,
                    b.real_gdp_growth_pct_imf AS real_gdp_growth_pct,
                    b.inflation_cpi_pct AS inflation_pct,
                    b.gross_debt_pct_gdp_imf AS govt_debt_pct_gdp,
                    b.net_lending_borrowing_pct_gdp_imf AS fiscal_balance_pct_gdp,
                    b.current_account_balance_pct_gdp_imf AS current_account_pct_gdp,
                    b.trade_balance_billions_usd,
                    b.violent_events_per_million,
                    b.fatalities_per_million,
                    b.fatalities,
                    b.violent_events,
                    b.fragility_band,
                    COALESCE(b.fsi_total_score, (SELECT fsi_total_score FROM latest_fsi)) AS avg_fsi_score,
                    b.trade_openness_pct_gdp,
                    (b.exports_billions_usd / NULLIF(b.gdp_current_usd_billions, 0)) * 100 AS exports_pct_gdp,
                    (b.imports_billions_usd / NULLIF(b.gdp_current_usd_billions, 0)) * 100 AS imports_pct_gdp,
                    b.year
                FROM base b
                """,
                [country, year, country, year, country],
            )
        else:
            rows = dbq(
                f"""
                WITH scoped AS (
                    SELECT s.*, f.fsi_total_score AS latest_fsi_total_score
                    FROM {CATALOG}.gold.dashboard_country_timeseries s
                    LEFT JOIN {CATALOG}.gold.dashboard_fragility_components f
                      ON f.country_iso3 = s.country_iso3
                    WHERE s.analytical_bloc_code = ? AND s.year = ?
                ),
                valid_partners AS (
                    SELECT
                        counterpart_iso3,
                        FIRST(counterpart_name) AS counterpart_name,
                        SUM(total_trade_billions_usd) AS partner_trade_billions_usd
                    FROM {CATALOG}.gold.dashboard_top_trade_partners
                    WHERE analytical_bloc_code = ? AND year = ?
                      AND counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
                    GROUP BY counterpart_iso3
                ),
                top_partner AS (
                    SELECT *
                    FROM valid_partners
                    ORDER BY partner_trade_billions_usd DESC
                    LIMIT 1
                )
                SELECT
                    SUM(total_trade_billions_usd)       AS total_trade_billions_usd,
                    SUM(exports_billions_usd)           AS exports_billions_usd,
                    SUM(imports_billions_usd)           AS imports_billions_usd,
                    SUM(total_trade_partner_hhi * total_trade_billions_usd)
                        / NULLIF(SUM(CASE WHEN total_trade_partner_hhi IS NOT NULL
                                           THEN total_trade_billions_usd ELSE 0 END), 0)
                                                        AS hhi,
                    (SELECT counterpart_iso3 FROM top_partner) AS main_partner_iso3,
                    (SELECT counterpart_name FROM top_partner) AS main_partner_name,
                    (SELECT partner_trade_billions_usd FROM top_partner) AS main_partner_trade_billions_usd,
                    (SELECT partner_trade_billions_usd FROM top_partner)
                        / NULLIF(SUM(total_trade_billions_usd), 0) * 100
                                                        AS top_partner_share_pct,
                    SUM(gdp_current_usd_billions)       AS gdp_current_usd_billions,
                    SUM(population_millions)            AS population_millions,
                    SUM(gdp_current_usd_billions) / NULLIF(SUM(population_millions), 0) * 1000
                                                        AS gdp_per_capita_usd,
                    SUM(real_gdp_growth_pct_imf * gdp_current_usd_billions)
                        / NULLIF(SUM(CASE WHEN real_gdp_growth_pct_imf IS NOT NULL
                                           THEN gdp_current_usd_billions ELSE 0 END), 0)
                                                        AS real_gdp_growth_pct,
                    SUM(inflation_cpi_pct * gdp_current_usd_billions)
                        / NULLIF(SUM(CASE WHEN inflation_cpi_pct IS NOT NULL
                                           THEN gdp_current_usd_billions ELSE 0 END), 0)
                                                        AS inflation_pct,
                    SUM(gross_debt_pct_gdp_imf * gdp_current_usd_billions)
                        / NULLIF(SUM(CASE WHEN gross_debt_pct_gdp_imf IS NOT NULL
                                           THEN gdp_current_usd_billions ELSE 0 END), 0)
                                                        AS govt_debt_pct_gdp,
                    SUM(net_lending_borrowing_pct_gdp_imf * gdp_current_usd_billions)
                        / NULLIF(SUM(CASE WHEN net_lending_borrowing_pct_gdp_imf IS NOT NULL
                                           THEN gdp_current_usd_billions ELSE 0 END), 0)
                                                        AS fiscal_balance_pct_gdp,
                    SUM(current_account_balance_pct_gdp_imf * gdp_current_usd_billions)
                        / NULLIF(SUM(CASE WHEN current_account_balance_pct_gdp_imf IS NOT NULL
                                           THEN gdp_current_usd_billions ELSE 0 END), 0)
                                                        AS current_account_pct_gdp,
                    SUM(trade_balance_billions_usd)     AS trade_balance_billions_usd,
                    SUM(violent_events)                 AS violent_events,
                    SUM(fatalities)                     AS fatalities,
                    SUM(violent_events) / NULLIF(SUM(population_millions), 0)
                                                        AS violent_events_per_million,
                    SUM(fatalities) / NULLIF(SUM(population_millions), 0)
                                                        AS fatalities_per_million,
                    CAST(NULL AS STRING)                AS fragility_band,
                    AVG(COALESCE(fsi_total_score, latest_fsi_total_score))
                                                        AS avg_fsi_score,
                    SUM(total_trade_billions_usd) / NULLIF(SUM(gdp_current_usd_billions), 0) * 100
                                                        AS trade_openness_pct_gdp,
                    SUM(exports_billions_usd) / NULLIF(SUM(gdp_current_usd_billions), 0) * 100
                                                        AS exports_pct_gdp,
                    SUM(imports_billions_usd) / NULLIF(SUM(gdp_current_usd_billions), 0) * 100
                                                        AS imports_pct_gdp,
                    MAX(year) AS year
                FROM scoped
                """,
                [bloc, year, bloc, year],
            )
        return rows[0] if rows else {}
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/map")
async def get_map(
    metric: str = Query("total_trade"),
    year: int = Query(2024),
) -> list[dict]:
    """Country-level values for the choropleth map."""
    if metric not in VALID_METRICS:
        raise HTTPException(400, f"Unknown metric '{metric}'. Valid: {sorted(VALID_METRICS)}")
    _validate_year(year)

    col = MAP_METRICS[metric]
    try:
        rows = dbq(
            f"""
            SELECT country_iso3, country_name, analytical_bloc_code, {col} AS value
            FROM {CATALOG}.gold.dashboard_country_timeseries
            WHERE year = ?
            """,
            [year],
        )
        return rows
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/partners")
async def get_partners(
    bloc: str = Query("CEMAC"),
    year: int = Query(2024),
    country: str | None = Query(None),
) -> list[dict]:
    """Top 10 trade partners for the selected scope."""
    _validate_bloc(bloc)
    _validate_country(country)
    _validate_year(year)

    try:
        if country:
            rows = dbq(
                f"""
                SELECT counterpart_iso3, counterpart_name,
                       exports_billions_usd, imports_billions_usd,
                       total_trade_billions_usd, total_trade_partner_share_pct,
                       partner_rank
                FROM {CATALOG}.gold.dashboard_top_trade_partners
                WHERE country_iso3 = ? AND year = ?
                  AND counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
                ORDER BY partner_rank
                LIMIT 10
                """,
                [country, year],
            )
        else:
            rows = dbq(
                f"""
                WITH agg AS (
                    SELECT
                        counterpart_iso3,
                        FIRST(counterpart_name) AS counterpart_name,
                        SUM(exports_billions_usd)           AS exports_billions_usd,
                        SUM(imports_billions_usd)           AS imports_billions_usd,
                        SUM(total_trade_billions_usd)       AS total_trade_billions_usd
                    FROM {CATALOG}.gold.dashboard_top_trade_partners
                    WHERE analytical_bloc_code = ? AND year = ?
                      AND counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
                    GROUP BY counterpart_iso3
                ),
                scope_total AS (
                    SELECT SUM(total_trade_billions_usd) AS total_trade_billions_usd
                    FROM {CATALOG}.gold.dashboard_country_timeseries
                    WHERE analytical_bloc_code = ? AND year = ?
                )
                SELECT
                    counterpart_iso3,
                    counterpart_name,
                    exports_billions_usd,
                    imports_billions_usd,
                    total_trade_billions_usd,
                    total_trade_billions_usd / NULLIF((SELECT total_trade_billions_usd FROM scope_total), 0) * 100
                        AS total_trade_partner_share_pct,
                    ROW_NUMBER() OVER (ORDER BY total_trade_billions_usd DESC) AS partner_rank
                FROM agg
                ORDER BY total_trade_billions_usd DESC
                LIMIT 10
                """,
                [bloc, year, bloc, year],
            )
        return rows
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/partner-history")
async def get_partner_history(
    bloc: str = Query("CEMAC"),
    partner1: str = Query("CHN"),
    partner2: str = Query("FRA"),
    country: str | None = Query(None),
) -> list[dict]:
    """Year-on-year trade share for two selected partners."""
    _validate_bloc(bloc)
    _validate_country(country)
    _validate_partner(partner1)
    _validate_partner(partner2)

    try:
        if country:
            rows = dbq(
                f"""
                SELECT year, counterpart_iso3, total_trade_partner_share_pct AS share_pct
                FROM {CATALOG}.gold.dashboard_top_trade_partners
                WHERE country_iso3 = ?
                  AND counterpart_iso3 IN (?, ?)
                  AND counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
                ORDER BY year
                """,
                [country, partner1, partner2],
            )
        else:
            rows = dbq(
                f"""
                WITH valid_rows AS (
                    SELECT *
                    FROM {CATALOG}.gold.dashboard_top_trade_partners
                    WHERE analytical_bloc_code = ?
                      AND counterpart_iso3 RLIKE '^[A-Z]{{3}}$'
                ),
                totals AS (
                    SELECT year, SUM(total_trade_billions_usd) AS year_total
                    FROM {CATALOG}.gold.dashboard_country_timeseries
                    WHERE analytical_bloc_code = ?
                    GROUP BY year
                ),
                selected AS (
                    SELECT year, counterpart_iso3, SUM(total_trade_billions_usd) AS partner_total
                    FROM valid_rows
                    WHERE counterpart_iso3 IN (?, ?)
                    GROUP BY year, counterpart_iso3
                )
                SELECT s.year, s.counterpart_iso3,
                       s.partner_total / NULLIF(t.year_total, 0) * 100 AS share_pct
                FROM selected s
                JOIN totals t ON t.year = s.year
                ORDER BY s.year
                """,
                [bloc, bloc, partner1, partner2],
            )
        return rows
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/concentration")
async def get_concentration(
    bloc: str = Query("CEMAC"),
    year: int = Query(2024),
    country: str | None = Query(None),
) -> dict:
    """HHI trend + intra-bloc trade share by year."""
    _validate_bloc(bloc)
    _validate_year(year)
    _validate_country(country)

    try:
        if country:
            # Return the selected country's own HHI trend across all years
            hhi_rows = dbq(
                f"""
                SELECT country_iso3, country_name, analytical_bloc_code,
                       total_trade_partner_hhi AS hhi, year
                FROM {CATALOG}.gold.dashboard_country_timeseries
                WHERE country_iso3 = ?
                ORDER BY year
                """,
                [country],
            )
        else:
            # Bloc-level HHI is trade-weighted across members, not a plain mean.
            hhi_rows = dbq(
                f"""
                SELECT
                    year,
                    analytical_bloc_code,
                    SUM(total_trade_partner_hhi * total_trade_billions_usd)
                      / NULLIF(SUM(CASE WHEN total_trade_partner_hhi IS NOT NULL
                                         THEN total_trade_billions_usd ELSE 0 END), 0)
                      AS hhi
                FROM {CATALOG}.gold.dashboard_country_timeseries
                GROUP BY year, analytical_bloc_code
                ORDER BY year
                """,
            )

        # UN Comtrade is not loaded, so the integration panel uses bloc trade
        # openness rather than product-level or mirror-pair metrics.
        intra_rows = dbq(
            f"""
            SELECT year, analytical_bloc_code,
                   trade_openness_pct_gdp AS intra_share_pct
            FROM {CATALOG}.gold.dashboard_bloc_comparison
            ORDER BY year
            """,
        )
        return {"hhi": hhi_rows, "intra": intra_rows}
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/growth")
async def get_growth(
    bloc: str = Query("CEMAC"),
    country: str | None = Query(None),
) -> list[dict]:
    """Indexed total goods trade growth.

    Standard formula:
      index_value = total_trade_billions_usd / 1990 total_trade_billions_usd * 100

    Total trade is exports + imports from the loaded IMF IMTS/DOTS mart, in
    nominal current USD. Missing current-year values remain null; they are not
    converted to zero.
    """
    _validate_bloc(bloc)
    _validate_country(country)

    try:
        if country:
            rows = dbq(
                f"""
                WITH base AS (
                    SELECT country_iso3, total_trade_billions_usd AS base_val
                    FROM {CATALOG}.gold.dashboard_country_timeseries
                    WHERE year = 1990
                      AND country_iso3 = ?
                      AND total_trade_billions_usd > 0
                )
                SELECT t.country_iso3, t.country_name, t.analytical_bloc_code,
                       t.year, 1990 AS base_year,
                       b.base_val AS base_trade_billions_usd,
                       t.total_trade_billions_usd,
                       CASE
                         WHEN t.total_trade_billions_usd IS NOT NULL
                         THEN (t.total_trade_billions_usd / b.base_val) * 100
                       END AS index_value
                FROM {CATALOG}.gold.dashboard_country_timeseries t
                JOIN base b ON b.country_iso3 = t.country_iso3
                WHERE t.country_iso3 = ?
                ORDER BY t.year
                """,
                [country, country],
            )
        else:
            members = BLOCS[bloc]
            placeholders = ", ".join(["?"] * len(members))
            rows = dbq(
                f"""
                WITH base AS (
                    SELECT country_iso3, total_trade_billions_usd AS base_val
                    FROM {CATALOG}.gold.dashboard_country_timeseries
                    WHERE year = 1990
                      AND country_iso3 IN ({placeholders})
                      AND total_trade_billions_usd > 0
                )
                SELECT t.country_iso3, t.country_name,
                       ? AS analytical_bloc_code,
                       t.year, 1990 AS base_year,
                       b.base_val AS base_trade_billions_usd,
                       t.total_trade_billions_usd,
                       CASE
                         WHEN t.total_trade_billions_usd IS NOT NULL
                         THEN (t.total_trade_billions_usd / b.base_val) * 100
                       END AS index_value
                FROM {CATALOG}.gold.dashboard_country_timeseries t
                JOIN base b ON b.country_iso3 = t.country_iso3
                WHERE t.country_iso3 IN ({placeholders})
                ORDER BY t.country_iso3, t.year
                """,
                [*members, bloc, *members],
            )
        return rows
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/operational")
async def get_operational(
    bloc: str = Query("CEMAC"),
    year: int = Query(2024),
    country: str | None = Query(None),
) -> dict:
    """ACLED conflict events + FSI fragility components."""
    _validate_bloc(bloc)
    _validate_country(country)
    _validate_year(year)

    try:
        scope_filter = "country_iso3 = ?" if country else "analytical_bloc_code = ?"
        scope_val = country if country else bloc

        if country:
            conflict_rows = dbq(
                f"""
                SELECT country_iso3, country_name, analytical_bloc_code,
                       admin1, window_start_year, window_end_year,
                       violent_events, fatalities, fatalities_per_million
                FROM {CATALOG}.gold.dashboard_conflict_hotspots
                WHERE country_iso3 = ?
                ORDER BY hotspot_rank
                """,
                [scope_val],
            )
        else:
            conflict_rows = dbq(
                f"""
                SELECT country_iso3, country_name, analytical_bloc_code,
                       CAST(NULL AS STRING) AS admin1,
                       MIN(window_start_year) AS window_start_year,
                       MAX(window_end_year) AS window_end_year,
                       SUM(violent_events) AS violent_events,
                       SUM(fatalities) AS fatalities,
                       CAST(NULL AS DOUBLE) AS fatalities_per_million
                FROM {CATALOG}.gold.dashboard_conflict_hotspots
                WHERE analytical_bloc_code = ?
                GROUP BY country_iso3, country_name, analytical_bloc_code
                ORDER BY violent_events DESC, fatalities DESC, country_name
                """,
                [scope_val],
            )

        fragility_rows = dbq(
            f"""
            SELECT country_iso3, country_name, analytical_bloc_code,
                   fsi_total_score,
                   cohesion_score, economic_score,
                   political_score, social_cross_cutting_score,
                   fsi_year
            FROM {CATALOG}.gold.dashboard_fragility_components
            WHERE {scope_filter}
            ORDER BY fsi_total_score DESC
            """,
            [scope_val],
        )

        return {"conflict": conflict_rows, "fragility": fragility_rows}
    except Exception as exc:
        raise HTTPException(503, f"Data not available: {exc}") from exc


@app.get("/api/products")
async def get_products(
    bloc: str = Query("CEMAC"),
    year: int = Query(2024),
    country: str | None = Query(None),
    flow: str = Query("export"),
) -> dict:
    """Top HS2 trade sectors by value for the selected scope and year."""
    try:
        _validate_bloc(bloc)
        _validate_country(country)
        _validate_year(year)
        if flow not in ("export", "import"):
            raise HTTPException(400, "flow must be 'export' or 'import'")

        if country:
            rows = dbq(
                f"""
                SELECT hs2_code, hs2_description,
                       trade_value_billions_usd, hs2_share_pct
                FROM {CATALOG}.gold.product_trade_hs2
                WHERE reporter_iso3 = ? AND year = ? AND flow_type = ?
                ORDER BY trade_value_billions_usd DESC NULLS LAST
                LIMIT 15
                """,
                [country, year, flow],
            )
            if not rows:
                latest_result = dbq(
                    f"""
                    SELECT MAX(year) AS latest_year
                    FROM {CATALOG}.gold.product_trade_hs2
                    WHERE reporter_iso3 = ? AND flow_type = ?
                    """,
                    [country, flow],
                )
                latest_year = (latest_result[0].get("latest_year") if latest_result else None)
                return {
                    "available": False,
                    "coverage_note": f"No Comtrade product data for {country} · {year}",
                    "rows": [],
                    "latest_year": latest_year,
                }
            return {
                "available": True,
                "coverage_note": f"UN Comtrade · {COUNTRY_NAMES.get(country, country)} · {year}",
                "rows": rows,
            }
        else:
            members = BLOCS[bloc]
            placeholders = ", ".join(["?"] * len(members))
            rows = dbq(
                f"""
                WITH agg AS (
                    SELECT hs2_code, hs2_description,
                           SUM(trade_value_billions_usd) AS trade_value_billions_usd
                    FROM {CATALOG}.gold.product_trade_hs2
                    WHERE reporter_iso3 IN ({placeholders})
                      AND year = ?
                      AND flow_type = ?
                    GROUP BY hs2_code, hs2_description
                ),
                grand AS (
                    SELECT SUM(trade_value_billions_usd) AS total FROM agg
                )
                SELECT a.hs2_code, a.hs2_description,
                       a.trade_value_billions_usd,
                       ROUND(100.0 * a.trade_value_billions_usd / NULLIF(g.total, 0), 1)
                           AS hs2_share_pct
                FROM agg a CROSS JOIN grand g
                ORDER BY a.trade_value_billions_usd DESC NULLS LAST
                LIMIT 15
                """,
                [*members, year, flow],
            )
            n_reporters_result = dbq(
                f"""
                SELECT COUNT(DISTINCT reporter_iso3) AS n_reporters
                FROM {CATALOG}.gold.product_trade_hs2
                WHERE reporter_iso3 IN ({placeholders})
                  AND year = ?
                  AND flow_type = ?
                """,
                [*members, year, flow],
            )
            n_reporters = (n_reporters_result[0].get("n_reporters") or 0) if n_reporters_result else 0
            coverage_note = (
                f"UN Comtrade · {n_reporters} of {len(members)} {bloc} reporters "
                f"with coverage · {year}"
            )
            if not rows:
                latest_result = dbq(
                    f"""
                    SELECT MAX(year) AS latest_year
                    FROM {CATALOG}.gold.product_trade_hs2
                    WHERE reporter_iso3 IN ({placeholders})
                      AND flow_type = ?
                    """,
                    [*members, flow],
                )
                latest_year = (latest_result[0].get("latest_year") if latest_result else None)
                return {"available": False, "coverage_note": coverage_note, "rows": [], "latest_year": latest_year}
            return {"available": True, "coverage_note": coverage_note, "rows": rows}
    except HTTPException:
        raise
    except Exception as exc:
        return {
            "available": False,
            "coverage_note": f"Product data unavailable: {exc}",
            "rows": [],
        }


@app.get("/api/health")
async def health() -> dict:
    try:
        core = dbq(
            f"""
            SELECT
              COUNT(*) AS rows,
              COUNT(DISTINCT country_iso3) AS countries,
              MIN(year) AS min_year,
              MAX(year) AS max_year
            FROM {CATALOG}.gold.dashboard_country_timeseries
            """
        )[0]
        fsi = dbq(
            f"""
            SELECT
              COUNT(*) AS countries,
              MIN(fsi_year) AS min_year,
              MAX(fsi_year) AS max_year
            FROM {CATALOG}.gold.dashboard_fragility_components
            """
        )[0]
        acled = dbq(
            f"""
            SELECT
              SUM(violent_events) AS violent_events,
              SUM(fatalities) AS fatalities,
              MIN(window_start_year) AS min_year,
              MAX(window_end_year) AS max_year
            FROM {CATALOG}.gold.dashboard_conflict_hotspots
            """
        )[0]
        blocs = dbq(
            f"""
            SELECT COUNT(*) AS rows, COUNT(DISTINCT analytical_bloc_code) AS blocs
            FROM {CATALOG}.gold.dashboard_bloc_comparison
            """
        )[0]
        return {
            "status": "ok",
            "panels": [
                {
                    "label": "Country-year mart",
                    "value": f"{core['rows']} rows",
                    "description": f"{core['countries']} countries · {core['min_year']}-{core['max_year']}",
                },
                {
                    "label": "Bloc mart",
                    "value": f"{blocs['blocs']} blocs",
                    "description": f"{blocs['rows']} bloc-year rows",
                },
                {
                    "label": "ACLED coverage",
                    "value": f"{int(acled['violent_events'] or 0):,} events",
                    "description": f"hotspot windows cover {acled['min_year']}-{acled['max_year']}",
                },
                {
                    "label": "FSI coverage",
                    "value": f"{fsi['countries']} countries",
                    "description": f"latest components from {fsi['min_year']}-{fsi['max_year']}; no 2024 release in source",
                },
            ],
        }
    except Exception as exc:
        raise HTTPException(503, f"Health data not available: {exc}") from exc
