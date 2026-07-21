# /root/.hermes/main-kpis-dashboard/backend/kpi_cache.py
"""
Gerador do cache de KPIs — le as 3 tabelas do Databricks, calcula os 10 KPIs
x 6 sites x 3 granularidades (dia/semana/mes) e regrava data/kpi_cache.db.

Uso:
  python3 kpi_cache.py
"""

import json, os, sqlite3, time
import urllib.request
from datetime import date, datetime
from collections import defaultdict

import cache_db
import periods as periods_mod
from kpi_calc import aggregate_daily, rollup, kpis_from_facts

HERMES_HOME = os.environ.get("HERMES_HOME", "/opt/data")
TOKEN_FILE = os.path.join(HERMES_HOME, ".db_token")
DB_PATH = os.environ.get(
    "MAIN_KPIS_DB",
    os.path.join(HERMES_HOME, "main-kpis-dashboard", "data", "kpi_cache.db"),
)

HOST = "dbc-75ba99ea-3667.cloud.databricks.com"
WAREHOUSE = "d2d0a2c550cdaf76"

PERIODICIDADES = ["dia", "semana", "mes"]

TOKEN = None
AUTH = None


def _load_token():
    global TOKEN, AUTH
    if TOKEN is None:
        with open(TOKEN_FILE) as f:
            TOKEN = f.read().strip()
        AUTH = "Bearer " + TOKEN


def db_query(sql):
    """Same SQL Statements API pattern as scripts/gerador_main_kpis.py — copied, not imported."""
    _load_token()
    data = json.dumps({"statement": sql, "warehouse_id": WAREHOUSE}).encode()
    req = urllib.request.Request(
        "https://" + HOST + "/api/2.0/sql/statements",
        data=data,
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req, timeout=120)
    result = json.loads(r.read())
    statement_id = result.get("statement_id")
    status = result.get("status", {})

    for _ in range(60):
        state = status.get("state", "")
        if state in ("SUCCEEDED", "FAILED", "CANCELED"):
            break
        time.sleep(2)
        req2 = urllib.request.Request(
            "https://" + HOST + "/api/2.0/sql/statements/" + statement_id,
            headers={"Authorization": AUTH},
        )
        r2 = urllib.request.urlopen(req2, timeout=30)
        result = json.loads(r2.read())
        status = result.get("status", {})

    if status.get("state") != "SUCCEEDED":
        raise Exception("Query failed: " + json.dumps(status)[:200])

    manifest = result.get("manifest", {})
    rows = result.get("result", {}).get("data_array", [])
    chunks = manifest.get("chunks", [])
    if not rows:
        for chunk in chunks:
            chunk_rows = chunk.get("rows", [])
            if chunk_rows:
                rows.extend(chunk_rows)

    for chunk in chunks:
        link = chunk.get("external_link") or chunk.get("next_chunk_internal_link")
        if link and not rows:
            req3 = urllib.request.Request(
                "https://" + HOST + link,
                headers={"Authorization": AUTH}
            )
            r3 = urllib.request.urlopen(req3, timeout=30)
            ext = json.loads(r3.read())
            rows.extend(ext.get("result", {}).get("data_array", []))
            for c in ext.get("manifest", {}).get("chunks", []):
                rows.extend(c.get("rows", []))

    return rows


def _fetch_vendas():
    rows = db_query("SELECT data_pedido, pedido_id, site_id, valor_bruto, status_pedido FROM default.faturamento_vendas")
    return [
        {"data_pedido": date.fromisoformat(r[0]), "pedido_id": r[1], "site_id": r[2],
         "valor_bruto": float(r[3]), "status_pedido": r[4]}
        for r in rows
    ]


def _fetch_logistica():
    rows = db_query("SELECT pedido_id, site_id, data_prometida, data_despacho, data_entrega, houve_reclamacao FROM default.logistica_entregas")
    return [
        {"pedido_id": r[0], "site_id": r[1], "data_prometida": date.fromisoformat(r[2]),
         "data_despacho": date.fromisoformat(r[3]), "data_entrega": date.fromisoformat(r[4]),
         "houve_reclamacao": r[5] in ("true", "True", True)}
        for r in rows
    ]


def _fetch_marketing():
    rows = db_query("SELECT data_registro, site_id, visitas, investimento_ads, faturamento_ads, novos_clientes FROM default.marketing_performance")
    return [
        {"data_registro": date.fromisoformat(r[0]), "site_id": r[1], "visitas": int(r[2]),
         "investimento_ads": float(r[3]), "faturamento_ads": float(r[4]), "novos_clientes": int(r[5])}
        for r in rows
    ]


def _group_days_into_periods(day_keys_by_site, periodicidade):
    grouped = defaultdict(list)
    for site_id, days in day_keys_by_site.items():
        for d in days:
            grouped[(site_id, periods_mod.period_key(periodicidade, d))].append(d)
    return grouped


def build_cache_rows(vendas_rows, logistica_rows, marketing_rows):
    daily_facts = aggregate_daily(vendas_rows, logistica_rows, marketing_rows)

    days_by_site = defaultdict(set)
    for (site_id, d) in daily_facts.keys():
        days_by_site[site_id].add(d)
    days_by_site = {site: sorted(days) for site, days in days_by_site.items()}

    cumulative_gmv = {}
    cumulative_novos_clientes = {}
    for site_id, days in days_by_site.items():
        cumulative_gmv[site_id] = sum(daily_facts[(site_id, d)].gmv for d in days)
        cumulative_novos_clientes[site_id] = sum(daily_facts[(site_id, d)].novos_clientes for d in days)

    cache_rows = []
    for periodicidade in PERIODICIDADES:
        grouped = _group_days_into_periods(days_by_site, periodicidade)
        for (site_id, periodo_key), days in grouped.items():
            facts = rollup([daily_facts[(site_id, d)] for d in days])
            kpis = kpis_from_facts(facts, cumulative_gmv[site_id], cumulative_novos_clientes[site_id])
            label = periods_mod.period_label(periodicidade, periodo_key)
            ano = int(periodo_key.split("-")[0])
            for kpi_name, valor in kpis.items():
                cache_rows.append({
                    "site_id": site_id, "kpi_name": kpi_name, "periodicidade": periodicidade,
                    "periodo_key": periodo_key, "periodo_label": label, "ano": ano, "valor": valor,
                })
    return cache_rows


def main():
    vendas = _fetch_vendas()
    logistica = _fetch_logistica()
    marketing = _fetch_marketing()

    cache_rows = build_cache_rows(vendas, logistica, marketing)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cache_db.init_db(conn)
        cache_db.write_kpi_rows(conn, cache_rows)
    finally:
        conn.close()

    print(f"Cache atualizado: {len(cache_rows)} linhas em {DB_PATH} ({datetime.utcnow().isoformat()})")


if __name__ == "__main__":
    main()
