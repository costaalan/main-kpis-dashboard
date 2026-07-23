# /root/.hermes/main-kpis-dashboard/backend/supervisor.py
"""Agente Supervisor: aggregates the Databricks, Dashboard, and Chat checks into
one overall_status, writes monitor_status.json on every run (the audit trail even
when nothing's wrong), and sends a single email only when overall_status == "fail"
— a hard failure needing human intervention. "warning" stays logged on the page.
Read-only — never inserts/updates/deletes production data itself; unlike guardiao,
this layer only observes and reports."""

import json
import os
import sqlite3
from datetime import datetime, timezone

import monitor_checks

# n8n runs the Databricks check 3x/day (08:00, 13:00, 18:00 America/Sao_Paulo
# — the n8n instance's GENERIC_TIMEZONE); this cron job runs 20min after each
# (11:20, 16:20, 21:20 UTC), so 1h of slack comfortably covers a late n8n run
# without masking a truly stale/missing status file — silence is never read
# as success.
DATABRICKS_STATUS_STALE_AFTER_SECONDS = 60 * 60

HERMES_HOME = os.environ.get("HERMES_HOME", "/opt/data")
DEFAULT_DB_PATH = os.path.join(HERMES_HOME, "main-kpis-dashboard", "data", "kpi_cache.db")
DEFAULT_DATABRICKS_STATUS_PATH = os.path.join(HERMES_HOME, "main-kpis-monitor", "databricks_status.json")
DEFAULT_MONITOR_STATUS_PATH = os.path.join(HERMES_HOME, "main-kpis-dashboard", "data", "monitor_status.json")
DEFAULT_AGENT_LOG_PATH = os.path.join(HERMES_HOME, "main-kpis-dashboard", "data", "agent_log.json")
DEFAULT_DASHBOARD_BASE_URL = os.environ.get("MAIN_KPIS_BASE_URL", "http://localhost:8708")


def _default_read_json(path):
    with open(path) as f:
        return json.load(f)


def check_databricks(status_path, read_json=_default_read_json, now=None, retry_count=3):
    """Reads databricks_status.json. If stale, auto-retries the generator up to
    retry_count times before marking FAIL — no human intervention needed."""
    import subprocess, time

    now = now or datetime.now(timezone.utc)
    gerador_script = os.path.join(HERMES_HOME, "scripts", "gerador_main_kpis.py")
    cache_script = os.path.join(HERMES_HOME, "scripts", "main-kpis-dashboard", "backend", "kpi_cache.py")

    def _read_and_check():
        try:
            data = read_json(status_path)
        except (FileNotFoundError, OSError):
            return None, f"databricks_status.json ausente em {status_path}"
        except json.JSONDecodeError as e:
            return None, f"databricks_status.json invalido: {e}"

        checked_at_raw = data.get("checked_at")
        if not checked_at_raw:
            return None, "databricks_status.json sem campo checked_at"

        checked_at = datetime.fromisoformat(checked_at_raw.replace("Z", "+00:00"))
        age_seconds = (now - checked_at).total_seconds()
        if age_seconds > DATABRICKS_STATUS_STALE_AFTER_SECONDS:
            return None, f"databricks_status.json desatualizado, ultimo check ha {int(age_seconds)}s"

        if data.get("status") != "ok":
            return None, data.get("message") or "Databricks check reportou falha"

        return data, data.get("message") or "tabelas Databricks populadas"

    # First check
    data, msg = _read_and_check()
    if data:
        return {"status": "ok", "message": msg}
    original_msg = msg

    # If stale, try to refresh automatically
    for attempt in range(1, retry_count + 1):
        print(f"[SUPERVISOR] Databricks stale, tentando refresh ({attempt}/{retry_count})...")
        try:
            # Run the data generator
            if os.path.isfile(gerador_script):
                subprocess.run(
                    ["python3", gerador_script],
                    capture_output=True, timeout=120, cwd=os.path.dirname(gerador_script)
                )
            # Refresh cache
            if os.path.isfile(cache_script):
                subprocess.run(
                    ["python3", cache_script],
                    capture_output=True, timeout=60, cwd=os.path.dirname(cache_script)
                )
            # Wait for file to update
            time.sleep(3)
            # Re-read now with updated timestamp
            now = datetime.now(timezone.utc)
            data, msg = _read_and_check()
            if data:
                return {"status": "ok", "message": f"Recuperado apos {attempt} tentativa(s): {msg}"}
        except Exception as e:
            print(f"[SUPERVISOR] Tentativa {attempt} falhou: {e}")

    return {"status": "fail", "message": f"Falha apos {retry_count} tentativas: {original_msg}"}


