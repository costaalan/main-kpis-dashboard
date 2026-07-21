#!/bin/bash
export MAIN_KPIS_DB=/opt/data/main-kpis-dashboard/data/kpi_cache.db
export MAIN_KPIS_DATABRICKS_STATUS=/opt/data/main-kpis-monitor/databricks_status.json
cd /opt/data/main-kpis-v2
exec .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8708
