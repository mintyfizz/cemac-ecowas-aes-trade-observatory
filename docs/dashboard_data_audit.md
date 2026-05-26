# Dashboard Data Audit

Generated: 2026-05-26 08:36:27 UTC

Status: **WARN**

This audit covers the GitHub Pages static dashboard. The browser reads only
local files under `static/data`; Databricks remains the
source of truth for those exported files.

## Failures

- None

## Warnings

- FSI is latest-available coverage, not true 2024 coverage.
- No representative HS2 export year for AES meets both 50% coverage thresholds; latest checked coverage is 1/3 reporters and 31.5% of flow value.
- No representative HS2 import year for AES meets both 50% coverage thresholds; latest checked coverage is 1/3 reporters and 16.2% of flow value.
- No representative HS2 export year for CEMAC meets both 50% coverage thresholds; latest checked coverage is 1/6 reporters and 0.1% of flow value.
- No representative HS2 import year for CEMAC meets both 50% coverage thresholds; latest checked coverage is 1/6 reporters and 0.8% of flow value.
- No representative HS2 export year for ECOWAS meets both 50% coverage thresholds; latest checked coverage is 4/12 reporters and 3.9% of flow value.
- No representative HS2 import year for ECOWAS meets both 50% coverage thresholds; latest checked coverage is 4/12 reporters and 4.1% of flow value.

## Notes

- country_timeseries formula checks passed.
- Latest available FSI year in export: 2023.
- product_trade_hs2 coverage: 48,901 rows, 12 reporters, years 1993-2024.
- AES analytical split coverage in country_timeseries: 2024-2024.

## Static Export Coverage

| Dataset | Source table | Rows | Years | Countries/reporters | Blocs |
| --- | --- | ---: | --- | ---: | ---: |
| `country_timeseries.json` | `gold.dashboard_country_timeseries` | 735 | 1990-2024 | 21 | 3 |
| `top_trade_partners.json` | `gold.dashboard_top_trade_partners` | 3,481 | 1990-2024 | 21 | 3 |
| `conflict_hotspots.json` | `gold.dashboard_conflict_hotspots` | 284 | n/a | 21 | 3 |
| `fragility_components.json` | `gold.dashboard_fragility_components` | 21 | n/a | 21 | 3 |
| `bloc_comparison.json` | `gold.dashboard_bloc_comparison` | 71 | 1990-2024 | 0 | 3 |
| `product_trade_hs2.json` | `gold.product_trade_hs2` | 48,901 | 1993-2024 | 12 | 0 |

## Live Databricks Counts

- `gold.dashboard_country_timeseries`: 735 rows
- `gold.dashboard_top_trade_partners`: 11,025 rows
- `gold.dashboard_conflict_hotspots`: 284 rows
- `gold.dashboard_fragility_components`: 21 rows
- `gold.dashboard_bloc_comparison`: 71 rows
- `gold.product_trade_hs2`: 53,242 rows

## Panel To Source Mapping

| Panel | Data source | Interpretation rule |
| --- | --- | --- |
| Overview cards | `country_timeseries, top_trade_partners, fragility_components` | Selected bloc/country and selected year. |
| Map | `country_timeseries` | Selected year only; metric selector changes the rendered value. |
| Top trading partners | `top_trade_partners` | ISO3 partners only; aggregate rows are filtered out of displayed outputs. |
| Partner dependence diagnostics | `top_trade_partners, country_timeseries` | Top partner and top-3 shares use the full total trade denominator. |
| Partner concentration | `country_timeseries, bloc_comparison` | HHI trend; selected country gets its own history. |
| Trade openness trend | `bloc_comparison` | Exports plus imports as percent of GDP. |
| Trade growth indexed to 1990 | `country_timeseries` | Total trade rebased to 1990 = 100; nulls remain gaps. |
| Trade exposure profile | `country_timeseries` | Exports, imports, and balance as percent of GDP. |
| Product trade structure | `product_trade_hs2` | Selected year only; empty state when selected-year HS2 coverage is absent. |
| Conflict | `conflict_hotspots` | Bloc view shows countries; country drilldown shows admin1 hotspots. |
| Fragility | `fragility_components` | Latest available FSI components, not true 2024 coverage when 2024 source is absent. |
| Macro-fiscal diagnostics | `country_timeseries` | Normalized dashboard diagnostic; not a credit rating or debt sustainability assessment. |
| Pipeline health | `all exported static JSON` | Row counts and coverage metadata from exported datasets. |

## Formula Checks

Validated where source columns are available:

- `total_trade = exports + imports`
- `trade_balance = exports - imports`
- `trade_openness_pct_gdp = total_trade / GDP * 100`
- `exports_pct_gdp = exports / GDP * 100`
- `imports_pct_gdp = imports / GDP * 100`
- `gdp_per_capita = GDP billions / population millions * 1000`
- `total_trade_partner_hhi` is constrained to `[0, 1]`

Missing inputs remain null. They must not be rendered as zero.

## Known Gaps And Interpretation Notes

- FSI should be read as latest-available coverage. If 2024 FSI is missing,
  the dashboard must not imply a true 2024 FSI release.
- ACLED hotspot panels use the latest loaded 3-year window, not necessarily a
  single selected calendar year.
- Product sectors use `gold.product_trade_hs2` only where selected-year HS2
  coverage exists. Bloc-level product composition requires at least 50%
  reporter coverage and 50% value coverage; otherwise the dashboard shows an
  insufficient-coverage state.
- Macro-fiscal diagnostics are normalized dashboard indicators, not an official
  credit rating, sovereign rating, or debt sustainability assessment.
- Partner panels filter non-ISO aggregate partner rows from displayed outputs.
  Static exports should contain ISO3 partner rows only.
- Bloc-level year-over-year card deltas are only meaningful when the selected
  bloc membership set is unchanged from the prior year. The dashboard suppresses
  bloc deltas across analytical scope breaks such as the recent AES split.

## Fix Priorities

1. Keep `static/index.html`, `static/css/styles.css`, `static/js/charts.js`,
   and `static/js/app_static.js` aligned before every GitHub Pages deployment.
2. Re-run `scripts/export_static.py` after gold tables change.
3. Re-run this audit before publishing and investigate any failure.
