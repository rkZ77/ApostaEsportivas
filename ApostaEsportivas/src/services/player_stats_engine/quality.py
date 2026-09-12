"""Dispersao, margem de projecao e qualidade do dado (§13, §15, §20, §22, §32).

TRES PERGUNTAS DIFERENTES, TRES NUMEROS DIFERENTES
--------------------------------------------------
O motor ja' produzia PROBABILIDADE. Ele nao produzia:

    o quanto essa probabilidade e' instavel     -> penalidade de variancia
    o quanto a projecao esta' longe da linha    -> margem de projecao
    o quanto o dado que a sustenta e' completo  -> qualidade do dado

Sao coisas distintas e o §18 do V2 cobra a separacao explicitamente: nunca
transformar `confidence` em `probabilidade`. Um jogador com media 2.5 e um com
media 2.2 contra a mesma linha 1.5 podem ter a mesma probabilidade e nao ter o
mesmo risco.

A REFERENCIA DE DISPERSAO E' POR METODO, E FOI MEDIDA
-----------------------------------------------------
Penalizar CV alto contra um limiar unico seria repetir o erro que o piso de
amostra ja' cometeu e que 10/09 corrigiu: os contadores nao estao na mesma
escala de dispersao. A reamostragem de PROD daquele dia deixou a tabela:

    saves       CV 0.65
    shots       CV 1.37
    shots_on    CV 1.90

Entao a pergunta nao e' "o CV deste jogador e' alto?" e sim "o CV deste jogador
e' alto PARA ESTE CONTADOR?". Um atacante com CV 1.4 em chutes no alvo e'
REGULAR; o mesmo 1.4 em defesas de goleiro seria um caso extremo. A penalidade
compara o jogador com a referencia do proprio metodo (`Metodo.cv_referencia`).

`pick_engine/variance_model.variance_penalty` nao serve aqui, e nao por
preguica: o limiar dele (0.45) foi derivado de contagem de TIME, onde CV 0.45 ja'
e' dispersao real. Aplicado a jogador, ele penalizaria no maximo todo mundo,
todo dia -- uma penalidade que atinge 100% dos candidatos nao ordena nada.
"""
from __future__ import annotations

import math

#: §13 -- classes de amostra. A classe e' o que entra na explicacao e na
#: contradicao; o CORTE continua sendo `Metodo.min_atuacoes`, que e' por metodo
#: e foi medido. Os dois nao competem: a classe descreve, o corte reprova.
def classificar_amostra(n: int | None) -> str:
    n = int(n or 0)
    if n < 5:
        return "insuficiente"
    if n <= 7:
        return "muito limitada"
    if n <= 12:
        return "limitada"
    if n <= 20:
        return "boa"
    return "forte"


def dispersao(valores: list) -> dict:
    """Media, mediana, extremos e CV da serie -- o §15 inteiro num dicionario.

    Media sozinha e' o jeito classico de errar contagem de jogador: 2,2,1,2,2,9,2
    e 3,3,3,3,3,3,2 tem medias parecidas e nao descrevem o mesmo jogador.
    """
    v = sorted(float(x) for x in (valores or []) if x is not None)
    if not v:
        return {"amostra": 0, "media": None, "mediana": None, "cv": None}
    n = len(v)
    media = sum(v) / n
    mediana = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    variancia = sum((x - media) ** 2 for x in v) / n
    desvio = math.sqrt(variancia)
    return {
        "amostra": n,
        "media": round(media, 3),
        "mediana": round(mediana, 3),
        "minimo": v[0],
        "maximo": v[-1],
        "desvio": round(desvio, 3),
        "cv": round(desvio / media, 3) if media > 0 else None,
        "variancia": round(variancia, 3),
    }


def outliers(valores: list, disp: dict) -> list:
    """Atuacoes que fogem da propria serie do jogador (§16).

    NAO REMOVE NADA. O §16 e' explicito: nao excluir automaticamente,
    interpretar. O motor nao tem como saber se o 9 veio de expulsao do
    adversario ou de um jogo caotico -- entao ele SINALIZA, a penalidade de
    variancia ja' cobra o preco da dispersao, e o valor continua na media.
    """
    if not disp.get("desvio") or disp["amostra"] < 4:
        return []
    media, desvio = disp["media"], disp["desvio"]
    return [float(v) for v in valores
            if v is not None and abs(float(v) - media) > 2.5 * desvio]


#: Teto da penalidade de variancia, em pontos de probabilidade. O mesmo teto de
#: 10 pontos que `variance_model` usa pro lado dos times -- o limiar muda por
#: metodo, o quanto ele pode custar no maximo nao.
PENALIDADE_MAX = 0.10


def penalidade_de_variancia(cv: float | None, cv_referencia: float | None) -> float:
    """0 a PENALIDADE_MAX. Zero quando o jogador e' tao disperso quanto o normal.

    Satura quando o CV do jogador chega ao DOBRO da referencia do metodo:
    dispersao alem disso nao e' mais informativa, e uma escala aberta faria um
    unico jogo esquisito zerar a probabilidade.
    """
    if not cv or not cv_referencia or cv_referencia <= 0 or cv <= cv_referencia:
        return 0.0
    excesso = min(cv - cv_referencia, cv_referencia) / cv_referencia
    return round(excesso * PENALIDADE_MAX, 4)


