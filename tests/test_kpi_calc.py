import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import date
from kpi_calc import DailyFacts, aggregate_daily, rollup, kpis_from_facts


def _vendas(data_pedido, pedido_id, site_id, valor_bruto, status_pedido):
    return {"data_pedido": data_pedido, "pedido_id": pedido_id, "site_id": site_id,
            "valor_bruto": valor_bruto, "status_pedido": status_pedido}


def _logistica(pedido_id, site_id, data_prometida, data_despacho, data_entrega, houve_reclamacao):
    return {"pedido_id": pedido_id, "site_id": site_id, "data_prometida": data_prometida,
            "data_despacho": data_despacho, "data_entrega": data_entrega,
            "houve_reclamacao": houve_reclamacao}


def _marketing(data_registro, site_id, visitas, investimento_ads, faturamento_ads, novos_clientes):
    return {"data_registro": data_registro, "site_id": site_id, "visitas": visitas,
            "investimento_ads": investimento_ads, "faturamento_ads": faturamento_ads,
            "custo_marketing": 0.0, "novos_clientes": novos_clientes}


D = date(2026, 7, 16)


def test_aggregate_daily_gmv_only_counts_entregue():
    vendas = [
        _vendas(D, "P1", "MLB", 100.0, "entregue"),
        _vendas(D, "P2", "MLB", 50.0, "cancelado"),
    ]
    facts = aggregate_daily(vendas, [], [])
    f = facts[("MLB", D)]
    assert f.gmv == 100.0
    assert f.pedidos_entregues == 1
    assert f.pedidos_total == 2
    assert f.pedidos_cancelados == 1


def test_aggregate_daily_logistica_otd_and_reclamacao():
    vendas = [_vendas(D, "P1", "MLB", 100.0, "entregue")]
    logistica = [_logistica("P1", "MLB", date(2026, 7, 20), date(2026, 7, 17), date(2026, 7, 19), True)]
    facts = aggregate_daily(vendas, logistica, [])
    f = facts[("MLB", D)]
    assert f.entregas_total == 1
    assert f.entregas_no_prazo == 1
    assert f.reclamacoes == 1
    assert f.soma_dias_despacho == 1


def test_aggregate_daily_marketing_sums_by_site_and_day():
    marketing = [_marketing(D, "MLB", 1000, 200.0, 800.0, 30)]
    facts = aggregate_daily([], [], marketing)
    f = facts[("MLB", D)]
    assert f.visitas == 1000
    assert f.investimento_ads == 200.0
    assert f.faturamento_ads == 800.0
    assert f.novos_clientes == 30


def test_rollup_sums_multiple_days():
    f1 = DailyFacts(); f1.gmv = 100.0; f1.pedidos_entregues = 1
    f2 = DailyFacts(); f2.gmv = 50.0; f2.pedidos_entregues = 1
    total = rollup([f1, f2])
    assert total.gmv == 150.0
    assert total.pedidos_entregues == 2


def test_kpis_from_facts_all_formulas():
    f = DailyFacts()
    f.gmv = 1000.0; f.pedidos_entregues = 10; f.pedidos_total = 12; f.pedidos_cancelados = 2
    f.visitas = 100; f.investimento_ads = 200.0; f.faturamento_ads = 800.0; f.novos_clientes = 5
    f.entregas_total = 10; f.entregas_no_prazo = 8; f.reclamacoes = 1; f.soma_dias_despacho = 20

    kpis = kpis_from_facts(f, cumulative_gmv=5000.0, cumulative_novos_clientes=50)

    assert kpis["GMV"] == 1000.0
    assert kpis["AOV"] == 100.0
    assert round(kpis["CVR"], 2) == 0.12
    assert kpis["ROAS"] == 4.0
    assert kpis["OTD"] == 0.8
    assert kpis["TEMPO_DESPACHO"] == 2.0
    assert kpis["TAXA_RECLAMACAO"] == 0.1
    assert round(kpis["TAXA_CANCELAMENTO"], 4) == round(2 / 12, 4)
    assert kpis["CAC"] == 40.0
    assert kpis["LTV"] == 100.0


def test_kpis_from_facts_zero_denominator_returns_zero_not_error():
    f = DailyFacts()
    kpis = kpis_from_facts(f, cumulative_gmv=0.0, cumulative_novos_clientes=0)
    for k in ("AOV", "CVR", "ROAS", "OTD", "TEMPO_DESPACHO", "TAXA_RECLAMACAO", "TAXA_CANCELAMENTO", "CAC", "LTV"):
        assert kpis[k] == 0.0


def test_aggregate_daily_orphaned_logistica_pedido_does_not_crash():
    vendas = [_vendas(D, "P1", "MLB", 100.0, "entregue")]
    logistica = [
        _logistica("P1", "MLB", date(2026, 7, 20), date(2026, 7, 17), date(2026, 7, 19), False),
        _logistica("P_ORPHANED", "MLB", date(2026, 7, 20), date(2026, 7, 17), date(2026, 7, 19), False),
    ]
    facts = aggregate_daily(vendas, logistica, [])
    f = facts[("MLB", D)]
    assert f.entregas_total == 1
    assert f.entregas_no_prazo == 1
