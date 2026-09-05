"""Convergencia de sinais, LIVE_SIGNAL_SCORE e confianca Live.

A IDEIA
-------
Nenhum sinal ao vivo e' confiavel sozinho. Posse alta pode ser time rodando a
bola atras; ritmo alto pode ser um lance de bola parada repetido; uma janela
de 10 minutos com 4 escanteios pode ser rajada. O que separa sinal de ruido e'
CONVERGENCIA: varios indicadores independentes apontando pro mesmo lado.

Por isso cada sinal e' reduzido a um numero em [-1, +1], onde:

    +1  aponta pra MAIS eventos no restante
    -1  aponta pra MENOS eventos no restante
     0  neutro / indisponivel

e o score final mede quantos deles concordam com a DIRECAO DO PICK, ponderados
pela forca de cada um. Um pick de Over sustentado por pressao alta, ritmo alto
e tendencia acelerando vale mais que o mesmo Over sustentado so' pela contagem
acumulada.

CONTRADICAO PESA CONTRA
-----------------------
Sinal que aponta pro lado oposto nao e' ignorado: ele DESCONTA. Um Over com
ritmo alto mas tendencia desacelerando e' menos confiavel que um Over com ritmo
alto e nada dizendo o contrario. E' essa subtracao que faz o score cair quando
os indicadores brigam entre si, que e' exatamente quando o motor deveria
duvidar de si mesmo.

ESTE MODULO NAO DECIDE
----------------------
Ele produz um score e uma confianca. Aprovar ou reprovar continua sendo dos
gates, com EV e limites de configuracao.
"""
from __future__ import annotations

from services.pick_engine_live import rhythm_model as rit
from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG, LiveEngineConfig
from services.pick_engine_live.live_state import DELAYED, FRESH, STALE, UNKNOWN

#: Peso de cada sinal na convergencia. Como os pesos de pressao, sao um ponto
#: de partida declarado -- ficam aqui pra serem calibrados contra resultado.
PESOS = {
    "pressao_total": 0.20,
    "ritmo": 0.20,
    "tendencia": 0.18,
    "janela_recente": 0.16,
    "contexto_placar": 0.09,
    "qualidade_da_chance": 0.07,
    # Necessidade do resultado (2026-08-14). Entra com peso proximo ao do
    # contexto de placar porque mede a mesma familia de coisa -- mas com a
    # informacao que faltava: quem precisa, quanto, e se o cronometro ja'
    # transformou isso em comportamento. Os outros pesos foram reduzidos
    # proporcionalmente pra a soma continuar em 1.0.
    "necessidade_resultado": 0.10,
}

#: Abaixo disso o sinal e' fraco demais pra contar como "convergente" na
#: contagem de sinais (ele ainda entra no score, com peso baixo).
FORCA_MINIMA_PARA_CONTAR = 0.15


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, v))


def _sinal_pressao(pressao: dict) -> float | None:
    """Pressao total da partida contra o equilibrio.

    0.50 e' o valor de dois times medios (a escala de pressure_model e'
    centrada nesse ponto de proposito), entao e' dele que se mede o desvio.
    Um desvio de 0.25 satura o sinal.
    """
    if not pressao or pressao.get("total") is None:
        return None
    return _clamp((pressao["total"] - 0.50) / 0.25)


def _sinal_ritmo(ritmo: dict) -> float | None:
    """Ritmo 1.0 = partida exatamente na media. Desvio de 0.35 satura."""
    if not ritmo or ritmo.get("score") is None:
        return None
    return _clamp((ritmo["score"] - 1.0) / 0.35)


def _sinal_tendencia(tendencia: dict) -> float | None:
    if not tendencia:
        return None
    rotulo = tendencia.get("rotulo")
    if rotulo == rit.ACELERANDO:
        variacao = tendencia.get("variacao")
        return _clamp(0.5 + min(0.5, (variacao or 0.3)))
    if rotulo == rit.DESACELERANDO:
        variacao = tendencia.get("variacao")
        return _clamp(-0.5 + max(-0.5, (variacao or -0.3)))
    if rotulo == rit.ESTAVEL:
        return 0.0
    return None


