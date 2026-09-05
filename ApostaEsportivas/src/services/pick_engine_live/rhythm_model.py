"""Ritmo da partida, janelas recentes e tendencia (acelerando/desacelerando).

O PROBLEMA DA FONTE
-------------------
/fixtures/statistics devolve APENAS acumulado. Nao existe "escanteios nos
ultimos 10 minutos" no feed -- existe "escanteios ate agora". Entao janela
recente nao e' algo que se pede a API: e' algo que se constroi guardando
leituras e subtraindo.

E' por isso que o pipeline grava `live_match_observations` a cada passada,
mesmo quando nao gera pick. Cada rodada custa uma leitura que ja foi paga, e
duas leituras viram uma janela. Tres viram uma tendencia.

Consequencia honesta: na PRIMEIRA rodada sobre uma partida o motor nao tem
ritmo nem tendencia, e isso aparece no rastro como tal. Ele nao finge ter.

TENDENCIA PRECISA DE DUAS JANELAS
---------------------------------
Saber que o jogo esta rapido nao basta -- 4 escanteios em 10 minutos significa
coisas opostas se os 10 minutos anteriores tiveram 1 ou tiveram 5. Por isso a
tendencia compara a janela recente com a janela ANTERIOR equivalente, nao com
a media do jogo.
"""
from __future__ import annotations

from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG, LiveEngineConfig

#: Referencia de PARTIDA INTEIRA (os dois times somados) em 90 minutos. Mesma
#: natureza dos numeros de pressure_model.REFERENCIA_POR_90: ponto de partida
#: declarado, nao medida deste projeto.
REFERENCIA_PARTIDA_POR_90 = {
    "corners": 10.2,
    "cards": 4.1,
    "shots": 24.0,
    "shots_on_target": 8.6,
    "goals": 2.72,
    "dangerous_attacks": 90.0,
    # MEDIDO, ao contrario dos de cima: 24.82 faltas por partida em 1.189
    # partidas encerradas de `match_statistics` (2026-09-04). Fica junto dos
    # declarados porque a pergunta e' a mesma; o rastro de origem e' este
    # comentario.
    "fouls": 24.82,
}

RITMO_BAIXO = "BAIXO"
RITMO_MEDIO = "MEDIO"
RITMO_ALTO = "ALTO"
RITMO_MUITO_ALTO = "MUITO_ALTO"

ACELERANDO = "ACELERANDO"
DESACELERANDO = "DESACELERANDO"
ESTAVEL = "ESTAVEL"
INDEFINIDA = "INDEFINIDA"

#: Minimo de eventos na soma das duas janelas pra a tendencia significar algo.
#: Com 1 escanteio de um lado e 0 do outro, qualquer razao vira +infinito ou
#: zero -- e' ruido com cara de sinal.
EVENTOS_MINIMOS_TENDENCIA = 3

#: Quanto do desvio da janela recente entra no fator de ritmo, e o teto dele.
#:
#: OS DOIS EXISTEM PRA CONTER A MESMA COISA: DUPLA CONTAGEM DA RAJADA.
#: A janela recente ja esta DENTRO do acumulado que produziu `taxa_estimada` --
#: os 4 escanteios dos ultimos 10 minutos sao parte dos 7 do jogo. Multiplicar
#: a taxa (ja elevada pela rajada) pelo fator de ritmo (que mede a mesma
#: rajada) conta o mesmo evento duas vezes.
#:
#: Foi medido num cenario real de validacao: 7 escanteios aos 38' com 4 nos
#: ultimos 10 projetavam 20.4 no total com amortecimento 0.5 e teto 1.55 --
#: percentil 95 de uma partida, tratado como cenario central. Com 0.35 e 1.35
#: a mesma partida projeta ~17, que e' agressivo mas defensavel.
#:
#: Escanteio vem em rajada por natureza (escanteio gera escanteio), entao a
#: rajada e' informacao real -- ela so' nao pode ser projetada inteira pro
#: resto do jogo. Numeros de partida declarados, pra calibrar contra resultado.
AMORTECIMENTO = 0.35
RITMO_MIN, RITMO_MAX = 0.72, 1.35

#: Quantos eventos uma janela precisa carregar pra valer metade do seu desvio.
#: 2 e' o ponto em que uma janela deixa de ser anedota: com 4 escanteios contra
#: 1.5 esperados o peso passa de 55%, com 0 contra 0.8 ele fica em ~16%.
INFORMACAO_DE_REFERENCIA = 2.0


def _nivel_ritmo(score: float) -> str:
    if score < 0.75:
        return RITMO_BAIXO
    if score < 1.00:
        return RITMO_MEDIO
    if score < 1.30:
        return RITMO_ALTO
    return RITMO_MUITO_ALTO


