"""Leitura das cotacoes de /odds/live e montagem dos pares Over/Under.

FORMATO QUE A API DEVOLVE
-------------------------
    odds: [
      {"id": 2, "name": "Over/Under Line",
       "values": [{"value": "Over", "odd": "1.85", "handicap": "2.5",
                   "main": true, "suspended": false}, ...]}
    ]

Diferente do pre-jogo, onde a linha vem embutida no texto do value ("Over
1.5") e precisa de regex, aqui `handicap` e' campo proprio. Menos ambiguidade,
mas dois cuidados novos:

  1. `suspended` existe e importa. Mercado suspenso e' mercado que nao aceita
     aposta -- publicar um pick em cima dele entrega ao usuario uma aposta que
     ele nao consegue fazer. Suspenso e' descartado aqui, na entrada.
  2. Os nomes de mercado ao vivo NAO sao os mesmos do pre-jogo. "Match Goals"
     ao vivo e' o "Goals Over/Under" pre-jogo. Por isso existe o mapa abaixo,
     em vez de reaproveitar stats_model.classify_market().

PROBABILIDADE DE MERCADO
------------------------
Sai do par completo, sem vig, reusando pick_engine/market_model.no_vig_pair_prob
-- a mesma funcao do pre-jogo, porque a matematica e' a mesma. Linha sem o
lado contrario cotado nao produz par e cai pra probabilidade implicita crua
(1/odd), que carrega a margem da casa e por isso e' marcada como tal no rastro.
"""
from __future__ import annotations

import re

from services.pick_engine import market_model

#: Nome do mercado ao vivo -> familia interna. Minusculo, comparacao exata
#: sobre o nome ja normalizado. A lista veio de
#: website/backend/routers/live.py::_LIVE_OVERUNDER_NAMES, que ja tinha sido
#: levantada contra a API real -- reusar evita descobrir de novo, errando.
NOMES_POR_FAMILIA = {
    "goals": {"match goals", "over/under line", "goals over/under", "over/under"},
    "corners": {"total corners", "match corners", "corners over/under",
                "asian corners", "corners"},
    "cards": {"total cards", "match cards", "cards over/under", "cards",
              "asian cards", "bookings over/under", "bookings"},
    # Faltas (2026-09-04, pedido do usuario). Os nomes vem do catalogo real da
    # API (`bet_markets_map` 170/171/173/174: "Fouls. Total", "Fouls. Home
    # Total", "Fouls. Away Total", "Fouls. Handicap") mais as variantes de
    # over/under que as casas usam ao vivo.
    #
    # OFERTA E' O GARGALO, NAO O MOTOR: na fila de odds de PROD em 2026-09-04
    # nao havia UMA linha de mercado de faltas, nem de time nem de jogador
    # (5.609 linhas coletadas, zero com "foul" no nome). A familia entra
    # cotavel; quantos picks ela produz depende da casa publicar.
    "fouls": {"total fouls", "match fouls", "fouls over/under", "fouls",
              "fouls. total", "asian fouls"},
}

#: Familias que a V1 cota.
#:
#: Cartoes entrou depois das duas primeiras, e por um motivo proprio: e' a
#: unica familia cujo numero ainda chega ao vivo quando a folha de estatistica
#: nao vem (o feed de eventos publica cartao), e a unica que tem uma terceira
#: estimativa independente do jogo em si -- a media de quem apita. Chutes e o
#: resto continuam fora ate' o residual estar medido.
FAMILIAS_V1 = ("corners", "goals", "cards", "fouls")

#: Rotulo em portugues do mercado, gravado na coluna `market` do pick. Mesmo
#: vocabulario que o pre-jogo ja usa (BET_ID_PT_MAP em
#: collectors/odds_collector_service.py), pra o card do site nao mostrar duas
#: nomenclaturas diferentes pro mesmo mercado.
ROTULO_PT = {
    "goals": "Gols Mais/Menos",
    "corners": "Escanteios Mais/Menos",
    "cards": "Cartoes Mais/Menos",
    # Mesmo rotulo que o pre-jogo grava (BET_ID_PT_MAP, bet_id 173).
    "fouls": "Faltas Mais/Menos",
}


