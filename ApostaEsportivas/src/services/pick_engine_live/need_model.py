"""Necessidade do resultado AO VIVO -- quem precisa marcar, agora.

O QUE ESTE MODULO EXISTE PRA IMPEDIR
------------------------------------
Que o motor continue acreditando no contexto pre-jogo depois que a partida
contou outra historia. O pedido do usuario em 2026-08-14 nomeia o caso:

    "Jogo de ida de copa + mandante teoricamente pressionado, mas aos 30
     minutos o mandante nao cria nada -> nao continuar assumindo pressao
     apenas pelo contexto."

Por isso a necessidade daqui NAO e' um campo copiado do pre-jogo. Ela e'
RECALCULADA a cada passada, a partir do agregado ATUAL (o da ida somado ao
placar de agora) e do placar de agora contra o que o time precisava na tabela.
O contexto pre-jogo entra como a regra do jogo -- quem se classifica com o
que -- e nunca como a resposta.

A SEGUNDA COISA QUE ELE FAZ: TEMPO
----------------------------------
Precisar de um gol aos 20' e precisar do mesmo gol aos 85' sao situacoes
diferentes, e a diferenca nao e' de grau -- e' de comportamento. Time que
precisa e tem tempo administra; time que precisa e nao tem tempo se desfaz
taticamente. Por isso toda necessidade daqui e' multiplicada por uma urgencia
que cresce com o cronometro.

O QUE ELE NAO FAZ
-----------------
Nao aprova nem reprova pick. Devolve um numero e o rastro de como chegou nele,
que entram como MAIS UM sinal na convergencia (signal_score) e como um fator no
lambda residual (residual_model). Quem decide continua sendo os gates.
"""
from __future__ import annotations

MINUTOS_REGULAMENTARES = 90

#: A partir daqui a necessidade comeca a virar comportamento. Antes disso o
#: time que precisa ainda joga o jogo dele -- trocar de postura aos 30' com um
#: gol de desvantagem e' incomum, e tratar isso como pressao seria antecipar
#: um efeito que ainda nao esta' em campo.
MINUTO_EM_QUE_APERTA = 55

#: Teto da urgencia temporal. Nao chega a 1.0 nem nos acrescimos de proposito:
#: o modelo nao tem como saber quantos minutos de acrescimo o arbitro vai dar.
URGENCIA_MAXIMA = 0.95

NINGUEM = None
HOME = "home"
AWAY = "away"
AMBOS = "ambos"


def urgencia_temporal(minuto: int | None) -> float:
    """0-1: quanto o cronometro aperta quem precisa de resultado.

    Zero ate MINUTO_EM_QUE_APERTA, crescendo dai ate o fim. E' a curva que
    separa "precisa de um gol" de "precisa de um gol AGORA".
    """
    if minuto is None:
        return 0.0
    m = int(minuto)
    if m <= MINUTO_EM_QUE_APERTA:
        return 0.0
    span = MINUTOS_REGULAMENTARES - MINUTO_EM_QUE_APERTA
    return round(min(URGENCIA_MAXIMA, (m - MINUTO_EM_QUE_APERTA) / span * URGENCIA_MAXIMA), 4)


# ─────────────────────────── mata-mata ────────────────────────────────────
def agregado_ao_vivo(tie: dict | None, saldo_mandante: int | None) -> dict | None:
    """O agregado do confronto AGORA, somando o placar em campo ao da ida.

    `tie` e' o contexto pre-jogo de match_context_model.tie_context, onde
    `agregado_home`/`agregado_away` sao os gols de cada lado NA IDA, ja'
    resolvidos por team_id (o mando inverte entre as pernas, e e' ali que uma
    conta de agregado costuma trocar o sinal).

    None quando nao ha confronto de duas pernas ou quando falta o placar da
    ida -- e' o caso normal, nao um erro.
    """
    if not tie or not tie.get("is_jogo_de_volta"):
        return None
    ida_home, ida_away = tie.get("agregado_home"), tie.get("agregado_away")
    if ida_home is None or ida_away is None or saldo_mandante is None:
        return None

    # Diferenca agregada do ponto de vista do mandante de HOJE.
    diferenca = (ida_home - ida_away) + int(saldo_mandante)
    if diferenca > 0:
        quem_precisa, lider = AWAY, HOME
    elif diferenca < 0:
        quem_precisa, lider = HOME, AWAY
    else:
        quem_precisa, lider = AMBOS, None
    return {
        "diferenca_agregada": diferenca,
        "lider": lider,
        "quem_precisa": quem_precisa,
        "ida_home": ida_home,
        "ida_away": ida_away,
        "saldo_mandante_agora": int(saldo_mandante),
        # Quantos gols o lado atras precisa AGORA so' pra empatar o agregado.
        # E' o numero que muda a cada gol e que separa "precisa de 1" de
        # "precisa de 3" -- sem ele a necessidade era binaria, e um time
        # perdendo o confronto por 1 era lido igual a um perdendo por 3.
        "gols_para_reverter": abs(diferenca) or None,
    }


