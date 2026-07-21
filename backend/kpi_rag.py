"""RAG de Sinônimos e Regras de Negócio — Main KPIs Dashboard.

Mapeia consultas em linguagem natural para os KPIs corretos usando:
1. Dicionário de sinônimos com pesos de confiança
2. Fuzzy matching para variações (difflib)
3. Regras de negócio (ex: "churn" = CANCELAMENTO, não RECLAMAÇÃO)
4. Contexto de domínio (e-commerce/logística)

Carregado em memória no startup — sem chamadas extras de LLM.
"""

import re
from difflib import SequenceMatcher

# ═══════════════════════════════════════════════════════════════════
# SINÔNIMOS E VARIAÇÕES POR KPI
# Formato: (termo, peso_confiança)
# ═══════════════════════════════════════════════════════════════════

KPI_SYNONYMS = {
    "GMV": [
        ("gmv", 1.0), ("gross merchandise value", 0.95),
        ("faturamento", 0.90), ("receita", 0.85), ("vendas", 0.80),
        ("valor bruto", 0.85), ("receita bruta", 0.85),
        ("quanto vendeu", 0.75), ("total vendido", 0.75),
        ("faturamento total", 0.85), ("vendas totais", 0.80),
        ("volume de vendas", 0.75), ("dinheiro entrou", 0.60),
    ],
    "AOV": [
        ("aov", 1.0), ("average order value", 0.95),
        ("ticket medio", 0.95), ("ticket médio", 0.95),
        ("tiquete medio", 0.85), ("valor medio por pedido", 0.85),
        ("valor médio por pedido", 0.85), ("pedido medio", 0.80),
        ("gasto medio", 0.70), ("ticket", 0.75),
        ("quanto gasta por compra", 0.65), ("valor por pedido", 0.80),
    ],
    "CVR": [
        ("cvr", 1.0), ("conversion rate", 0.95),
        ("taxa de conversao", 0.95), ("taxa de conversão", 0.95),
        ("conversao", 0.85), ("conversão", 0.85),
        ("taxa de visita", 0.70), ("visitantes que compraram", 0.65),
        ("efetividade", 0.60), ("quantos compraram", 0.60),
    ],
    "ROAS": [
        ("roas", 1.0), ("return on ad spend", 0.95),
        ("retorno sobre investimento", 0.85), ("retorno ads", 0.85),
        ("roi de marketing", 0.80), ("retorno de anuncio", 0.80),
        ("retorno de anúncio", 0.80), ("eficiencia de ads", 0.75),
        ("eficiência de ads", 0.75), ("marketing roi", 0.80),
    ],
    "OTD": [
        ("otd", 1.0), ("on-time delivery", 0.95),
        ("entregas no prazo", 0.95), ("entrega no prazo", 0.90),
        ("pontualidade", 0.85), ("taxa de pontualidade", 0.85),
        ("entregas pontuais", 0.80), ("prazo de entrega cumprido", 0.75),
        ("atrasos", 0.65), ("no prazo", 0.70),
    ],
    "TEMPO_DESPACHO": [
        ("tempo despacho", 1.0), ("tempo de despacho", 0.98),
        ("dispatch time", 0.90), ("tempo medio despacho", 0.95),
        ("tempo médio despacho", 0.95), ("tempo para enviar", 0.80),
        ("demora para despachar", 0.75), ("dias ate despacho", 0.80),
        ("dias até despacho", 0.80), ("lead time despacho", 0.75),
        ("tempo de preparo", 0.70), ("sla despacho", 0.65),
    ],
    "TAXA_RECLAMACAO": [
        ("taxa reclamacao", 1.0), ("taxa de reclamação", 0.98),
        ("taxa de reclamacao", 0.98), ("reclamacoes", 0.90),
        ("reclamações", 0.90), ("complaint rate", 0.85),
        ("indice de reclamacao", 0.85), ("índice de reclamação", 0.85),
        ("insatisfacao", 0.70), ("insatisfação", 0.70),
        ("clientes reclamando", 0.65), ("queixas", 0.65),
        ("problemas reportados", 0.60), ("reports de cliente", 0.55),
    ],
    "TAXA_CANCELAMENTO": [
        ("taxa cancelamento", 1.0), ("taxa de cancelamento", 0.98),
        ("cancelamentos", 0.90), ("cancellation rate", 0.85),
        ("churn", 0.90), ("churn rate", 0.95),
        ("taxa de churn", 0.95), ("rotatividade", 0.80),
        ("clientes perdidos", 0.75), ("abandono", 0.70),
        ("desistencia", 0.70), ("desistência", 0.70),
        ("pedidos cancelados", 0.85), ("perda de clientes", 0.75),
        ("drop rate", 0.65), ("attrition", 0.70),
    ],
    "CAC": [
        ("cac", 1.0), ("customer acquisition cost", 0.95),
        ("custo de aquisicao", 0.95), ("custo de aquisição", 0.95),
        ("custo adquirir cliente", 0.85), ("quanto custa cliente", 0.80),
        ("custo por cliente novo", 0.85), ("aquisicao", 0.75),
        ("aquisição", 0.75), ("cpa", 0.70),
    ],
    "LTV": [
        ("ltv", 1.0), ("lifetime value", 0.95),
        ("valor do ciclo de vida", 0.90), ("valor vitalicio", 0.85),
        ("valor vitalício", 0.85), ("customer lifetime value", 0.90),
        ("clv", 0.80), ("valor total do cliente", 0.80),
        ("receita por cliente", 0.75), ("lifetime", 0.75),
    ],
}