def _decimal(valor) -> float | None:
    if valor is None:
        return None
    try:
        return float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _familia_do_mercado(nome: str | None) -> str | None:
    limpo = (nome or "").strip().lower()
    if not limpo:
        return None
    # "half" pega "1st Half Goals", "Corners 1st Half" etc. Mercado de tempo
    # tem contador proprio que a folha nao separa -- fica fora, pelo mesmo
    # motivo que o pre-jogo exclui mercado de 1o tempo.
    if "half" in limpo or "1st" in limpo or "2nd" in limpo:
        return None
    for familia, nomes in NOMES_POR_FAMILIA.items():
        if limpo in nomes:
            return familia
    return None


# ── PROP DE JOGADOR AO VIVO ──────────────────────────────────────────────
#
# A API cota prop de jogador ao vivo, e o motor nao enxergava nada disso --
# nem pra cotar, nem pra RELATAR. `mercados_nao_lidos`, que existe justamente
# pra responder "que mercado da' pra abrir?", filtra por value == "over"/
# "under", e prop de jogador nao tem essa forma: o nome do jogador e a direcao
# vem grudados num campo so' ("Deniz Undav/Over 1.5"), com `handicap` nulo.
# Entao o mercado existia, era baixado junto e sumia em silencio.
#
# LEVANTADO CONTRA A API REAL EM 2026-09-04, e nao deduzido de nome: dos 266
# tipos de aposta que /odds/live/bets declara, tres sao contador individual --
# 148 "Player Shots", 153 "Player Shots on Targets" e 155 "Player Assists".
# Numa amostra de 6 jogos ao vivo em ligas do projeto, 148 e 153 apareceram em
# 1 (Bundesliga, 95 e 50 valores) e 155 em 4. Oferta escassa, como no pre-jogo.
#
# Assistencia fica de fora: e' evento raro (nao contagem com media utilizavel)
# e o motor nao tem residual pra ela.

#: Rotulo em portugues, no mesmo vocabulario que o pre-jogo ja' usa pro card.
ROTULO_PT_JOGADOR = {
    "shots": "Chutes do jogador",
    "shots_on_target": "Chutes no alvo do jogador",
}

CONTADORES_DE_JOGADOR = {
    "shots": {"player shots"},
    "shots_on_target": {"player shots on targets", "player shots on target"},
}

#: "Deniz Undav/Over 1.5" -> ("Deniz Undav", "over", 1.5). Formato proprio do
#: /odds/live: no pre-jogo a mesma aposta chega como "Deniz Undav - 2"
#: ("2 ou mais"), aqui como linha Over de verdade. Sao notacoes do mesmo
#: produto, e por isso a conversao mora no ponto de leitura de cada um.
_VALOR_DE_JOGADOR = re.compile(
    r"^(?P<nome>.+?)\s*/\s*(?P<direcao>over|under)\s+(?P<linha>\d+(?:[.,]\d+)?)$",
    re.IGNORECASE)


def parse_valor_de_jogador(valor: str | None) -> tuple | None:
    """(nome, direcao, linha) do value ao vivo. None quando o formato nao bate.

    Nunca adivinha, pelo mesmo motivo do `name_match.parse_valor` do pre-jogo:
    formato inesperado vira descarte, nao um pick com a linha errada.
    """
    m = _VALOR_DE_JOGADOR.match((valor or "").strip())
    if not m:
        return None
    nome = m.group("nome").strip()
    linha = _decimal(m.group("linha"))
    if not nome or linha is None:
        return None
    return (nome, m.group("direcao").lower(), linha)


def _contador_do_mercado(nome: str | None) -> str | None:
    limpo = (nome or "").strip().lower()
    if not limpo or "half" in limpo or "1st" in limpo or "2nd" in limpo:
        return None
    for contador, nomes in CONTADORES_DE_JOGADOR.items():
        if limpo in nomes:
            return contador
    return None


