"""Pure aggregation + KPI ratio math. No I/O, no Databricks, no SQLite."""

_FIELDS = (
    "gmv", "pedidos_entregues", "pedidos_total", "pedidos_cancelados",
    "visitas", "investimento_ads", "faturamento_ads", "novos_clientes",
    "entregas_total", "entregas_no_prazo", "reclamacoes", "soma_dias_despacho",
)


class DailyFacts:
    def __init__(self):
        self.gmv = 0.0
        self.pedidos_entregues = 0
        self.pedidos_total = 0
        self.pedidos_cancelados = 0
        self.visitas = 0
        self.investimento_ads = 0.0
        self.faturamento_ads = 0.0
        self.novos_clientes = 0
        self.entregas_total = 0
        self.entregas_no_prazo = 0
        self.reclamacoes = 0
        self.soma_dias_despacho = 0

    def merge(self, other):
        merged = DailyFacts()
        for field in _FIELDS:
            setattr(merged, field, getattr(self, field) + getattr(other, field))
        return merged


def aggregate_daily(vendas_rows, logistica_rows, marketing_rows):
    facts = {}
    pedido_lookup = {}

    for v in vendas_rows:
        key = (v["site_id"], v["data_pedido"])
        f = facts.setdefault(key, DailyFacts())
        f.pedidos_total += 1
        if v["status_pedido"] == "entregue":
            f.pedidos_entregues += 1
            f.gmv += v["valor_bruto"]
        elif v["status_pedido"] == "cancelado":
            f.pedidos_cancelados += 1
        pedido_lookup[v["pedido_id"]] = (v["data_pedido"], v["site_id"])

    for l in logistica_rows:
        lookup_result = pedido_lookup.get(l["pedido_id"])
        if lookup_result is None:
            continue
        data_pedido, site_id = lookup_result
        key = (site_id, data_pedido)
        f = facts.setdefault(key, DailyFacts())
        f.entregas_total += 1
        if l["data_entrega"] <= l["data_prometida"]:
            f.entregas_no_prazo += 1
        if l["houve_reclamacao"]:
            f.reclamacoes += 1
        f.soma_dias_despacho += (l["data_despacho"] - data_pedido).days

    for m in marketing_rows:
        key = (m["site_id"], m["data_registro"])
        f = facts.setdefault(key, DailyFacts())
        f.visitas += m["visitas"]
        f.investimento_ads += m["investimento_ads"]
        f.faturamento_ads += m["faturamento_ads"]
        f.novos_clientes += m["novos_clientes"]

    return facts


def rollup(daily_facts_list):
    total = DailyFacts()
    for f in daily_facts_list:
        total = total.merge(f)
    return total


def kpis_from_facts(facts, cumulative_gmv, cumulative_novos_clientes):
    def ratio(num, den):
        return num / den if den else 0.0

    return {
        "GMV": facts.gmv,
        "AOV": ratio(facts.gmv, facts.pedidos_entregues),
        "CVR": ratio(facts.pedidos_total, facts.visitas),
        "ROAS": ratio(facts.faturamento_ads, facts.investimento_ads),
        "OTD": ratio(facts.entregas_no_prazo, facts.entregas_total),
        "TEMPO_DESPACHO": ratio(facts.soma_dias_despacho, facts.entregas_total),
        "TAXA_RECLAMACAO": ratio(facts.reclamacoes, facts.entregas_total),
        "TAXA_CANCELAMENTO": ratio(facts.pedidos_cancelados, facts.pedidos_total),
        "CAC": ratio(facts.investimento_ads, facts.novos_clientes),
        "LTV": ratio(cumulative_gmv, cumulative_novos_clientes),
    }
