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
from datetime import datetime, timezone

from services.ai_performance_service import AIPerformanceService
from services.pick_engine import red_analysis

# Picks anteriores a esta data foram gerados com bugs reais de calculo de
# taxa ja corrigidos (cartao vermelho contando igual a amarelo; empate em
# linha redonda contando como vitoria em vez de PUSH -- ver stats_model.py).
# Confidence declarada nesses picks veio inflada/deflacionada por bug, nao
# por excesso/falta de confianca real do modelo -- deixar a calibracao
# aprender com esses gap"s ensinaria o motor a compensar um bug que ja nao
# existe mais (penalidade duplicada). Cai fora do calculo ate o proprio
# historico pos-fix acumular amostra suficiente organicamente.
_CALIBRATION_CUTOFF = datetime(2026, 7, 25, tzinfo=timezone.utc)

# Amostra minima pra o hit-rate virar PRIOR do encolhimento bayesiano
# (bayesian_model.shrink_taxa) -- ali o numero substitui a taxa empirica, entao
# precisa de um piso duro. A CORRECAO de confidence nao usa mais este corte:
# ver _evidence_weight.
_MIN_N_FOR_ADJUSTMENT = 10
_GAP_OVERCONFIDENT_THRESHOLD = 0.10
_GAP_CONSERVATIVE_THRESHOLD = -0.05
_MIN_HIT_FOR_CONFIDENCE = 0.50
_MIN_N_FOR_HIT_FLOOR = 15
_CONSERVATIVE_BONUS = 0.02
_HIT_FLOOR_PENALTY = -0.10

# Forca do encolhimento da CORRECAO de confidence. Mesma constante e mesma
# formula n/(n+k) que bayesian_model._DEFAULT_PRIOR_STRENGTH ja usa pra taxa --
# aqui o "prior" e' "nao corrigir nada", entao a correcao entra proporcional a
# evidencia acumulada em vez de tudo-ou-nada.
#
# Por que trocar o corte seco: com _MIN_N_FOR_ADJUSTMENT=10, n=9 recebia zero
# correcao e n=10 recebia a correcao INTEIRA. Medido em producao em 2026-08-03,
# dos 6 market_types com historico so' `corners` (n=10) passava do corte --
# `cards`, com o pior gap de todos (+0.323: declarava 82% e acertava 50%),
# ficava impune por ter n=2. E o gap de corners, +0.118 com n=10, e' MENOR que
# o proprio erro-padrao do hit-rate nessa amostra (sqrt(.7*.3/10) = 0.145), ou
# seja: a correcao inteira estava sendo aplicada em cima de ruido.
#
# Com n/(n+10): n=2 -> 17% da correcao, n=10 -> 50%, n=30 -> 75%, n=90 -> 90%.
# Todo mercado passa a ser corrigido na medida do que a amostra dele sustenta,
# e a correcao converge pro valor cheio conforme o historico cresce.
_EVIDENCE_STRENGTH = 10

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


def _after_cutoff(row: dict) -> bool:
    created_at = row.get("created_at")
    if created_at is None:
        return True  # sem data (dado antigo/teste) -- nao filtra por engano
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at >= _CALIBRATION_CUTOFF


def get_market_calibration(days: int = 60) -> dict:
    """Retorna {"by_market_league": {(market_type, league_id): {n,hit,conf,gap}},
    "by_market": {market_type: {n,hit,conf,gap}}} a partir das linhas cruas de
    ai_performance_service.get_calibration_rows(). Cada pipeline decide a
    frequencia de refresh (nao ha cache aqui). Filtra fora picks anteriores
    a _CALIBRATION_CUTOFF (ver comentario acima -- gerados com bug de taxa
    ja corrigido, nao contam pra calibracao)."""
    rows = [r for r in AIPerformanceService().get_calibration_rows(days=days) if _after_cutoff(r)]
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


def _resolve_stats(market_type: str, league_id: int | None, calibration: dict,
                    min_n: int = _MIN_N_FOR_ADJUSTMENT) -> dict | None:
    """Tenta (market_type, league_id) primeiro (amostra suficiente); cai pra
    market_type agregado (todas as ligas) se a liga especifica nao tiver dado
    ou amostra insuficiente. None se nem o agregado tiver amostra -- dado
    insuficiente em qualquer granularidade, nao ha correcao pra aplicar.

    `min_n` e' parametro porque os dois consumidores exigem coisas diferentes:
    get_prior() precisa de piso duro (o numero SUBSTITUI a taxa empirica),
    calibration_adjustment() nao (a correcao ja entra encolhida por
    _evidence_weight, entao amostra pequena vira correcao pequena, nao ausente)."""
    if league_id is not None:
        fine = calibration.get("by_market_league", {}).get((market_type, league_id))
        if fine and fine.get("n", 0) >= min_n:
            return fine
    coarse = calibration.get("by_market", {}).get(market_type)
    if coarse and coarse.get("n", 0) >= min_n:
        return coarse
    return None


def _evidence_weight(n: int) -> float:
    """Quanto da correcao a amostra sustenta: n/(n+k), de 0 a 1.

    Mesma formula de encolhimento bayesiano de bayesian_model.shrink_taxa,
    com o "prior" sendo nao corrigir nada. Substitui o corte seco em n>=10
    -- ver comentario em _EVIDENCE_STRENGTH."""
    if n <= 0:
        return 0.0
    return round(n / (n + _EVIDENCE_STRENGTH), 4)


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
    historico real desse market_type (com fallback por liga), ENCOLHIDO pela
    evidencia que a amostra sustenta (ver _evidence_weight).

    Sem nenhum historico do mercado -> 0 (nao ha o que corrigir). Com
    historico curto -> correcao pequena na direcao certa, em vez do zero
    absoluto de antes. A granularidade fina (market_type, league_id) so' e'
    usada quando tem amostra propria suficiente; senao cai pro agregado, e o
    encolhimento usa o n da granularidade que de fato respondeu."""
    # min_n=1: qualquer historico ja' informa alguma coisa. O peso da correcao
    # e' que varia com n -- nao a existencia dela.
    stats = _resolve_stats(market_type, league_id, calibration, min_n=1)
    if not stats:
        return 0.0

    gap = stats.get("gap", 0.0)
    hit = stats.get("hit", 0.0)
    n = stats["n"]
    peso = _evidence_weight(n)

    # Piso de hit-rate continua exigindo amostra robusta ANTES de disparar:
    # e' a penalidade mais dura do modulo e nao pode ser acionada por um par
    # de REDs em sequencia. Passando do piso, ainda entra encolhida.
    if hit < _MIN_HIT_FOR_CONFIDENCE and n >= _MIN_N_FOR_HIT_FLOOR:
        return round(_HIT_FLOOR_PENALTY * peso, 4)

    if gap > _GAP_OVERCONFIDENT_THRESHOLD:
        return -round(gap * peso, 4)
    if gap < _GAP_CONSERVATIVE_THRESHOLD:
        return round(_CONSERVATIVE_BONUS * peso, 4)

    return 0.0
