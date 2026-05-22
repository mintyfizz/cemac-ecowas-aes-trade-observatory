"""Databricks SQL Statement Execution API helpers for build scripts."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import requests


CATALOG = os.getenv("DATABRICKS_CATALOG", "cemac_ecowas_aes_trade")


def _creds() -> tuple[str, str, str]:
    host = os.environ.get("DATABRICKS_HOST", "").removeprefix("https://").strip("/")
    path = os.environ.get("DATABRICKS_HTTP_PATH", "")
    token = os.environ.get("DATABRICKS_TOKEN", "")
    if not (host and path and token):
        raise RuntimeError(
            "Databricks credentials not set. Configure DATABRICKS_HOST, "
            "DATABRICKS_HTTP_PATH, and DATABRICKS_TOKEN as environment variables."
        )
    return host, path, token


def _warehouse_id(http_path: str) -> str:
    return http_path.rstrip("/").rsplit("/", 1)[-1]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _request_json(method: str, host: str, token: str, path: str, **kwargs) -> dict:
    response = requests.request(
        method,
        f"https://{host}{path}",
        headers=_headers(token),
        timeout=60,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def _parameter_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "DOUBLE"
    return "STRING"


def _prepare_statement(sql_text: str, params: list[Any] | None) -> tuple[str, list[dict[str, str]]]:
    params = params or []
    prepared = sql_text
    statement_params: list[dict[str, str]] = []

    for idx, value in enumerate(params):
        name = f"p{idx}"
        prepared = prepared.replace("?", f":{name}", 1)
        statement_params.append(
            {
                "name": name,
                "value": str(value),
                "type": _parameter_type(value),
            }
        )

    if "?" in prepared:
        raise RuntimeError("SQL statement has more placeholders than provided parameters.")

    return prepared, statement_params


def _state(response: dict) -> str:
    return str(response.get("status", {}).get("state", "")).upper()


def _wait(host: str, token: str, statement_id: str) -> dict:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = _request_json("GET", host, token, f"/api/2.0/sql/statements/{statement_id}")
        state = _state(response)
        if state == "SUCCEEDED":
            return response
        if state in {"FAILED", "CANCELED", "CLOSED"}:
            message = response.get("status", {}).get("error", {}).get("message", response)
            raise RuntimeError(f"Databricks statement {state.lower()}: {message}")
        time.sleep(1.5)
    raise RuntimeError("Databricks statement timed out after 180 seconds.")


def _fetch_chunk(host: str, token: str, statement_id: str, chunk_index: int) -> list[list[Any]]:
    response = _request_json(
        "GET",
        host,
        token,
        f"/api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index}",
    )
    return response.get("result", response).get("data_array", []) or []


def _coerce(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    type_name = type_name.upper()
    if type_name in {"BYTE", "SHORT", "INT", "INTEGER", "LONG", "BIGINT"}:
        return int(value)
    if type_name in {"FLOAT", "DOUBLE", "DECIMAL"}:
        return float(value)
    if type_name == "BOOLEAN":
        return str(value).lower() == "true"
    return value


def _rows(response: dict, host: str, token: str, statement_id: str) -> list[dict[str, Any]]:
    manifest = response.get("manifest", {})
    schema_columns = manifest.get("schema", {}).get("columns", []) or []
    column_names = [column.get("name") for column in schema_columns]
    column_types = [column.get("type_name", "STRING") for column in schema_columns]
    data = response.get("result", {}).get("data_array", []) or []

    for chunk_index in range(1, int(manifest.get("total_chunk_count", 1) or 1)):
        data.extend(_fetch_chunk(host, token, statement_id, chunk_index))

    rows: list[dict[str, Any]] = []
    for raw_row in data:
        row = {
            name: _coerce(raw_row[idx], column_types[idx])
            for idx, name in enumerate(column_names)
        }
        rows.append(row)
    return rows


def query(sql_text: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Execute SQL against Databricks and return rows as dictionaries.

    Callers may write SQL with `?` placeholders. This helper converts them to
    Databricks named parameters before submitting the statement.
    """
    host, http_path, token = _creds()
    statement, statement_params = _prepare_statement(sql_text, params)
    payload: dict[str, Any] = {
        "warehouse_id": _warehouse_id(http_path),
        "statement": re.sub(r"\s+", " ", statement).strip(),
        "wait_timeout": "50s",
        "on_wait_timeout": "CONTINUE",
        "disposition": "INLINE",
    }
    if statement_params:
        payload["parameters"] = statement_params

    response = _request_json("POST", host, token, "/api/2.0/sql/statements", json=payload)
    statement_id = response.get("statement_id")
    if not statement_id:
        raise RuntimeError("Databricks statement response did not include a statement_id.")

    if _state(response) != "SUCCEEDED":
        response = _wait(host, token, statement_id)

    if _state(response) != "SUCCEEDED":
        message = response.get("status", {}).get("error", {}).get("message", response)
        raise RuntimeError(f"Databricks statement did not succeed: {message}")

    return _rows(response, host, token, statement_id)
