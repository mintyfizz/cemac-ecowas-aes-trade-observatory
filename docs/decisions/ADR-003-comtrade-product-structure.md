# ADR-003: Comtrade product-structure scope

## Status

Accepted, May 26, 2026.

## Context

ADR-002 removed UN Comtrade from the active partner-dependency path because
Databricks serverless could not resolve `comtradeapi.un.org`, and the local
fallback carried API key and quota friction. IMF IMTS/DOTS remains the
primary source for annual bilateral partner flows.

The dashboard also needs a product-structure view: top HS2 export/import
sectors by reporter and year. That question does not require partner-level
bilateral rows. It can be answered from national-total Comtrade rows where
`partner_iso3 = 'W00'`.

## Decision

Reintroduce UN Comtrade only for product structure, using a local W00
national-total extract.

Ownership is split by grain:

- Notebook 10b owns bilateral Comtrade tables for partner-dependency:
  `silver.comtrade_hs6_normalized`, `silver.comtrade_partner_annual`, and
  `silver.comtrade_country_year_coverage`.
- `scripts/load_comtrade_silver.py` owns product-structure tables from W00
  national totals: `silver.comtrade_hs2_annual_w00` and
  `silver.comtrade_product_coverage`.
- `gold.product_trade_hs2` reads only the product-structure tables and
  exposes HS2 rows with good product coverage.

Notebook 10 then keeps IMF IMTS/DOTS as the baseline partner source and
uses Comtrade bilateral data only when `silver.comtrade_country_year_coverage`
marks the reporter-year as `good`.

## Consequences

**Positive:**

- Product charts can show HS2 composition without requiring a full bilateral
  partner extract.
- The partner-dependency layer keeps a defensible IMTS-primary contract.
- W00 product coverage can be audited separately from bilateral coverage.
- The table collision between bilateral and product Comtrade writers is
  removed.

**Negative / risks:**

- Bloc-level product composition is only representative when reporter and
  value coverage are sufficient.
- The local W00 extract remains a separate operational path from Databricks
  notebook execution.

**Reversibility:**

- If a complete bilateral Comtrade path becomes reliable later, it can feed
  notebook 10 through `silver.comtrade_partner_annual` without changing the
  W00 product tables.