def aggregate(databricks_result, dashboard_result, chat_result, chat_accuracy_result):
    """fail beats warning beats ok across the four agent results."""
    results = {
        "databricks": databricks_result,
        "dashboard": dashboard_result,
        "chat": chat_result,
        "chat_accuracy": chat_accuracy_result,
    }
    statuses = {r["status"] for r in results.values()}
    if "fail" in statuses:
        overall = "fail"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "ok"
    return overall, results


def build_status_doc(databricks_result, dashboard_result, chat_result, chat_accuracy_result, now=None):
    now = now or datetime.now(timezone.utc)
    overall_status, results = aggregate(databricks_result, dashboard_result, chat_result, chat_accuracy_result)
    checked_at = now.isoformat()
    return {
        "checked_at": checked_at,
        "overall_status": overall_status,
        "agents": [
            {"name": name, "status": r["status"], "last_run": checked_at, "message": r["message"]}
            for name, r in results.items()
        ],
    }


def write_status(status_doc, output_path, write_json=None):
    if write_json is None:
        def write_json(path, doc):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
    write_json(output_path, status_doc)


def append_to_daily_log(status_doc, log_path, read_json=_default_read_json, write_json=None):
    """Appends this run to today's log. Resets to a fresh, single-run log the
    moment the date rolls over, so the file only ever holds one day's runs —
    never accumulates across days."""
    today = status_doc["checked_at"][:10]
    try:
        log = read_json(log_path)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        log = None

    if not log or log.get("date") != today:
        log = {"date": today, "runs": []}

    log["runs"].append(status_doc)
    write_status(log, log_path, write_json=write_json)
    return log


def notify_if_needed(status_doc, send_email):
    """Sends one consolidated email only when overall_status == 'fail' — a hard
    failure needing human intervention. "warning" (soft/self-recovering issues)
    and "ok" stay logged in monitor_status.json / the Agentes tab without an
    email; no daily "all good" email either."""
    if status_doc["overall_status"] != "fail":
        return None
    subject = f"Main KPIs Monitor — {status_doc['overall_status'].upper()}"
    lines = [f"{a['name']}: {a['status']} — {a['message']}" for a in status_doc["agents"]]
    body = f"Verificado em {status_doc['checked_at']}\n\n" + "\n".join(lines)
    return send_email(subject, body)


def run_cycle(
    conn,
    dashboard_base_url=DEFAULT_DASHBOARD_BASE_URL,
    databricks_status_path=DEFAULT_DATABRICKS_STATUS_PATH,
    monitor_status_path=DEFAULT_MONITOR_STATUS_PATH,
    agent_log_path=DEFAULT_AGENT_LOG_PATH,
    send_email=None,
    now=None,
    read_json=_default_read_json,
    get_json=monitor_checks._http_get_json,
    post_json=monitor_checks._http_post_json,
    get_ground_truth=None,
    write_json=None,
):
    """One full Supervisor cycle: read Databricks status, run Dashboard/Chat/
    Chat-Accuracy checks in-process, aggregate, write monitor_status.json, and
    notify on failure."""
    databricks_result = check_databricks(databricks_status_path, read_json=read_json, now=now)
    dashboard_result = monitor_checks.check_dashboard(conn, dashboard_base_url, get_json=get_json)
    chat_result = monitor_checks.check_chat(dashboard_base_url, post_json=post_json)
    chat_accuracy_result = monitor_checks.check_chat_accuracy(
        conn, dashboard_base_url, post_json=post_json, get_json=get_json,
        get_ground_truth=get_ground_truth, now=now
    )

    status_doc = build_status_doc(databricks_result, dashboard_result, chat_result, chat_accuracy_result, now=now)
    write_status(status_doc, monitor_status_path, write_json=write_json)
    append_to_daily_log(status_doc, agent_log_path, read_json=read_json, write_json=write_json)

    if send_email is not None:
        notify_if_needed(status_doc, send_email)

    return status_doc


if __name__ == "__main__":
    import sys

    guardiao_dir = os.path.join(HERMES_HOME, "guardiao")
    if os.path.isdir(guardiao_dir):
        sys.path.insert(0, guardiao_dir)
    try:
        from actions import send_email as _send_email
    except ImportError:
        _send_email = None

    _conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        doc = run_cycle(_conn, send_email=_send_email)
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    finally:
        _conn.close()
