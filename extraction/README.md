# Local extraction fallback

UN Comtrade was tested and removed from the active Week 2 path because it
combined three operational problems: Databricks Free Edition DNS resolution
failed for `comtradeapi.un.org`, the local API key path returned repeated
authentication/quota problems, and the current Week 2 requirement only needs
annual total trade by partner rather than HS product-level detail.

The active bilateral trade source is now IMF IMTS, implemented directly in
`04_bronze_imts_extract.ipynb`. It writes `bronze.bilateral_trade_raw` with
all available partner rows for the 21 project countries.

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
