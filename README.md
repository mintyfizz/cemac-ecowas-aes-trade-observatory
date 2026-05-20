# CEMAC–ECOWAS–AES Trade Observatory

A Databricks lakehouse platform tracking trade flows, partner dependencies,
and structural economic vulnerability across CEMAC, ECOWAS, and the
Alliance of Sahel States (AES). Covers 21 countries from 1990 to 2024.

**Live dashboard → [mintyfizz.github.io/cemac-ecowas-aes-trade-observatory](https://mintyfizz.github.io/cemac-ecowas-aes-trade-observatory)**

The dashboard is a fully static site hosted on GitHub Pages. Every push to
`main` triggers a GitHub Actions workflow that queries the Databricks gold
tables, exports them to JSON, and redeploys the site automatically. No
server or API key is needed to view it.

---

## Dashboard

The dashboard is organised into six panels accessible via tab navigation:

| Panel | What it shows |
|---|---|
| **Overview** | Country map coloured by a selectable metric (trade volume, openness, HHI, GDP, fragility, conflict fatalities). Click a country to drill in. Summary stat cards per bloc. |
| **Economic profile** | GDP trend, trade openness over time, and macro-fiscal scorecard for the selected country. |
| **Trading partners** | Top 10 trading partners by year (bar chart) and a two-partner share comparison over time (line chart). IMF aggregate groups excluded. |
| **Concentration & regional integration** | Partner concentration (HHI) trend and bloc-level trade openness as a proxy for regional integration. |
| **Growth & trade structure** | Trade indexed to 1990 base = 100, and a trade exposure mix showing exports, imports, balance, openness, and HHI. |
| **Operational context** | ACLED conflict events and fatalities (latest 3-year hotspot window), FSI fragility component breakdown, and a normalised macro-fiscal risk scorecard. |

### How the static build works

```
git push → GitHub Actions
  └── scripts/export_static.py          queries Databricks gold tables
        ├── static/data/country_timeseries.json
        ├── static/data/top_trade_partners.json
        ├── static/data/conflict_hotspots.json
        ├── static/data/fragility_components.json
        └── static/data/bloc_comparison.json
  └── copies public/css/ and public/js/charts.js into static/
  └── uploads static/ → GitHub Pages
```

The browser loads the five JSON files at startup. All filtering, chart
rendering, and map colouring happens client-side with no back-end calls.

---

## Architecture

The pipeline follows a medallion pattern inside a single Unity Catalog
catalog (`cemac_ecowas_aes_trade`) on Databricks Free Edition:

```
Raw sources → Bronze (Delta) → Silver (Delta) → Gold marts → Static JSON → GitHub Pages
```

### Bronze layer — raw, append-only, replayable

| Table | Source | Contents |
|---|---|---|
| `bronze.data360_raw` | World Bank Data360 | Macroeconomic indicators for CEMAC countries, 1990–2024 |
| `bronze.imts_raw` | IMF IMTS / DOTS API | Annual bilateral goods exports and imports for all 21 countries and their partners, 1990–2024 |
| `bronze.acled_events_historical` | ACLED | Individual conflict events (coordinates, actor, event type, fatalities), 1990–2024 |
| `bronze.acled_weekly_aggregated` | ACLED | Country-week rollup of event counts and fatalities |
| `bronze.imf_weo_raw` | IMF World Economic Outlook | Debt-to-GDP, fiscal balance, inflation, current account, 1990–2024 |
| `bronze.fsi_raw` | Fund for Peace FSI | Composite and component fragility scores per country per year |

### Silver layer — reconciled, typed, time-aware

| Table | Contents |
|---|---|
| `silver.dim_country` | ISO3 code, country name, region, bloc flags |
| `silver.dim_bloc_membership` | Country–bloc mapping with primary analytical bloc flag |
| `silver.fact_macro_annual` | GDP, trade openness, debt ratios, and fiscal indicators per country per year |
| `silver.fact_trade_partner_annual` | Bilateral export and import totals per reporter–partner–year |
| `silver.trade_partner_concentration_annual` | Herfindahl-Hirschman Index (HHI) of partner concentration per country per year |
| `silver.fact_acled_events` | Cleaned and typed individual conflict events |
| `silver.fact_acled_weekly` | Country-week event and fatality aggregates |
| `silver.fact_acled_country_year` | Country-year conflict summary (events, fatalities, fatalities per million) |
| `silver.fact_fsi_annual` | Normalised FSI total and component scores per country per year |

### Gold layer — pre-aggregated mart tables

#### Core observatory tables (notebook 14)

| Table | Contents |
|---|---|
| `gold.country_year_observatory` | Full joined country–year record: trade, macro, conflict, and fragility |
| `gold.country_latest_snapshot` | Single-row-per-country snapshot at the latest available year |
| `gold.bloc_year_observatory` | Bloc-level aggregated view per year |
| `gold.bloc_latest_snapshot` | Single-row-per-bloc snapshot at latest year |

#### Dashboard panel marts (notebook 15)

| Table | Rows | Powers |
|---|---|---|
| `gold.dashboard_country_timeseries` | 735 | Overview map, economic profile, growth chart |
| `gold.dashboard_top_trade_partners` | 11,025 | Top 10 partners bar chart, two-partner comparison |
| `gold.dashboard_conflict_hotspots` | 284 | Conflict events & fatalities panel |
| `gold.dashboard_fragility_components` | 21 | FSI fragility component breakdown |
| `gold.dashboard_bloc_comparison` | 71 | Regional integration and HHI trend charts |

---

## Data sources

| Source | What it provides | Coverage | Access |
|---|---|---|---|
| World Bank Data360 | GDP and macro indicators | 1990–2024 | Public |
| IMF IMTS / DOTS | Annual bilateral goods exports and imports by partner | 1990–2024 | Public API |
| ACLED | Conflict events, fatalities, actor types | 1990–2024 | Research key |
| IMF WEO | Debt-to-GDP, fiscal balance, inflation, current account | 1990–2024 | Public CSV |
| Fund for Peace FSI | Composite and 12-component fragility scores | 2006–2024 | Public CSV |

IMF aggregate partner groups (e.g. `G001`, `W00`) are excluded from all
partner panels. Only named country counterparts appear in the dashboard.

---

## Countries covered

**CEMAC (6):** Cameroon, Central African Republic, Chad, Congo, Equatorial Guinea, Gabon

**ECOWAS (15):** Benin, Burkina Faso, Cabo Verde, Côte d'Ivoire, Gambia, Ghana, Guinea, Guinea-Bissau, Liberia, Mali, Niger, Nigeria, Senegal, Sierra Leone, Togo

**AES (3, subset of ECOWAS):** Mali, Burkina Faso, Niger

---

## Repository structure

```text
.
├── 00_setup_catalog.ipynb              Unity Catalog and schema initialisation
├── 01_network_test.ipynb               API reachability checks from Databricks
├── 02_bronze_data360_first_pull.ipynb  World Bank Data360 → bronze.data360_raw
├── 04_bronze_imts_extract.ipynb        IMF IMTS bilateral trade → bronze.imts_raw
├── 05_bronze_acled_extract.ipynb       ACLED events → bronze.acled_*
├── 06_bronze_imf_weo_extract.ipynb     IMF WEO → bronze.imf_weo_raw
├── 07_bronze_fsi_extract.ipynb         FSI scores → bronze.fsi_raw
├── 08_silver_country_dimensions.ipynb  silver.dim_country, silver.dim_bloc_membership
├── 09_silver_macro_annual.ipynb        silver.fact_macro_annual
├── 10_silver_trade_partner_annual.ipynb silver.fact_trade_partner_annual, silver.trade_partner_concentration_annual
├── 11_silver_acled_conflict.ipynb      silver.fact_acled_events/weekly/country_year
├── 12_silver_fsi_annual.ipynb          silver.fact_fsi_annual
├── 13_audit_cross_source_coverage.ipynb Cross-source coverage and quality audit
├── 14_gold_dashboard_core_marts.ipynb  gold.country_year/latest, gold.bloc_year/latest
├── 15_gold_dashboard_panel_marts.ipynb gold.dashboard_* (five panel marts)
│
├── scripts/
│   ├── export_static.py                Queries gold tables → static/data/*.json
│   └── validate_dashboard_contract.py  Validates row counts and schema
│
├── static/                             GitHub Pages build target
│   ├── index.html                      Dashboard shell (static version)
│   ├── js/app_static.js                Client-side rendering (reads local JSON)
│   └── data/                           Exported JSON files (written by CI)
│
├── public/                             Shared frontend assets
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── app.js                      Rendering logic (shared with static build)
│       └── charts.js                   Chart drawing helpers (Plotly wrappers)
│
├── extraction/                         Local extraction fallback scripts
│   └── extract/
│       ├── acled_extract.py
│       ├── fsi_extract.py
│       ├── imf_dots_extract.py
│       └── imf_weo_extract.py
│
├── data/raw/                           Local raw data landing zone
│   ├── acled/
│   ├── imts/
│   ├── weo/
│   └── fsi/
│
├── docs/decisions/
│   ├── ADR-001-extraction-architecture.md
│   └── ADR-002-bilateral-trade-source.md
│
├── .github/workflows/deploy-pages.yml  CI/CD: export + deploy to GitHub Pages
├── databricks.yml                      Databricks Asset Bundle config
└── requirements.txt
```

---

## Local development

Clone the repo and activate the virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To preview the dashboard locally against live Databricks data, export the
gold tables to JSON and serve the static directory:

```bash
export DATABRICKS_HOST="dbc-xxxx.cloud.databricks.com"
export DATABRICKS_HTTP_PATH="/sql/1.0/warehouses/xxxx"
export DATABRICKS_TOKEN="..."
export DATABRICKS_CATALOG="cemac_ecowas_aes_trade"   # optional, this is the default

python scripts/export_static.py
python -m http.server 8080 --directory static
# open http://localhost:8080
```

---

## Author

Nathan Thomas Gatse · International Business and Data Science, Protection &
Security · Thomas More University of Applied Sciences, Belgium.

This is the second project in a planned series of African regional data
infrastructure work. The first project, focused on digital readiness
indicators across CEMAC, demonstrated a relational data pipeline. This
project extends into lakehouse architecture with multi-source reconciliation,
a medallion Delta Lake pipeline, and a fully static public dashboard.
