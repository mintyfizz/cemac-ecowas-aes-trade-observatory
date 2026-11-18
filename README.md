# CEMAC-ECOWAS-AES Trade Observatory

[![Deploy static dashboard to GitHub Pages](https://github.com/mintyfizz/cemac-ecowas-aes-trade-observatory/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/mintyfizz/cemac-ecowas-aes-trade-observatory/actions/workflows/deploy-pages.yml)

A Databricks lakehouse and static public dashboard for tracking trade flows,
partner dependence, macro-fiscal exposure, conflict, and fragility across
CEMAC, ECOWAS, and the Alliance of Sahel States (AES).

**Live dashboard:** <https://mintyfizz.github.io/cemac-ecowas-aes-trade-observatory/>

The public dashboard is hosted on GitHub Pages. There is no public backend and
no runtime secret in the browser. The site reads JSON files under `static/data/`,
rebuilt deterministically from preserved raw source snapshots
(`scripts/offline_rebuild.py`) and checked by exact-identity contract tests
before deployment.

> **November 2026 data revision.** Trade totals in the May 2026 export were
> inflated about 4.6–5.1× (IMF aggregate areas summed as partners), conflict
> rates were 10⁶ too small, and hotspots were duplicated for the AES members.
> UN Comtrade product values are quarantined pending revalidation. See
> [docs/methodology.md](docs/methodology.md) for the defects, fixes and rules.

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
| Overview | For a bloc or country and year: goods trade (IMF World), openness, top partner share, partner concentration, GDP, conflict fatalities per million, and observed IMF WEO indicators with units. Bloc figures state how many members report. |
| Map | One selected metric for all 21 countries in the selected year. A keyboard-accessible Country menu offers the same drill-down. |
| Trade dependence | Top named partners (share of World trade), top-partner and top-3 shares over time, HHI over named partners, and named-partner coverage of the World total. |
| Trade exposure | Openness trend, goods trade indexed to 1990 for a fixed member cohort, and the exports/imports/balance profile. |
| Product structure | UN Comtrade HS2 data, quarantined with the reason and the revalidation steps. |
| Context (latest snapshot) | ACLED hotspots for 2022–2024 combined, and the latest loaded Fund for Peace FSI edition with its year. Uses current membership, not the selected year. |
| Sources and methods | Source periods, snapshot dates and hashes, membership rule, definitions and flagged source values. |

The URL keeps `bloc`, `year`, `country` and `metric`, so views are shareable and
back/forward navigation works.

## Interpretation Rules

These are enforced by `scripts/check_static_contract.py`. Full definitions are
in [docs/methodology.md](docs/methodology.md).

- **Totals are IMF World rows.** Partner rows are named economies from a
  reviewed codelist. Aggregates are excluded, and "not specified" areas count as
  unallocated. World minus the named-partner sum is shown as a signed difference.
- **One HHI definition.** HHI is computed over the full named-partner
  distribution before any top-N cut. Bloc HHI is computed at bloc grain. It is
  conditional on named-partner coverage, and no risk verdicts are attached.
- **Analytical AES cohort.** Burkina Faso, Mali and Niger are grouped as AES from
  the AES confederation treaty (6 July 2024). Their legal ECOWAS exit took effect
  on 29 January 2025. This is labelled in the UI and is not a legal-membership
  claim.
- **No look-ahead.** FSI values appear only for their own edition year. The
  latest edition is shown separately with its date.
- **Rates are exact identities.** rate = count / population in millions for the
  same year. Population is stored in persons.
- **Missing stays missing.** Nulls are never rendered as zero. ACLED years before
  a country's coverage starts are null.
- **Quarantine over invention.** Product values that cannot be validated are not
  published.

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
| UN Comtrade | HS2 product trade structure | Quarantined since Nov 2026: earlier values summed breakdown slices. Revalidation must match same-provider TOTALs. |
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
  -> node --check static/js/*.js
  -> scripts/check_static_contract.py        (exact identities)
  -> scripts/test_contract_mutations.py      (known defects must be caught)
  -> upload static/ to GitHub Pages
```

Other branches run the same checks without deploying
(`.github/workflows/checks.yml`). The Databricks export step is out of the
deploy path until the corrected notebooks have been rerun (see
docs/methodology.md).

## Local Preview

```bash
python -m http.server 8080 --directory static
```

Open <http://localhost:8080>.

## Rebuilding the Data

From preserved raw extractor snapshots, with no network and no Databricks:

```bash
python scripts/offline_rebuild.py --raw-dir <raw snapshot dir>
python scripts/check_static_contract.py --raw-dir <raw snapshot dir>
python scripts/test_contract_mutations.py
```

The same inputs produce byte-identical outputs; the contract check verifies
this.

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
│   ├── methodology.md
│   ├── dashboard_data_audit.md   (superseded May 2026 audit)
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
├── config/
│   ├── imf_cl_imts_country_1.0.0.tsv
│   ├── imts_counterpart_roles.csv
│   └── iso3166_alpha3.csv
├── scripts/
│   ├── observatory_definitions.py
│   ├── offline_rebuild.py
│   ├── check_static_contract.py
│   ├── test_contract_mutations.py
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
python scripts/check_static_contract.py
python scripts/test_contract_mutations.py
```

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
