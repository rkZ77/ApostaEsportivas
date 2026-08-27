"""Limiares do Player Stats.

Herda as decisoes que ja' foram tomadas (e discutidas) no motor de goleiros,
que este motor absorve:

  · FAIXA DE ODD [1.10, 2.00], reposta em 2026-08-16 a pedido do usuario. O
    teto e' a parte que mais importa: prop de jogador com odd alta nao e' odd
    generosa, e' o mercado dizendo que o evento e' raro -- e a estimativa do
    modelo tem erro proprio que pesa mais justamente na cauda. O piso baixo
    fica porque estatistica forte sai em odd BAIXA, nao alta.

  · O SCORE ORDENA, o corte duro aprova. Mesma separacao de faltas/goleiros.
"""
from __future__ import annotations

from services.pick_engine.market_pick_score import faixa_config

ODD_MIN = 1.10
ODD_MAX = 2.00

#: Config de score na faixa de odd deste motor -- reusa a mesma funcao que
#: faltas e goleiros usam, pra o "safety bonus" ser calculado do mesmo jeito.
SCORE_CONFIG = faixa_config(ODD_MIN, ODD_MAX)

#: Probabilidade minima pra um candidato virar pick.
PROB_MINIMA = 0.62

#: Margem minima sobre a odd oferecida. Prop de jogador tem spread largo; sem
#: um piso de edge o motor publicaria linha justa, que nao paga o erro do
#: modelo.
EDGE_MINIMO = 0.04

#: Onde o bonus de amostra satura no pick_score. Dez atuacoes de titular ja'
#: e' amostra boa pra prop de jogador -- exigir mais so' penalizaria jogador
#: que voltou de lesao sem melhorar a estimativa.
AMOSTRA_SATURACAO = 10

#: Um pick por JOGADOR por dia. Duas linhas do mesmo jogador (2+ e 3+ chutes)
#: sao a mesma aposta em graus diferentes: publicar as duas e' dobrar a
#: exposicao ao mesmo erro. Fica a de maior Score.
UM_PICK_POR_JOGADOR = True

#: Teto de picks por rodada, somando todos os metodos. Nao e' limite de
#: qualidade: e' pra uma falha de calibragem nao publicar cinquenta props de
#: uma vez.
MAX_PICKS_POR_RODADA = 10