def margem_de_projecao(esperado: float | None, linha: float | None) -> dict:
    """§22 -- a distancia entre a projecao e a linha, absoluta e relativa.

    A relativa e' a que decide: 0.4 de folga sobre uma linha de 0.5 e' outra
    coisa que 0.4 sobre uma linha de 24.5 (passes). Sem normalizar, um piso
    unico de margem reprovaria todo mercado de contagem alta e liberaria todo
    mercado de contagem baixa.

    `direcao` sai daqui e nao do chamador porque e' consequencia dos numeros:
    projecao acima da linha sustenta Over, abaixo sustenta Under. Hoje o motor
    so' publica Over (§ do catalogo de mercados), mas a margem NEGATIVA precisa
    existir como numero pra o detector de contradicao poder ve-la.
    """
    if esperado is None or linha is None:
        return {"absoluta": None, "relativa": None, "direcao": None}
    absoluta = float(esperado) - float(linha)
    base = max(float(linha), 0.5)
    return {
        "absoluta": round(absoluta, 3),
        "relativa": round(absoluta / base, 4),
        "direcao": "over" if absoluta > 0 else "under" if absoluta < 0 else "neutro",
    }


#: Pesos da qualidade do dado. Somam 100 e nao sao medidos -- sao uma
#: DECLARACAO de o que o motor considera indispensavel, e estao aqui pra poder
#: ser discutidos num lugar so' em vez de espalhados em ifs pelo pipeline.
#:
#: A amostra pesa mais que tudo porque foi ela que explicou o gap medido em
#: 10/09 (o motor previa 75.9% e entregou 56.2% com media carregando 40-52% de
#: erro). O adversario pesa pouco porque neste motor ele e' ajuste, nao sinal --
#: ver opponent_model.
PESO_AMOSTRA = 35
PESO_MINUTOS = 25
PESO_TITULARIDADE = 20
PESO_RECENCIA = 10
PESO_ADVERSARIO = 10


def data_quality_score(*, amostra: int | None, min_atuacoes: int,
                       perfil_minutos: dict | None, status_titular: str,
                       risco_minutos: str, dias_desde_ultima: int | None,
                       adversario: dict | None) -> dict:
    """0 a 100 (§32), com a conta aberta -- o total sozinho nao se explica.

    Devolve os componentes porque a auditoria precisa responder POR QUE um pick
    ficou em 68: "amostra curta" e "sem dado de adversario" pedem acoes
    diferentes, e um numero unico apaga a diferenca.
    """
    componentes = {}

    # AMOSTRA · o piso do metodo vale a metade dos pontos; o dobro do piso vale
    # todos. Crescer sem teto premiaria ler a carreira inteira, que
    # `player_history.LIMITE_ATUACOES` ja' recusa de proposito.
    n = int(amostra or 0)
    if n <= 0 or min_atuacoes <= 0:
        componentes["amostra"] = 0
    else:
        razao = n / min_atuacoes
        componentes["amostra"] = round(PESO_AMOSTRA * min(max(razao / 2, 0.0), 1.0), 1)

    # MINUTOS · classe, nao numero: a folha nao sustenta precisao maior.
    componentes["minutos"] = {"LOW": PESO_MINUTOS,
                              "MEDIUM": PESO_MINUTOS * 0.5,
                              "HIGH": 0.0}.get(risco_minutos, 0.0)
    if not (perfil_minutos or {}).get("amostra"):
        componentes["minutos"] = 0.0

    componentes["titularidade"] = {"PROVAVEL_TITULAR": PESO_TITULARIDADE,
                                   "ALTERNA": PESO_TITULARIDADE * 0.4,
                                   "RESERVA": 0.0,
                                   "DESCONHECIDO": 0.0}.get(status_titular, 0.0)

    # RECENCIA · uma media de dois meses atras descreve um jogador que pode ter
    # trocado de funcao, de forma ou de time. 21 dias e' uma parada de selecao;
    # alem disso a amostra envelheceu.
    if dias_desde_ultima is None:
        componentes["recencia"] = 0.0
    elif dias_desde_ultima <= 10:
        componentes["recencia"] = PESO_RECENCIA
    elif dias_desde_ultima <= 21:
        componentes["recencia"] = PESO_RECENCIA * 0.6
    else:
        componentes["recencia"] = 0.0

    componentes["adversario"] = (PESO_ADVERSARIO if (adversario or {}).get("disponivel")
                                 else 0.0)

    total = round(sum(float(v) for v in componentes.values()), 1)
    return {"score": total, "componentes": {k: round(float(v), 1)
                                            for k, v in componentes.items()},
            "classificacao": _classe_de_qualidade(total)}


def _classe_de_qualidade(score: float) -> str:
    if score >= 90:
        return "excelente"
    if score >= 80:
        return "boa"
    if score >= 70:
        return "limitada"
    return "insuficiente"
