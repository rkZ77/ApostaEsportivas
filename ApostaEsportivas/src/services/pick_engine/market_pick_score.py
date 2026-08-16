"""Score de selecao dos pipelines de mercado proprio (faltas e goleiros).

POR QUE ESTE MODULO EXISTE
--------------------------
Ate' 2026-08-16 os dois pipelines escolhiam o candidato por MAIOR EDGE -- tanto
pra decidir a linha dentro de um jogo quanto pra ordenar os jogos entre si. O
motor generico abandonou esse criterio em 2026-08-14, com numero medido sobre os
65 picks ja' resolvidos do motor deterministico:

    edge de 10-20%   acertou 57,1%
    edge abaixo de 10%   acertou 71,4%

Edge maior anunciava linha PIOR, nao melhor, e isso tem explicacao: edge grande
contra mercado liquido quase sempre significa que a probabilidade do modelo
esta' otimista, nao que a casa errou. La' o peso do edge caiu de 0.25 pra 0.10 e
o da taxa subiu pra 0.40 (ver config.py). Aqui o edge seguia valendo 100% da
decisao, entao os dois pipelines continuavam fazendo exatamente o que o usuario
pediu pra o motor parar de fazer: "quero picks que ganham estatisticamente, nao
achar onde tem valor de odd" (2026-08-08, repetido em 16/08).

O QUE ENTRA, E POR QUE NAO E' COPIA EXATA DE ranking._line_score
---------------------------------------------------------------
O line_score do motor generico soma taxa, edge, seguranca na faixa, consenso de
bookmakers e estabilidade historica da linha. Dois desses nao existem aqui:

    bookmakers_count  os dois pipelines leem odd RAW (load_odds_by_fixture), que
                      nao agrupa por linha nem conta casas -- ver o comentario
                      em faltas_pipeline._avaliar_fixture explicando por que o
                      caminho estruturado descarta esses mercados.
    stability         line_stability e' calculada dentro do caminho generico de
                      stats_model, que nenhum dos dois percorre.

Os pesos dos dois (0.10 + 0.15 = 0.25) nao foram redistribuidos no chute: os
dois respondiam "o quanto eu confio NESTE numero", e o sinal equivalente que
existe aqui e' o tamanho da amostra que sustenta a estimativa. Por isso 0.17 vai
pra um termo de amostra e 0.08 reforca a taxa.

O peso do edge fica exatamente em 0.10, igual ao do motor generico. Esse numero
saiu de medicao, nao de gosto, e mexer nele junto com a troca do criterio
misturaria dois efeitos numa mudanca so'.

O QUE ESTE SCORE NAO FAZ
------------------------
Nao aprova nada. Os cortes continuam onde sempre estiveram, em cada pipeline:
faixa de odd, PROB_MIN e EDGE_MIN. Isto aqui so' ordena o que ja' passou -- a
mesma divisao de papeis que o motor generico tem entre evaluate_all_lines
(aprova) e _line_score (ordena).
"""
from __future__ import annotations

from services.pick_engine.config import PickEngineConfig
from services.pick_engine.ranking import _safety_bonus

# Somam 1.0. Ver a docstring do modulo pra a origem de cada um.
PESO_TAXA = 0.45
PESO_SEGURANCA = 0.28
PESO_AMOSTRA = 0.17
PESO_EDGE = 0.10

# Edge acima disto nao pontua mais que isto. Mesmo teto do _line_score generico:
# a partir de certo ponto edge grande e' sinal de estimativa otimista, entao
# deixar a escala aberta faria o outlier voltar a vencer pela porta dos fundos.
EDGE_TETO = 0.5


def faixa_config(odd_min: float, odd_max: float) -> PickEngineConfig:
    """Config so' pra o termo de seguranca enxergar a faixa DESTE pipeline.

    _safety_bonus mede a odd contra conservative_odd_low/high. Os pipelines de
    mercado proprio tem faixa propria ([1.10, 2.00] desde 2026-08-16), diferente
    da faixa 1.50-1.90 do VIP/Dica -- sem isto o termo pontuaria toda odd do
    pipeline como se estivesse abaixo do piso, que e' a regiao onde a funcao
    despenca.
    """
    return PickEngineConfig(
        conservative_odd_low=odd_min, conservative_odd_high=odd_max)


def amostra_bonus(amostra: int | None, saturacao: int) -> float:
    """0-1, satura em `saturacao` observacoes.

    Mesma forma do _bookmakers_bonus generico, e pelo mesmo motivo: mais
    evidencia sustentando o numero vale mais, com retorno decrescente. A
    saturacao e' por pipeline porque as duas amostras nao estao na mesma escala
    (jogos do adversario num mando, contra jogos da faixa da tabela empirica).

    Amostra ausente vale 0, nao neutro: aqui a ausencia e' informacao. Os dois
    modelos ja' recusam candidato sem amostra minima, entao o que chega aqui com
    amostra vazia e' caso de borda, e caso de borda nao merece pontos.
    """
    if not amostra or amostra <= 0 or saturacao <= 0:
        return 0.0
    return round(min(amostra / saturacao, 1.0), 4)


def pick_score(probability: float, odd: float, edge: float,
               amostra: int | None, amostra_saturacao: int,
               config: PickEngineConfig) -> float:
    """Pontuacao de um candidato ja' aprovado, pra ordenar contra os outros.

    probability e' a do modelo do mercado (tabela empirica em faltas, Binomial
    Negativa em goleiros) -- e' o analogo direto do taxa_real do motor generico.
    """
    edge_norm = min(max(edge or 0.0, 0.0), EDGE_TETO) / EDGE_TETO
    score = (
        (probability or 0.0) * PESO_TAXA
        + _safety_bonus(odd, config) * PESO_SEGURANCA
        + amostra_bonus(amostra, amostra_saturacao) * PESO_AMOSTRA
        + edge_norm * PESO_EDGE
    )
    return round(max(score, 0.0), 4)
