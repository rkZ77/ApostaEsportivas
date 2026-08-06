"""Atribuicao de desempenho: as contas puras que transformam uma perna do
`picks_ledger` num conjunto de dimensoes recortaveis, e um conjunto de
pernas num painel de metricas por dimensao.

POR QUE ESTE MODULO E' PURO (sem banco)
---------------------------------------
Todo calculo aqui e' funcao de dados que ja' estao na linha do ledger. Isso
permite testar a matematica de CLV, ROI, faixa de odd e agregacao sem subir
banco -- e' o que separa "o dashboard mostra um numero" de "o numero esta'
certo". O acesso a banco fica em services/performance_attribution_service.py,
que so' busca linhas e delega pra ca.

O QUE E' CLV E POR QUE ELE VEM ANTES DO ROI
-------------------------------------------
Closing Line Value compara a odd que se pegou com a odd de fechamento do
mesmo mercado. Pegar 2.10 num mercado que fecha em 1.90 e' capturar valor,
independentemente de aquele jogo especifico ter dado GREEN ou RED.

O ganho pratico e' de amostra: o resultado de uma aposta carrega a variancia
inteira do jogo, entao detectar ROI positivo com significancia exige da ordem
de mil apostas. O CLV tira o resultado da conta e mede so' o processo, entao
algumas dezenas de picks ja' dizem alguma coisa. Com o volume que a PickIA
tem hoje, CLV e' a unica das duas metricas que consegue responder "este
mercado tem vantagem real?" dentro de uma janela util.

Regra de leitura: quando ROI e CLV discordam, o CLV descreve melhor o
processo e a diferenca e' variancia.
"""
from __future__ import annotations

import math

# Faixas de odd. Cortes escolhidos pra separar regimes de aposta que se
# comportam de forma diferente na calibracao, nao pra ficar bonito no
# grafico: ate 1.50 e' o territorio de "quase certo" onde erro de calibracao
# custa caro; 1.50-2.00 e' a faixa conservadora que o line_score ja' prefere
# (config.conservative_odd_low/high); acima de 3.00 a amostra fica rala e a
# variancia domina.
_ODD_BANDS = ((1.50, "1.01-1.50"), (2.00, "1.51-2.00"), (3.00, "2.01-3.00"), (float("inf"), "3.01+"))

# Uma selecao com probabilidade implicita acima disto e' "favorita" no sentido
# do MERCADO (o mercado acha o evento mais provavel que nao). Nao confundir
# com o time favorito da partida -- ver docstring de selection_role().
_FAVORITE_IMPLIED_THRESHOLD = 0.50

# Faixas horarias (Brasilia), por limite SUPERIOR exclusivo. Jogo de meio de
# semana as 21h30 e jogo de domingo 11h tem publico, arbitragem e ritmo
# diferentes; o recorte existe pra deixar isso medivel, nao porque ja' se
# saiba que importa.
_HOUR_BUCKETS = ((6, "madrugada"), (12, "manha"), (18, "tarde"), (24, "noite"))


def odd_band(odd: float | None) -> str | None:
    """Faixa de odd da perna. None quando nao ha odd (nunca inventa faixa)."""
    if odd is None:
        return None
    try:
        valor = float(odd)
    except (TypeError, ValueError):
        return None
    if valor <= 1.0:
        return None
    for limite, rotulo in _ODD_BANDS:
        if valor <= limite:
            return rotulo
    return None


def hour_bucket(hora: int | None) -> str | None:
    """Faixa do dia a partir da hora do pontape inicial (0-23)."""
    if hora is None or not (0 <= hora <= 23):
        return None
    for limite, rotulo in _HOUR_BUCKETS:
        if hora < limite:
            return rotulo
    return None


def selection_role(odd: float | None) -> str | None:
    """'favorito' ou 'azarao' pela probabilidade implicita da PROPRIA selecao
    apostada, nao do time.

    A distincao importa e e' fonte de confusao: num "Over 2.5" a odd 1.60, a
    selecao e' favorita (o mercado acha que sai over), e isso nao diz nada
    sobre qual TIME e' favorito. Chamar de 'favorito' o time exigiria a odd do
    mercado 1X2, que o motor nem gera mais desde 2026-07-24 -- entao a leitura
    honesta com o dado disponivel e' esta, sobre a selecao.
    """
    if odd is None:
        return None
    try:
        implicita = 1.0 / float(odd)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not (0.0 < implicita <= 1.0):
        return None
    return "favorito" if implicita >= _FAVORITE_IMPLIED_THRESHOLD else "azarao"