def _sinal_janela(janelas: dict, taxa_estimada_min: float | None) -> float | None:
    """A janela recente contra a taxa que o modelo ja esta usando. Mede se o
    AGORA e' mais quente que a estimativa que ja incorpora o jogo inteiro."""
    principal = (janelas or {}).get("principal")
    if not principal or not taxa_estimada_min or taxa_estimada_min <= 0:
        return None
    razao = principal["por_minuto"] / taxa_estimada_min
    return _clamp((razao - 1.0) / 0.6)


def _sinal_contexto(estado: dict, eventos: dict | None) -> float | None:
    """Placar e expulsao. O que este sinal captura, e por que:

    - PLACAR APERTADO NO FIM abre a partida: quem perde se lanca, quem ganha
      contra-ataca. Vale pra gol e, por consequencia do volume ofensivo, pra
      escanteio.
    - JOGO RESOLVIDO (3+ de diferenca) desacelera: ninguem forca mais nada.
    - EXPULSAO CEDO abre espaco pro resto do jogo; expulsao no fim quase nao
      muda nada. Por isso o peso cai com o minuto em que ela aconteceu -- e'
      pra isso que o minuto do evento e' lido em /fixtures/events.
    """
    minuto = estado.get("minuto")
    diferenca = estado.get("diferenca_gols")
    if minuto is None or diferenca is None:
        return None

    valor = 0.0
    if diferenca >= 3:
        valor -= 0.6
    elif int(minuto) >= 70 and diferenca <= 1:
        valor += 0.5

    vermelho_min = (eventos or {}).get("vermelho_minuto")
    if vermelho_min is not None:
        # Quanto do jogo ainda restava quando a expulsao aconteceu.
        restante = max(0.0, (90 - int(vermelho_min)) / 90.0)
        valor += 0.5 * restante
    elif estado.get("red_cards_total"):
        # Ha vermelho na folha mas nao sabemos QUANDO (eventos indisponiveis).
        # Entra com metade do efeito, porque metade da informacao falta.
        valor += 0.2

    return _clamp(valor)


def _sinal_qualidade_da_chance(estado: dict, familia: str) -> float | None:
    """O sinal que separa "muito chute" de "muito perigo".

    Para GOLS: expected_goals contra o placar. xG bem acima dos gols marcados
    diz que o jogo esta criando e nao convertendo, e o que nao converteu tende
    a converter.

    Para ESCANTEIOS: chute bloqueado e' o antecedente mais direto que existe --
    bloqueio vira escanteio com frequencia alta. Muitos bloqueios com poucos
    escanteios e' pressao que ainda nao virou contagem.
    """
    minuto = estado.get("minuto")
    if not minuto or int(minuto) <= 0:
        return None

    if familia == "goals":
        xg_casa, xg_fora = estado.get("xg_home"), estado.get("xg_away")
        gols = estado.get("goals_total")
        if xg_casa is None or xg_fora is None or gols is None:
            return None
        xg_total = float(xg_casa) + float(xg_fora)
        return _clamp((xg_total - gols) / 1.2)

    if familia == "corners":
        bloqueios = estado.get("blocked_shots_total")
        escanteios = estado.get("corners_total")
        if bloqueios is None or escanteios is None:
            return None
        # ~1 bloqueio pra cada 2 escanteios e' a proporcao tipica.
        esperado = escanteios / 2.0
        if esperado <= 0:
            return 0.5 if bloqueios > 0 else 0.0
        return _clamp((bloqueios - esperado) / max(1.5, esperado))

    return None


def _sinal_necessidade(nec: dict | None) -> float | None:
    """Necessidade do resultado, ja' pesada pelo cronometro (need_model).

    Aponta sempre PRA CIMA quando existe: time que precisa mudar o placar e
    nao tem mais tempo produz mais volume ofensivo, e o adversario que segura
    produz falta e escanteio defensivo. Nunca aponta pra baixo -- "ninguem
    precisa de nada" e' ausencia de sinal, nao evidencia de jogo travado, e
    devolver -1 ali seria inventar informacao que o modulo nao tem.
    """
    if not nec or not nec.get("disponivel"):
        return None
    intensidade = nec.get("intensidade") or 0.0
    if intensidade <= 0:
        return None
    return _clamp(intensidade)


