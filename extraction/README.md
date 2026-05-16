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

You can also store it in a local `.env` file, which is ignored by Git:

```bash
COMTRADE_API_KEY=your-rotated-key
```

If both are present, the shell `COMTRADE_API_KEY` value wins over `.env`.

Install the local extraction dependency:

```bash
python3 -m pip install -r extraction/requirements.txt
```

Run a small extraction:

```bash
python3 extraction/extract/comtrade_totals.py \
  --all-cemac-ecowas \
  --start-year 2010 \
  --end-year 2023 \
  --out data/raw/comtrade/cemac_ecowas_totals_2010_2023.jsonl
```

The script writes one JSON object per reporter-year request. It sends the
subscription key as an HTTP header and avoids printing the key or embedding
it in logged URLs. Each request uses `partnerCode=all`, so the payload
contains all available bilateral partner rows for that reporter-year. The
Databricks bronze notebook removes `partnerCode = 0` World aggregate rows
before writing `bronze.comtrade_raw`.

### Troubleshooting

`HTTP 401` means UN Comtrade rejected the configured key. The script now
checks the key once before the full extraction loop and prints whether it is
reading from `.env` or from the shell environment. Rotate or recopy the key
from the UN Comtrade developer portal, update the reported location, then
rerun the command.
