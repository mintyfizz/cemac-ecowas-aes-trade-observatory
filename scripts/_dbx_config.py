"""Shared Databricks configuration for local maintenance scripts."""

from __future__ import annotations

import configparser
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Load repo-local .env values without overriding real environment vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _warehouse_from_http_path(http_path: str) -> str:
    return http_path.rstrip("/").rsplit("/", 1)[-1] if http_path else ""


def dbx_config() -> dict[str, str]:
    """Return Databricks config from env vars first, then ~/.databrickscfg."""
    _load_dotenv(ROOT / ".env")

    cfg = configparser.ConfigParser()
    cfg.read(Path.home() / ".databrickscfg")
    sec = cfg["cemac-project"] if cfg.has_section("cemac-project") else {}

    http_path = os.getenv("DATABRICKS_HTTP_PATH", sec.get("http_path", ""))
    return {
        "host": os.getenv("DATABRICKS_HOST", sec.get("host", "")).removeprefix("https://").strip("/"),
        "warehouse": (
            os.getenv("DATABRICKS_WAREHOUSE_ID")
            or sec.get("warehouse_id", "")
            or _warehouse_from_http_path(http_path)
        ),
        "token": os.getenv("DATABRICKS_TOKEN", sec.get("token", "")),
        "catalog": os.getenv("DATABRICKS_CATALOG", sec.get("catalog", "cemac_ecowas_aes_trade")),
        "user": os.getenv("DATABRICKS_WORKSPACE_USER", sec.get("workspace_user", "")),
    }


def require_dbx_config(config: dict[str, str], *keys: str) -> None:
    missing = [key for key in keys if not config.get(key)]
    if missing:
        env_by_key = {
            "host": "DATABRICKS_HOST",
            "warehouse": "DATABRICKS_WAREHOUSE_ID or DATABRICKS_HTTP_PATH",
            "token": "DATABRICKS_TOKEN",
            "catalog": "DATABRICKS_CATALOG",
            "user": "DATABRICKS_WORKSPACE_USER",
        }
        env_names = ", ".join(env_by_key.get(key, f"DATABRICKS_{key.upper()}") for key in missing)
        raise RuntimeError(f"Missing Databricks configuration: {env_names}")
