# CEMAC–ECOWAS–AES Trade Observatory

A Databricks lakehouse platform tracking trade flows, partner dependencies,
and structural economic vulnerability across CEMAC, ECOWAS, and the
Alliance of Sahel States (AES). Covers 21 countries from 1990 to today.

A public Streamlit dashboard (link coming) will surface the findings.
The pipeline lives in this repository and is built on Databricks Free Edition.

## Status

**Week 1 of 12 — Foundation complete.**

- Databricks workspace provisioned
- Unity Catalog set up with bronze, silver, gold, audit schemas
- First bronze Delta table populated with World Bank GDP data
  for the six CEMAC countries, 1990 to 2024
- IMF IMTS bilateral trade extraction notebook added for all partners
- ACLED event and weekly aggregate extraction notebook added
- IMF WEO fiscal and macro context extraction added
- Fragile States Index extraction added

Project under active development. Status updates will follow weekly.

## Architecture

The pipeline follows a medallion pattern inside a single Unity Catalog
catalog (`cemac_ecowas_aes_trade`):

| Tier   | Role                                                | Tables so far                |
| ------ | --------------------------------------------------- | ---------------------------- |
| Bronze | Raw API responses, append-only, replayable          | `bronze.data360_raw`, `bronze.bilateral_trade_raw`, `bronze.acled_events_historical`, `bronze.acled_weekly_aggregated`, `bronze.imf_weo_raw`, `bronze.fsi_raw` |
| Silver | Reconciled, typed, time-aware facts and dimensions  | (week 3-4)                   |
| Gold   | Pre-aggregated marts, one per dashboard panel       | (week 6-7)                   |
| Audit  | Operational metadata, pipeline health, data quality | (week 7)                     |

Five external sources will feed bronze by end of week 2: World Bank
Data360, IMF IMTS, ACLED, IMF WEO, and the Fragile States Index. Sources
that Databricks Free Edition serverless compute can reach directly are
extracted in Databricks notebooks. Sources blocked by serverless DNS or
egress restrictions can use a local extraction fallback and then land raw
files in Databricks.

## Data sources

| Source               | What it provides                              | Access     |
| -------------------- | --------------------------------------------- | ---------- |
| World Bank Data360   | Macroeconomic indicators, bilateral trade     | Public     |
| IMF IMTS             | Annual goods exports/imports by partner       | Public API |
| ACLED                | Conflict events, country-week and event-level | Research   |
| IMF WEO              | Debt-to-GDP and fiscal context                | Public CSV |
| Fragile States Index | Composite institutional fragility scores      | Public CSV |

## Repository structure

```text
.
├── 00_setup_catalog.ipynb                 Unity Catalog initialization
├── 01_network_test.ipynb                  API access verification
├── 02_bronze_data360_first_pull.ipynb     First bronze table
├── 04_bronze_imts_extract.ipynb           IMF IMTS bilateral trade totals
├── 05_bronze_acled_extract.ipynb          ACLED events and weekly aggregates
├── 06_bronze_imf_weo_extract.ipynb        IMF WEO fiscal and macro context
├── 07_bronze_fsi_extract.ipynb            Fragile States Index scores
├── docs/
│   └── decisions/
│       ├── ADR-001-extraction-architecture.md
│       └── ADR-002-bilateral-trade-source.md
└── README.md
```

More notebooks land here through weeks 2-7 as the bronze, silver, gold,
and dashboard layers are built out.

## Author

Nathan Thomas Gatse · International Business and Data Science, Protection &
Security · Thomas More University of Applied Sciences, Belgium.

This is the second project in a planned series of African regional data
infrastructure work. The first project, focused on digital readiness
indicators across CEMAC, demonstrated a relational data pipeline. This
project extends into lakehouse architecture with multi-source
reconciliation and a custom dashboard.
