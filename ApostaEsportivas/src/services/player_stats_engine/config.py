"""Limiares do Player Stats.

Herda as decisoes que ja' foram tomadas (e discutidas) no motor de goleiros,
que este motor absorve:

  · PISO DE ODD 1.44, SEM TETO (2026-09-04, decisao do usuario).

    Era [1.10, 2.00]. O piso subiu de 1.10 pra 1.44 e o teto caiu fora.

    O QUE O TETO FAZIA, pra quem for reconsiderar: prop de jogador com odd alta
    nao e' odd generosa, e' o mercado dizendo que o evento e' raro -- e a
    estimativa do modelo tem erro proprio que pesa mais justamente na cauda.
    Cortar em 2.00 era proteger contra o proprio erro na regiao onde ele e'
    maior.

    O QUE SEGURA A CAUDA SEM O TETO sao os cortes que ja' existiam e continuam:
    PROB_MINIMA de 62% recusa evento raro por definicao (a 62% a odd justa e'
    1.61, entao odd muito alta so' passa se o modelo discordar MUITO do
    mercado), e EDGE_MINIMO cobra margem sobre a odd oferecida. O que se perde
    e' a rede que agia sem olhar a probabilidade.

    E O SCORE CONTINUA ENXERGANDO UMA FAIXA -- ver SCORE_ODD_ALTA abaixo. Teto
    de PONTUACAO nao e' teto de corte: ele ordena candidatos, nao reprova
    nenhum.

  · O SCORE ORDENA, o corte duro aprova. Mesma separacao de faltas/goleiros.
"""
from __future__ import annotations

from services.pick_engine.market_pick_score import faixa_config

ODD_MIN = 1.44

#: Sem teto (2026-09-04). `None` e nao um numero grande: numero grande vira um
#: teto disfarcado que ninguem lembra de conferir, e a leitura "nao ha' teto"
#: fica explicita em quem le' o config e em quem le' a auditoria.
ODD_MAX = None

#: Onde o termo de seguranca do Score para de premiar odd baixa.
#:
#: Ele NAO reprova nada: o Score ordena candidatos entre si, e quem aprova sao
#: os cortes duros (PROB_MINIMA, EDGE_MINIMO, amostra). E' a separacao que este
#: motor herdou de faltas e goleiros, escrita no topo do arquivo.
#:
#: Fica em 2.00, que era o teto antigo, porque a pergunta que ele responde nao
#: mudou: acima disso o modelo esta' apostando contra o mercado numa regiao
#: onde o erro dele e' maior, e isso deve pesar na ORDEM. Sem uma referencia
#: aqui o termo pontuaria toda odd como se estivesse fora da faixa, que e' a
#: regiao onde a funcao despenca.
SCORE_ODD_ALTA = 2.00

#: Config de score na faixa deste motor -- reusa a mesma funcao que faltas e
#: goleiros usam, pra o "safety bonus" ser calculado do mesmo jeito.
SCORE_CONFIG = faixa_config(ODD_MIN, SCORE_ODD_ALTA)

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