def pick_side(market: str | None, line: str | None) -> str:
    """De que lado da partida a aposta esta': 'home', 'away' ou 'neutral'.

    Mercado de total do jogo (Over 2.5 gols, escanteios totais) e' 'neutral'
    -- nao aposta em time nenhum. Mercado de escopo de time ("Escanteios
    Casa", "Total de Gols Visitante") carrega lado, e o desempenho por lado e'
    exatamente onde o bug de mando de 2026-08-05 se escondia: vale medir
    separado pra flagrar se sobra alguma assimetria.
    """
    texto = f"{market or ''} {line or ''}".lower()
    tem_casa = any(k in texto for k in ("casa", "home", "mandante"))
    tem_fora = any(k in texto for k in ("visitante", "away", "fora"))
    if tem_casa and not tem_fora:
        return "home"
    if tem_fora and not tem_casa:
        return "away"
    return "neutral"


def clv(entry_odd: float | None, closing_odd: float | None) -> float | None:
    """Closing Line Value: quanto a odd pega e' melhor que a de fechamento.

    +0.05 significa que se pegou 5% mais valor que o preco final do mercado.
    Positivo de forma consistente e' a evidencia mais barata de vantagem real
    que existe. None quando falta qualquer um dos lados -- nunca assume que
    "sem fechamento" quer dizer CLV zero, porque isso enviesaria a media pra
    perto de zero justamente nos mercados com menos cobertura.
    """
    if entry_odd is None or closing_odd is None:
        return None
    try:
        entrada, fechamento = float(entry_odd), float(closing_odd)
    except (TypeError, ValueError):
        return None
    if entrada <= 1.0 or fechamento <= 1.0:
        return None
    return round(entrada / fechamento - 1.0, 4)


def realized_ev(result: str | None, odd: float | None) -> float | None:
    """EV realizado de uma perna, na mesma unidade do `ev` esperado: retorno
    por unidade apostada. GREEN devolve odd-1, RED devolve -1, PUSH devolve 0.

    Serve pra confrontar o esperado com o acontecido no MESMO eixo. A media do
    ev_realizado de um recorte e' o ROI daquele recorte; a media do `ev` do
    mesmo recorte e' o que o motor prometeu. A diferenca entre os dois e' o
    erro de calibracao economica -- distinto do Brier, que mede o erro
    probabilistico sem olhar preco.
    """
    if result is None:
        return None
    normalizado = str(result).strip().upper()
    if normalizado == "PUSH":
        return 0.0
    if odd is None:
        return None
    try:
        valor = float(odd)
    except (TypeError, ValueError):
        return None
    if normalizado == "GREEN":
        return round(valor - 1.0, 4)
    if normalizado == "RED":
        return -1.0
    return None


# ----------------------------------------------------------------------
# Agregacao
# ----------------------------------------------------------------------
_Z_95 = 1.96


def _mean(valores: list) -> float | None:
    return sum(valores) / len(valores) if valores else None


def _std_error(valores: list) -> float | None:
    """Erro padrao da media. None com menos de 2 pontos -- uma amostra de 1
    nao tem dispersao, e reportar intervalo ali seria inventar precisao."""
    n = len(valores)
    if n < 2:
        return None
    media = sum(valores) / n
    variancia = sum((v - media) ** 2 for v in valores) / (n - 1)
    return math.sqrt(variancia / n)


def confidence_interval(valores: list, z: float = _Z_95) -> tuple | None:
    """Intervalo de confianca de 95% da media. None quando a amostra nao
    sustenta.

    Existe porque ROI sem intervalo e' ruido formatado: 30 picks com ROI de
    +12% nao distinguem vantagem real de sorte, e um painel que mostra so' o
    ponto convida exatamente a essa confusao.
    """
    erro = _std_error(valores)
    if erro is None:
        return None
    media = sum(valores) / len(valores)
    return round(media - z * erro, 4), round(media + z * erro, 4)


