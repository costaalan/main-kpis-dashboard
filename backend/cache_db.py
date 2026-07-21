"""SQLite cache schema + read/write helpers for the Main KPIs dashboard."""

import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_values (
  site_id TEXT NOT NULL,
  kpi_name TEXT NOT NULL,
  periodicidade TEXT NOT NULL,
  periodo_key TEXT NOT NULL,
  periodo_label TEXT NOT NULL,
  ano INTEGER NOT NULL,
  valor REAL NOT NULL,
  PRIMARY KEY (site_id, kpi_name, periodicidade, periodo_key)
);
CREATE TABLE IF NOT EXISTS cache_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def write_kpi_rows(conn, rows):
    if not rows:
        raise ValueError("write_kpi_rows recebeu lista vazia — recusando apagar o cache existente")
    conn.execute("DELETE FROM kpi_values")
    conn.executemany(
        "INSERT INTO kpi_values (site_id, kpi_name, periodicidade, periodo_key, periodo_label, ano, valor) "
        "VALUES (:site_id, :kpi_name, :periodicidade, :periodo_key, :periodo_label, :ano, :valor)",
        rows,
    )
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('last_refresh_at', ?)",
        (datetime.datetime.utcnow().isoformat(),),
    )
    conn.commit()


def get_row(conn, site_id, kpi_name, periodicidade, periodo_key):
    cur = conn.execute(
        "SELECT valor FROM kpi_values WHERE site_id=? AND kpi_name=? AND periodicidade=? AND periodo_key=?",
        (site_id, kpi_name, periodicidade, periodo_key),
    )
    row = cur.fetchone()
    return row[0] if row else None


def list_periods(conn, site_id, kpi_name, periodicidade, limit=None):
    sql = (
        "SELECT periodo_key, periodo_label, ano, valor FROM kpi_values "
        "WHERE site_id=? AND kpi_name=? AND periodicidade=? ORDER BY periodo_key DESC"
    )
    params = (site_id, kpi_name, periodicidade)
    if limit:
        sql += " LIMIT ?"
        params = params + (limit,)
    cur = conn.execute(sql, params)
    return [{"periodo_key": r[0], "periodo_label": r[1], "ano": r[2], "valor": r[3]} for r in cur.fetchall()]


def list_series(conn, site_id, kpi_name, periodicidade, limit=None):
    if limit:
        cur = conn.execute(
            "SELECT periodo_key, periodo_label, ano, valor FROM ("
            "  SELECT periodo_key, periodo_label, ano, valor FROM kpi_values "
            "  WHERE site_id=? AND kpi_name=? AND periodicidade=? ORDER BY periodo_key DESC LIMIT ?"
            ") sub ORDER BY periodo_key ASC",
            (site_id, kpi_name, periodicidade, limit),
        )
    else:
        cur = conn.execute(
            "SELECT periodo_key, periodo_label, ano, valor FROM kpi_values "
            "WHERE site_id=? AND kpi_name=? AND periodicidade=? ORDER BY periodo_key ASC",
            (site_id, kpi_name, periodicidade),
        )
    return [{"periodo_key": r[0], "periodo_label": r[1], "ano": r[2], "valor": r[3]} for r in cur.fetchall()]


def list_anos(conn, periodicidade=None):
    if periodicidade:
        cur = conn.execute(
            "SELECT DISTINCT ano FROM kpi_values WHERE periodicidade=? ORDER BY ano DESC", (periodicidade,)
        )
    else:
        cur = conn.execute("SELECT DISTINCT ano FROM kpi_values ORDER BY ano DESC")
    return [r[0] for r in cur.fetchall()]


def get_last_refresh(conn):
    cur = conn.execute("SELECT value FROM cache_meta WHERE key='last_refresh_at'")
    row = cur.fetchone()
    return row[0] if row else None
