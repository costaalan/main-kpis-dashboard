"""FastAPI backend for the Main KPIs dashboard. Reads only from the SQLite cache — never queries Databricks live."""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure backend/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent as agent_mod
import cache_db
import export_utils
import periods as periods_mod
import trend as trend_mod

SITES = ["MLB", "MLM", "MCO", "MLA", "MLC", "MLU"]
KPI_NAMES = ["GMV", "AOV", "CVR", "ROAS", "OTD", "TEMPO_DESPACHO", "TAXA_RECLAMACAO", "TAXA_CANCELAMENTO", "CAC", "LTV"]
# KPIs that are themselves a rate (stored as a 0-1 ratio in kpi_calc.py) — their period-over-period
# delta is an absolute point difference (pp), not a relative percentage (see periods.absolute_delta).
PERCENT_KPIS = {"CVR", "OTD", "TAXA_RECLAMACAO", "TAXA_CANCELAMENTO"}
DELTA_LABELS = {"dia": "DoD", "semana": "WoW", "mes": "MoM"}
MAX_PERIODOS = {"dia": 15, "semana": 10, "mes": 12}
STALE_AFTER_SECONDS = 60 * 60 * 30

_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

app = FastAPI(title="Main KPIs Dashboard API")


def _db_path():
    return os.environ.get("MAIN_KPIS_DB", "/app/data/kpi_cache.db")


def _get_conn():
    path = _db_path()
    if not os.path.exists(path):
        raise HTTPException(status_code=503, detail="Cache de KPIs ainda nao foi gerado")
    return sqlite3.connect(path)


def _is_stale(last_refresh_iso):
    if not last_refresh_iso:
        return True
    last = datetime.fromisoformat(last_refresh_iso)
    return (datetime.utcnow() - last).total_seconds() > STALE_AFTER_SECONDS


def _monitor_status_path():
    return os.environ.get(
        "MAIN_KPIS_MONITOR_STATUS",
        os.path.join(os.path.dirname(_db_path()), "monitor_status.json"),
    )


def _agent_log_path():
    return os.environ.get(
        "MAIN_KPIS_AGENT_LOG",
        os.path.join(os.path.dirname(_db_path()), "agent_log.json"),
    )


def _databricks_status_path():
    return os.environ.get("MAIN_KPIS_DATABRICKS_STATUS", "/app/monitor/databricks_status.json")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/agents/status")
def get_agents_status():
    """Serves the last Supervisor snapshot verbatim. No live checks triggered
    here — this only reads what the Supervisor cron already wrote."""
    path = _monitor_status_path()
    if not os.path.exists(path):
        return {"checked_at": None, "overall_status": "unknown", "agents": []}
    with open(path) as f:
        return json.load(f)


@app.get("/api/agents/log")
def get_agents_log():
    """Serves today's accumulated Supervisor runs (written by
    supervisor.append_to_daily_log — one run per Schedule Trigger fire, reset
    the moment the date rolls over so this file never accumulates across days)."""
    path = _agent_log_path()
    if not os.path.exists(path):
        return {"date": None, "runs": []}
    with open(path) as f:
        return json.load(f)


class DatabricksStatusPayload(BaseModel):
    checked_at: str
    status: str
    tables: dict = {}
    message: str = ""


@app.post("/api/agents/databricks-status")
def post_databricks_status(payload: DatabricksStatusPayload):
    """Written by the n8n "Agente Databricks" workflow after its daily D-1
    row-count checks. Lands on the /app/monitor mount (bind-mounted from the
    same host path the hermes-side supervisor.py reads directly), closing the
    Databricks -> Supervisor handoff without giving n8n filesystem access."""
    path = _databricks_status_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload.model_dump(), f, ensure_ascii=False, indent=2)
    return {"written": True}


@app.get("/api/kpis")
def get_kpis(
    periodicidade: str = Query("dia", pattern="^(dia|semana|mes)$"),
    ano: Optional[int] = None,
    site_id: Optional[str] = None,
    kpi_name: Optional[str] = None,
    num_periodos: int = Query(3, ge=1),
):
    conn = _get_conn()
    try:
        sites = [site_id] if site_id else SITES
        kpis = [kpi_name] if kpi_name else KPI_NAMES
        delta_label = DELTA_LABELS[periodicidade]
        num_periodos = min(num_periodos, MAX_PERIODOS[periodicidade])

        panels = []
        for site in sites:
            rows = []
            for kpi in kpis:
                recent = cache_db.list_periods(conn, site, kpi, periodicidade, limit=num_periodos)
                if ano:
                    recent = [r for r in recent if r["ano"] == ano]
                if not recent:
                    continue
                latest = recent[0]

                delta_fn = periods_mod.absolute_delta if kpi in PERCENT_KPIS else periods_mod.period_delta

                prev_key = periods_mod.previous_period_key(periodicidade, latest["periodo_key"])
                prev_valor = cache_db.get_row(conn, site, kpi, periodicidade, prev_key)
                delta_recente = delta_fn(latest["valor"], prev_valor)

                yoy_key = periods_mod.year_ago_period_key(periodicidade, latest["periodo_key"])
                yoy_valor = cache_db.get_row(conn, site, kpi, periodicidade, yoy_key)
                yoy = delta_fn(latest["valor"], yoy_valor)

                rows.append({
                    "kpi_name": kpi,
                    "periods": [{"label": r["periodo_label"], "valor": r["valor"]} for r in recent],
                    "delta_recente": {"label": delta_label, "valor": delta_recente},
                    "yoy": yoy,
                })
            panels.append({"site_id": site, "rows": rows})

        last_refresh = cache_db.get_last_refresh(conn)
        return {"panels": panels, "last_refresh_at": last_refresh, "stale": _is_stale(last_refresh)}
    finally:
        conn.close()


