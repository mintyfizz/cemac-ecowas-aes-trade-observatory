#!/usr/bin/env python3
"""
Trigger one-time Databricks job runs for notebooks 14 and 15 (gold layer rebuild)
using the Jobs API v2.1 with serverless compute.

Usage:
    python scripts/rebuild_gold_dashboard.py

Run this after load_weo_silver.py has completed successfully.
"""

from __future__ import annotations

import sys
import time

import requests

from _dbx_config import dbx_config, require_dbx_config

DBX = dbx_config()
HOST = DBX["host"]


def notebooks(workspace_user: str) -> list[dict[str, str]]:
    return [
        {
            "run_name": "rebuild-gold-core-marts-14",
            "path": f"/Users/{workspace_user}/14_gold_dashboard_core_marts",
            "description": "gold.country_year_observatory + bloc_year_observatory",
        },
        {
            "run_name": "rebuild-gold-panel-marts-15",
            "path": f"/Users/{workspace_user}/15_gold_dashboard_panel_marts",
            "description": "gold.dashboard_country_timeseries + panel marts",
        },
    ]


def _get_pat() -> str:
    return DBX["token"]


def _headers(pat: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pat}", "Content-Type": "application/json"}


def submit_notebook_run(pat: str, run_name: str, notebook_path: str) -> str:
    """Submit a one-time notebook run with serverless compute. Returns run_id."""
    url = f"https://{HOST}/api/2.1/jobs/runs/submit"
    payload = {
        "run_name": run_name,
        "tasks": [
            {
                "task_key": "run_notebook",
                "notebook_task": {
                    "notebook_path": notebook_path,
                    "source": "WORKSPACE",
                },
            }
        ],
        "queue": {"enabled": False},
    }
    resp = requests.post(url, headers=_headers(pat), json=payload, timeout=30)
    if not resp.ok:
        body = resp.text
        # Try with a minimal classic cluster if serverless is not available
        print(f"  Serverless attempt failed ({resp.status_code}): {body[:200]}")
        print("  Retrying with a minimal classic cluster spec ...")
        payload["tasks"][0]["new_cluster"] = {
            "spark_version": "15.4.x-scala2.12",
            "node_type_id": "m5.xlarge",
            "num_workers": 1,
            "aws_attributes": {"availability": "SPOT_WITH_FALLBACK"},
        }
        resp = requests.post(url, headers=_headers(pat), json=payload, timeout=30)
        resp.raise_for_status()

    run_id = resp.json()["run_id"]
    return str(run_id)


def poll_run(pat: str, run_id: str, notebook_label: str, poll_interval: int = 20) -> bool:
    """Poll until the run completes. Returns True on success."""
    url = f"https://{HOST}/api/2.1/jobs/runs/get?run_id={run_id}"
    dots = 0
    while True:
        resp = requests.get(url, headers=_headers(pat), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        state = data.get("state", {})
        life_cycle = state.get("life_cycle_state", "")
        result_state = state.get("result_state", "")
        message = state.get("state_message", "")

        if life_cycle == "TERMINATED":
            if result_state == "SUCCESS":
                print(f"\n  ✓ {notebook_label} completed successfully.")
                return True
            else:
                print(f"\n  ✗ {notebook_label} failed ({result_state}): {message}")
                # Print task error if available
                for task in data.get("tasks", []):
                    t_state = task.get("state", {})
                    t_err = t_state.get("state_message", "")
                    if t_err:
                        print(f"    Task error: {t_err}")
                # Show run URL
                run_url = f"https://{HOST}/#job/runs/{run_id}"
                print(f"    Run URL: {run_url}")
                return False
        elif life_cycle in ("SKIPPED", "INTERNAL_ERROR"):
            print(f"\n  ✗ {notebook_label} {life_cycle}: {message}")
            return False

        # Still running
        dots += 1
        status = f"{life_cycle}"
        if message:
            status += f" ({message})"
        print(f"\r  [{dots * poll_interval}s] {status}   ", end="", flush=True)
        time.sleep(poll_interval)


def main() -> None:
    require_dbx_config(DBX, "host", "token", "user")
    pat = _get_pat()
    print(f"PAT loaded (ends ...{pat[-6:]})\n")

    for nb in notebooks(DBX["user"]):
        print(f"Submitting: {nb['run_name']}")
        print(f"  Notebook: {nb['path']}")
        print(f"  Builds:   {nb['description']}")

        run_id = submit_notebook_run(pat, nb["run_name"], nb["path"])
        print(f"  Run ID: {run_id}")
        run_url = f"https://{HOST}/#job/runs/{run_id}"
        print(f"  URL:    {run_url}")

        ok = poll_run(pat, run_id, nb["run_name"])
        if not ok:
            print("\nAborting — fix the failing notebook before running notebook 15.")
            sys.exit(1)
        print()

    print("All gold notebooks completed. Dashboard gold layer is rebuilt.")
    print("\nVerify with:")
    print("  python scripts/export_static.py")
    print("  python -m http.server 8080 --directory static")


if __name__ == "__main__":
    main()
