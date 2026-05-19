"""Databricks SQL access helpers for the Streamlit dashboard."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import requests
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


CATALOG = "cemac_ecowas_aes_trade"

TABLES = {
    "country_latest": f"{CATALOG}.gold.country_latest_snapshot",
    "bloc_latest": f"{CATALOG}.gold.bloc_latest_snapshot",
    "country_ts": f"{CATALOG}.gold.dashboard_country_timeseries",
    "top_partners": f"{CATALOG}.gold.dashboard_top_trade_partners",
    "conflict_hotspots": f"{CATALOG}.gold.dashboard_conflict_hotspots",
    "fragility": f"{CATALOG}.gold.dashboard_fragility_components",
    "bloc_comparison": f"{CATALOG}.gold.dashboard_bloc_comparison",
    "source_summary": f"{CATALOG}.audit.source_coverage_summary",
    "coverage": f"{CATALOG}.audit.country_year_source_coverage",
}


@dataclass(frozen=True)
class DatabricksConfig:
    server_hostname: str
    http_path: str
    access_token: str


class DashboardDataError(RuntimeError):
    """Raised when dashboard data cannot be loaded."""


def _secret_value(*keys: str) -> str | None:
    """Read a config value from Streamlit secrets or environment variables."""
    for key in keys:
        if key in os.environ and os.environ[key].strip():
            return os.environ[key].strip()

    try:
        databricks_secrets = st.secrets.get("databricks", {})
    except StreamlitSecretNotFoundError:
        databricks_secrets = {}

    for key in keys:
        secret_key = key.lower().replace("databricks_", "")
        value = databricks_secrets.get(secret_key)
        if value:
            return str(value).strip()
    return None


def get_config() -> DatabricksConfig | None:
    server_hostname = _secret_value("DATABRICKS_SERVER_HOSTNAME", "SERVER_HOSTNAME")
    http_path = _secret_value("DATABRICKS_HTTP_PATH", "HTTP_PATH")
    access_token = _secret_value("DATABRICKS_TOKEN", "ACCESS_TOKEN", "TOKEN")

    if not all([server_hostname, http_path, access_token]):
        return None

    if server_hostname.startswith("https://"):
        server_hostname = server_hostname.removeprefix("https://").split("/", 1)[0]

    return DatabricksConfig(
        server_hostname=server_hostname,
        http_path=http_path,
        access_token=access_token,
    )


def missing_config_message() -> str:
    return (
        "Databricks SQL credentials are not configured. Add them to "
        "`.streamlit/secrets.toml` or environment variables: "
        "`DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN`."
    )


def _warehouse_id(config: DatabricksConfig) -> str:
    return config.http_path.rstrip("/").rsplit("/", 1)[-1]


def _api_url(config: DatabricksConfig, path: str) -> str:
    return f"https://{config.server_hostname}{path}"


def _api_headers(config: DatabricksConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.access_token}",
        "Content-Type": "application/json",
    }


def _request_json(config: DatabricksConfig, method: str, path: str, **kwargs) -> dict:
    try:
        response = requests.request(
            method,
            _api_url(config, path),
            headers=_api_headers(config),
            timeout=60,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise DashboardDataError(f"Databricks SQL API request failed: {exc}") from exc


def _statement_state(response: dict) -> str:
    return str(response.get("status", {}).get("state", "")).upper()


def _wait_for_statement(config: DatabricksConfig, statement_id: str) -> dict:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = _request_json(config, "GET", f"/api/2.0/sql/statements/{statement_id}")
        state = _statement_state(response)
        if state == "SUCCEEDED":
            return response
        if state in {"FAILED", "CANCELED", "CLOSED"}:
            message = response.get("status", {}).get("error", {}).get("message", response)
            raise DashboardDataError(f"Databricks statement {state.lower()}: {message}")
        time.sleep(2)
    raise DashboardDataError("Databricks statement timed out after 180 seconds.")


def _fetch_chunk(config: DatabricksConfig, statement_id: str, chunk_index: int) -> list[list]:
    response = _request_json(
        config,
        "GET",
        f"/api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index}",
    )
    result = response.get("result", response)
    return result.get("data_array", []) or []


def _coerce_dataframe_types(df: pd.DataFrame, columns: list[dict]) -> pd.DataFrame:
    for column in columns:
        name = column.get("name")
        type_name = str(column.get("type_name", "")).upper()
        if not name or name not in df.columns:
            continue
        if type_name in {"BYTE", "SHORT", "INT", "INTEGER", "LONG", "BIGINT", "FLOAT", "DOUBLE", "DECIMAL"}:
            df[name] = pd.to_numeric(df[name], errors="coerce")
        elif type_name in {"DATE", "TIMESTAMP"}:
            df[name] = pd.to_datetime(df[name], errors="coerce")
        elif type_name == "BOOLEAN":
            df[name] = df[name].map({"true": True, "false": False, True: True, False: False})
    return df


def _execute_statement(config: DatabricksConfig, query: str) -> pd.DataFrame:
    payload = {
        "warehouse_id": _warehouse_id(config),
        "statement": query,
        "wait_timeout": "50s",
        "on_wait_timeout": "CONTINUE",
        "disposition": "INLINE",
    }
    response = _request_json(config, "POST", "/api/2.0/sql/statements", json=payload)
    statement_id = response.get("statement_id")
    if not statement_id:
        raise DashboardDataError("Databricks statement response did not include a statement_id.")

    state = _statement_state(response)
    if state != "SUCCEEDED":
        response = _wait_for_statement(config, statement_id)

    status = response.get("status", {})
    if _statement_state(response) != "SUCCEEDED":
        message = status.get("error", {}).get("message", response)
        raise DashboardDataError(f"Databricks statement did not succeed: {message}")

    manifest = response.get("manifest", {})
    schema_columns = manifest.get("schema", {}).get("columns", []) or []
    column_names = [column.get("name") for column in schema_columns]
    rows = response.get("result", {}).get("data_array", []) or []

    total_chunks = int(manifest.get("total_chunk_count", 1) or 1)
    for chunk_index in range(1, total_chunks):
        rows.extend(_fetch_chunk(config, statement_id, chunk_index))

    df = pd.DataFrame(rows, columns=column_names)
    return _coerce_dataframe_types(df, schema_columns)


@st.cache_data(ttl=900, show_spinner=False)
def run_query(query: str) -> pd.DataFrame:
    config = get_config()
    if config is None:
        raise DashboardDataError(missing_config_message())

    try:
        return _execute_statement(config, query)
    except Exception as exc:  # pragma: no cover - exercised against Databricks
        raise DashboardDataError(f"Databricks query failed: {exc}") from exc


def table_query(table_name: str, columns: Iterable[str] | None = None) -> str:
    selected_columns = ", ".join(columns) if columns else "*"
    return f"SELECT {selected_columns} FROM {table_name}"


@st.cache_data(ttl=900, show_spinner="Loading Databricks gold tables...")
def load_dashboard_tables() -> dict[str, pd.DataFrame]:
    return {key: run_query(table_query(table_name)) for key, table_name in TABLES.items()}
