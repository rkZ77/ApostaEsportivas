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
}

#: Familias que a V1 cota.
#:
#: Cartoes entrou depois das duas primeiras, e por um motivo proprio: e' a
#: unica familia cujo numero ainda chega ao vivo quando a folha de estatistica
#: nao vem (o feed de eventos publica cartao), e a unica que tem uma terceira
#: estimativa independente do jogo em si -- a media de quem apita. Chutes e o
#: resto continuam fora ate' o residual estar medido.
FAMILIAS_V1 = ("corners", "goals", "cards")

#: Rotulo em portugues do mercado, gravado na coluna `market` do pick. Mesmo
#: vocabulario que o pre-jogo ja usa (BET_ID_PT_MAP em
#: collectors/odds_collector_service.py), pra o card do site nao mostrar duas
#: nomenclaturas diferentes pro mesmo mercado.
ROTULO_PT = {
    "goals": "Gols Mais/Menos",
    "corners": "Escanteios Mais/Menos",
    "cards": "Cartoes Mais/Menos",
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


def ha_mercado_para(odds_brutas: list, familia: str) -> bool:
    """Se a casa esta' cotando aquela familia agora. Usado no log pra separar
    'nao ha oportunidade' de 'nao ha mercado', que sao diagnosticos
    diferentes e levam a acoes diferentes."""
    for mercado in odds_brutas or []:
        if _familia_do_mercado(mercado.get("name")) == familia:
            return True
    return False
