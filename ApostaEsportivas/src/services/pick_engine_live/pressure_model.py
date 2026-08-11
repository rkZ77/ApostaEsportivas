"""Pressao ofensiva por equipe, derivada da folha de estatistica ao vivo.

POR QUE ISTO EXISTE
-------------------
"7 escanteios aos 35'" nao diz se o jogo vai produzir mais. Sete escanteios de
um time que finaliza 12 vezes, acerta 5 no alvo e vive no campo de ataque e'
uma coisa; sete escanteios num jogo travado, com dois chutes no total, e' o
oposto -- e o segundo caso regride pra media, o primeiro nao.

O total sozinho e' um placar. Pressao e' a leitura de se aquilo se sustenta.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao inventa numero. Componente que a API nao publicou simplesmente SAI da
conta, e os pesos dos que sobraram sao renormalizados -- em vez de entrar como
zero, que afirmaria "este time nao atacou nada". Quantos componentes
sobreviveram vai no rastro, porque uma pressao calculada com 2 sinais vale
menos que a mesma pressao calculada com 5.

POSSE NAO E' PRESSAO
--------------------
70% de posse nao e' 70% de pressao -- time que roda a bola no campo de defesa
tem posse alta e pressao nenhuma. Por isso posse tem o MENOR peso da tabela e
nunca decide sozinha; ela entra como confirmador dos outros sinais.

A ESCALA, E POR QUE ELA E' CENTRADA EM 0.5
------------------------------------------
Cada componente vira uma razao contra a taxa de referencia de um time medio,
truncada em 2x, e o score e' metade dessa razao. Isso da' uma leitura direta:

    0.50  time exatamente na media
    0.25  metade do volume de um time medio
    1.00  o dobro (teto)

Um score so' e' util se der pra ler sem tabela de conversao, e "0.5 e' normal"
e' a unica escala que faz isso. Os numeros de referencia estao abaixo e sao
explicitamente um ponto de partida: a calibracao vem depois, medindo contra
resultado.
"""
from __future__ import annotations

from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG, LiveEngineConfig

#: Taxa de referencia POR EQUIPE em 90 minutos (futebol de clubes). Nao sao
#: medidos deste projeto: sao valores tipicos de mercado, usados como regua
#: enquanto nao ha amostra propria. Trocar por medida real de
#: `match_statistics` e' melhoria natural da V2.
REFERENCIA_POR_90 = {
    "shots_on_target": 4.3,
    "shots": 12.0,
    "dangerous_attacks": 45.0,
    "corners": 5.1,
    "blocked_shots": 2.6,
    "expected_goals": 1.35,
}

#: Nome do contador na folha da API-Football. Levantado contra a resposta real
#: de /fixtures/statistics: os tipos publicados sao "Shots on Goal", "Shots off
#: Goal", "Total Shots", "Blocked Shots", "Shots insidebox", "Shots
#: outsidebox", "Fouls", "Corner Kicks", "Offsides", "Ball Possession",
#: "Yellow Cards", "Red Cards", "Goalkeeper Saves", "Total passes", "Passes
#: accurate", "Passes %" e "expected_goals".
#:
#: "Dangerous Attacks" NAO esta nessa lista -- e' por isso que o modelo trata
#: ausencia como caso normal e nao como falha. Fica mapeado porque parte das
#: ligas publica o campo, e quando publica ele vale.
CAMPO_NA_FOLHA = {
    "shots_on_target": "Shots on Goal",
    "shots": "Total Shots",
    "dangerous_attacks": "Dangerous Attacks",
    "corners": "Corner Kicks",
    "blocked_shots": "Blocked Shots",
    "expected_goals": "expected_goals",
}

#: Teto da razao contra a referencia. Um time 3x acima da media nao e' 3x mais
#: perigoso -- volume ofensivo satura, e sem teto um outlier de 10 minutos
#: dominaria o score. O teto de 2x tambem e' o que faz a escala fechar em 1.0.
TETO_RAZAO = 2.0

NIVEL_BAIXA = "BAIXA"
NIVEL_MEDIA = "MEDIA"
NIVEL_ALTA = "ALTA"
NIVEL_MUITO_ALTA = "MUITO_ALTA"

#: Cortes na escala centrada em 0.5 (= time medio). BAIXA e' "produzindo bem
#: menos que um time medio", MUITO_ALTA e' "produzindo bem mais".
CORTE_BAIXA, CORTE_MEDIA, CORTE_ALTA = 0.35, 0.50, 0.68


