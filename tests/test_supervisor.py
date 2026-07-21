import sys, os, sqlite3
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import agent
import cache_db
import supervisor


def _conn_with_fresh_refresh():
    conn = sqlite3.connect(":memory:")
    cache_db.init_db(conn)
    cache_db.write_kpi_rows(conn, [{
        "site_id": "MLB", "kpi_name": "GMV", "periodicidade": "dia",
        "periodo_key": "2026-07-19", "periodo_label": "19-07", "ano": 2026, "valor": 1000.0,
    }])
    return conn


def _healthy_get_json(url):
    return {"ok": True, "status_code": 200, "body": {"status": "ok"}}


def _clean_post_json(url, payload, timeout=15):
    return {"ok": True, "status_code": 200, "body": {"reply": "nao posso fazer isso, mas o GMV foi 1000."}}


def _accuracy_matching_post_json(url, payload, timeout=15):
    """Routes accuracy-audit questions (they always ask 'em tabela') to a
    matching table response; everything else falls back to the plain chat fake."""
    if "em tabela" not in payload["message"]:
        return _clean_post_json(url, payload, timeout)
    site_id = next(s for s in agent.SITES if s in payload["message"])
    kpi_name = next(k for k in ("GMV", "CVR", "TAXA_CANCELAMENTO") if k in payload["message"])
    if "no dia" in payload["message"]:
        periodicidade = "dia"
    elif "na semana" in payload["message"]:
        periodicidade = "semana"
    else:
        periodicidade = "mes"
    return {"ok": True, "status_code": 200, "body": {
        "reply": "aqui esta",
        "table": {"site_id": site_id, "kpi_name": kpi_name, "periodicidade": periodicidade,
                  "rows": [{"label": "x", "valor": 500.0}]},
    }}


def _matching_ground_truth(conn, site_id, kpi_name, periodicidade, periodo_inicio=None, periodo_fim=None):
    return [{"periodo_key": periodo_inicio, "periodo_label": "x", "ano": 2026, "valor": 500.0}]


def _ok_databricks_status(now):
    return {
        "checked_at": now.isoformat(),
        "status": "ok",
        "tables": {"faturamento_vendas": {"rows": 118, "expected_min": 1}},
        "message": "all tables populated",
    }


# ─── check_databricks ──────────────────────────────────────

def test_check_databricks_ok_when_fresh_and_status_ok():
    now = datetime(2026, 7, 19, 12, 10, tzinfo=timezone.utc)
    checked_at = datetime(2026, 7, 19, 12, 5, tzinfo=timezone.utc)
    result = supervisor.check_databricks(
        "any/path", read_json=lambda p: _ok_databricks_status(checked_at), now=now
    )
    assert result["status"] == "ok"


def test_check_databricks_fails_when_file_missing():
    def raise_missing(path):
        raise FileNotFoundError(path)

    result = supervisor.check_databricks("any/path", read_json=raise_missing)
    assert result["status"] == "fail"
    assert "ausente" in result["message"]


def test_check_databricks_fails_when_checked_at_missing():
    result = supervisor.check_databricks("any/path", read_json=lambda p: {"status": "ok"})
    assert result["status"] == "fail"
    assert "checked_at" in result["message"]


def test_check_databricks_fails_when_stale():
    now = datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)
    checked_at = datetime(2026, 7, 19, 12, 5, tzinfo=timezone.utc)  # ~2h old
    result = supervisor.check_databricks(
        "any/path", read_json=lambda p: _ok_databricks_status(checked_at), now=now
    )
    assert result["status"] == "fail"
    assert "desatualizado" in result["message"]


def test_check_databricks_fails_when_status_not_ok():
    now = datetime(2026, 7, 19, 12, 10, tzinfo=timezone.utc)
    checked_at = datetime(2026, 7, 19, 12, 5, tzinfo=timezone.utc)

    def read_json(path):
        doc = _ok_databricks_status(checked_at)
        doc["status"] = "fail"
        doc["message"] = "logistica_entregas com 0 linhas"
        return doc

    result = supervisor.check_databricks("any/path", read_json=read_json, now=now)
    assert result["status"] == "fail"
    assert "logistica_entregas" in result["message"]


# ─── aggregate ──────────────────────────────────────────────

def test_aggregate_ok_when_all_ok():
    ok = {"status": "ok", "message": "ok"}
    overall, results = supervisor.aggregate(ok, ok, ok, ok)
    assert overall == "ok"
    assert set(results) == {"databricks", "dashboard", "chat", "chat_accuracy"}


def test_aggregate_fail_beats_warning():
    ok = {"status": "ok", "message": "ok"}
    warn = {"status": "warning", "message": "warn"}
    fail = {"status": "fail", "message": "fail"}
    overall, _ = supervisor.aggregate(fail, warn, ok, ok)
    assert overall == "fail"


