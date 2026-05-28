# CEMAC-ECOWAS-AES Trade Observatory

[![Deploy static dashboard to GitHub Pages](https://github.com/mintyfizz/cemac-ecowas-aes-trade-observatory/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/mintyfizz/cemac-ecowas-aes-trade-observatory/actions/workflows/deploy-pages.yml)

A Databricks lakehouse and static public dashboard for tracking trade flows,
partner dependence, macro-fiscal exposure, conflict, and fragility across
CEMAC, ECOWAS, and the Alliance of Sahel States (AES).

**Live dashboard:** <https://mintyfizz.github.io/cemac-ecowas-aes-trade-observatory/>

The public dashboard is hosted on GitHub Pages. There is no public backend and
no runtime secret in the browser. The site reads pre-exported JSON files under
`static/data/`; GitHub Actions refreshes those files from Databricks gold tables
for each Pages deployment.

## What This Project Demonstrates

- A medallion lakehouse pipeline on Databricks using bronze, silver, and gold
  Delta tables.
- Multi-source reconciliation across IMF trade, IMF macroeconomic data, UN
  Comtrade product data, ACLED conflict data, and Fund for Peace FSI data.
- Time-aware analytical bloc membership, including the recent AES split.
- Contract-checked static exports for a dashboard that can be opened from a
  fresh clone without Databricks access.
- Clear interpretation rules for incomplete product coverage, latest-available
  fragility data, and snapshot panels.

## Dashboard Surface

| Area | What it answers |
| --- | --- |
| Map and overview | Which countries/blocs have the largest trade, GDP, openness, partner concentration, conflict burden, or fragility score in a selected year? |
| Economic profile | What does the selected country or bloc look like across GDP, population, debt, inflation, fiscal balance, current account, and trade intensity? |
| Trading partners | Which named country partners dominate trade, and how concentrated is dependence on the top partner and top three partners? |
| Partner concentration | How concentrated is partner trade over time, measured with HHI? Bloc HHI is computed from aggregated partner shares, not a weighted average of member HHIs. |
| Trade openness | How large are exports plus imports relative to GDP over time? |
| Growth and exposure | How has total trade grown since 1990, and how exposed is the selected scope through exports, imports, and trade balance as shares of GDP? |
| Product structure | Which HS2 sectors dominate exports or imports where UN Comtrade coverage is sufficient? |
| Operational context | Where are conflict hotspots, how do latest-available FSI components compare, and what macro-fiscal pressures stand out? |
| Pipeline health | Which rows, years, countries, and source caveats are present in the static export? |

## Interpretation Rules

These rules are intentional and are enforced either in the data mart, frontend,
or audit layer.

- **Time series use historical analytical membership.** AES appears as an
  analytical bloc only from the 2024 split onward; earlier Mali, Burkina Faso,
  and Niger rows remain historical ECOWAS rows.
- **Snapshot panels use current membership.** Conflict hotspots and FSI
  components are latest-window or latest-available panels, so the frontend
  scopes bloc views by the current dashboard membership map. This keeps AES
  populated even when the latest FSI source year predates the split.
- **FSI is latest available, not necessarily current-year.** The current static
  export uses FSI components through 2023.
- **ACLED conflict is a latest-window operational view.** It is not a selected
  single-year chart.
- **Bloc HHI is calculated at bloc grain.** Partner totals are aggregated across
  current members first, then HHI is computed on the resulting partner-share
  distribution. The static partner export keeps the top 15 partners per
  reporter, so bloc HHI can still be biased upward by clipped long-tail
  partners.
- **Product charts are coverage-gated.** Bloc-level HS2 product structure is
  shown only when reporter and value coverage meet the dashboard thresholds.
  Otherwise the dashboard shows an insufficient-coverage state instead of
  implying precision.
- **Missing values stay missing.** Nulls are never rendered as zeros.

## Pipeline Architecture

```text
External sources
  -> bronze Delta tables
  -> silver reconciled facts and dimensions
  -> gold dashboard marts
  -> static/data/*.json
  -> GitHub Pages dashboard
```

The Databricks catalog is `cemac_ecowas_aes_trade`.

### Bronze

| Table | Source | Role |
| --- | --- | --- |
| `bronze.imts_raw` | IMF IMTS / DOTS | Annual bilateral goods exports and imports, 1990-2024. |
| `bronze.comtrade_hs6_raw` | UN Comtrade | Product trade extract used for HS2 product structure. |
| `bronze.acled_events_historical` | ACLED | Event-level conflict records. |
| `bronze.acled_weekly_aggregated` | ACLED | Country-week conflict rollups. |
| `bronze.imf_weo_raw` | IMF WEO | GDP, debt, fiscal balance, inflation, current account, and related macro indicators. |
| `bronze.fsi_raw` | Fund for Peace FSI | Total and component fragility scores. |
| `bronze.data360_raw` | World Bank Data360 | Reachability and Delta time-travel demonstration; not a dashboard source. |

### Silver

| Table | Role |
| --- | --- |
| `silver.dim_country` | Country metadata, current primary bloc, and names. |
| `silver.dim_bloc_membership` | Time-aware country-to-bloc membership. |
| `silver.fact_macro_annual` | Typed macroeconomic and trade-intensity facts per country-year. |
| `silver.fact_trade_partner_annual` | Bilateral reporter-partner trade totals. |
| `silver.trade_partner_concentration_annual` | Country-level partner HHI. |
| `silver.comtrade_partner_annual` | Bilateral Comtrade partner data for coverage overrides. |
| `silver.comtrade_hs2_annual_w00` | National-total HS2 product data for product structure. |
| `silver.comtrade_product_coverage` | Coverage flags for product chart eligibility. |
| `silver.fact_acled_events` | Clean event-level conflict data. |
| `silver.fact_acled_weekly` | Country-week conflict aggregates. |
| `silver.fact_acled_country_year` | Country-year conflict metrics. |
| `silver.fact_fsi_annual` | Normalized annual FSI scores and components. |

### Gold

| Table | Role |
| --- | --- |
| `gold.country_year_observatory` | Joined country-year observatory record. |
| `gold.country_latest_snapshot` | Latest country snapshot. |
| `gold.bloc_year_observatory` | Bloc-year aggregate observatory record. |
| `gold.bloc_latest_snapshot` | Latest bloc snapshot. |
| `gold.dashboard_country_timeseries` | Map, overview, macro profile, growth, and exposure panels. |
| `gold.dashboard_top_trade_partners` | Partner bars and partner dependence diagnostics. |
| `gold.dashboard_conflict_hotspots` | Operational conflict panel. |
| `gold.dashboard_fragility_components` | FSI component panel. |
| `gold.dashboard_bloc_comparison` | Bloc comparison and trade openness trend. |
| `gold.product_trade_hs2` | HS2 export/import product structure. |

## Data Sources

| Source | Used for | Notes |
| --- | --- | --- |
| IMF IMTS / DOTS | Bilateral goods trade by reporter, partner, and year | Primary source for partner-dependence layer. |
| UN Comtrade | HS2 product trade structure | Product panel uses national-total W00 rows and coverage gates. |
| IMF World Economic Outlook | GDP and macro-fiscal indicators | Includes a CI scale anchor for Nigeria GDP to catch unit errors. |
| ACLED | Conflict events and fatalities | Operational context, latest loaded hotspot window. |
| Fund for Peace FSI | Fragility total and component scores | Latest available coverage through 2023 in the current export. |
| World Bank Data360 | Engineering demonstration | Kept as a bronze reachability/time-travel example, not a dashboard source. |

## Country And Bloc Scope

The project covers 21 countries.

| Dashboard scope | Countries |
| --- | --- |
| CEMAC | Cameroon, Central African Republic, Chad, Congo, Equatorial Guinea, Gabon |
| ECOWAS current non-AES members | Benin, Cabo Verde, Cote d'Ivoire, Gambia, Ghana, Guinea, Guinea-Bissau, Liberia, Nigeria, Senegal, Sierra Leone, Togo |
| AES | Mali, Burkina Faso, Niger |

Historically, AES members are treated as ECOWAS members before the 2024 split
for annual time-series panels. Latest snapshot panels show them under AES.

## Static Deployment

```text
push to main
  -> .github/workflows/deploy-pages.yml
  -> scripts/export_static.py
  -> node --check static/js/*.js
  -> scripts/audit_dashboard_data.py --check-only
  -> scripts/validate_dashboard_contract.py
  -> upload static/ to GitHub Pages
```

Exported dashboard files:

```text
static/data/country_timeseries.json
static/data/top_trade_partners.json
static/data/conflict_hotspots.json
static/data/fragility_components.json
static/data/bloc_comparison.json
static/data/product_trade_hs2.json
```

The committed `static/data/` files make local preview possible without
Databricks credentials. The deployed Pages artifact is refreshed from live
Databricks during CI.

## Local Preview

No Databricks access is required to preview the committed dashboard export.

```bash
python -m http.server 8080 --directory static
```

Open <http://localhost:8080>.

## Refreshing From Databricks

Create a local `.env` file or export the variables directly:

```bash
DATABRICKS_HOST=dbc-xxxx.cloud.databricks.com
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxx
DATABRICKS_TOKEN=...
DATABRICKS_CATALOG=cemac_ecowas_aes_trade
```

Then run:

```bash
pip install -r requirements.txt
python scripts/export_static.py
python scripts/audit_dashboard_data.py --check-only
python scripts/validate_dashboard_contract.py
```

For a full gold-table rebuild from Databricks notebooks:

```bash
python scripts/rebuild_gold_dashboard.py
python scripts/export_static.py
```

## Repository Map

```text
.
├── 00_setup_catalog.ipynb
├── 01_network_test.ipynb
├── 02_bronze_data360_first_pull.ipynb
├── 03_bronze_comtrade_extract.ipynb
├── 04_bronze_imts_extract.ipynb
├── 05_bronze_acled_extract.ipynb
├── 06_bronze_imf_weo_extract.ipynb
├── 07_bronze_fsi_extract.ipynb
├── 08_silver_country_dimensions.ipynb
├── 09_silver_macro_annual.ipynb
├── 10_silver_trade_partner_annual.ipynb
├── 10b_silver_comtrade_normalize.ipynb
├── 11_silver_acled_conflict.ipynb
├── 12_silver_fsi_annual.ipynb
├── 13_audit_cross_source_coverage.ipynb
├── 14_gold_dashboard_core_marts.ipynb
├── 15_gold_dashboard_panel_marts.ipynb
├── docs/
│   ├── dashboard_data_audit.md
│   └── decisions/
│       ├── ADR-001-extraction-architecture.md
│       ├── ADR-002-bilateral-trade-source.md
│       └── ADR-003-comtrade-product-structure.md
├── extraction/
│   ├── README.md
│   └── extract/
│       ├── acled_extract.py
│       ├── comtrade_extract.py
│       ├── fsi_extract.py
│       ├── imf_dots_extract.py
│       ├── imf_weo_extract.py
│       └── tradingeconomics_trade_page_extract.py
├── scripts/
│   ├── _dbx_config.py
│   ├── audit_dashboard_data.py
│   ├── databricks_sql.py
│   ├── export_static.py
│   ├── load_comtrade_silver.py
│   ├── load_weo_silver.py
│   ├── rebuild_gold_dashboard.py
│   └── validate_dashboard_contract.py
├── static/
│   ├── index.html
│   ├── css/styles.css
│   ├── js/app_static.js
│   ├── js/charts.js
│   └── data/*.json
├── .github/workflows/deploy-pages.yml
├── databricks.yml
└── requirements.txt
```

## Validation Commands

```bash
node --check static/js/charts.js
node --check static/js/app_static.js
python -m py_compile scripts/databricks_sql.py scripts/export_static.py scripts/audit_dashboard_data.py scripts/validate_dashboard_contract.py
python scripts/audit_dashboard_data.py --check-only
```

`scripts/validate_dashboard_contract.py` also checks live Databricks row counts
and the Nigeria GDP scale anchor when credentials are present.

## License

This project is released under the [MIT License](LICENSE).

The MIT License applies to original code, notebooks, scripts, and
documentation in this repository. Data files and derived datasets remain
subject to the terms of their original providers.

## Author

Nathan Thomas Gatse - International Business and Data Science, Protection &
Security - Thomas More University of Applied Sciences, Belgium.

This is the second project in a planned series of African regional data
infrastructure work. The first project focused on digital readiness indicators
across CEMAC. This project extends that work into a lakehouse architecture with
multi-source reconciliation, analytical bloc membership, and a static public
dashboard.
