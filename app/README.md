# CEMAC-ECOWAS-AES Streamlit Dashboard

Live Streamlit dashboard for the Databricks gold and audit marts.

The app reads Databricks SQL with the Statement Execution API using the
warehouse ID embedded in the SQL warehouse HTTP path.

## Tables Used

- `gold.country_latest_snapshot`
- `gold.bloc_latest_snapshot`
- `gold.dashboard_country_timeseries`
- `gold.dashboard_top_trade_partners`
- `gold.dashboard_conflict_hotspots`
- `gold.dashboard_fragility_components`
- `gold.dashboard_bloc_comparison`
- `audit.source_coverage_summary`
- `audit.country_year_source_coverage`

The app does not query bronze or silver tables.

## Local Setup

```bash
cd cemac-ecowas-aes-trade-observatory
python3 -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
```

Create `.streamlit/secrets.toml` in the repository root:

```toml
[databricks]
server_hostname = "dbc-xxxx.cloud.databricks.com"
http_path = "/sql/1.0/warehouses/xxxxxxxx"
access_token = "dapi..."
```

Run:

```bash
streamlit run app/streamlit_app.py
```

## Dashboard Panels

- Overview cards: macro, trade, conflict, and latest FSI.
- Map: country-level metric choropleth.
- Macro-fiscal risk: GDP, debt, inflation, fiscal pressure.
- Trade dependence: openness, exports/GDP, imports/GDP, trade balance.
- Top partners: export/import bars.
- Partner concentration: HHI trend.
- Regional integration: bloc openness comparison.
- Conflict hotspots: ACLED admin1 intensity.
- Fragility profile: latest FSI components.
- Pipeline health: source coverage and known gaps.

Unsupported mockup panels were intentionally removed: LPI logistics, HS product composition, mirror gap, and distinct products.
