# Local extraction fallback

UN Comtrade was tested and removed from the active Week 2
partner-dependency path because it combined three operational problems:
Databricks Free Edition DNS resolution failed for `comtradeapi.un.org`, the
local API key path returned repeated authentication/quota problems, and the
current Week 2 partner requirement only needs annual total trade by partner.
Comtrade later returned only for product-structure analysis through local
W00 national-total rows.

The active bilateral trade source is now IMF IMTS, implemented directly in
`04_bronze_imts_extract.ipynb`. It writes `bronze.imts_raw` with all
available partner rows for the 21 project countries.

## Trading Economics public-page fallback

Trading Economics also publishes visible country trade partner tables, for
example `exports-by-country` and `imports-by-country`. The extractor
`extraction/extract/tradingeconomics_trade_page_extract.py` uses a
`tedata`-style public-page scrape: it requests those pages, parses the HTML
table shown in the browser, and writes the rows to JSONL.

This is intentionally a diagnostic fallback, not the canonical dashboard
source. The public pages expose latest available partner-table rows, not a
complete 1990-2024 historical panel. Use the IMF IMTS marts for production
partner-dependency charts unless a later source decision promotes Trading
Economics API data to the core pipeline.

Run a single-country check from the repository root:

```bash
python3 extraction/extract/tradingeconomics_trade_page_extract.py \
  --reporter-codes COG \
  --flows export import \
  --out data/raw/tradingeconomics/cog_te_trade_pages_latest.jsonl
```

Run all project countries:

```bash
python3 extraction/extract/tradingeconomics_trade_page_extract.py \
  --all-cemac-ecowas \
  --out data/raw/tradingeconomics/cemac_ecowas_te_trade_pages_latest.jsonl
```

Each JSONL line is one reporter-flow pair. The `payload` includes the partner
name, raw page value, parsed USD value, reported year, and a `Total` row marked
with `is_total=true`. Missing values remain `null`. If Trading Economics shows
a generic country trade table instead of the partner-by-country table, the
extractor writes an explicit `status="no_partner_table"` record with an empty
payload so the coverage gap is visible.

## ACLED

Databricks Free Edition serverless also failed DNS resolution for
`acleddata.com`. ACLED therefore uses a local extractor plus Databricks
Volume ingestion.

Run locally from the repository root:

```bash
python3 extraction/extract/acled_extract.py \
  --all-cemac-ecowas \
  --start-year 2010 --end-year 2026 \
  --out data/raw/acled/cemac_ecowas_acled_2010_2026.jsonl
```

The script first checks `ACLED_ACCESS_TOKEN` in the local environment or
`.env`. If no token is present, it reads `ACLED_USERNAME` and
`ACLED_PASSWORD`. If either username/password value is missing, it prompts
interactively so the password does not go into shell history.

If password OAuth returns HTTP 403, confirm the account can log in at
`https://acleddata.com`, that the account is activated, and that it has API
access. You can also generate an access token manually with ACLED's OAuth
request and store it in `.env` as `ACLED_ACCESS_TOKEN=...`; `.env` is ignored
by Git.

Upload the JSONL to Databricks:

```bash
databricks fs mkdirs dbfs:/Volumes/cemac_ecowas_aes_trade/bronze/raw_landing/acled -p cemac-project
databricks fs cp data/raw/acled/cemac_ecowas_acled_2010_2026.jsonl \
  dbfs:/Volumes/cemac_ecowas_aes_trade/bronze/raw_landing/acled/cemac_ecowas_acled_2010_2026.jsonl \
  --overwrite -p cemac-project
```

Then run `05_bronze_acled_extract.ipynb` in Databricks. It writes
`bronze.acled_events_historical` and `bronze.acled_weekly_aggregated`.

## IMF WEO

IMF World Economic Outlook fiscal and macro context is extracted locally
from the IMF SDMX API, then uploaded to Databricks for bronze ingestion.

Run locally from the repository root:

```bash
python3 extraction/extract/imf_weo_extract.py \
  --all-cemac-ecowas \
  --start-year 1990 --end-year 2024 \
  --out data/raw/weo/cemac_ecowas_weo_1990_2024.jsonl
```

Upload the JSONL to Databricks:

```bash
databricks fs mkdirs dbfs:/Volumes/cemac_ecowas_aes_trade/bronze/raw_landing/weo -p cemac-project
databricks fs cp data/raw/weo/cemac_ecowas_weo_1990_2024.jsonl \
  dbfs:/Volumes/cemac_ecowas_aes_trade/bronze/raw_landing/weo/cemac_ecowas_weo_1990_2024.jsonl \
  --overwrite -p cemac-project
```

Then run `06_bronze_imf_weo_extract.ipynb` in Databricks. It writes
`bronze.imf_weo_raw`.

## Fragile States Index

Fragile States Index scores are extracted from the official annual Excel
downloads published by the Fund for Peace. The official download page
currently exposes 2006-2023 files; wider requested ranges are allowed, but
only available official years are written.

Run locally from the repository root:

```bash
python3 extraction/extract/fsi_extract.py \
  --all-cemac-ecowas \
  --start-year 1990 --end-year 2024 \
  --out data/raw/fsi/cemac_ecowas_fsi_1990_2024.jsonl
```

Upload the JSONL to Databricks:

```bash
databricks fs mkdirs dbfs:/Volumes/cemac_ecowas_aes_trade/bronze/raw_landing/fsi -p cemac-project
databricks fs cp data/raw/fsi/cemac_ecowas_fsi_1990_2024.jsonl \
  dbfs:/Volumes/cemac_ecowas_aes_trade/bronze/raw_landing/fsi/cemac_ecowas_fsi_1990_2024.jsonl \
  --overwrite -p cemac-project
```

Then run `07_bronze_fsi_extract.ipynb` in Databricks. It writes
`bronze.fsi_raw`.