# ─────────────────────────── pontos corridos ──────────────────────────────
def _necessidade_de_tabela(pressao: dict | None, lado: str, saldo_mandante: int | None) -> float:
    """Quanto este lado precisa MUDAR o placar atual, dada a necessidade de
    pontos que ele trouxe pra partida.

    A necessidade da tabela diz o quanto o time precisa de PONTOS. O placar
    diz quantos pontos ele esta' levando agora. Cruzar os dois e' o passo que
    faltava: um time que precisa desesperadamente de pontos e esta' GANHANDO
    nao vai se abrir -- ele vai administrar, e o efeito no volume e' o oposto.
    """
    if not pressao or not pressao.get("disponivel") or saldo_mandante is None:
        return 0.0
    base = (pressao.get(lado) or {}).get("necessidade") or 0.0
    if base <= 0:
        return 0.0

    saldo = int(saldo_mandante) if lado == HOME else -int(saldo_mandante)
    if saldo > 0:
        return 0.0            # esta ganhando: leva os 3 pontos, nao precisa forcar
    if saldo == 0:
        return round(base * 0.55, 4)   # empate serve pela metade
    return round(base, 4)     # perdendo: precisa do resultado inteiro


def _rotulo(precisa_home: float, precisa_away: float) -> str | None:
    if precisa_home > 0 and precisa_away > 0:
        return AMBOS
    if precisa_home > 0:
        return HOME
    if precisa_away > 0:
        return AWAY
    return NINGUEM