def convergencia(direcao: str, familia: str, estado: dict, pressao: dict,
                 ritmo: dict, tendencia: dict, janelas: dict,
                 taxa_estimada_min: float | None, eventos: dict | None = None,
                 config: LiveEngineConfig = DEFAULT_LIVE_CONFIG,
                 necessidade: dict | None = None) -> dict:
    """Quantos sinais sustentam a direcao do pick, e com que forca.

    `direcao` e' "over" ou "under". Um sinal positivo (mais eventos vindo)
    sustenta um Over e contradiz um Under -- e' a mesma leitura, com o sinal
    invertido.
    """
    brutos = {
        "pressao_total": _sinal_pressao(pressao),
        "ritmo": _sinal_ritmo(ritmo),
        "tendencia": _sinal_tendencia(tendencia),
        "janela_recente": _sinal_janela(janelas, taxa_estimada_min),
        "contexto_placar": _sinal_contexto(estado, eventos),
        "qualidade_da_chance": _sinal_qualidade_da_chance(estado, familia),
        "necessidade_resultado": _sinal_necessidade(necessidade),
    }
    orientacao = 1.0 if (direcao or "").lower() == "over" else -1.0

    detalhes = []
    soma_pesos = 0.0
    soma_ponderada = 0.0
    a_favor = 0
    contra = 0
    for nome, valor in brutos.items():
        peso = PESOS[nome]
        if valor is None:
            detalhes.append({"sinal": nome, "valor": None, "peso": peso,
                             "disponivel": False, "posicao": "indisponivel"})
            continue
        alinhado = valor * orientacao  # +1 sustenta o pick, -1 contradiz
        if alinhado >= FORCA_MINIMA_PARA_CONTAR:
            posicao = "a_favor"
            a_favor += 1
        elif alinhado <= -FORCA_MINIMA_PARA_CONTAR:
            posicao = "contra"
            contra += 1
        else:
            posicao = "neutro"
        detalhes.append({"sinal": nome, "valor": round(valor, 4),
                         "alinhado": round(alinhado, 4), "peso": peso,
                         "disponivel": True, "posicao": posicao})
        soma_pesos += peso
        soma_ponderada += alinhado * peso

    if soma_pesos <= 0:
        return {"score": None, "a_favor": 0, "contra": 0, "sinais": detalhes,
                "convergente": False, "motivo": "nenhum sinal disponivel"}

    # Media ponderada em [-1, 1] reescalada pra [0, 1]: 0.5 e' "sinais
    # empatados", 1.0 e' "tudo aponta pro lado do pick".
    bruto = soma_ponderada / soma_pesos
    score = round((bruto + 1) / 2, 4)
    return {
        "score": score,
        "bruto": round(bruto, 4),
        "a_favor": a_favor,
        "contra": contra,
        "cobertura": round(soma_pesos, 3),
        "sinais": detalhes,
        "convergente": a_favor >= config.sinais_minimos_convergentes and contra == 0,
        "motivo": None,
    }


#: Multiplicador de confianca por qualidade do dado. STALE nem chega aqui (a
#: analise e' bloqueada antes), mas o valor fica definido pra o caso de alguem
#: chamar a funcao direto.
FATOR_FRESHNESS = {FRESH: 1.0, DELAYED: 0.75, UNKNOWN: 0.6, STALE: 0.3}