def is_significant(valores: list, z: float = _Z_95) -> bool:
    """A media e' estatisticamente diferente de zero no nivel dado?

    Este e' o teste que decide se um mercado "tem vantagem demonstrada" ou
    apenas "teve sorte ate agora". Um intervalo que cruza o zero significa
    que o dado ainda nao distingue as duas hipoteses.
    """
    intervalo = confidence_interval(valores, z)
    if intervalo is None:
        return False
    baixo, alto = intervalo
    return baixo > 0 or alto < 0


def summarize(legs: list) -> dict:
    """Painel de um recorte: volume, acerto, ROI, CLV, Brier e o veredito de
    significancia.

    `legs` sao linhas do picks_ledger (dicts). Cada metrica usa so' as pernas
    que tem o campo necessario, e reporta o proprio n -- misturar
    denominadores diferentes num painel unico e' como um ROI de 40 picks vira
    ROI "de 200 picks" sem ninguem perceber.
    """
    resolvidas = [l for l in legs if str(l.get("result") or "").upper() in ("GREEN", "RED", "PUSH")]
    binarias = [l for l in resolvidas if str(l.get("result")).upper() in ("GREEN", "RED")]

    lucros = [float(l["profit"]) for l in resolvidas if l.get("profit") is not None]
    clvs = [float(l["clv"]) for l in legs if l.get("clv") is not None]

    greens = sum(1 for l in binarias if str(l["result"]).upper() == "GREEN")
    hit_rate = round(greens / len(binarias), 4) if binarias else None

    # Brier sobre a PROBABILIDADE declarada (nao o confidence) -- ver a
    # auditoria: confidence e' score composto, nao probabilidade, e media-lo
    # contra desfecho binario mede a coisa errada.
    pares = [
        (float(l["probability"]), 1 if str(l["result"]).upper() == "GREEN" else 0)
        for l in binarias if l.get("probability") is not None
    ]
    brier = round(sum((p - o) ** 2 for p, o in pares) / len(pares), 4) if pares else None

    ev_esperado = _mean([float(l["ev"]) for l in resolvidas if l.get("ev") is not None])
    roi = _mean(lucros)

    return {
        "n_total": len(legs),
        "n_resolvidas": len(resolvidas),
        "n_binarias": len(binarias),
        "hit_rate": hit_rate,
        "roi": round(roi, 4) if roi is not None else None,
        "roi_ic95": confidence_interval(lucros),
        "roi_significativo": is_significant(lucros),
        "clv_medio": round(_mean(clvs), 4) if clvs else None,
        "clv_n": len(clvs),
        "clv_ic95": confidence_interval(clvs),
        "clv_significativo": is_significant(clvs),
        "brier": brier,
        "brier_n": len(pares),
        "ev_esperado_medio": round(ev_esperado, 4) if ev_esperado is not None else None,
        # A conta que mais informa e a que ninguem olha: o motor prometeu
        # ev_esperado_medio e entregou roi. A diferenca e' o vies economico.
        "gap_ev": (round(ev_esperado - roi, 4)
                   if ev_esperado is not None and roi is not None else None),
    }


def group_by(legs: list, dimensao: str) -> dict:
    """Agrupa pernas por uma coluna do ledger e resume cada grupo.

    Valor ausente vira a chave '(nao atribuido)' em vez de sumir: uma
    dimensao com muito NULL e' informacao sobre cobertura de dado, e esconder
    isso faria o painel parecer mais completo do que e'.
    """
    grupos: dict = {}
    for leg in legs:
        chave = leg.get(dimensao)
        chave = "(nao atribuido)" if chave is None or chave == "" else str(chave)
        grupos.setdefault(chave, []).append(leg)
    return {chave: summarize(pernas) for chave, pernas in grupos.items()}


# Dimensoes que o painel percorre por padrao. Cobre o recorte pedido:
# liga/temporada/mercado/submercado/arbitro/casa/horario/tipo e fase de
# competicao/lado/papel da selecao.
DIMENSOES_PADRAO = (
    "market_type", "line", "league_id", "season", "competition_type", "round_phase",
    "referee", "bet_house", "hour_bucket", "pick_side", "selection_role", "odd_band",
    "pick_type", "source_system",
)


def full_report(legs: list, dimensoes: tuple = DIMENSOES_PADRAO) -> dict:
    """Painel completo: o agregado geral mais um recorte por dimensao."""
    return {
        "geral": summarize(legs),
        "por_dimensao": {d: group_by(legs, d) for d in dimensoes},
    }