def extrair_linhas_de_jogador(odds_brutas: list) -> list[dict]:
    """Uma entrada por (jogador, contador, linha, direcao) cotada e ativa.

    Mesma forma de saida de `extrair_linhas`, com `jogador` a mais -- inclusive
    o no-vig, que aqui pareia Over e Under DO MESMO JOGADOR na MESMA linha. Par
    de jogadores diferentes nao e' par: sao dois eventos que podem acontecer
    juntos, e tratar um como complemento do outro produziria uma probabilidade
    que nao descreve nenhum dos dois.

    NA PRATICA O PAR NAO EXISTE, e isso importa. Medido contra jogo ao vivo em
    2026-09-04 (Bundesliga, 11 minutos): 53 entradas, 10 jogadores, e nenhuma
    linha com o lado Under cotado. Prop de jogador ao vivo sai so' em Over,
    entao `prob_mercado` cai sempre na implicita crua, que carrega a margem da
    casa -- a ancora de mercado deste caminho e' pior que a das familias de
    partida, e quem for calcular edge sobre ela precisa saber disso. O campo
    `origem_prob_mercado` diz qual dos dois casos aconteceu.

    NAO decide nada e nao gasta requisicao: as odds ao vivo ja' foram baixadas
    pra cotar as familias de partida. Enquanto o modelo de jogador ao vivo nao
    estiver medido, isto serve pra RELATAR o que a casa oferece.
    """
    pares: dict[tuple, dict] = {}
    for mercado in odds_brutas or []:
        contador = _contador_do_mercado(mercado.get("name"))
        if contador is None:
            continue
        for valor in mercado.get("values", []) or []:
            if valor.get("suspended"):
                continue
            lido = parse_valor_de_jogador(valor.get("value"))
            odd = _decimal(valor.get("odd"))
            if not lido or odd is None or odd <= 1.0:
                continue
            nome, direcao, linha = lido
            alvo = pares.setdefault((nome, contador, linha), {})
            if direcao not in alvo or odd > alvo[direcao]:
                alvo[direcao] = odd

    saida: list[dict] = []
    for (nome, contador, linha), lados in sorted(pares.items()):
        over, under = lados.get("over"), lados.get("under")
        prob_over = prob_under = None
        origem = "implied"
        if over and under:
            prob_over, prob_under = market_model.no_vig_pair_prob(over, under)
            if prob_over is not None:
                origem = "no_vig"
        for direcao, odd in (("over", over), ("under", under)):
            if not odd:
                continue
            prob = ((prob_over if direcao == "over" else prob_under)
                    if origem == "no_vig" else market_model.implied_prob(odd))
            saida.append({
                "jogador": nome,
                "contador": contador,
                "familia": contador,
                "market_type": f"player_{contador}",
                "market": ROTULO_PT_JOGADOR.get(contador, contador),
                "linha": linha,
                "direcao": direcao,
                "line": f"{direcao.capitalize()} {linha}",
                "odd": round(odd, 2),
                "prob_mercado": prob,
                "origem_prob_mercado": origem,
                "tem_par": bool(over and under),
            })
    return saida


def extrair_linhas(odds_brutas: list, familias: tuple = FAMILIAS_V1) -> list[dict]:
    """Devolve uma entrada por (familia, linha, direcao) cotada e ativa.

    Cada entrada ja vem com a probabilidade de mercado resolvida e a origem
    dela, porque e' esse numero que vira a ancora da estimativa e o baseline
    do edge -- guardar so' a odd obrigaria a recalcular isso em dois lugares.
    """
    # (familia, linha) -> {"over": odd, "under": odd}
    pares: dict[tuple, dict] = {}
    for mercado in odds_brutas or []:
        familia = _familia_do_mercado(mercado.get("name"))
        if familia is None or familia not in familias:
            continue
        for valor in mercado.get("values", []) or []:
            if valor.get("suspended"):
                continue
            direcao = (valor.get("value") or "").strip().lower()
            if direcao not in ("over", "under"):
                continue
            linha = _decimal(valor.get("handicap"))
            odd = _decimal(valor.get("odd"))
            if linha is None or odd is None or odd <= 1.0:
                continue
            alvo = pares.setdefault((familia, linha), {})
            # Melhor odd vence quando a API repete a linha em mais de um
            # bloco de mercado (acontece com "Over/Under Line" e "Match
            # Goals" cotando o mesmo 2.5).
            if direcao not in alvo or odd > alvo[direcao]:
                alvo[direcao] = odd

    saida: list[dict] = []
    for (familia, linha), lados in pares.items():
        over, under = lados.get("over"), lados.get("under")
        prob_over = prob_under = None
        origem = "implied"
        if over and under:
            prob_over, prob_under = market_model.no_vig_pair_prob(over, under)
            if prob_over is not None:
                origem = "no_vig"
        for direcao, odd in (("over", over), ("under", under)):
            if not odd:
                continue
            if origem == "no_vig":
                prob = prob_over if direcao == "over" else prob_under
            else:
                prob = market_model.implied_prob(odd)
            saida.append({
                "familia": familia,
                "market_type": familia,
                "market": ROTULO_PT.get(familia, familia),
                "linha": linha,
                "direcao": direcao,
                "line": f"{direcao.capitalize()} {linha}",
                "odd": round(odd, 2),
                "prob_mercado": prob,
                "origem_prob_mercado": origem,
                "tem_par": bool(over and under),
            })
    saida.sort(key=lambda e: (e["familia"], e["linha"], e["direcao"]))
    return saida


