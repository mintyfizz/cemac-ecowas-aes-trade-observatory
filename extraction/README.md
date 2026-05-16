# Local extraction fallback

There are no active local fallback extractors at the moment.

UN Comtrade was tested and removed from the active Week 2 path because it
combined three operational problems: Databricks Free Edition DNS resolution
failed for `comtradeapi.un.org`, the local API key path returned repeated
authentication/quota problems, and the current Week 2 requirement only needs
annual total trade by partner rather than HS product-level detail.

The active bilateral trade source is now IMF IMTS, implemented directly in
`04_bronze_imts_extract.ipynb`. It writes `bronze.bilateral_trade_raw` with
all available partner rows for the 21 project countries.

This directory is kept for future sources that may truly require local
extraction before upload to Databricks.
