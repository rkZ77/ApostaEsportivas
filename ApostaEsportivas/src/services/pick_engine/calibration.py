"""NOVO na Fase 1: ajuste deterministico de confidence baseado no
desempenho historico REAL por market_type (ai_performance_service.
get_summary()). Substitui a secao "CALIBRACAO" do prompt antigo, que
pedia pra IA "reduzir confidence pelo gap" em texto livre -- vira conta
fixa aqui, sem interpretacao.

gap = confidence_media_declarada_no_passado - hit_rate_real.
gap alto (>0.10) com amostra >=10 -> mercado historicamente superconfiante
-> penaliza exatamente pelo excesso. hit_rate muito baixo com amostra
robusta -> padrao negativo real -> penalidade maior. gap bem negativo ->
mercado conservador -> pequeno bonus. Amostra pequena -> ignora, dado
insuficiente pra confiar na correcao.
"""
from services.ai_performance_service import AIPerformanceService

_MIN_N_FOR_ADJUSTMENT = 10
_GAP_OVERCONFIDENT_THRESHOLD = 0.10
_GAP_CONSERVATIVE_THRESHOLD = -0.05
_MIN_HIT_FOR_CONFIDENCE = 0.50
_MIN_N_FOR_HIT_FLOOR = 15
_CONSERVATIVE_BONUS = 0.02
_HIT_FLOOR_PENALTY = -0.10


def get_market_calibration(days: int = 60) -> dict:
    """Retorna {market_type: {n, hit, conf, gap}} usando o resumo real de
    ai_performance_service. Cada pipeline decide a frequencia de refresh
    (nao ha cache aqui)."""
    summary = AIPerformanceService().get_summary(days=days)
    if not summary:
        return {}
    return summary.get("por_mercado", {})


def get_prior(market_type: str, calibration: dict) -> float | None:
    """Hit-rate real historico do market_type, pra uso como prior no
    encolhimento Bayesiano (bayesian_model.shrink_taxa) -- MESMO limiar de
    confianca que calibration_adjustment ja usa (_MIN_N_FOR_ADJUSTMENT),
    nao um segundo criterio. None quando a amostra historica nao sustenta
    um prior confiavel (nunca inventa)."""
    stats = calibration.get(market_type)
    if not stats or stats.get("n", 0) < _MIN_N_FOR_ADJUSTMENT:
        return None
    return stats.get("hit")


def calibration_adjustment(market_type: str, calibration: dict) -> float:
    """Delta deterministico pra somar ao confidence bruto, baseado no
    historico real desse market_type. Sempre 0 se amostra insuficiente
    (nao ha correcao sem dado)."""
    stats = calibration.get(market_type)
    if not stats or stats.get("n", 0) < _MIN_N_FOR_ADJUSTMENT:
        return 0.0

    gap = stats.get("gap", 0.0)
    hit = stats.get("hit", 0.0)
    n = stats["n"]

    if hit < _MIN_HIT_FOR_CONFIDENCE and n >= _MIN_N_FOR_HIT_FLOOR:
        return _HIT_FLOOR_PENALTY

    if gap > _GAP_OVERCONFIDENT_THRESHOLD:
        return -round(gap, 4)
    if gap < _GAP_CONSERVATIVE_THRESHOLD:
        return _CONSERVATIVE_BONUS

    return 0.0