#: Mercado que o motor NUNCA vai cotar, e por isso nao interessa listar como
#: "possivel". Nao e' falta de modelo: e' outro tipo de aposta. Over/Under de
#: TEMPO (1o/2o) tem contador proprio que a folha nao separa -- e' o mesmo
#: corte que o pre-jogo faz --, e resultado/handicap/placar nao sao contagem,
#: entao o modelo de residual deste motor nao os descreve nem em principio.
_FORA_DO_ESCOPO = (
    "half", "1st", "2nd", "handicap", "correct score", "result", "winner",
    "double chance", "draw no bet", "to score", "to win", "odd/even",
    "asian", "method", "penalty", "htft", "ht/ft",
)


def mercados_nao_lidos(odds_brutas: list) -> list[dict]:
    """Os mercados de CONTAGEM que a casa esta' cotando e o motor ignora.

    Existe porque a pergunta "que mercado ao vivo da' pra abrir?" nunca teve
    resposta baseada em dado: NOMES_POR_FAMILIA foi levantado uma vez, contra
    uma amostra, e desde entao a unica forma de saber o que a API oferece de
    verdade seria ler um payload na mao. Aqui a propria rodada responde --
    de graca, porque as odds JA' foram baixadas pra cotar as familias triadas.

    Filtra o que nunca sera' cotado (`_FORA_DO_ESCOPO`) pra a lista nao virar
    ruido: sobra mercado de contagem com linha Over/Under, que e' exatamente
    a forma que este motor sabe precificar assim que tiver baseline pro
    contador. Nao decide nada, nao gasta requisicao -- so' relata.
    """
    achados: dict[str, dict] = {}
    for mercado in odds_brutas or []:
        nome = (mercado.get("name") or "").strip()
        limpo = nome.lower()
        if not limpo or _familia_do_mercado(nome) is not None:
            continue
        # Prop de jogador tem forma propria e sai por `extrair_linhas_de_jogador`
        # -- listar aqui tambem faria o relatorio contar o mesmo mercado duas
        # vezes. O que ele NAO pode e' sumir: ate' 04/09 sumia, porque o filtro
        # de value == "over"/"under" logo abaixo nao casa com "Fulano/Over 1.5".
        if _contador_do_mercado(nome) is not None:
            continue
        if any(termo in limpo for termo in _FORA_DO_ESCOPO):
            continue
        linhas = {
            _decimal(v.get("handicap"))
            for v in (mercado.get("values") or [])
            if not v.get("suspended")
            and (v.get("value") or "").strip().lower() in ("over", "under")
            and _decimal(v.get("handicap")) is not None
        }
        if not linhas:
            continue  # sem par Over/Under nao e' mercado de contagem
        registro = achados.setdefault(nome, {"mercado": nome, "linhas": set()})
        registro["linhas"] |= linhas
    return [{"mercado": r["mercado"], "linhas": sorted(r["linhas"])}
            for r in sorted(achados.values(), key=lambda r: r["mercado"])]


def ha_mercado_para(odds_brutas: list, familia: str) -> bool:
    """Se a casa esta' cotando aquela familia agora. Usado no log pra separar
    'nao ha oportunidade' de 'nao ha mercado', que sao diagnosticos
    diferentes e levam a acoes diferentes."""
    for mercado in odds_brutas or []:
        if _familia_do_mercado(mercado.get("name")) == familia:
            return True
    return False
