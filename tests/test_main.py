import sys, os, sqlite3, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("MAIN_KPIS_DB", path)

    import cache_db
    conn = sqlite3.connect(path)
    cache_db.init_db(conn)
    cache_db.write_kpi_rows(conn, [
        {"site_id": "MLB", "kpi_name": "GMV", "periodicidade": "dia", "periodo_key": "2026-07-14",
         "periodo_label": "14-07", "ano": 2026, "valor": 1000.0},
        {"site_id": "MLB", "kpi_name": "GMV", "periodicidade": "dia", "periodo_key": "2026-07-15",
         "periodo_label": "15-07", "ano": 2026, "valor": 1100.0},
        {"site_id": "MLB", "kpi_name": "GMV", "periodicidade": "dia", "periodo_key": "2026-07-16",
         "periodo_label": "16-07", "ano": 2026, "valor": 1210.0},
        {"site_id": "MLM", "kpi_name": "GMV", "periodicidade": "dia", "periodo_key": "2026-07-16",
         "periodo_label": "16-07", "ano": 2026, "valor": 500.0},
        {"site_id": "MLB", "kpi_name": "CVR", "periodicidade": "dia", "periodo_key": "2026-07-15",
         "periodo_label": "15-07", "ano": 2026, "valor": 0.02},
        {"site_id": "MLB", "kpi_name": "CVR", "periodicidade": "dia", "periodo_key": "2026-07-16",
         "periodo_label": "16-07", "ano": 2026, "valor": 0.03},
    ])
    conn.close()

    import importlib
    import main as main_mod
    importlib.reload(main_mod)
    yield TestClient(main_mod.app)

    os.remove(path)


def test_get_kpis_missing_cache_returns_503(monkeypatch):
    monkeypatch.setenv("MAIN_KPIS_DB", "/tmp/does-not-exist-main-kpis.db")
    import importlib
    import main as main_mod
    importlib.reload(main_mod)
    client = TestClient(main_mod.app)
    resp = client.get("/api/kpis")
    assert resp.status_code == 503


def test_get_kpis_returns_panel_per_site(client):
    resp = client.get("/api/kpis", params={"kpi_name": "GMV"})
    assert resp.status_code == 200
    body = resp.json()
    site_ids = {p["site_id"] for p in body["panels"]}
    assert "MLB" in site_ids
    assert "MLM" in site_ids


def test_get_kpis_last_3_periods_and_delta(client):
    resp = client.get("/api/kpis", params={"kpi_name": "GMV", "site_id": "MLB"})
    body = resp.json()
    row = body["panels"][0]["rows"][0]
    assert [p["label"] for p in row["periods"]] == ["16-07", "15-07", "14-07"]
    assert round(row["delta_recente"]["valor"], 4) == round((1210.0 - 1100.0) / 1100.0, 4)
    assert row["delta_recente"]["label"] == "DoD"


def test_get_kpis_percent_kpi_delta_is_absolute_not_relative(client):
    resp = client.get("/api/kpis", params={"kpi_name": "CVR", "site_id": "MLB"})
    body = resp.json()
    row = body["panels"][0]["rows"][0]
    assert round(row["delta_recente"]["valor"], 4) == round(0.03 - 0.02, 4)


def test_get_kpis_yoy_none_when_no_prior_year_data(client):
    resp = client.get("/api/kpis", params={"kpi_name": "GMV", "site_id": "MLB"})
    body = resp.json()
    row = body["panels"][0]["rows"][0]
    assert row["yoy"] is None


def test_get_kpis_num_periodos_overrides_default(client):
    resp = client.get("/api/kpis", params={"kpi_name": "GMV", "site_id": "MLB", "num_periodos": 2})
    body = resp.json()
    row = body["panels"][0]["rows"][0]
    assert [p["label"] for p in row["periods"]] == ["16-07", "15-07"]


