"""Modelo de defesas de goleiro (mercado Over/Under defesas).

Todos os numeros aqui foram medidos contra 1892 atuacoes reais de goleiro
(946 jogos de match_statistics em PROD, 2026-08-01), nao arbitrados.

DUAS DESCOBERTAS QUE DEFINEM O MODELO
-------------------------------------

1. Defesa e' quase mecanicamente chute-no-alvo-sofrido menos gol tomado:
   defesas/chutes_no_alvo = 0.678 e gols/chutes_no_alvo = 0.359 (soma 1.04).
   Correlacao entre defesas e chutes no alvo do adversario = 0.88. Ou seja,
   prever defesas e' prever o volume ofensivo do adversario.

2. A distribuicao e' FORTEMENTE SUPERDISPERSA: variancia/media = 1.80.
   Poisson erra +8.6pp na linha Over 1.5 (diz 72.0% onde o real e' 63.4%),
   o que viraria odd justa 1.39 em vez de 1.58 -- o motor acharia EV
   positivo em odd 1.45 que na verdade e' negativa. Por isso o modelo usa
   Binomial Negativa: erro absoluto acumulado de 14.8pp contra 33.5pp do
   Poisson, e na linha Over 1.5 erra so 0.7pp, PRA BAIXO (conservador --
   subestimar probabilidade nunca cria edge falso).

Nao trocar por Poisson "pra simplificar". A superdispersao e' o fato central
desse mercado.
"""
from __future__ import annotations

import math

from services.pick_engine.bayesian_model import shrink_taxa

# Defesas por chute no alvo sofrido (medido: 4800/7077).
SAVE_RATE_PER_SHOT_ON = 0.678

# Media de defesas por goleiro/jogo (medido: 4800/1892). Prior de encolhimento.
LEAGUE_MEAN_SAVES = 2.54

# Parametro de dispersao r da Binomial Negativa, por momentos:
# r = mu^2 / (var - mu) = 2.537^2 / (4.553 - 2.537).
DISPERSION_R = 3.19

# Taxa base de Over 1.5 defesas sem nenhum filtro (medido: 63.4%). Serve de
# referencia pra saber se um candidato realmente melhora sobre "chutar".
BASE_RATE_OVER_15 = 0.634

# Amostra minima de jogos do adversario pra confiar na media de chutes no
# alvo. Abaixo disso o backtest nao sustenta o filtro.
MIN_OPPONENT_SAMPLE = 5


def _nb_pmf(k: int, mu: float, r: float) -> float:
    """P(X = k) na Binomial Negativa parametrizada por media e dispersao."""
    if mu <= 0 or r <= 0:
        return 0.0
    log_p = (
        math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
        + r * math.log(r / (r + mu))
        + k * math.log(mu / (r + mu))
    )
    return math.exp(log_p)


def prob_over(line: float, mu: float, r: float = DISPERSION_R) -> float:
    """P(defesas > line). Para line=1.5 e' P(defesas >= 2).

    Soma as caudas de baixo (poucos termos) em vez da cauda de cima, que e'
    infinita.
    """
    if mu <= 0:
        return 0.0
    limite = math.floor(line)          # line=1.5 -> soma k=0 e k=1
    abaixo = sum(_nb_pmf(k, mu, r) for k in range(limite + 1))
    return max(0.0, min(1.0, 1.0 - abaixo))


def _const(constantes: dict | None, chave: str, padrao: float) -> float:
    """Constante recalibrada, ou a congelada quando nao houver.

    `constantes` vem de saves_calibration.recalibrar (2026-08-16). None mantem
    exatamente os numeros medidos em 01/08, que e' o que todo chamador que nao
    sabe da recalibragem continua vendo -- inclusive os testes que travam eles.
    """
    if not constantes:
        return padrao
    valor = constantes.get(chave)
    return padrao if valor is None else valor


