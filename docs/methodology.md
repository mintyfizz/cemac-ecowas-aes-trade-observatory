# Methodology and data contract

This document describes how every number on the dashboard is produced. The
definitions live in code in `scripts/observatory_definitions.py`. The offline
builder (`scripts/offline_rebuild.py`) and the Databricks notebooks implement
the same rules, and `scripts/check_static_contract.py` enforces them.

## November 2026 data revision

A review in November 2026 found that the published dashboard (main @ 0699de1,
data refreshed 26 May 2026) was wrong in three ways.

| Defect | Effect on the published site | Fix |
| --- | --- | --- |
| IMF IMTS aggregate counterparts (G001 World, G110, G200, GX*, TX*, …) were summed as if they were trading partners. Notebook 10 only recognised `W00`, which is a UN Comtrade code. | Totals inflated about 4.6–5.1×. This fed into openness, partner shares, HHI, the growth index and the product coverage gates. "Main partner" was `G001` in all 735 rows. | Headline totals come from the World (G001) row. Partner rows are named economies classified by a reviewed codelist. |
| `population` was stored as persons × 10⁶. | Every stored per-million rate was 10⁶ too small. Country and map views showed about 0. | Population is stored in persons, and rate = count / population_millions. |
| Hotspots were grouped by bloc label. | Burkina Faso, Mali and Niger admin1 areas appeared twice (ECOWAS 2022–23, AES 2024) with different windows. | One row per country × admin1 over a fixed window. |

UN Comtrade HS2 product values were also found to be summed across customs,
mode-of-transport and second-partner breakdown slices. For example, Ghana's 2023
HS2 exports summed to $67.5B, while the same-provider TOTAL is $16.8B. Those
values are **quarantined** (see below).

## Sources and snapshots

The static data is rebuilt from preserved raw extractor snapshots. File hashes,
extraction dates and record counts are written to `static/data/provenance.json`.

| Source | File | Notes |
| --- | --- | --- |
| IMF IMTS | `cemac_ecowas_imts_1990_2024.jsonl` | Goods exports (FOB) and imports (CIF), every counterpart code. |
| IMF WEO | `cemac_ecowas_weo_1990_2024.jsonl` | The extractor applied the SDMX `SCALE`, so NGDPD is in USD and LP is in persons. The formal WEO release vintage is not recorded in the snapshot; the country update dates are. |
| ACLED | `cemac_ecowas_acled_1990_2024.jsonl` | One envelope per country-year query. Event IDs are unique. |
| Fund for Peace FSI | `cemac_ecowas_fsi_1990_2024.jsonl` | Editions 2006–2023. FSI 2024 is not in the snapshot. |

## Definitions

**Membership.** Annual rows use the analytical bloc valid on 31 December of the
year.
- Burkina Faso, Mali and Niger are an **analytical** AES cohort from the AES
  confederation treaty (6 July 2024). Their legal ECOWAS withdrawal took effect
  on 29 January 2025.
- The dashboard labels AES and post-split ECOWAS as analytical cohorts. It makes
  no legal-membership claim.

**Trade.**
- Exports, imports and total goods trade are the IMF World (`G001`) rows.
- Partner rows are named economies only. Every counterpart code is classified in
  `config/imts_counterpart_roles.csv`, using the codelist
  IMF.STA:CL_IMTS_COUNTRY 1.0.0 (`config/imf_cl_imts_country_1.0.0.tsv`) with
  these roles:
  - `world`
  - `named_partner`: includes former or combined economies such as SUN, YUG and
    TX126 Belgium-Luxembourg
  - `aggregate`: excluded
  - `unallocated`: the "not specified" areas
- The build fails on any code that is not in the table.
- A partner's share is its trade divided by World total trade.
- World minus the named-partner sum is reported as a signed difference. It is
  not called "unallocated trade", because it can be negative.

**Concentration (HHI).**
- HHI = Σ sᵢ² over the full named-partner distribution, with shares normalised by
  the named sum, computed before any top-N cut.
- It is conditional on named-partner coverage, which is shown next to it.
- Bloc HHI is computed at bloc grain: members' named partners are aggregated
  first, and the result includes trade between members.
- No "diversified" or "high risk" verdicts are attached.

**Bloc figures.**
- Sums run over the members that report; each figure states *n/m* reporting.
- Openness uses the same members in the numerator and denominator.
- Ratios (debt, growth, inflation, fiscal and current-account balances) are
  GDP-weighted.
- Year-on-year changes are shown only when membership is unchanged.

**Conflict (ACLED).**
- Violent events = Battles, Explosions/Remote violence, Violence against
  civilians and Riots.
- A country is covered from the first year ACLED returned any event for it.
  Covered years with no events are 0; earlier years are null. Four country-years
  are covered with no events: COG 2008, COG 2011, GAB 2007 and GNQ 1999.
- Rate = count / population in millions for the same year.
- Hotspots cover 2022–2024 combined and are ranked by violent events, then
  fatalities, then name.
- No admin1 per-capita rates are published, because there is no admin1
  population source.

**Fragility (FSI).**
- A value appears only for the edition year it belongs to; there is no
  carry-forward into other years.
- The context panel shows each country's latest loaded edition with its year.
- Pillars are sums of the published indicators, which are rounded to 0.1. One
  source row (Mali 2015) has indicators summing 0.2 above the published total;
  it is disclosed in provenance.

**Products (UN Comtrade).** Quarantined.
- `static/data/product_trade_hs2.json` carries no values, only the reason and the
  revalidation steps.
- The extractor now pins partner2 = World, customs = C00 and mode = 0.
- The loader rejects unpinned slices and duplicate keys.
- Revalidation must reconcile HS2 sums against UN Comtrade TOTAL with identical
  dimensions; IMF IMTS is only a cross-source warning.

## Known source values that are kept but flagged

- Openness above 200% of GDP: Gambia 2023 (IMF World exports of $2.83B, largely
  attributed to Kazakhstan). This is shown as published.
- 183 country-years where named-partner trade differs from the World total by
  more than 2% (for example Cabo Verde 2015, at 25%). These are visible in the
  coverage chart.

## Reproduce

```bash
python scripts/offline_rebuild.py --raw-dir <raw snapshot dir>
python scripts/check_static_contract.py --raw-dir <raw snapshot dir>   # identities + raw recount + byte reproducibility
python scripts/test_contract_mutations.py                              # proves the known defects are caught
python -m http.server 8080 --directory static
```

## Databricks notebooks

Notebooks 09, 10, 11, 14 and 15 carry the same fixes:
- population identity assertion
- counterpart roles and the World headline
- duplicate rejection
- Comtrade partner override disabled
- rates from population_millions
- named-only ranking before top-N
- fixed hotspot window without bloc grouping
- bloc-grain HHI and same-year FSI counts

They have **not yet been rerun**. Until they are, `scripts/export_static.py` is
disabled, and the deploy workflow publishes the committed, contract-checked data
instead of exporting from Databricks. `scripts/rebuild_gold_dashboard.py` is
serverless-only, with no classic-cluster fallback, and never prints credential
fragments.

Before re-enabling the Databricks export path:
1. Rerun the notebooks.
2. Map the gold output to the static schema.
3. Require `check_static_contract.py --raw-dir` to pass.
