import sys, os, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import cache_db


def _conn():
    conn = sqlite3.connect(":memory:")
    cache_db.init_db(conn)
    return conn


def _row(site_id="MLB", kpi_name="GMV", periodicidade="dia", periodo_key="2026-07-16",
         periodo_label="16-07", ano=2026, valor=1000.0):
    return {"site_id": site_id, "kpi_name": kpi_name, "periodicidade": periodicidade,
            "periodo_key": periodo_key, "periodo_label": periodo_label, "ano": ano, "valor": valor}


def test_write_and_get_row():
    conn = _conn()
    cache_db.write_kpi_rows(conn, [_row()])
    assert cache_db.get_row(conn, "MLB", "GMV", "dia", "2026-07-16") == 1000.0


def test_get_row_missing_returns_none():
    conn = _conn()
    cache_db.write_kpi_rows(conn, [_row()])
    assert cache_db.get_row(conn, "MLB", "GMV", "dia", "2026-07-15") is None


def test_write_kpi_rows_replaces_previous_contents():
    conn = _conn()
    cache_db.write_kpi_rows(conn, [_row(periodo_key="2026-07-15", valor=500.0)])
    cache_db.write_kpi_rows(conn, [_row(periodo_key="2026-07-16", valor=1000.0)])
    assert cache_db.get_row(conn, "MLB", "GMV", "dia", "2026-07-15") is None
    assert cache_db.get_row(conn, "MLB", "GMV", "dia", "2026-07-16") == 1000.0


def test_list_periods_descending_and_limit():
    conn = _conn()
    rows = [
        _row(periodo_key="2026-07-14", periodo_label="14-07", valor=100.0),
        _row(periodo_key="2026-07-15", periodo_label="15-07", valor=200.0),
        _row(periodo_key="2026-07-16", periodo_label="16-07", valor=300.0),
    ]
    cache_db.write_kpi_rows(conn, rows)
    result = cache_db.list_periods(conn, "MLB", "GMV", "dia", limit=2)
    assert [r["periodo_key"] for r in result] == ["2026-07-16", "2026-07-15"]


def test_list_series_ascending_full_history():
    conn = _conn()
    rows = [
        _row(periodo_key="2026-07-16", valor=300.0),
        _row(periodo_key="2026-07-14", valor=100.0),
        _row(periodo_key="2026-07-15", valor=200.0),
    ]
    cache_db.write_kpi_rows(conn, rows)
    result = cache_db.list_series(conn, "MLB", "GMV", "dia")
    assert [r["periodo_key"] for r in result] == ["2026-07-14", "2026-07-15", "2026-07-16"]


def test_get_last_refresh_set_on_write():
    conn = _conn()
    assert cache_db.get_last_refresh(conn) is None
    cache_db.write_kpi_rows(conn, [_row()])
    assert cache_db.get_last_refresh(conn) is not None


def test_queries_isolate_by_site_kpi_and_periodicidade():
    conn = _conn()
    cache_db.write_kpi_rows(conn, [
        _row(site_id="MLB", kpi_name="GMV", periodicidade="dia", periodo_key="2026-07-16", valor=100.0),
        _row(site_id="MLM", kpi_name="GMV", periodicidade="dia", periodo_key="2026-07-16", valor=200.0),
        _row(site_id="MLB", kpi_name="AOV", periodicidade="dia", periodo_key="2026-07-16", valor=300.0),
        _row(site_id="MLB", kpi_name="GMV", periodicidade="semana", periodo_key="2026-W29", valor=400.0),
    ])
    assert cache_db.get_row(conn, "MLB", "GMV", "dia", "2026-07-16") == 100.0
    assert cache_db.get_row(conn, "MLM", "GMV", "dia", "2026-07-16") == 200.0
    assert cache_db.get_row(conn, "MLB", "AOV", "dia", "2026-07-16") == 300.0
    assert cache_db.get_row(conn, "MLB", "GMV", "semana", "2026-W29") == 400.0
    assert len(cache_db.list_periods(conn, "MLB", "GMV", "dia")) == 1


def test_write_kpi_rows_empty_list_raises_instead_of_wiping():
    conn = _conn()
    cache_db.write_kpi_rows(conn, [_row()])
    import pytest
    with pytest.raises(ValueError):
        cache_db.write_kpi_rows(conn, [])
    assert cache_db.get_row(conn, "MLB", "GMV", "dia", "2026-07-16") == 1000.0
