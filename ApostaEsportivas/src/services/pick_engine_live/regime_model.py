"""Regime da partida: em que estado o jogo esta', e se o que falta explica o
que ja' aconteceu.

A DISTINCAO QUE ESTE MODULO EXISTE PRA FAZER
--------------------------------------------
Duas partidas com 2 escanteios aos 35 minutos:

    A) 3 finalizacoes no total, ninguem ataca, posse morta no meio
    B) 14 finalizacoes, 6 no alvo, xG 1.9 e nenhum gol

O motor residual le' as duas do mesmo jeito -- taxa observada baixa, projecao
baixa, Under. Mas sao jogos opostos: (A) e' BAIXA PRODUCAO, e produzir pouco
tende a continuar; (B) e' BAIXA CONVERSAO, e o que foi criado e nao virou
contagem tende a virar. Comprar Under em (B) e' comprar contra a pressao.

O QUE ELE FAZ, E O QUE DELIBERADAMENTE NAO FAZ
----------------------------------------------
FAZ: rotula o regime, mede producao e conversao separadamente, e devolve a
CONFIANCA do proprio rotulo (quantos insumos existiam pra decidi-lo).

NAO FAZ: nao multiplica a projecao. Pressao ja' entra na projecao por
`residual_model.ajuste_estado`, e ritmo por `rhythm_model.fator_de_ritmo` --
somar aqui um terceiro multiplicador feito dos MESMOS dois numeros seria
contar duas vezes o mesmo sinal, que e' o defeito que o pre-jogo pagou pra
remover da escolha por EV. O regime entra na decisao pelo caminho certo: como
insumo de contradicao (contradiction_model) e como rotulo no rastro.

ESCALA DOS NUMEROS QUE ELE LE
-----------------------------
    pressao.total   0.50 = dois times medios (pressure_model e' centrado nisso)
    ritmo.score     1.00 = a partida exatamente na media dela
"""
from __future__ import annotations

LOW_ACTIVITY = "LOW_ACTIVITY"
NORMAL = "NORMAL"
HIGH_ACTIVITY = "HIGH_ACTIVITY"
CHAOTIC = "CHAOTIC"
PRESSURE_HIGH = "PRESSURE_HIGH"
PRESSURE_LOW = "PRESSURE_LOW"
CONVERSION_LOW = "CONVERSION_LOW"
CONVERSION_HIGH = "CONVERSION_HIGH"
INDEFINIDO = "INDEFINIDO"

#: Cortes de producao e ritmo. Declarados, nao medidos -- ficam aqui pra serem
#: calibrados contra resultado quando houver amostra por regime.
PRODUCAO_BAIXA, PRODUCAO_ALTA = 0.80, 1.25     # razao contra o time medio
RITMO_BAIXO, RITMO_ALTO = 0.78, 1.25           # razao contra o esperado
CONVERSAO_BAIXA, CONVERSAO_ALTA = 0.65, 1.50   # observado / esperado pela producao

#: Volume MINIMO de producao pra a conversao significar alguma coisa.
#:
#: Conversao e' uma razao, e razao com denominador pequeno nao mede nada: um
#: jogo com xG 0.3 e nenhum gol aos 60 minutos tem conversao 0.00, e chamar
#: isso de CONVERSION_LOW seria dizer "criou e nao converteu" sobre uma partida
#: que nao criou -- exatamente a confusao entre BAIXA PRODUCAO e BAIXA
#: CONVERSAO que este modulo existe pra desfazer. Abaixo destes pisos a
#: conversao fica INDISPONIVEL e o regime cai nos rotulos de volume, que e' o
#: diagnostico certo pra um jogo morto.
XG_MINIMO_PRA_MEDIR_CONVERSAO = 0.90
BLOQUEIOS_MINIMOS_PRA_MEDIR_CONVERSAO = 2

#: Acima disto o jogo e' CHAOTIC: ritmo bem acima da media somado a um evento
#: que reescreve o resto da partida (expulsao ou goleada em formacao). Nao e'
#: "muita coisa acontecendo" -- e' "o que ja aconteceu mudou as regras".
RITMO_CAOTICO = 1.45


def _razao(valor: float | None, referencia: float) -> float | None:
    if valor is None or referencia <= 0:
        return None
    return round(float(valor) / referencia, 4)


