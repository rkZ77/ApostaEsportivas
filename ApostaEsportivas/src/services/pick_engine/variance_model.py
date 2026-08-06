"""Variancia / desvio-padrao / coeficiente de variacao por mercado -- sinal
que falta hoje em stats_model.weighted_rate (que so devolve uma media
ponderada). Duas equipes podem ter a MESMA media com dispersao bem
diferente (ex.: 10,10,10,10,10 vs 2,18,5,15,10 -- mesma media 10, perfis
de risco completamente diferentes). A segunda e muito menos previsivel
mesmo com taxa igual, e deveria perder confidence por isso."""
import math

from services.pick_engine.stats_model import _extract_stat, pool_and_field

# Familias com leitura direta de valor bruto por partida (nao 0/1) -- btts/
# outcome/handicap/etc nao tem "o valor daquele jogo", so um hit binario,
# entao variancia nao se aplica a elas.
_VALUE_FAMILIES = {"goals", "corners", "cards", "shots", "shots_on_target", "offsides", "fouls"}


def variance_stats(family: str, scope: str, last10_home: list, last10_away: list,
                    team_id: int | None = None) -> dict | None:
    """Desvio-padrao populacional e coeficiente de variacao (CV = desvio/
    media) do valor bruto da familia/escopo, no pool de jogos correto. CV
    normaliza o desvio pela media -- compara dispersao entre mercados de
    escala diferente (cartoes ~3/jogo vs gols ~2.5/jogo) de forma justa.
    None se a familia nao suportar leitura de valor ou a amostra for
    pequena demais (<2 jogos, desvio nao faz sentido).

    `team_id` resolve o mando por partida (ver stats_model.resolve_side) --
    sem ele, num escopo home/away metade dos valores vem do adversario e a
    dispersao medida e' a do vai-e-vem entre os dois times, nao a do time
    analisado: inflava o CV e cobrava uma penalidade de confidence que o
    historico real nao justificava."""
    if family not in _VALUE_FAMILIES:
        return None

    pool, _ = pool_and_field(family, scope, last10_home, last10_away)
    if not pool or len(pool) < 2:
        return None

    values = [_extract_stat(m, family, scope, team_id) for m in pool]
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std_dev = math.sqrt(variance)
    cv = round(std_dev / mean, 4) if mean > 0 else None

    return {
        "mean": round(mean, 3),
        "std_dev": round(std_dev, 3),
        "coefficient_of_variation": cv,
        "amostra": n,
    }


# CV acima do limiar = mercado instavel (dispersao grande relativa a media)
# -- aplica penalidade de confidence proporcional, saturando no maximo em
# 2x o limiar (excesso de instabilidade alem disso nao pune mais que isso).
# Referencia: pra uma distribuicao Poisson pura, CV=1/sqrt(media) (ex.:
# media=10 -> CV~0.32 so de ruido aleatorio esperado). O limiar de 0.45
# fica acima disso pra so penalizar dispersao REAL (alem do que o proprio
# acaso Poisson ja explicaria), nao a variabilidade normal de contagens.
_CV_HIGH_THRESHOLD = 0.45
_CV_PENALTY_MAX = 0.10


def variance_penalty(cv: float | None) -> float:
    """Penalidade (0 a _CV_PENALTY_MAX) pra subtrair do confidence quando o
    coeficiente de variacao passa do limiar. CV None (familia sem leitura
    de valor, ou amostra <2) -> sem penalidade -- amostra pequena ja e
    coberta separadamente por Q, nao pune duas vezes pelo mesmo motivo."""
    if cv is None or cv <= _CV_HIGH_THRESHOLD:
        return 0.0
    excess = min(cv - _CV_HIGH_THRESHOLD, _CV_HIGH_THRESHOLD) / _CV_HIGH_THRESHOLD
    return round(excess * _CV_PENALTY_MAX, 4)
