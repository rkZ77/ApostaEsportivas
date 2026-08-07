"""Forma recente do MERCADO do pick.

Responde a pergunta que o card nao respondia: "nos ultimos jogos, esse mercado
teria batido?". Nao e' a forma do time (vitoria/empate/derrota) -- e' a serie do
contador que a aposta observa, jogo a jogo, comparada com a linha do pick.

Duas decisoes que sustentam o modulo inteiro:

1. Nao existe mapeamento novo de mercado. Qual contador cada familia observa e'
   uma pergunta ja respondida, e mal respondida custa caro: routers/live.py
   carrega no comentario dois bugs reais de producao nessa conta (chutes totais
   somados como chutes no alvo, mercado de time resolvido pelo total). Este
   modulo monta a folha de estatistica do jogo historico no MESMO formato que
   a API ao vivo entrega e chama `_stat_for_market` sem tocar nele. Se aquela
   funcao aprender uma familia nova, esta tela aprende junto.

2. Quem decide GREEN/RED e' services/settlement.py, o mesmo modulo que liquida
   o pick de verdade. Escrever aqui um `valor > linha` pareceria inofensivo e
   erraria em duas frentes ja resolvidas la: meia-linha asiatica (Over 9.25 nao
   e' um teste so) e PUSH em linha cheia (10 escanteios num Over 10.0 nao e'
   nem GREEN nem RED). A barra so' fica verde no que teria PAGO.

Estatistica ausente nunca vira zero. A partida entra na serie como "sem dado" e
fica de fora da taxa -- o RED de 05/08 que motivou o modulo de liquidacao
nasceu exatamente de tratar "nao sei" como "zero".
"""

from settlement_bridge import settlement

# Colunas de match_statistics -> chaves da folha da API-Football.
#
# O adaptador existe porque as duas fontes descrevem o mesmo jogo com nomes
# diferentes: a tabela guarda coluna por contador (home_corners), a API entrega
# lista de {type, value} que routers/live.py ja le por nome. Traduzindo aqui, o
# dispatch de familia continua sendo um so' pros dois caminhos.
_ADAPTADOR = (
    # (chave da API,        coluna do mandante,   coluna do visitante)
    ("Corner Kicks",        "home_corners",       "away_corners"),
    ("Yellow Cards",        "home_yellow_cards",  "away_yellow_cards"),
    ("Red Cards",           "home_red_cards",     "away_red_cards"),
    ("Fouls",               "home_fouls",         "away_fouls"),
    ("Shots on Goal",       "home_shots_on",      "away_shots_on"),
)


def folha_do_jogo(ms: dict) -> tuple[dict, dict]:
    """Converte uma linha de match_statistics nas duas folhas (casa, fora).

    Coluna ausente vira chave ausente, nunca 0: `_stat_side` devolve None
    quando falta o contador, e e' esse None que mantem o jogo fora da taxa em
    vez de contar como um jogo de zero escanteios.
    """
    casa: dict = {}
    fora: dict = {}
    for chave, col_casa, col_fora in _ADAPTADOR:
        if ms.get(col_casa) is not None:
            casa[chave] = ms[col_casa]
        if ms.get(col_fora) is not None:
            fora[chave] = ms[col_fora]
    return casa, fora


def serie_do_mercado(jogos: list, market: str, market_type: str | None, line: str,
                     stat_para_mercado) -> dict:
    """Monta a serie do mercado sobre `jogos` (mais recente primeiro).

    `stat_para_mercado` e' routers/live.py::_stat_for_market, recebida por
    parametro em vez de importada: este modulo nao depende de rota nenhuma e da
    pra testar cada regra sem subir FastAPI -- mesma escolha de
    services/settlement.py, e pelo mesmo motivo.
    """
    parsed = settlement.parse_line(line)
    op, valor_linha = parsed["op"], parsed["value"]

    itens: list[dict] = []
    rotulo = ""
    for ms in jogos:
        casa, fora = folha_do_jogo(ms)
        valor, rotulo_jogo, _dir = stat_para_mercado(
            market, line, casa, fora,
            ms.get("home_goals"), ms.get("away_goals"),
            market_type,
        )
        rotulo = rotulo or rotulo_jogo

        resultado = None
        if valor is not None and op in ("over", "under"):
            resultado, _factor = settlement.settle_over_under(valor, valor_linha, op)

        itens.append({
            "fixture_id": ms.get("fixture_id"),
            "match_date": str(ms["match_date"]) if ms.get("match_date") else None,
            "value": float(valor) if valor is not None else None,
            "result": resultado,
        })

    # Sem dado nao entra na conta, em nenhuma das duas pontas.
    resolvidos = [i for i in itens if i["result"] is not None]
    verdes = sum(1 for i in resolvidos if i["result"] == settlement.GREEN)
    com_valor = [i["value"] for i in itens if i["value"] is not None]

    return {
        "label": rotulo,
        "line": float(valor_linha) if valor_linha is not None else None,
        "op": op,
        "matches": itens,
        "resolved": len(resolvidos),
        "greens": verdes,
        "hit_rate": round(verdes / len(resolvidos), 4) if resolvidos else None,
        "average": round(sum(com_valor) / len(com_valor), 2) if com_valor else None,
    }
