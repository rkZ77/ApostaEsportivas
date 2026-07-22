"""NOVO na Fase 1: ajuste deterministico de confidence baseado no
desempenho historico REAL por market_type (ai_performance_service.
get_calibration_rows()). Substitui a secao "CALIBRACAO" do prompt antigo, que
pedia pra IA "reduzir confidence pelo gap" em texto livre -- vira conta
fixa aqui, sem interpretacao.

gap = confidence_media_declarada_no_passado - hit_rate_real.
gap alto (>0.10) com amostra >=10 -> mercado historicamente superconfiante
-> penaliza exatamente pelo excesso. hit_rate muito baixo com amostra
robusta -> padrao negativo real -> penalidade maior. gap bem negativo ->
mercado conservador -> pequeno bonus. Amostra pequena -> ignora, dado
insuficiente pra confiar na correcao.

Duas granularidades (pedido do usuario, 2026-07-22): calcula por
(market_type, league_id) E por market_type isolado -- calibration_adjustment/
get_prior tentam a mais fina primeiro, caem pra agregada se a liga especifica
nao tiver amostra suficiente (mesmo espirito de fallback gracioso de
ranking.select_smart_safe_line).

Antes de contar um RED contra a calibracao, classifica o motivo
(red_analysis.classify_miss): so' "erro_real" (motor nao tinha sinal de
risco e ainda assim errou) e "sem_dado" (pick anterior a essa feature,
tratado como RED normal por continuidade) entram no denominador de
hit-rate. "evento_atipico" (cartao vermelho no jogo) e "variancia_esperada"
(motor ja tinha descontado confidence por dispersao alta) saem do calculo
inteiramente -- nao sao sinal de erro sistematico do modelo, contar contra
a calibracao ali seria aprender com ruido em vez de sinal real."""
from services.ai_performance_service import AIPerformanceService
from services.pick_engine import red_analysis

_MIN_N_FOR_ADJUSTMENT = 10
_GAP_OVERCONFIDENT_THRESHOLD = 0.10
_GAP_CONSERVATIVE_THRESHOLD = -0.05
_MIN_HIT_FOR_CONFIDENCE = 0.50
_MIN_N_FOR_HIT_FLOOR = 15
_CONSERVATIVE_BONUS = 0.02
_HIT_FLOOR_PENALTY = -0.10

# REDs nestas categorias nao contam pra hit-rate (nem como acerto, nem como
# erro informativo) -- ver docstring do modulo.
_RED_EXCLUDED_FROM_CALIBRATION = {"evento_atipico", "variancia_esperada"}


def _aggregate(rows: list) -> dict:
    """Agrega linhas cruas (ja filtradas pro grupo certo) em {n, hit, conf, gap}.
    `rows` = subset de get_calibration_rows() -- cada linha classificada via
    red_analysis.classify_miss antes de entrar ou nao no calculo."""
    included = []
    hits = 0
    for r in rows:
        if r["result"] == "GREEN":
            included.append(r)
            hits += 1
            continue
        # RED: classifica antes de decidir se conta
        verdict = red_analysis.classify_miss(r.get("engine_debug"), r.get("red_cards"))
        if verdict["category"] in _RED_EXCLUDED_FROM_CALIBRATION:
            continue
        included.append(r)  # erro_real ou sem_dado -- conta como RED normal

    n = len(included)
    if n == 0:
        return {"n": 0, "hit": 0.0, "conf": 0.0, "gap": 0.0}

    hit = round(hits / n, 3)
    conf_vals = [float(r["confidence"]) for r in included if r.get("confidence") is not None]
    conf = round(sum(conf_vals) / len(conf_vals), 3) if conf_vals else 0.0
    return {"n": n, "hit": hit, "conf": conf, "gap": round(conf - hit, 3)}


def get_market_calibration(days: int = 60) -> dict:
    """Retorna {"by_market_league": {(market_type, league_id): {n,hit,conf,gap}},
    "by_market": {market_type: {n,hit,conf,gap}}} a partir das linhas cruas de
    ai_performance_service.get_calibration_rows(). Cada pipeline decide a
    frequencia de refresh (nao ha cache aqui)."""
    rows = AIPerformanceService().get_calibration_rows(days=days)
    if not rows:
        return {"by_market_league": {}, "by_market": {}}

    by_market_league_rows: dict = {}
    by_market_rows: dict = {}
    for r in rows:
        mt = r.get("market_type") or "unknown"
        by_market_rows.setdefault(mt, []).append(r)
        if r.get("league_id") is not None:
            by_market_league_rows.setdefault((mt, r["league_id"]), []).append(r)

    return {
        "by_market_league": {k: _aggregate(v) for k, v in by_market_league_rows.items()},
        "by_market": {k: _aggregate(v) for k, v in by_market_rows.items()},
    }


def _resolve_stats(market_type: str, league_id: int | None, calibration: dict) -> dict | None:
    """Tenta (market_type, league_id) primeiro (amostra suficiente); cai pra
    market_type agregado (todas as ligas) se a liga especifica nao tiver dado
    ou amostra insuficiente. None se nem o agregado tiver amostra -- dado
    insuficiente em qualquer granularidade, nao ha correcao pra aplicar."""
    if league_id is not None:
        fine = calibration.get("by_market_league", {}).get((market_type, league_id))
        if fine and fine.get("n", 0) >= _MIN_N_FOR_ADJUSTMENT:
            return fine
    coarse = calibration.get("by_market", {}).get(market_type)
    if coarse and coarse.get("n", 0) >= _MIN_N_FOR_ADJUSTMENT:
        return coarse
    return None


def get_prior(market_type: str, calibration: dict, league_id: int | None = None) -> float | None:
    """Hit-rate real historico do market_type (com fallback por liga, ver
    _resolve_stats), pra uso como prior no encolhimento Bayesiano
    (bayesian_model.shrink_taxa) -- MESMO criterio de amostra que
    calibration_adjustment ja usa. None quando nenhuma granularidade sustenta
    um prior confiavel (nunca inventa)."""
    stats = _resolve_stats(market_type, league_id, calibration)
    return stats.get("hit") if stats else None


def calibration_adjustment(market_type: str, calibration: dict, league_id: int | None = None) -> float:
    """Delta deterministico pra somar ao confidence bruto, baseado no
    historico real desse market_type (com fallback por liga). Sempre 0 se
    amostra insuficiente em qualquer granularidade (nao ha correcao sem dado)."""
    stats = _resolve_stats(market_type, league_id, calibration)
    if not stats:
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
