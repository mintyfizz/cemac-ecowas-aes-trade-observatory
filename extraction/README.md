# Local extraction fallback

Databricks Free Edition serverless compute can reach some public APIs, such
as the World Bank endpoint tested in `01_network_test.ipynb`, but it failed
DNS resolution for `comtradeapi.un.org` during the UN Comtrade extraction
test. UN Comtrade therefore uses the local fallback path.

## UN Comtrade

Set a rotated UN Comtrade key in your local shell:

```bash
export COMTRADE_API_KEY="your-rotated-key"
```

Install the local extraction dependency:

```bash
python3 -m pip install -r extraction/requirements.txt
```

Run a small extraction:

```bash
python3 extraction/extract/comtrade_totals.py \
  --reporter-codes 120 140 148 \
  --start-year 2010 \
  --end-year 2023 \
  --out data/raw/comtrade/cemac_totals_2010_2023.jsonl
```

The script writes one JSON object per reporter-year request. It sends the
subscription key as an HTTP header and avoids printing the key or embedding
it in logged URLs.
