# Web Dashboard Deployment

The production web dashboard uses:

- `public/` for the browser UI.
- `api/` for the FastAPI backend.
- Databricks SQL Statement Execution API for reads from `gold.*` tables.
- Vercel environment variables for secrets.

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn api.index:app --host 127.0.0.1 --port 8502
```

Local credentials come from environment variables:

```bash
export DATABRICKS_HOST="dbc-xxxx.cloud.databricks.com"
export DATABRICKS_HTTP_PATH="/sql/1.0/warehouses/xxxxxxxx"
export DATABRICKS_TOKEN="..."
export DATABRICKS_CATALOG="cemac_ecowas_aes_trade"
```

Open `http://127.0.0.1:8502`.

## Vercel Setup

1. Push this repository to GitHub.
2. Import the repo in Vercel.
3. Use the existing `vercel.json`.
4. Add these Vercel environment variables:

```text
DATABRICKS_HOST
DATABRICKS_HTTP_PATH
DATABRICKS_TOKEN
DATABRICKS_CATALOG
```

Do not commit `.env`, `.streamlit/secrets.toml`, `.databricks`, or any token.

## Data Contract

The dashboard reads only:

- `gold.dashboard_country_timeseries`
- `gold.dashboard_top_trade_partners`
- `gold.dashboard_conflict_hotspots`
- `gold.dashboard_fragility_components`
- `gold.dashboard_bloc_comparison`

UN Comtrade-only views are intentionally not shown. The dashboard uses IMF
IMTS/DOTS-style bilateral partner totals instead:

- Top partner bars use actual ISO3 counterpart rows only.
- IMF aggregate groups such as `G001` are filtered out of partner panels.
- Product composition, HS product treemaps, and mirror gaps are omitted.
- The integration panel uses bloc trade openness because intra-product and
mirror-pair details are not available without Comtrade.

## Expected Validation Counts

```text
gold.dashboard_country_timeseries      735 rows
gold.dashboard_top_trade_partners      11025 rows
gold.dashboard_conflict_hotspots       284 rows
gold.dashboard_fragility_components    21 rows
gold.dashboard_bloc_comparison         71 rows
```