def test_get_kpis_num_periodos_clamped_to_periodicidade_max(client, monkeypatch):
    import main as main_mod
    captured = {}
    original = main_mod.cache_db.list_periods

    def spy(conn, site_id, kpi_name, periodicidade, limit=None):
        captured["limit"] = limit
        return original(conn, site_id, kpi_name, periodicidade, limit=limit)

    monkeypatch.setattr(main_mod.cache_db, "list_periods", spy)
    resp = client.get("/api/kpis", params={
        "kpi_name": "GMV", "site_id": "MLB", "periodicidade": "dia", "num_periodos": 999,
    })
    assert resp.status_code == 200
    assert captured["limit"] == main_mod.MAX_PERIODOS["dia"]


def test_get_valor_returns_exact_value_for_periodo_key(client):
    resp = client.get("/api/kpis/valor", params={
        "site_id": "MLB", "kpi_name": "GMV", "periodicidade": "dia", "periodo_key": "2026-07-15",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valor"] == 1100.0
    assert body["site_id"] == "MLB"
    assert body["periodo_key"] == "2026-07-15"


def test_get_valor_invalid_site_id_returns_400(client):
    resp = client.get("/api/kpis/valor", params={
        "site_id": "NOT_A_SITE", "kpi_name": "GMV", "periodicidade": "dia", "periodo_key": "2026-07-15",
    })
    assert resp.status_code == 400


def test_get_valor_invalid_kpi_name_returns_400(client):
    resp = client.get("/api/kpis/valor", params={
        "site_id": "MLB", "kpi_name": "NOT_A_KPI", "periodicidade": "dia", "periodo_key": "2026-07-15",
    })
    assert resp.status_code == 400


def test_get_valor_no_data_returns_404(client):
    resp = client.get("/api/kpis/valor", params={
        "site_id": "MLU", "kpi_name": "AOV", "periodicidade": "dia", "periodo_key": "2026-07-15",
    })
    assert resp.status_code == 404


def test_get_series_returns_trend_and_full_history(client):
    resp = client.get("/api/kpis/series", params={"kpi_name": "GMV", "site_id": "MLB"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kpi_name"] == "GMV"
    assert [p["label"] for p in body["series"]] == ["14-07", "15-07", "16-07"]
    assert body["trend"] == "alta"
    assert len(body["trend_line"]) == 3


def test_get_series_invalid_kpi_name_returns_400(client):
    resp = client.get("/api/kpis/series", params={"kpi_name": "NOT_A_KPI", "site_id": "MLB"})
    assert resp.status_code == 400


def test_get_series_no_data_returns_404(client):
    resp = client.get("/api/kpis/series", params={"kpi_name": "AOV", "site_id": "MLU"})
    assert resp.status_code == 404


def test_get_series_multi_returns_one_entry_per_site_with_data(client):
    resp = client.get("/api/kpis/series-multi", params={"kpi_name": "GMV"})
    assert resp.status_code == 200
    body = resp.json()
    site_ids = {s["site_id"] for s in body["by_site"]}
    assert site_ids == {"MLB", "MLM"}


def test_get_series_multi_invalid_kpi_name_returns_400(client):
    resp = client.get("/api/kpis/series-multi", params={"kpi_name": "NOT_A_KPI"})
    assert resp.status_code == 400


def test_get_series_multi_no_data_returns_404(client):
    resp = client.get("/api/kpis/series-multi", params={"kpi_name": "AOV"})
    assert resp.status_code == 404


def test_post_chat_returns_reply(client, monkeypatch):
    import main as main_mod
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    monkeypatch.setattr(
        main_mod.agent_mod, "chat_reply",
        lambda conn, message, history: (f"echo: {message}", None, None, usage),
    )
    resp = client.post("/api/chat", json={"message": "oi", "history": []})
    assert resp.status_code == 200
    assert resp.json() == {"reply": "echo: oi", "chart": None, "table": None, "usage": usage}


def test_post_chat_returns_chart_when_agent_provides_one(client, monkeypatch):
    import main as main_mod
    chart = {"kpi_name": "GMV", "site_id": "MLB", "periodicidade": "dia",
             "series": [{"label": "16-07", "valor": 1000.0}], "trend_line": [1000.0], "trend": "estavel"}
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    monkeypatch.setattr(
        main_mod.agent_mod, "chat_reply",
        lambda conn, message, history: ("aqui esta", chart, None, usage),
    )
    resp = client.post("/api/chat", json={"message": "grafico do gmv", "history": []})
    assert resp.status_code == 200
    assert resp.json()["chart"] == chart


def test_post_chat_returns_table_when_agent_provides_one(client, monkeypatch):
    import main as main_mod
    table = {"kpi_name": "GMV", "site_id": "MLB", "periodicidade": "dia",
             "rows": [{"label": "16-07", "valor": 1000.0}]}
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    monkeypatch.setattr(
        main_mod.agent_mod, "chat_reply",
        lambda conn, message, history: ("aqui esta", None, table, usage),
    )
    resp = client.post("/api/chat", json={"message": "tabela do gmv", "history": []})
    assert resp.status_code == 200
    assert resp.json()["table"] == table


def test_post_chat_missing_cache_returns_503(monkeypatch):
    monkeypatch.setenv("MAIN_KPIS_DB", "/tmp/does-not-exist-main-kpis-chat.db")
    import importlib
    import main as main_mod
    importlib.reload(main_mod)
    client = TestClient(main_mod.app)
    resp = client.post("/api/chat", json={"message": "oi", "history": []})
    assert resp.status_code == 503


def test_get_agents_status_returns_placeholder_when_no_supervisor_run_yet(client, monkeypatch):
    monkeypatch.setenv("MAIN_KPIS_MONITOR_STATUS", "/tmp/does-not-exist-monitor-status.json")
    resp = client.get("/api/agents/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "unknown"
    assert body["agents"] == []


def test_get_agents_status_returns_last_supervisor_snapshot(client, monkeypatch, tmp_path):
    status_doc = {
        "checked_at": "2026-07-20T12:25:00+00:00",
        "overall_status": "ok",
        "agents": [
            {"name": "databricks", "status": "ok", "last_run": "2026-07-20T12:25:00+00:00", "message": "all tables populated"},
            {"name": "dashboard", "status": "ok", "last_run": "2026-07-20T12:25:00+00:00", "message": "cache fresco, /health 200"},
            {"name": "chat", "status": "ok", "last_run": "2026-07-20T12:25:00+00:00", "message": "7/7 synthetic checks passed"},
        ],
    }
    status_path = tmp_path / "monitor_status.json"
    status_path.write_text(json.dumps(status_doc))
    monkeypatch.setenv("MAIN_KPIS_MONITOR_STATUS", str(status_path))

    resp = client.get("/api/agents/status")
    assert resp.status_code == 200
    assert resp.json() == status_doc


def test_post_databricks_status_writes_file(client, monkeypatch, tmp_path):
    status_path = tmp_path / "monitor" / "databricks_status.json"
    monkeypatch.setenv("MAIN_KPIS_DATABRICKS_STATUS", str(status_path))

    payload = {
        "checked_at": "2026-07-20T12:05:00Z",
        "status": "ok",
        "tables": {"faturamento_vendas": {"rows": 118, "expected_min": 1, "ok": True}},
        "message": "todas as tabelas populadas para 2026-07-19",
    }
    resp = client.post("/api/agents/databricks-status", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"written": True}
    assert json.loads(status_path.read_text()) == payload


def test_post_databricks_status_defaults_tables_and_message(client, monkeypatch, tmp_path):
    status_path = tmp_path / "databricks_status.json"
    monkeypatch.setenv("MAIN_KPIS_DATABRICKS_STATUS", str(status_path))

    resp = client.post("/api/agents/databricks-status", json={"checked_at": "2026-07-20T12:05:00Z", "status": "fail"})
    assert resp.status_code == 200
    written = json.loads(status_path.read_text())
    assert written["tables"] == {}
    assert written["message"] == ""