@app.get("/api/kpis/valor")
def get_valor(site_id: str, kpi_name: str, periodicidade: str, periodo_key: str):
    """Single ground-truth value lookup for one site/kpi/periodicidade/periodo_key.
    Used by the Chat Accuracy monitoring check (backend/monitor_checks.py), which
    runs from the hermes cron venv and has no groq dependency available there —
    this endpoint lets it fetch ground truth over HTTP instead of importing
    agent.py in-process."""
    if site_id not in SITES:
        raise HTTPException(status_code=400, detail="site_id invalido")
    if kpi_name not in KPI_NAMES:
        raise HTTPException(status_code=400, detail="kpi_name invalido")
    if periodicidade not in ("dia", "semana", "mes"):
        raise HTTPException(status_code=400, detail="periodicidade invalida")

    conn = _get_conn()
    try:
        valor = cache_db.get_row(conn, site_id, kpi_name, periodicidade, periodo_key)
        if valor is None:
            raise HTTPException(status_code=404, detail="Sem dado para essa combinacao")
        return {
            "site_id": site_id, "kpi_name": kpi_name,
            "periodicidade": periodicidade, "periodo_key": periodo_key, "valor": valor,
        }
    finally:
        conn.close()


@app.get("/api/kpis/anos")
def get_anos(periodicidade: Optional[str] = Query(None, pattern="^(dia|semana|mes)$")):
    conn = _get_conn()
    try:
        return {"anos": cache_db.list_anos(conn, periodicidade)}
    finally:
        conn.close()


@app.get("/api/kpis/series")
def get_series(
    kpi_name: str,
    site_id: str,
    periodicidade: str = Query("dia", pattern="^(dia|semana|mes)$"),
    num_periodos: Optional[int] = Query(None, ge=1),
):
    if kpi_name not in KPI_NAMES:
        raise HTTPException(status_code=400, detail="kpi_name invalido")
    if site_id not in SITES:
        raise HTTPException(status_code=400, detail="site_id invalido")

    conn = _get_conn()
    try:
        limit = min(num_periodos, MAX_PERIODOS[periodicidade]) if num_periodos else None
        series = cache_db.list_series(conn, site_id, kpi_name, periodicidade, limit=limit)
        if not series:
            raise HTTPException(status_code=404, detail="Sem dados para essa combinacao")

        values = [r["valor"] for r in series]
        trend_label, trend_line = trend_mod.classify_trend(list(enumerate(values)))

        return {
            "kpi_name": kpi_name,
            "site_id": site_id,
            "periodicidade": periodicidade,
            "series": [{"label": r["periodo_label"], "valor": r["valor"]} for r in series],
            "trend_line": trend_line,
            "trend": trend_label,
        }
    finally:
        conn.close()


@app.get("/api/kpis/series-multi")
def get_series_multi(
    kpi_name: str,
    periodicidade: str = Query("dia", pattern="^(dia|semana|mes)$"),
    num_periodos: Optional[int] = Query(None, ge=1),
):
    if kpi_name not in KPI_NAMES:
        raise HTTPException(status_code=400, detail="kpi_name invalido")

    conn = _get_conn()
    try:
        limit = min(num_periodos, MAX_PERIODOS[periodicidade]) if num_periodos else None
        by_site = []
        for site in SITES:
            series = cache_db.list_series(conn, site, kpi_name, periodicidade, limit=limit)
            if not series:
                continue
            values = [r["valor"] for r in series]
            trend_label, trend_line = trend_mod.classify_trend(list(enumerate(values)))
            by_site.append({
                "site_id": site,
                "series": [{"label": r["periodo_label"], "valor": r["valor"]} for r in series],
                "trend_line": trend_line,
                "trend": trend_label,
            })

        if not by_site:
            raise HTTPException(status_code=404, detail="Sem dados para esse KPI")

        return {"kpi_name": kpi_name, "periodicidade": periodicidade, "by_site": by_site}
    finally:
        conn.close()


class ChatRequest(BaseModel):
    message: str
    history: list = []


class ChatResponse(BaseModel):
    reply: str
    chart: Optional[dict] = None
    table: Optional[dict] = None
    usage: Optional[dict] = None


@app.post("/api/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest):
    conn = _get_conn()
    try:
        reply, chart, table, usage = agent_mod.chat_reply(conn, req.message, req.history)
        return {"reply": reply, "chart": chart, "table": table, "usage": usage}
    finally:
        conn.close()


class ExportRequest(BaseModel):
    messages: list = []
    site_id: Optional[str] = None


@app.post("/api/export/html")
def export_html(req: ExportRequest):
    """Generate a standalone HTML report from chat messages."""
    conn = _get_conn()
    try:
        html = export_utils.generate_html_report(conn, req.messages, req.site_id)
        return StreamingResponse(
            iter([html]),
            media_type="text/html",
            headers={"Content-Disposition": "attachment; filename=relatorio-kpis.html"},
        )
    finally:
        conn.close()


@app.post("/api/export/ppt")
def export_ppt(req: ExportRequest):
    """Generate a PowerPoint presentation from chat messages."""
    conn = _get_conn()
    try:
        ppt_bytes = export_utils.generate_ppt(conn, req.messages, req.site_id)
        return StreamingResponse(
            ppt_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": "attachment; filename=relatorio-kpis.pptx"},
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