def ritmo(estado: dict, minuto: int) -> dict:
    """Quanto a partida esta produzindo contra o que uma partida media
    produziria no mesmo tempo. 1.0 = exatamente na media.

    Combina as familias disponiveis com peso igual: nenhuma delas e' mais
    "verdadeira" que a outra pra medir andamento de jogo, e ponderar aqui seria
    inventar hierarquia sem base.
    """
    if minuto <= 0:
        return {"score": None, "nivel": None, "familias": [],
                "motivo": "minuto invalido"}

    fracao = minuto / 90.0
    familias = []
    for chave, observado in (
        ("corners", estado.get("corners_total")),
        ("shots", estado.get("shots_total")),
        ("shots_on_target", estado.get("shots_on_target_total")),
        ("goals", estado.get("goals_total")),
        ("cards", estado.get("cards_points_total")),
        ("fouls", estado.get("fouls_total")),
        ("dangerous_attacks", estado.get("dangerous_attacks_total")),
    ):
        if observado is None:
            continue
        esperado = REFERENCIA_PARTIDA_POR_90[chave] * fracao
        if esperado <= 0:
            continue
        familias.append({
            "familia": chave, "observado": observado,
            "esperado_ate_agora": round(esperado, 2),
            "razao": round(observado / esperado, 3),
        })

    if not familias:
        return {"score": None, "nivel": None, "familias": [],
                "motivo": "nenhum contador de volume publicado"}

    score = sum(f["razao"] for f in familias) / len(familias)
    return {
        "score": round(score, 4),
        "nivel": _nivel_ritmo(score),
        "familias": familias,
        "sinais": len(familias),
        "motivo": None,
    }


def _observacao_proxima(observacoes: list, minuto_alvo: int, tolerancia: int = 6) -> dict | None:
    """A leitura gravada mais proxima de um minuto alvo, dentro da tolerancia.

    Tolerancia existe porque as rodadas sao manuais e nao caem em minutos
    redondos: pedir exatamente o minuto 50 nunca acharia nada.
    """
    if not observacoes:
        return None
    candidatas = [o for o in observacoes if o.get("minuto") is not None]
    if not candidatas:
        return None
    melhor = min(candidatas, key=lambda o: abs(int(o["minuto"]) - minuto_alvo))
    if abs(int(melhor["minuto"]) - minuto_alvo) > tolerancia:
        return None
    return melhor


def janela(observacoes: list, familia: str, minuto_atual: int,
           valor_atual: int | None, largura: int) -> dict | None:
    """Quantos eventos daquela familia aconteceram nos ultimos `largura`
    minutos. None quando nao ha leitura anterior utilizavel."""
    if valor_atual is None:
        return None
    anterior = _observacao_proxima(observacoes, minuto_atual - largura)
    if anterior is None:
        return None
    antes = anterior.get(f"{familia}_observado")
    if antes is None:
        return None
    janela_real = minuto_atual - int(anterior["minuto"])
    if janela_real <= 0:
        return None
    delta = int(valor_atual) - int(antes)
    if delta < 0:
        # Contador que regride e' correcao do provedor, nao evento negativo.
        return None
    return {
        "largura_pedida": largura,
        "largura_real": janela_real,
        "de_minuto": int(anterior["minuto"]),
        "ate_minuto": minuto_atual,
        "eventos": delta,
        "por_minuto": round(delta / janela_real, 4),
    }