# ═══════════════════════════════════════════════════════════════════
# REGRAS DE NEGÓCIO — DESAMBIGUAÇÃO
# ═══════════════════════════════════════════════════════════════════

BUSINESS_RULES = {
    # "churn" em e-commerce = cancelamento, NÃO reclamação
    "churn": "TAXA_CANCELAMENTO",
    "churn rate": "TAXA_CANCELAMENTO",
    "rotatividade": "TAXA_CANCELAMENTO",
    # "reclamação" ≠ "cancelamento"
    "reclamacao": "TAXA_RECLAMACAO",
    "reclamação": "TAXA_RECLAMACAO",
    "queixa": "TAXA_RECLAMACAO",
    # "conversão" em e-commerce = CVR
    "conversao": "CVR",
    "conversão": "CVR",
    # "entrega" sem contexto = OTD (mais comum)
    "entrega": "OTD",
    "entregas": "OTD",
    # "marketing" = ROAS (mais provável) ou CAC
    "marketing": "ROAS",
    "anuncio": "ROAS",
    "anúncio": "ROAS",
    "ads": "ROAS",
}

# ═══════════════════════════════════════════════════════════════════
# CONTEXTO DE DOMÍNIO — EXPLICAÇÕES
# ═══════════════════════════════════════════════════════════════════

