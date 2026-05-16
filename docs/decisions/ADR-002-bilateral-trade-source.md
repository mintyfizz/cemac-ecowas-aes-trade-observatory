# ADR-002: Bilateral trade source

## Status

Accepted, May 16, 2026.

## Context

The project needs annual bilateral trade totals for all partners of each
CEMAC and ECOWAS country. The immediate analytical need is partner
dependency: which countries each reporter exports to and imports from, and
how concentrated those relationships are over time.

UN Comtrade was the original candidate because it also provides product-level
HS detail. In practice, it introduced unnecessary friction for the current
requirement:

- Databricks Free Edition serverless failed DNS resolution for
  `comtradeapi.un.org`.
- The local fallback required a subscription key and hit authentication or
  quota failures during testing.
- Week 2 needs annual total partner flows, not product-level HS rows.

IMF IMTS provides annual goods exports and imports by partner country through
a public SDMX API. It does not require an API key and exposes the reporter,
partner, year, flow, valuation basis, and trade value needed for the partner
dependency layer.

## Decision

Use IMF IMTS for the active bronze bilateral trade extractor.

The implementation lives in `04_bronze_imts_extract.ipynb` and writes
`bronze.bilateral_trade_raw`.

The notebook extracts:

- Exports of goods, FOB, US dollar (`XG_FOB_USD`)
- Imports of goods, CIF, US dollar (`MG_CIF_USD`)
- All available partner rows per reporter
- The 21 project reporters
- Annual observations from 2010 through 2023

UN Comtrade is removed from the active Week 2 path.

## Consequences

**Positive:**
- No Comtrade API key is required.
- No Comtrade daily quota blocks the Week 2 extraction.
- The extraction can run directly inside Databricks as a normal bronze
  notebook.
- The resulting data answers the immediate all-partners trade dependency
  question.

**Negative / risks:**
- IMF IMTS is total goods trade only. It does not provide HS product-level
  product composition.
- Product-level analysis must be handled later by a separate decision, likely
  using CEPII BACI or a repaired Comtrade path.

**Reversibility:**
- If product-level HS analysis becomes necessary before the dashboard ships,
  a separate bronze source can be added without changing
  `bronze.bilateral_trade_raw`.
