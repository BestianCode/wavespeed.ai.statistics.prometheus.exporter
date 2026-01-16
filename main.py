import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, Response


app = Flask(__name__)

BASE_URL = os.getenv("WS_AI_BASE_URL", "https://api.wavespeed.ai").rstrip("/")
TOKEN = os.getenv("WS_AI_TOKEN")

PORT = int(os.getenv("PORT", "8080"))
UPDATE_INTERVAL_SECONDS = int(os.getenv("UPDATE_INTERVAL_SECONDS", "300"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
STATE_FILE = os.getenv("STATE_FILE", "./wavespeed_state.json")

USAGE_WINDOW_DAYS = 31


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("wavespeed_exporter")


state_lock = threading.Lock()
state = {
    "balance_usd": None,
    "daily": {},  # date -> {count:int, cost_usd:float, models:{model_uuid:{count:int,cost_usd:float,model_type:str}}}
    "last_success_utc": None,
    "last_error": None,
}


def _escape_label_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _atomic_write_json(path: str, payload: dict) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _load_state_from_disk() -> None:
    global state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            with state_lock:
                state["balance_usd"] = loaded.get("balance_usd")
                state["daily"] = loaded.get("daily", {}) if isinstance(loaded.get("daily", {}), dict) else {}
                state["last_success_utc"] = loaded.get("last_success_utc")
                state["last_error"] = loaded.get("last_error")
        logger.info("Loaded state from %s", STATE_FILE)
    except FileNotFoundError:
        logger.info("No state file found at %s (first start)", STATE_FILE)
    except Exception as exc:
        logger.warning("Failed to load state from %s: %s", STATE_FILE, exc)


def _save_state_to_disk() -> None:
    with state_lock:
        snapshot = dict(state)
    try:
        _atomic_write_json(STATE_FILE, snapshot)
    except Exception as exc:
        logger.warning("Failed to save state to %s: %s", STATE_FILE, exc)


def _auth_headers() -> dict:
    if not TOKEN:
        return {}
    return {"Authorization": f"Bearer {TOKEN}"}


def fetch_balance_usd(session: requests.Session) -> Optional[float]:
    url = f"{BASE_URL}/api/v3/balance"
    resp = session.get(url, headers=_auth_headers(), timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise RuntimeError(f"Unexpected balance response: {payload}")
    data = payload.get("data") or {}
    balance = data.get("balance")
    if balance is None:
        return None
    return float(balance)


def _to_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_usage_window(session: requests.Session) -> dict:
    now_utc = datetime.now(timezone.utc)
    end_dt = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start_dt = end_dt - timedelta(days=USAGE_WINDOW_DAYS)

    url = f"{BASE_URL}/api/v3/user/usage_stats"
    body = {
        "start_time": _to_z(start_dt),
        "end_time": _to_z(end_dt),
    }
    resp = session.post(
        url,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise RuntimeError(f"Unexpected usage response: {payload}")

    data = payload.get("data") or {}
    daily_usage = data.get("daily_usage") or []

    by_date: Dict[str, Dict[str, Any]] = {}
    if isinstance(daily_usage, list):
        for row in daily_usage:
            if not isinstance(row, dict):
                continue
            date_str = row.get("date")
            if not date_str:
                continue
            count = int(row.get("count") or 0)
            cost_usd = float(row.get("amount") or 0.0)

            models_out: Dict[str, Dict[str, Any]] = {}
            models = row.get("models") or []
            if isinstance(models, list):
                for m in models:
                    if not isinstance(m, dict):
                        continue
                    model_uuid = m.get("model_uuid")
                    if not model_uuid:
                        continue
                    models_out[str(model_uuid)] = {
                        "count": int(m.get("count") or 0),
                        "cost_usd": float(m.get("amount") or 0.0),
                        "model_type": "",
                    }

            by_date[str(date_str)] = {
                "count": count,
                "cost_usd": cost_usd,
                "models": models_out,
            }

    model_type_by_uuid: Dict[str, str] = {}
    per_model_usage = data.get("per_model_usage") or []
    if isinstance(per_model_usage, list):
        for row in per_model_usage:
            if not isinstance(row, dict):
                continue
            model_uuid = row.get("model_uuid")
            model_type = row.get("model_type")
            if model_uuid and model_type:
                model_type_by_uuid[str(model_uuid)] = str(model_type)

    # Fill missing days with zeros for totals, so Grafana graphs are continuous.
    expected_dates: List[str] = []
    current = start_dt.date()
    while current < end_dt.date():
        expected_dates.append(current.isoformat())
        current = current + timedelta(days=1)

    for date_str in expected_dates:
        if date_str not in by_date:
            by_date[date_str] = {"count": 0, "cost_usd": 0.0, "models": {}}
        else:
            for model_uuid, m in (by_date[date_str].get("models") or {}).items():
                if model_uuid in model_type_by_uuid and isinstance(m, dict):
                    m["model_type"] = model_type_by_uuid[model_uuid]

    return {
        "window_start": expected_dates[0] if expected_dates else None,
        "window_end_exclusive": end_dt.date().isoformat(),
        "by_date": by_date,
    }


def update_loop() -> None:
    if not TOKEN:
        logger.error("WS_AI_TOKEN is not set; exporter will serve NaN/empty data until configured")

    session = requests.Session()

    while True:
        try:
            balance = fetch_balance_usd(session) if TOKEN else None
            usage = fetch_usage_window(session) if TOKEN else {"by_date": {}}

            with state_lock:
                if balance is not None:
                    state["balance_usd"] = balance

                daily = state.get("daily")
                if not isinstance(daily, dict):
                    daily = {}
                    state["daily"] = daily

                for date_str, day in (usage.get("by_date") or {}).items():
                    daily[date_str] = day

                state["last_success_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                state["last_error"] = None

            _save_state_to_disk()
            logger.info("Updated data (balance + daily usage)")
        except Exception as exc:
            with state_lock:
                state["last_error"] = str(exc)
            logger.warning("Update failed: %s", exc)

        time.sleep(UPDATE_INTERVAL_SECONDS)


@app.route("/healthz")
def healthz() -> Response:
    return Response("ok\n", mimetype="text/plain")


@app.route("/metrics")
def metrics() -> Response:
    with state_lock:
        balance_usd = state.get("balance_usd")
        daily = state.get("daily") or {}

    lines: List[str] = []

    # Metric 1: balance
    lines.append("# HELP wavespeed_balance_usd Current account balance in USD")
    lines.append("# TYPE wavespeed_balance_usd gauge")
    if balance_usd is None:
        lines.append("wavespeed_balance_usd NaN")
    else:
        lines.append(f"wavespeed_balance_usd {float(balance_usd)}")

    # Metric 2: daily usage (counts + costs, totals + per-model) under a single metric name
    lines.append("# HELP wavespeed_daily_usage Daily usage per day; metric=count|cost_usd; model_uuid empty means total")
    lines.append("# TYPE wavespeed_daily_usage gauge")

    if isinstance(daily, dict):
        for date_str in sorted(daily.keys()):
            day = daily.get(date_str) or {}
            if not isinstance(day, dict):
                continue

            total_count = int(day.get("count") or 0)
            total_cost = float(day.get("cost_usd") or 0.0)

            base_labels = (
                f'date="{_escape_label_value(date_str)}",'
                f'model_uuid="",'
                f'model_type=""'
            )
            lines.append(f'wavespeed_daily_usage{{{base_labels},metric="count"}} {total_count}')
            lines.append(f'wavespeed_daily_usage{{{base_labels},metric="cost_usd"}} {total_cost}')

            models = day.get("models") or {}
            if isinstance(models, dict):
                for model_uuid, m in models.items():
                    if not isinstance(m, dict):
                        continue
                    m_count = int(m.get("count") or 0)
                    m_cost = float(m.get("cost_usd") or 0.0)
                    m_type = m.get("model_type") or ""

                    labels = (
                        f'date="{_escape_label_value(date_str)}",'
                        f'model_uuid="{_escape_label_value(model_uuid)}",'
                        f'model_type="{_escape_label_value(m_type)}"'
                    )
                    lines.append(f'wavespeed_daily_usage{{{labels},metric="count"}} {m_count}')
                    lines.append(f'wavespeed_daily_usage{{{labels},metric="cost_usd"}} {m_cost}')

    return Response("\n".join(lines) + "\n", mimetype="text/plain")


if __name__ == "__main__":
    _load_state_from_disk()
    fetch_thread = threading.Thread(target=update_loop, daemon=True)
    fetch_thread.start()
    app.run(host="0.0.0.0", port=PORT)