def producao(pressao: dict | None) -> dict:
    """Quanto a partida esta' PRODUZINDO, contra dois times medios.

    Devolve tambem a cobertura da leitura: pressao calculada com 2 dos 7
    componentes descreve menos que a mesma pressao calculada com 6, e quem
    decide o que fazer com isso e' data_quality.
    """
    if not pressao or pressao.get("total") is None:
        return {"disponivel": False, "indice": None, "cobertura": 0.0,
                "motivo": "pressao indisponivel"}
    lados = [pressao.get("home") or {}, pressao.get("away") or {}]
    cobertos = [l.get("peso_coberto") for l in lados if l.get("peso_coberto")]
    cobertura = (sum(cobertos) / len(cobertos)) if cobertos else 0.0
    return {
        "disponivel": True,
        "indice": _razao(pressao["total"], 0.50),
        "nivel": pressao.get("nivel_total"),
        "cobertura": round(min(1.0, cobertura), 4),
        "motivo": None,
    }


def conversao(estado: dict, familia: str) -> dict:
    """Quanto do que foi CRIADO virou contagem, na unidade da familia.

    gols        gols marcados contra expected_goals -- a medida direta que a
                folha publica em boa parte das ligas.
    corners     escanteios contra a estimativa por chutes bloqueados: bloqueio
                vira escanteio com frequencia alta, e a proporcao tipica e' de
                ~1 bloqueio pra cada 2 escanteios (mesma constante que
                signal_score._sinal_qualidade_da_chance ja' usa -- uma so',
                nao duas copias).
    cards/fouls sem medida de conversao. Cartao nao e' convertido de nada e
                falta e' o proprio evento; devolver um numero aqui seria
                inventar. Indisponivel e' a resposta certa.
    """
    if familia == "goals":
        xg_casa, xg_fora = estado.get("xg_home"), estado.get("xg_away")
        gols = estado.get("goals_total")
        if xg_casa is None or xg_fora is None or gols is None:
            return {"disponivel": False, "indice": None,
                    "motivo": "expected_goals nao publicado"}
        esperado = float(xg_casa) + float(xg_fora)
        if esperado < XG_MINIMO_PRA_MEDIR_CONVERSAO:
            return {"disponivel": False, "indice": None,
                    "esperado": round(esperado, 3),
                    "motivo": f"expected_goals {esperado:.2f} baixo demais pra medir "
                              f"conversao: isto e' baixa PRODUCAO, nao baixa conversao"}
        return {"disponivel": True, "indice": round(float(gols) / esperado, 4),
                "observado": gols, "esperado": round(esperado, 3), "motivo": None}

    if familia == "corners":
        bloqueios = estado.get("blocked_shots_total")
        escanteios = estado.get("corners_total")
        if bloqueios is None or escanteios is None:
            return {"disponivel": False, "indice": None,
                    "motivo": "chutes bloqueados nao publicados"}
        if float(bloqueios) < BLOQUEIOS_MINIMOS_PRA_MEDIR_CONVERSAO:
            return {"disponivel": False, "indice": None,
                    "motivo": f"{bloqueios} bloqueio(s) nao medem conversao: isto e' "
                              f"baixa PRODUCAO, nao baixa conversao"}
        esperado = float(bloqueios) * 2.0
        return {"disponivel": True, "indice": round(float(escanteios) / esperado, 4),
                "observado": escanteios, "esperado": round(esperado, 3), "motivo": None}

    return {"disponivel": False, "indice": None,
            "motivo": f"conversao nao definida para {familia}"}