def live_confidence(prob_final: float, prob_mercado: float | None,
                    minuto: int, conv: dict, fresh: dict,
                    distancia_da_linha: float | None = None,
                    prob_modelo_puro: float | None = None) -> dict:
    """Confianca do pick Live. Formula PROPRIA, nao a do pre-jogo.

    Cinco termos, e cada um responde uma pergunta diferente:

      C  a probabilidade em si -- aposta mais provavel e' mais confiavel
      Q  quanto de jogo ja foi observado -- amostra do proprio jogo
      A  acordo com o mercado
      V  convergencia dos sinais ao vivo
      D  folga entre a projecao e a linha

    O TERMO A MERECE EXPLICACAO. No pre-jogo, edge grande e' o produto: o motor
    tem historico que o mercado de abertura nem sempre precifica. Ao vivo isso
    se inverte -- o mercado in-play e' repreçado a cada evento, com dado que
    chega antes do nosso. Uma divergencia enorme contra ele quase nunca e'
    valor encontrado, e quase sempre e' o nosso lado olhando uma folha
    atrasada. Por isso aqui a divergencia PENALIZA a confianca.

    Quem aprova o pick continua sendo o EV, num gate separado. A confianca diz
    o quanto acreditar nele, e e' ela que decide o stake.

    O TERMO A MEDE A DIVERGENCIA DEPOIS DO ENCOLHIMENTO, E ISSO SUBESTIMA
    (medido em 2026-09-05, nos 7 picks de DEV)
    ---------------------------------------------------------------------
    `prob_final` ja' foi puxada em direcao ao mercado por
    `residual_model.encolher_contra_mercado`:

        prob_final - prob_mercado = w * (prob_modelo - prob_mercado)
        w = minuto / (minuto + 45)

    Ou seja, a divergencia medida aqui e' a divergencia REAL multiplicada pelo
    peso do modelo. Ela e' menor sempre, e e' MUITO menor cedo -- aos 20' o w
    e' 0.31 --, que e' exatamente o regime em que a docstring acima diz que a
    divergencia e' mais suspeita. A penalidade e' mais fraca onde ela foi
    desenhada pra ser mais forte.

    Nos 7 picks gravados em DEV:

        pick  minuto  divergencia real  a medida   A
          1     23'        0.267          0.090   0.55
          3     28'        0.306          0.117   0.41
          7     29'        0.312          0.122   0.39

    Tres picks cujo modelo discordava do mercado em ~30 pontos receberam de
    0.39 a 0.55 no termo que existe pra punir exatamente isso. Com a
    divergencia real, os tres iriam a 0.00.

    POR QUE O SCORE NAO MUDOU JUNTO: `confianca_minima = 0.58` foi calibrado
    CONTRA esta formula. Trocar o numerador sozinho derruba 6 dos 7 picks
    abaixo do piso -- nao e' uma correcao, e' desligar o motor por efeito
    colateral. Entao aqui a divergencia real passou a ser MEDIDA e gravada
    (`divergencia_modelo`), e o score continua o mesmo ate' haver amostra pra
    recalibrar o piso junto. Ver a nota em config.confianca_minima.
    """
    c = max(0.0, min(1.0, float(prob_final)))
    q = min(1.0, max(0, int(minuto)) / 45.0)

    if prob_mercado is None:
        a = 0.5
        divergencia = None
        divergencia_modelo = None
    else:
        divergencia = abs(c - float(prob_mercado))
        a = max(0.0, 1.0 - divergencia / 0.20)
        # O desacordo ANTES do encolhimento -- o numero que a docstring
        # descreve e que o score ainda nao usa. Sem ele gravado, a pergunta
        # "quanto o modelo discordava de verdade?" nao tem resposta no rastro,
        # e a recalibracao do piso nunca sai do lugar.
        divergencia_modelo = (abs(float(prob_modelo_puro) - float(prob_mercado))
                              if prob_modelo_puro is not None else None)

    v = conv.get("score") if conv and conv.get("score") is not None else 0.5

    if distancia_da_linha is None:
        d = 0.5
    else:
        # Projecao colada na linha e' moeda ao ar, mesmo com EV positivo:
        # meio evento decide. Meio evento de folga ja vale bastante.
        d = min(1.0, abs(distancia_da_linha) / 1.5)

    score = c * 0.28 + q * 0.12 + a * 0.28 + v * 0.22 + d * 0.10
    fator = FATOR_FRESHNESS.get((fresh or {}).get("nivel"), 0.6)
    score = score * fator
    score = max(0.20, min(0.92, score))
    return {
        "confidence": round(score, 4),
        "C": round(c, 4), "Q": round(q, 4), "A": round(a, 4),
        "V": round(v, 4), "D": round(d, 4),
        "fator_freshness": fator,
        "freshness": (fresh or {}).get("nivel"),
        "divergencia_mercado": round(divergencia, 4) if divergencia is not None else None,
        # A que o score usa e' `divergencia_mercado`; esta e' a real.
        "divergencia_modelo": (round(divergencia_modelo, 4)
                               if divergencia_modelo is not None else None),
        "A_com_divergencia_real": (round(max(0.0, 1.0 - divergencia_modelo / 0.20), 4)
                                   if divergencia_modelo is not None else None),
        "distancia_da_linha": (round(distancia_da_linha, 3)
                               if distancia_da_linha is not None else None),
    }