KPI_CONTEXT = {
    "GMV": {
        "formula": "Soma do valor bruto dos pedidos entregues",
        "fonte": "faturamento_vendas (Databricks)",
        "campos": ["valor_bruto", "status_pedido=entregue"],
        "dominio": "Vendas / Faturamento",
        "correlacionados": ["AOV", "CVR", "LTV"],
        "benchmark": "Varia muito por mercado. Brasil > México > Argentina",
    },
    "AOV": {
        "formula": "GMV ÷ pedidos_entregues",
        "fonte": "faturamento_vendas (Databricks)",
        "campos": ["gmv", "pedidos_entregues"],
        "dominio": "Vendas / Ticket",
        "correlacionados": ["GMV", "CVR"],
        "benchmark": "Brasil ~R$30-45, México ~R$20-30",
    },
    "CVR": {
        "formula": "pedidos_total ÷ visitas",
        "fonte": "faturamento_vendas + marketing_performance (Databricks)",
        "campos": ["pedidos_total", "visitas"],
        "dominio": "Conversão / Marketing",
        "correlacionados": ["GMV", "ROAS", "AOV"],
        "benchmark": "E-commerce LATAM: 2-5% é saudável",
    },
    "ROAS": {
        "formula": "faturamento_ads ÷ investimento_ads",
        "fonte": "marketing_performance (Databricks)",
        "campos": ["faturamento_ads", "investimento_ads"],
        "dominio": "Marketing / Performance",
        "correlacionados": ["CVR", "CAC", "GMV"],
        "benchmark": "ROAS > 3 é bom, > 5 é excelente",
    },
    "OTD": {
        "formula": "entregas_no_prazo ÷ entregas_total",
        "fonte": "logistica_entregas (Databricks)",
        "campos": ["data_entrega", "data_prometida"],
        "dominio": "Logística / SLA",
        "correlacionados": ["TEMPO_DESPACHO", "TAXA_RECLAMACAO"],
        "benchmark": "OTD > 95% é excelente, < 90% preocupa",
    },
    "TEMPO_DESPACHO": {
        "formula": "soma_dias_despacho ÷ entregas_total",
        "fonte": "logistica_entregas + faturamento_vendas (Databricks)",
        "campos": ["data_despacho", "data_pedido"],
        "dominio": "Logística / Operação",
        "correlacionados": ["OTD", "TAXA_RECLAMACAO"],
        "benchmark": "Ideal < 2 dias. Acima de 5 dias = alerta",
    },
    "TAXA_RECLAMACAO": {
        "formula": "reclamacoes ÷ entregas_total",
        "fonte": "logistica_entregas (Databricks)",
        "campos": ["houve_reclamacao"],
        "dominio": "Qualidade / CSAT",
        "correlacionados": ["OTD", "TEMPO_DESPACHO", "TAXA_CANCELAMENTO"],
        "benchmark": "< 5% aceitável, > 10% crítico",
        "nota": "MENOR = MELHOR. Reclamações indicam problema de qualidade, entrega ou produto.",
    },
    "TAXA_CANCELAMENTO": {
        "formula": "pedidos_cancelados ÷ pedidos_total",
        "fonte": "faturamento_vendas (Databricks)",
        "campos": ["status_pedido=cancelado"],
        "dominio": "Operação / Churn",
        "correlacionados": ["TAXA_RECLAMACAO", "OTD", "TEMPO_DESPACHO"],
        "benchmark": "< 5% saudável, > 10% preocupante",
        "nota": "MENOR = MELHOR. Cancelamento alto = problema no funil de compra ou pós-venda.",
    },
    "CAC": {
        "formula": "investimento_ads ÷ novos_clientes",
        "fonte": "marketing_performance (Databricks)",
        "campos": ["investimento_ads", "novos_clientes"],
        "dominio": "Marketing / Aquisição",
        "correlacionados": ["ROAS", "LTV", "CVR"],
        "benchmark": "Depende do LTV. CAC < LTV/3 é saudável",
        "nota": "MENOR = MELHOR. Custo menor para adquirir cliente = mais eficiente.",
    },
    "LTV": {
        "formula": "GMV_acumulado ÷ novos_clientes_acumulados",
        "fonte": "faturamento_vendas + marketing_performance (Databricks)",
        "campos": ["gmv acumulado", "novos_clientes acumulado"],
        "dominio": "Estratégia / Financeiro",
        "correlacionados": ["CAC", "GMV", "AOV"],
        "benchmark": "LTV > 3x CAC é o ideal",
    },
}

# ═══════════════════════════════════════════════════════════════════
# MOTOR DE BUSCA
# ═══════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """Remove acentos, lowercase, trim."""
    text = text.lower().strip()
    # Remove acentos comuns
    for a, s in [("á","a"),("à","a"),("ã","a"),("â","a"),("é","e"),("ê","e"),
                  ("í","i"),("ó","o"),("ô","o"),("õ","o"),("ú","u"),("ç","c")]:
        text = text.replace(a, s)
    return text