def regime(estado: dict, pressao: dict | None, ritmo: dict | None,
           eventos: dict | None, familia: str) -> dict:
    """O estado do jogo, com a confianca do proprio rotulo.

    A ordem dos testes e' a precedencia: CHAOTIC descreve a partida inteira e
    ganha de tudo; depois vem a divergencia entre producao e contagem (que e' o
    achado que este modulo existe pra produzir); e so' no fim os rotulos de
    volume, que sao os menos informativos porque ritmo e pressao ja' entram na
    projecao por conta propria.
    """
    prod = producao(pressao)
    conv = conversao(estado, familia)
    ritmo_score = (ritmo or {}).get("score")
    minuto = estado.get("minuto")
    diferenca = estado.get("diferenca_gols")

    insumos = sum(1 for x in (prod.get("disponivel"), conv.get("disponivel"),
                              ritmo_score is not None) if x)
    if insumos == 0:
        return {"estado": INDEFINIDO, "confianca": 0.0, "producao": prod,
                "conversao": conv, "motivos": ["nenhum insumo de regime disponivel"]}

    motivos: list[str] = []
    estado_regime = NORMAL

    vermelho = (eventos or {}).get("vermelho_minuto")
    caotico = (
        ritmo_score is not None and ritmo_score >= RITMO_CAOTICO
        and (vermelho is not None or (diferenca is not None and abs(diferenca) >= 3))
    )
    if caotico:
        estado_regime = CHAOTIC
        motivos.append(
            f"ritmo {ritmo_score:.2f}x com "
            + (f"expulsao aos {vermelho}'" if vermelho is not None
               else f"{abs(diferenca)} gols de diferenca"))
    elif conv.get("disponivel") and conv["indice"] <= CONVERSAO_BAIXA:
        estado_regime = CONVERSION_LOW
        motivos.append(
            f"criou {conv['esperado']} e converteu {conv['observado']} "
            f"({conv['indice']:.2f}x): producao sem contagem")
    elif conv.get("disponivel") and conv["indice"] >= CONVERSAO_ALTA:
        estado_regime = CONVERSION_HIGH
        motivos.append(
            f"converteu {conv['observado']} sobre {conv['esperado']} esperados "
            f"({conv['indice']:.2f}x): contagem acima do que foi criado")
    elif (prod.get("disponivel") and ritmo_score is not None
            and prod["indice"] >= PRODUCAO_ALTA and ritmo_score <= RITMO_BAIXO):
        estado_regime = PRESSURE_HIGH
        motivos.append(f"pressao {prod['indice']:.2f}x com ritmo {ritmo_score:.2f}x: "
                       f"o volume ainda nao virou contagem")
    elif (prod.get("disponivel") and ritmo_score is not None
            and prod["indice"] <= PRODUCAO_BAIXA and ritmo_score >= RITMO_ALTO):
        estado_regime = PRESSURE_LOW
        motivos.append(f"contagem {ritmo_score:.2f}x com pressao {prod['indice']:.2f}x: "
                       f"o acumulado veio de rajada, nao de dominio")
    elif (prod.get("disponivel") and prod["indice"] <= PRODUCAO_BAIXA
            and (ritmo_score is None or ritmo_score <= RITMO_BAIXO)):
        estado_regime = LOW_ACTIVITY
        motivos.append(f"pressao {prod['indice']:.2f}x e ritmo baixo: jogo travado dos dois lados")
    elif (prod.get("disponivel") and prod["indice"] >= PRODUCAO_ALTA
            and ritmo_score is not None and ritmo_score >= RITMO_ALTO):
        estado_regime = HIGH_ACTIVITY
        motivos.append(f"pressao {prod['indice']:.2f}x e ritmo {ritmo_score:.2f}x")
    else:
        motivos.append("producao e contagem dentro do esperado")

    # A confianca do rotulo e' quanto insumo existia pra decidi-lo, pesado pela
    # cobertura da pressao. Regime declarado com 1 dos 3 insumos e' um palpite
    # com nome, e quem le' precisa saber disso.
    confianca = (insumos / 3.0) * (0.5 + 0.5 * prod.get("cobertura", 0.0))
    if minuto is not None and int(minuto) < 25:
        # Cedo o regime descreve pouco: 20 minutos de jogo cabem numa rajada.
        confianca *= 0.75
        motivos.append("leitura cedo no jogo (< 25'), regime vale menos")

    return {
        "estado": estado_regime,
        "confianca": round(min(1.0, confianca), 4),
        "producao": prod,
        "conversao": conv,
        "ritmo_score": ritmo_score,
        "motivos": motivos,
    }


#: Regimes em que uma direcao especifica e' comprar contra a evidencia.
#:
#: CONVERSION_LOW + UNDER: o jogo criou e nao converteu. O motor residual le'
#: a contagem baixa e projeta baixo, mas o que foi criado tende a virar -- e' o
#: caso (B) do cabecalho, e e' o unico ponto do motor onde o Under fica
#: perigoso (o veto de Over em gols cobre o lado oposto).
#:
#: PRESSURE_LOW + OVER: o acumulado veio de rajada sem dominio. E' o mesmo
#: erro que `ritmos_vetados` ja corta no caso extremo (MUITO_ALTO), aqui na
#: forma fraca.
DIRECAO_CONTRA_O_REGIME = {
    (CONVERSION_LOW, "under"): "o jogo criou muito e converteu pouco: o Under compra contra o que foi criado",
    (PRESSURE_LOW, "over"): "a contagem veio de rajada sem dominio: o Over compra a continuacao de um pico",
    (CHAOTIC, "under"): "partida reescrita por expulsao ou goleada: o Under projeta sobre um jogo que acabou",
}