def necessidade(estado: dict, contexto_pre_jogo: dict | None = None) -> dict:
    """A leitura de necessidade da partida no minuto atual.

    `contexto_pre_jogo` e' o dict de context_gate.build_for_fixture -- traz
    `tie` (mata-mata) e `pressao_competitiva` (tabela). Sem ele o modulo
    devolve necessidade zero e diz por que: um jogo sem contexto conhecido nao
    e' um jogo sem contexto: e' um jogo cujo contexto nao foi lido, e as duas
    coisas nao podem produzir o mesmo numero por acidente.
    """
    minuto = estado.get("minuto")
    saldo = estado.get("saldo_mandante")
    urgencia = urgencia_temporal(minuto)

    vazio = {
        "disponivel": False, "intensidade": 0.0, "assimetria": 0.0,
        "quem_precisa": NINGUEM, "urgencia_temporal": urgencia,
        "agregado": None, "descricao": [],
    }
    if not contexto_pre_jogo:
        return {**vazio, "motivo": "sem contexto pre-jogo carregado"}
    if saldo is None:
        return {**vazio, "motivo": "placar nao publicado"}

    tie = contexto_pre_jogo.get("tie") or {}
    pressao = contexto_pre_jogo.get("pressao_competitiva")

    agregado = agregado_ao_vivo(tie, saldo)
    descricao: list = []

    # MATA-MATA MANDA. Onde ha eliminacao em jogo, a tabela nao decide nada --
    # e o agregado ao vivo ja' incorpora o placar de agora.
    if agregado:
        quem = agregado["quem_precisa"]
        # QUANTOS gols faltam, nao so' se faltam. Precisar de 1 gol e precisar
        # de 3 produzem comportamentos diferentes em campo, e o modelo tratava
        # os dois como 1.0 ate 2026-08-19. A escala e' a mesma do pre-jogo
        # (match_context_model._PRESSAO_POR_DIFERENCA), pra o motor ao vivo nao
        # ler a mesma situacao numa escala e o pre-jogo noutra.
        faltam = agregado.get("gols_para_reverter") or 0
        grau = {0: 0.0, 1: 0.60, 2: 0.85}.get(min(faltam, 3), 1.00)
        precisa_home = grau if quem in (HOME, AMBOS) else 0.0
        precisa_away = grau if quem in (AWAY, AMBOS) else 0.0
        # O peso da fase modula: precisar de um gol numa final nao e' o mesmo
        # que precisar de um gol numa fase de 32.
        peso = tie.get("peso_fase") or 0.6
        precisa_home *= peso
        precisa_away *= peso
        if quem == AMBOS:
            # Agregado empatado AO VIVO e' um estado instavel, nao um empate
            # confortavel: qualquer gol decide. Os dois precisam, e o grau
            # acima e' zero (faltam=0), entao a necessidade vem da fase.
            precisa_home = precisa_away = peso * 0.60
            descricao.append("agregado empatado, os dois precisam do resultado")
        elif quem:
            alvo = "mandante" if quem == HOME else "visitante"
            descricao.append(f"{alvo} precisa de {faltam} gol(s) pra empatar o agregado")
        origem = "mata_mata"
    else:
        precisa_home = _necessidade_de_tabela(pressao, HOME, saldo)
        precisa_away = _necessidade_de_tabela(pressao, AWAY, saldo)
        origem = "tabela" if (precisa_home or precisa_away) else None
        if precisa_home:
            descricao.append("mandante precisa de pontos e nao esta' vencendo")
        if precisa_away:
            descricao.append("visitante precisa de pontos e nao esta' vencendo")

    quem_precisa = _rotulo(precisa_home, precisa_away)
    if quem_precisa is NINGUEM:
        return {**vazio, "disponivel": True, "agregado": agregado,
                "motivo": "ninguem precisa mudar o placar atual"}

    maior, menor = max(precisa_home, precisa_away), min(precisa_home, precisa_away)
    # A URGENCIA MULTIPLICA, NAO SOMA. Sem tempo curto, precisar do resultado
    # nao muda o comportamento em campo -- e e' comportamento, nao intencao,
    # que produz escanteio e finalizacao.
    intensidade = round(min(1.0, (maior + menor * 0.35)) * urgencia, 4)
    if intensidade > 0 and minuto is not None:
        descricao.append(f"aos {int(minuto)}', com o cronometro contra")

    return {
        "disponivel": True,
        "origem": origem,
        "intensidade": intensidade,
        "assimetria": round(abs(precisa_home - precisa_away) * urgencia, 4),
        "quem_precisa": quem_precisa,
        "precisa_home": round(precisa_home, 4),
        "precisa_away": round(precisa_away, 4),
        "urgencia_temporal": urgencia,
        "agregado": agregado,
        "descricao": descricao,
        "motivo": None,
    }


def confirma_o_contexto(nec: dict | None, pressao_ofensiva: dict | None) -> dict:
    """O que o contexto previa esta' de fato acontecendo em campo?

    E' a pergunta do pedido: "se o contexto e os dados ao vivo estiverem
    alinhados -> aumentar a confianca da leitura". E o contrario tambem, que e'
    a parte que importa mais -- contexto que diz "vai ser aberto" com campo
    dizendo "nao esta' acontecendo nada" e' contexto que precisa ser
    descontado, nao repetido.

    `pressao_ofensiva` e' a saida de pressure_model.pressao (escala centrada em
    0.50 = dois times medios).
    """
    if not nec or not nec.get("disponivel") or nec.get("intensidade", 0) <= 0:
        return {"aplicavel": False, "alinhado": None, "fator": 1.0,
                "motivo": "sem necessidade medida pra confirmar"}
    if not pressao_ofensiva or pressao_ofensiva.get("total") is None:
        return {"aplicavel": False, "alinhado": None, "fator": 1.0,
                "motivo": "sem pressao ofensiva publicada"}

    # Quem precisa deveria estar pressionando. Se a pressao total da partida
    # esta' abaixo do equilibrio, o contexto nao virou jogo.
    desvio = pressao_ofensiva["total"] - 0.50
    alinhado = desvio >= 0
    # Contexto confirmado reforca pouco (o sinal ja' esta' na pressao, e
    # contar duas vezes o mesmo dado e' o erro que o pre-jogo ja' pagou);
    # contexto desmentido desconta mais, porque e' informacao nova.
    fator = 1.0 + (0.06 if alinhado else -0.15) * min(1.0, nec["intensidade"])
    return {
        "aplicavel": True,
        "alinhado": alinhado,
        "fator": round(fator, 4),
        "pressao_total": pressao_ofensiva["total"],
        "necessidade": nec["intensidade"],
        "motivo": (None if alinhado else
                   "quem precisa do resultado nao esta' pressionando em campo"),
    }