def resolve_kpi(query: str) -> dict:
    """Resolve uma query em linguagem natural para o KPI mais provável.

    Returns:
        {"kpi_name": str, "confidence": float, "matched_term": str,
         "context": dict|None, "alternatives": list}
    """
    query_norm = normalize(query)

    # 1. Regras de negócio (match exato de termos-chave)
    for term, kpi in BUSINESS_RULES.items():
        if normalize(term) in query_norm:
            return {
                "kpi_name": kpi,
                "confidence": 0.95,
                "matched_term": term,
                "context": KPI_CONTEXT.get(kpi),
                "alternatives": _find_alternatives(query_norm, kpi),
            }

    # 2. Sinônimos com fuzzy matching
    best_kpi = None
    best_score = 0.0
    best_term = ""

    for kpi_name, synonyms in KPI_SYNONYMS.items():
        for term, weight in synonyms:
            term_norm = normalize(term)
            # Match exato
            if term_norm in query_norm:
                score = weight
                if score > best_score:
                    best_score = score
                    best_kpi = kpi_name
                    best_term = term
            # Fuzzy match para variações
            else:
                ratio = SequenceMatcher(None, term_norm, query_norm).ratio()
                if ratio > 0.75:
                    score = weight * ratio
                    if score > best_score:
                        best_score = score
                        best_kpi = kpi_name
                        best_term = term

    if best_kpi and best_score > 0.4:
        return {
            "kpi_name": best_kpi,
            "confidence": round(best_score, 2),
            "matched_term": best_term,
            "context": KPI_CONTEXT.get(best_kpi),
            "alternatives": _find_alternatives(query_norm, best_kpi),
        }

    # 3. Nada encontrado — retorna None
    return {
        "kpi_name": None,
        "confidence": 0.0,
        "matched_term": "",
        "context": None,
        "alternatives": [],
    }


def _find_alternatives(query_norm: str, exclude_kpi: str) -> list:
    """Encontra KPIs alternativos que também podem corresponder."""
    alts = []
    for kpi_name, synonyms in KPI_SYNONYMS.items():
        if kpi_name == exclude_kpi:
            continue
        for term, weight in synonyms:
            if normalize(term) in query_norm and weight > 0.5:
                alts.append((kpi_name, weight))
                break
    return [{"kpi_name": k, "confidence": w} for k, w in sorted(alts, key=lambda x: -x[1])[:3]]


def get_kpi_info(kpi_name: str) -> dict:
    """Retorna informação completa sobre um KPI."""
    return KPI_CONTEXT.get(kpi_name, {})


def get_all_kpis() -> list:
    """Lista todos os KPIs com contexto."""
    return [{"name": k, **v} for k, v in KPI_CONTEXT.items()]


def explain_kpi(kpi_name: str) -> str:
    """Gera explicação em markdown para um KPI."""
    ctx = KPI_CONTEXT.get(kpi_name, {})
    if not ctx:
        return f"KPI '{kpi_name}' não encontrado."

    direction = "MAIOR = MELHOR" if kpi_name in ("GMV","AOV","CVR","ROAS","OTD","LTV") else "MENOR = MELHOR"

    return f"""**{kpi_name}** — {ctx.get('dominio', '')}

**Fórmula:** {ctx.get('formula', '')}
**Fonte:** {ctx.get('fonte', '')}
**Campos:** {', '.join(ctx.get('campos', []))}
**Regra:** {direction}
**Benchmark:** {ctx.get('benchmark', '')}
**KPIs relacionados:** {', '.join(ctx.get('correlacionados', []))}
{f"**Nota:** {ctx.get('nota', '')}" if ctx.get('nota') else ""}"""


if __name__ == "__main__":
    # Testes rápidos
    tests = [
        "churn", "taxa de cancelamento", "cancelamentos",
        "reclamacao", "tx de reclamação", "reclamações",
        "gmv", "faturamento", "quanto vendeu",
        "ticket medio", "tíquete médio",
        "conversao", "conversão",
        "roas", "retorno de ads",
        "entregas no prazo", "otd", "pontualidade",
        "tempo de despacho", "demora para enviar",
        "cac", "custo de aquisição",
        "ltv", "lifetime",
        "churn dos clientes", "abandono",
        "indice de reclamação",
    ]
    for t in tests:
        r = resolve_kpi(t)
        icon = "✅" if r["confidence"] > 0.7 else "⚠️" if r["confidence"] > 0.4 else "❌"
        print(f"{icon} '{t}' → {r['kpi_name']} ({r['confidence']}) [{r['matched_term']}]")