def janelas_recentes(observacoes: list, familia: str, minuto_atual: int,
                     valor_atual: int | None,
                     config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> dict:
    """Todas as janelas configuradas, mais a escolhida como principal.

    A principal e' a primeira da lista que existir -- 10 minutos por padrao,
    que e' o compromisso entre "recente o bastante pra descrever agora" e
    "largo o bastante pra ter evento dentro".
    """
    resultado = {}
    for largura in config.janelas_minutos:
        j = janela(observacoes, familia, minuto_atual, valor_atual, largura)
        if j:
            resultado[f"ultimos_{largura}"] = j
    principal = None
    for largura in config.janelas_minutos:
        if f"ultimos_{largura}" in resultado:
            principal = resultado[f"ultimos_{largura}"]
            break
    return {"janelas": resultado, "principal": principal}


def tendencia(observacoes: list, familia: str, minuto_atual: int,
              valor_atual: int | None,
              config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> dict:
    """ACELERANDO / DESACELERANDO / ESTAVEL, comparando a janela recente com a
    janela anterior de mesma largura.

    Exemplo do que isto captura: 0-60' com ritmo alto e 60-75' com ritmo baixo
    devolve DESACELERANDO, mesmo com o acumulado do jogo ainda alto. O
    acumulado descreve o passado; a tendencia descreve pra onde vai.
    """
    largura = config.janelas_minutos[0]
    recente = janela(observacoes, familia, minuto_atual, valor_atual, largura)
    if recente is None:
        return {"rotulo": INDEFINIDA, "motivo": "sem janela recente utilizavel"}

    anterior_ref = _observacao_proxima(observacoes, minuto_atual - largura)
    inicio_anterior = _observacao_proxima(observacoes, minuto_atual - 2 * largura)
    if anterior_ref is None or inicio_anterior is None:
        return {"rotulo": INDEFINIDA, "recente": recente,
                "motivo": "sem janela anterior equivalente"}

    a_antes = inicio_anterior.get(f"{familia}_observado")
    a_depois = anterior_ref.get(f"{familia}_observado")
    largura_anterior = int(anterior_ref["minuto"]) - int(inicio_anterior["minuto"])
    if a_antes is None or a_depois is None or largura_anterior <= 0:
        return {"rotulo": INDEFINIDA, "recente": recente,
                "motivo": "janela anterior sem contador"}

    delta_anterior = int(a_depois) - int(a_antes)
    if delta_anterior < 0:
        return {"rotulo": INDEFINIDA, "recente": recente,
                "motivo": "contador da janela anterior regrediu"}

    if recente["eventos"] + delta_anterior < EVENTOS_MINIMOS_TENDENCIA:
        return {"rotulo": ESTAVEL, "recente": recente,
                "anterior": {"eventos": delta_anterior, "largura_real": largura_anterior},
                "motivo": "poucos eventos nas duas janelas pra afirmar tendencia"}

    taxa_recente = recente["por_minuto"]
    taxa_anterior = delta_anterior / largura_anterior
    if taxa_anterior <= 0:
        rotulo = ACELERANDO if taxa_recente > 0 else ESTAVEL
        variacao = None
    else:
        variacao = (taxa_recente - taxa_anterior) / taxa_anterior
        if variacao >= config.limiar_tendencia:
            rotulo = ACELERANDO
        elif variacao <= -config.limiar_tendencia:
            rotulo = DESACELERANDO
        else:
            rotulo = ESTAVEL

    return {
        "rotulo": rotulo,
        "recente": recente,
        "anterior": {"eventos": delta_anterior, "largura_real": largura_anterior,
                     "por_minuto": round(taxa_anterior, 4)},
        "variacao": round(variacao, 4) if variacao is not None else None,
        "motivo": None,
    }


def fator_de_ritmo(janelas: dict, tend: dict, taxa_estimada_min: float | None,
                   config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> dict:
    """Multiplicador do lambda residual vindo do ritmo OBSERVADO da familia.

    Duas correcoes sobre a versao ingenua "taxa da janela / taxa estimada":

    1. AMORTECIMENTO. O fator entra pela metade do desvio. Uma rajada de 10
       minutos e' informacao, nao veredito -- escanteio vem em rajada por
       natureza (escanteio gera escanteio), e projetar a rajada inteira pro
       resto do jogo e' o erro mais facil de cometer aqui.
    2. TETO E PISO. Sem eles um jogo com 4 escanteios em 10 minutos dobraria a
       projecao sozinho.

    A tendencia entra como ajuste FINO em cima disso: acelerando empurra um
    pouco pra cima, desacelerando um pouco pra baixo. Pequeno de proposito --
    a tendencia ja esta parcialmente embutida na propria janela recente, e
    contar duas vezes o mesmo sinal e' o erro que o pre-jogo teve que corrigir
    quando K e M mediam a mesma coisa.
    """
    principal = (janelas or {}).get("principal")
    if not principal or not taxa_estimada_min or taxa_estimada_min <= 0:
        return {"fator": 1.0, "motivo": "sem janela recente pra medir ritmo"}

    bruto = principal["por_minuto"] / taxa_estimada_min
    amortecido = 1 + (bruto - 1) * AMORTECIMENTO

    # PESO DA JANELA: quanta evidencia ela realmente carrega.
    #
    # Sem isto, uma janela de 10 minutos com ZERO escanteios puxava o fator pro
    # piso -- e 10 minutos sem escanteio nao e' evidencia de nada. Com lambda
    # tipico de 1.2 por 10 minutos, P(zero) e' ~30%: acontece em quase um terco
    # das janelas de qualquer jogo normal. Tratar isso como "o jogo esfriou"
    # e' ler ruido como sinal, e era o espelho exato do problema da rajada no
    # outro extremo.
    #
    # A informacao da janela cresce com quantos eventos ela tem, observados E
    # esperados. Quatro escanteios contra 1.5 esperados e' desvio grande e
    # informativo; zero contra 0.8 esperados nao diz nada.
    esperado_na_janela = taxa_estimada_min * principal["largura_real"]
    informacao = (principal["eventos"] + esperado_na_janela) / 2
    peso = informacao / (informacao + INFORMACAO_DE_REFERENCIA)
    ponderado = 1 + (amortecido - 1) * peso

    ajuste_tendencia = 1.0
    rotulo = (tend or {}).get("rotulo")
    if rotulo == ACELERANDO:
        ajuste_tendencia = 1.06
    elif rotulo == DESACELERANDO:
        ajuste_tendencia = 0.94

    fator = max(RITMO_MIN, min(RITMO_MAX, ponderado * ajuste_tendencia))
    return {
        "fator": round(fator, 4),
        "fator_bruto": round(bruto, 4),
        "amortecido": round(amortecido, 4),
        "esperado_na_janela": round(esperado_na_janela, 3),
        "peso_da_janela": round(peso, 4),
        "ponderado": round(ponderado, 4),
        "tendencia": rotulo,
        "ajuste_tendencia": ajuste_tendencia,
        "janela": principal,
        "motivo": None,
    }