def _razao(valor: int | None, referencia: float, minuto: int) -> float | None:
    """Quanto o time produziu contra o que um time medio teria produzido no
    mesmo tempo de jogo. None quando o provedor nao publicou o contador."""
    if valor is None or minuto <= 0 or referencia <= 0:
        return None
    esperado_ate_agora = referencia * (minuto / 90.0)
    if esperado_ate_agora <= 0:
        return None
    return min(TETO_RAZAO, valor / esperado_ate_agora)


def _nivel(score: float) -> str:
    if score < CORTE_BAIXA:
        return NIVEL_BAIXA
    if score < CORTE_MEDIA:
        return NIVEL_MEDIA
    if score < CORTE_ALTA:
        return NIVEL_ALTA
    return NIVEL_MUITO_ALTA


def pressao_de_um_time(stats: dict, minuto: int, posse: int | None,
                       config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> dict:
    """Score 0-1 de um lado, com o rastro de cada componente."""
    componentes: list[dict] = []

    for chave, peso in (
        ("shots_on_target", config.peso_shots_on_target),
        ("shots", config.peso_shots),
        ("dangerous_attacks", config.peso_ataques_perigosos),
        ("corners", config.peso_escanteios),
        ("blocked_shots", config.peso_bloqueados),
        ("expected_goals", config.peso_xg),
    ):
        campo = CAMPO_NA_FOLHA[chave]
        razao = _razao(stats.get(campo), REFERENCIA_POR_90[chave], minuto)
        if razao is None:
            componentes.append({"sinal": chave, "valor": None, "peso": peso,
                                "disponivel": False})
            continue
        componentes.append({
            "sinal": chave, "valor": stats.get(campo), "razao": round(razao, 3),
            "normalizado": round(razao / TETO_RAZAO, 4), "peso": peso, "disponivel": True,
        })

    # Posse ja nasce numa escala 0-1 centrada em 0.5 quando dividida por 100 --
    # jogo equilibrado da' 50% pra cada lado, que e' exatamente o ponto neutro
    # da escala de pressao. Nao precisa de transformacao nenhuma.
    if posse is not None:
        componentes.append({"sinal": "possession", "valor": posse,
                            "normalizado": round(max(0.0, min(1.0, float(posse) / 100.0)), 4),
                            "peso": config.peso_posse, "disponivel": True})
    else:
        componentes.append({"sinal": "possession", "valor": None,
                            "peso": config.peso_posse, "disponivel": False})

    disponiveis = [c for c in componentes if c.get("disponivel")]
    peso_total = sum(c["peso"] for c in disponiveis)
    if not disponiveis or peso_total <= 0:
        return {"score": None, "nivel": None, "componentes": componentes,
                "sinais_disponiveis": 0,
                "motivo": "nenhum contador ofensivo publicado"}

    # Renormaliza sobre os que existem. Componente ausente NAO entra como zero
    # -- isso afirmaria que o time nao atacou, e o que houve foi a API nao ter
    # publicado o numero.
    score = sum(c["normalizado"] * c["peso"] for c in disponiveis) / peso_total
    return {
        "score": round(score, 4),
        "nivel": _nivel(score),
        "componentes": componentes,
        "sinais_disponiveis": len(disponiveis),
        "peso_coberto": round(peso_total, 3),
        "motivo": None,
    }


def pressao(home_stats: dict, away_stats: dict, minuto: int,
            config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> dict:
    """Pressao dos dois lados mais a leitura de dominio.

    `dominancia` e' a fatia do lado da casa (0.5 = equilibrio). E' o numero que
    interessa a mercado de EQUIPE; `total` e' o que interessa a mercado de
    partida (escanteios totais, gols totais).
    """
    casa = pressao_de_um_time(home_stats, minuto, home_stats.get("Ball Possession"), config)
    fora = pressao_de_um_time(away_stats, minuto, away_stats.get("Ball Possession"), config)

    if casa["score"] is None or fora["score"] is None:
        return {"home": casa, "away": fora, "total": None, "dominancia": None,
                "desequilibrio": None,
                "motivo": "pressao indisponivel em pelo menos um lado"}

    soma = casa["score"] + fora["score"]
    dominancia = round(casa["score"] / soma, 4) if soma > 0 else 0.5
    return {
        "home": casa,
        "away": fora,
        # Media dos dois lados: e' quanto a PARTIDA esta sendo jogada pra
        # frente, que e' o que alimenta mercado de total.
        "total": round(soma / 2, 4),
        "nivel_total": _nivel(soma / 2),
        "dominancia": dominancia,
        # 0 = equilibrado, 1 = um lado domina completamente. Jogo desequilibrado
        # produz mais escanteio pro lado forte e menos volume total no fim,
        # quando o placar ja resolveu.
        "desequilibrio": round(abs(dominancia - 0.5) * 2, 4),
        "motivo": None,
    }