def expected_saves(opponent_shots_on_avg: float | None,
                   keeper_saves_avg: float | None = None,
                   sample_size: int | None = None,
                   keeper_sample: int | None = None,
                   constantes: dict | None = None) -> float | None:
    """Defesas esperadas do goleiro neste jogo.

    Combina dois sinais e encolhe pra media da liga quando a amostra e'
    pequena (mesma logica de bayesian_model.shrink_taxa usada no resto do
    motor):

    - via adversario: quantos chutes no alvo ele costuma produzir, vezes a
      fracao que vira defesa. E' o sinal forte (correlacao 0.88).
    - via goleiro: a media historica de defesas dele. Captura o que o volume
      do adversario nao explica (qualidade da defesa, estilo de jogo).

    Retorna None se nao houver nem um dos dois -- nunca inventa numero.
    """
    base_liga = _const(constantes, "league_mean_saves", LEAGUE_MEAN_SAVES)

    sinais = []
    if opponent_shots_on_avg is not None and opponent_shots_on_avg > 0:
        sinais.append(opponent_shots_on_avg
                      * _const(constantes, "save_rate_per_shot_on", SAVE_RATE_PER_SHOT_ON))
    if keeper_saves_avg is not None and keeper_saves_avg > 0:
        # A MEDIA DO GOLEIRO E' ENCOLHIDA PELA AMOSTRA DELE (2026-08-20).
        #
        # Ate' aqui ela entrava crua na mistura, com peso 1/3, e o unico
        # encolhimento acontecia depois, sobre o blend, usando `sample_size`
        # -- que e' a quantidade de jogos do ADVERSARIO, nao do goleiro. Um
        # goleiro com UMA aparicao contribuia com o placar de defesas de um
        # jogo unico como se fosse a media dele, porque quem tinha 8 jogos era
        # o time que chuta contra ele.
        #
        # Medido em PROD: das 125 aparicoes com historico previo, 86 vem de
        # goleiro com 1 ou 2 jogos anteriores. Nao e' caso de borda, e' o caso
        # comum -- `player_match_stats` so' tem 240 aparicoes de goleiro na
        # base inteira.
        #
        # Nao e' regra nova: e' o mesmo encolhimento que o resto do motor ja'
        # aplica a toda taxa de amostra curta. O que estava errado era a
        # amostra que chegava aqui.
        encolhido_do_goleiro = shrink_taxa(keeper_saves_avg, keeper_sample, base_liga)
        sinais.append(encolhido_do_goleiro
                      if encolhido_do_goleiro is not None else keeper_saves_avg)
    if not sinais:
        return None

    # O sinal do adversario pesa o dobro: e' o que o backtest sustenta.
    mu = sinais[0] if len(sinais) == 1 else (sinais[0] * 2 + sinais[1]) / 3

    encolhido = shrink_taxa(mu, sample_size, base_liga)
    return round(encolhido if encolhido is not None else mu, 3)


def analyze_saves_market(opponent_shots_on_avg: float | None,
                         keeper_saves_avg: float | None,
                         sample_size: int | None,
                         odd: float | None,
                         line: float = 1.5,
                         constantes: dict | None = None,
                         keeper_sample: int | None = None) -> dict | None:
    """Candidato de pick de defesas, ou None se nao der pra avaliar.

    Devolve probabilidade, odd justa, edge e EV no mesmo formato que o resto
    do motor consome. Quem decide se aprova e' o ranking do pipeline, nao
    esta funcao -- aqui so' calcula.
    """
    if sample_size is not None and sample_size < MIN_OPPONENT_SAMPLE:
        return None

    mu = expected_saves(opponent_shots_on_avg, keeper_saves_avg, sample_size,
                        keeper_sample=keeper_sample, constantes=constantes)
    if mu is None:
        return None

    prob = prob_over(line, mu, _const(constantes, "dispersion_r", DISPERSION_R))
    if prob <= 0:
        return None

    odd_justa = round(1 / prob, 3)
    resultado = {
        "line": line,
        "expected_saves": mu,
        "probability": round(prob, 4),
        "fair_odd": odd_justa,
        "sample_size": sample_size,
        "lift_vs_base": round(
            prob - _const(constantes, "base_rate_over_15", BASE_RATE_OVER_15), 4),
    }
    if odd is not None and odd > 1:
        resultado["odd"] = float(odd)
        resultado["edge"] = round(prob - 1 / float(odd), 4)
        resultado["ev"] = round(prob * (float(odd) - 1) - (1 - prob), 4)
    return resultado
