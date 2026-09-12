"""Detector de contradicao (§34) -- quando os sinais nao contam a mesma historia.

O QUE UMA CONTRADICAO E'
------------------------
Nao e' um sinal fraco. Sinal fraco ja' tem tratamento: entra encolhido, desconta
qualidade de dado, custa pontos no Score. Contradicao e' quando DOIS sinais
apontam pra lados opostos, e a media deles nao descreve nenhum dos dois.

O exemplo que da' o tom: media alta com minutos esperados baixos. A media diz
"este jogador produz 2.4 chutes"; os minutos dizem "ele nao vai jogar o jogo em
que produzia 2.4". Publicar a media ajustada por um fator e' uma resposta
razoavel pra um desvio pequeno e uma resposta ERRADA pra um desvio grande --
porque o que mudou nao foi a escala, foi o regime.

CRITICA REPROVA, GRAVE DESCONTA
-------------------------------
Duas severidades, e a diferenca entre elas e' se o motor consegue PRECIFICAR a
contradicao ou nao:

    CRITICA   nao ha' como transformar em numero -> NO_PICK
    GRAVE     da' pra cobrar em probabilidade    -> desconto declarado

Nao ha' terceira classe de "aviso". Um aviso que nao muda nada e' enfeite de
auditoria, e este motor ja' teve um campo assim (o `ai_review` que nascia None
ate' 04/09 e fazia a auditoria ler "a IA nao vetou" onde a verdade era "a IA
nunca olhou").
"""
from __future__ import annotations

CRITICA = "CRITICA"
GRAVE = "GRAVE"

#: Quanto uma contradicao GRAVE custa em probabilidade, cada uma. Duas graves
#: custam o dobro, e o teto de desconto mora no chamador.
DESCONTO_GRAVE = 0.04

#: Teto do desconto somado. Alem disso, o que existe nao e' um pick caro: e' um
#: pick que o motor nao sabe avaliar, e o lugar dele e' o NO_PICK.
DESCONTO_MAX = 0.10


def _c(codigo: str, severidade: str, texto: str) -> dict:
    return {"codigo": codigo, "severidade": severidade, "texto": texto}


def detectar(*, analise: dict, disp: dict, margem: dict, frequencia: float | None,
             amostra: int | None, classe_amostra: str, minutos: dict,
             risco_minutos: str, risco_funcao: str, status_titular: str,
             adversario: dict | None, outliers_serie: list) -> list:
    """Todas as contradicoes deste candidato, da mais grave pra menos.

    Cada uma responde a um item do §34 e as tres primeiras estao la' nominadas.
    """
    achados = []
    prob = analise.get("probability") or 0

    # §34 · "media alta MAS minutos esperados baixos".
    fator = (minutos or {}).get("fator")
    if fator is not None and float(fator) <= 0.85:
        achados.append(_c(
            "MINUTOS_CONTRA_MEDIA", CRITICA,
            f"a média vem de atuações mais longas do que os "
            f"{(minutos or {}).get('esperados')} minutos esperados hoje"))
    elif fator is not None and float(fator) < 0.95:
        achados.append(_c(
            "MINUTOS_ABAIXO_DA_AMOSTRA", GRAVE,
            "expectativa de minutos abaixo do regime que gerou a média"))

    if risco_minutos == "HIGH":
        achados.append(_c("RISCO_DE_MINUTOS_ALTO", CRITICA,
                          "rodízio ou ausências recentes tornam os minutos imprevisíveis"))

    if status_titular in ("RESERVA", "DESCONHECIDO"):
        achados.append(_c(
            "TITULARIDADE_NAO_SUSTENTADA", CRITICA,
            "o jogador não tem titularidade provável medida na janela"))

    if risco_funcao == "HIGH":
        achados.append(_c("FUNCAO_INSTAVEL", CRITICA,
                          "o jogador vem sendo escalado em funções diferentes"))

    # §34 · "frequencia alta MAS projecao abaixo da linha". Os dois numeros
    # falam do mesmo evento e discordam do sinal -- e' o caso em que a media
    # esta' sendo puxada por poucas atuacoes e a frequencia por outras.
    if (frequencia is not None and float(frequencia) >= 0.7
            and (margem or {}).get("absoluta") is not None
            and float(margem["absoluta"]) <= 0):
        achados.append(_c(
            "FREQUENCIA_CONTRA_PROJECAO", CRITICA,
            "a linha foi batida na maioria das atuações mas a projeção fica abaixo dela"))

    # §34 · "probabilidade alta MAS amostra muito pequena".
    if prob >= 0.75 and classe_amostra in ("insuficiente", "muito limitada"):
        achados.append(_c(
            "CONFIANCA_SEM_AMOSTRA", CRITICA,
            f"probabilidade de {prob * 100:.0f}% sobre amostra {classe_amostra}"))
    elif prob >= 0.80 and classe_amostra == "limitada":
        achados.append(_c("CONFIANCA_ACIMA_DA_AMOSTRA", GRAVE,
                          "probabilidade alta sobre amostra limitada"))

    # §34 · historico favoravel MAS setor do adversario desfavoravel. Aqui o
    # adversario e' ajuste e nao sinal (ver opponent_model), entao ele so' vira
    # contradicao quando esta' no limite do que o ajuste pode deslocar.
    if (adversario or {}).get("disponivel") and adversario.get("limitado"):
        if float(adversario.get("razao_crua") or 1) < 1:
            achados.append(_c(
                "ADVERSARIO_CONTRA_A_MEDIA", GRAVE,
                "o adversário concede bem menos que a média da liga neste contador"))

    # §16 · outlier que sustenta a projecao. Se tirar o maior valor derruba a
    # media abaixo da linha, quem esta' pagando o pick e' um jogo so'.
    if outliers_serie and (margem or {}).get("absoluta") is not None:
        media_sem = _media_sem_outliers(disp, outliers_serie)
        if media_sem is not None and media_sem <= float(analise.get("linha") or 0):
            achados.append(_c(
                "PROJECAO_SUSTENTADA_POR_OUTLIER", CRITICA,
                "sem a atuação atípica a média fica abaixo da linha"))

    ordem = {CRITICA: 0, GRAVE: 1}
    return sorted(achados, key=lambda a: ordem.get(a["severidade"], 9))


def _media_sem_outliers(disp: dict, fora: list) -> float | None:
    """A media que sobra quando as atuacoes atipicas saem da conta.

    E' um NUMERO DE DIAGNOSTICO, nao a media que o motor usa. O §16 proibe
    excluir outlier automaticamente e este modulo respeita isso: a media do pick
    continua com tudo dentro, e o que sai daqui so' serve pra dizer se a
    projecao depende de um jogo.
    """
    n, media = disp.get("amostra") or 0, disp.get("media")
    if not n or media is None or not fora:
        return None
    restantes = n - len(fora)
    if restantes <= 0:
        return None
    return round((media * n - sum(fora)) / restantes, 3)


def desconto(achados: list) -> float:
    """Quanto as contradicoes GRAVES custam em probabilidade, somadas."""
    graves = sum(1 for a in achados if a["severidade"] == GRAVE)
    return round(min(graves * DESCONTO_GRAVE, DESCONTO_MAX), 4)


def criticas(achados: list) -> list:
    return [a for a in achados if a["severidade"] == CRITICA]