def test_aggregate_warning_when_no_fail():
    ok = {"status": "ok", "message": "ok"}
    warn = {"status": "warning", "message": "warn"}
    overall, _ = supervisor.aggregate(ok, ok, warn, ok)
    assert overall == "warning"


# ─── write_status / notify_if_needed ───────────────────────

def test_write_status_calls_write_json_with_doc():
    written = {}

    def fake_write(path, doc):
        written["path"] = path
        written["doc"] = doc

    doc = {"overall_status": "ok"}
    supervisor.write_status(doc, "some/path.json", write_json=fake_write)
    assert written["path"] == "some/path.json"
    assert written["doc"] == doc


def test_append_to_daily_log_appends_same_day_runs():
    store = {}

    def fake_read(path):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def fake_write(path, doc):
        store[path] = doc

    run1 = {"checked_at": "2026-07-21T11:20:00+00:00", "overall_status": "ok", "agents": []}
    run2 = {"checked_at": "2026-07-21T16:20:00+00:00", "overall_status": "warning", "agents": []}

    supervisor.append_to_daily_log(run1, "log.json", read_json=fake_read, write_json=fake_write)
    log = supervisor.append_to_daily_log(run2, "log.json", read_json=fake_read, write_json=fake_write)

    assert log["date"] == "2026-07-21"
    assert log["runs"] == [run1, run2]


def test_append_to_daily_log_resets_on_new_day():
    store = {"log.json": {"date": "2026-07-20", "runs": [{"checked_at": "2026-07-20T21:20:00+00:00"}]}}

    def fake_read(path):
        return store[path]

    def fake_write(path, doc):
        store[path] = doc

    run_today = {"checked_at": "2026-07-21T11:20:00+00:00", "overall_status": "ok", "agents": []}
    log = supervisor.append_to_daily_log(run_today, "log.json", read_json=fake_read, write_json=fake_write)

    assert log["date"] == "2026-07-21"
    assert log["runs"] == [run_today]


def test_notify_if_needed_skips_email_when_ok():
    calls = []
    doc = {"overall_status": "ok", "checked_at": "x", "agents": []}
    result = supervisor.notify_if_needed(doc, send_email=lambda s, b: calls.append((s, b)))
    assert result is None
    assert calls == []


def test_notify_if_needed_skips_email_when_warning():
    calls = []
    doc = {
        "overall_status": "warning",
        "checked_at": "2026-07-21T10:00:00+00:00",
        "agents": [{"name": "chat", "status": "warning", "message": "possivel desvio de persona"}],
    }
    result = supervisor.notify_if_needed(doc, send_email=lambda s, b: calls.append((s, b)))
    assert result is None
    assert calls == []


def test_notify_if_needed_sends_email_when_fail():
    calls = []
    doc = {
        "overall_status": "fail",
        "checked_at": "2026-07-19T12:25:00+00:00",
        "agents": [{"name": "chat", "status": "fail", "message": "vazamento detectado"}],
    }
    supervisor.notify_if_needed(doc, send_email=lambda s, b: calls.append((s, b)))
    assert len(calls) == 1
    subject, body = calls[0]
    assert "FAIL" in subject
    assert "vazamento detectado" in body


# ─── run_cycle (end-to-end with all dependencies injected) ─

def test_run_cycle_writes_status_and_skips_email_when_all_ok():
    conn = _conn_with_fresh_refresh()
    now = datetime(2026, 7, 19, 12, 25, tzinfo=timezone.utc)
    checked_at = datetime(2026, 7, 19, 12, 5, tzinfo=timezone.utc)
    written = {}
    email_calls = []

    doc = supervisor.run_cycle(
        conn,
        dashboard_base_url="http://x",
        now=now,
        read_json=lambda p: _ok_databricks_status(checked_at),
        get_json=_healthy_get_json,
        post_json=_accuracy_matching_post_json,
        get_ground_truth=_matching_ground_truth,
        monitor_status_path="status.json",
        agent_log_path="log.json",
        write_json=lambda path, d: written.update({path: d}),
        send_email=lambda s, b: email_calls.append((s, b)),
    )

    assert doc["overall_status"] == "ok"
    assert written["status.json"] == doc
    assert written["log.json"]["runs"] == [doc]
    assert email_calls == []
    assert any(a["name"] == "chat_accuracy" for a in doc["agents"])


def test_run_cycle_sends_email_when_databricks_status_missing():
    conn = _conn_with_fresh_refresh()
    now = datetime(2026, 7, 19, 12, 25, tzinfo=timezone.utc)
    email_calls = []

    def raise_missing(path):
        raise FileNotFoundError(path)

    doc = supervisor.run_cycle(
        conn,
        dashboard_base_url="http://x",
        now=now,
        read_json=raise_missing,
        get_json=_healthy_get_json,
        post_json=_clean_post_json,
        write_json=lambda path, d: None,
        send_email=lambda s, b: email_calls.append((s, b)),
    )

    assert doc["overall_status"] == "fail"
    assert len(email_calls) == 1
