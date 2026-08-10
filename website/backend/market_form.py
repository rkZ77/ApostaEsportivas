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

AMBAS MARCAM (2026-08-08). O mercado ficava sem serie nenhuma: `_stat_for_market`
devolvia 1.0/0.0, que decide o pick mas nao e' contador -- sem contador nao ha
barra, e a secao inteira sumia do card. O contador existe e sempre existiu: e' o
placar do time que MENOS marcou, que passa de 0 pra 1 exatamente quando o
mercado vira GREEN. Hoje `_stat_for_market` devolve esse minimo (mesma decisao
pra quem so compara com 1.0) e a regua do grafico fica em 0.5.

UMA SERIE POR TIME, NO MANDO DO JOGO (2026-08-10). Ate' aqui o mercado de total
desenhava UMA fileira de barras com os jogos dos dois times embaralhados por
data -- nao dava pra saber de quem era cada barra. Agora a rota monta uma serie
POR TIME, e cada uma so' com os jogos NO MANDO que aquele time vai jogar: o
mandante aparece com os ultimos jogos EM CASA dele, o visitante com os ultimos
FORA. Se o Goias joga em casa, a serie do Goias e' de jogos em casa, ponto.

Nao e' preferencia de layout, e' a mesma correcao de 2026-08-08 aplicada ao
card: na Serie A 2026 o mandante faz 5.62 escanteios contra 4.41 do visitante
(+27%), entao juntar os dois mandos numa media so' produz um numero que nao
descreve nem uma coisa nem outra (foi o que gerou o pick #1573, ver
pool_and_field no motor).

`team_id` e' o que torna isso possivel: a serie sabe DE QUEM ela fala, resolve o
mando por partida e, nos mercados de um time so' ("Escanteios Casa"), poe o time
no lado que o nome do mercado nomeia.
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


def escopo_do_mercado(market: str) -> str:
    """'home', 'away' ou 'total' -- de qual lado o mercado fala.

    Mora aqui, e nao em routers/live.py, porque agora tem DOIS consumidores e
    eles precisam concordar: `_stat_for_market` usa pra escolher de qual folha
    ler o contador, e routers/suggestions.py::get_market_form usa pra escolher
    QUAIS JOGOS entram na serie. Enquanto so' o primeiro existia, a regra podia
    viver inline; com os dois, uma copia divergente traria de volta exatamente
    o bug de 2026-08-08 (serie de "Escanteios Visitante" medindo o time errado
    em 5 dos 8 jogos).

    A ordem importa: "casa"/"home" e' testado antes de "fora"/"away" porque
    nomes de mercado costumam trazer os dois times, e o rotulo do escopo vem
    primeiro ("Escanteios Casa Mais/Menos")."""
    m = (market or "").lower()
    if "casa" in m or "home" in m:
        return "home"
    if any(k in m for k in ("fora", "away", "visitante")):
        return "away"
    return "total"


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


def perspectiva_do_time(ms: dict, team_id: int | None, escopo: str) -> tuple:
    """(casa, fora, gols_casa, gols_fora, jogou_em_casa) do ponto de vista do time.

    Num mercado de UM time ("Escanteios Casa Mais/Menos"), `_stat_for_market` le
    sempre a folha do lado que o nome do mercado cita. Enquanto a serie so'
    mostrava jogos daquele mando, isso bastava; mostrando os 10 jogos do time
    (casa E fora, que e' a comparacao que o card existe pra fazer), metade deles
    entregaria o numero do ADVERSARIO -- o bug de 2026-08-08 de volta, agora
    dentro da propria serie.

    A correcao e' girar a folha, nao ensinar um segundo dispatch: o time vai
    sempre pro slot que o mercado nomeia, e `_stat_for_market` continua lendo o
    lado que sempre leu. O placar acompanha o giro, senao BTTS e gols contariam
    o lado errado no mesmo jogo.

    Mercado de total nao gira nada: ele soma os dois lados de qualquer jeito.
    """
    casa, fora = folha_do_jogo(ms)
    gols_casa, gols_fora = ms.get("home_goals"), ms.get("away_goals")

    if team_id is None or ms.get("home_team_id") is None:
        return casa, fora, gols_casa, gols_fora, None

    em_casa = ms.get("home_team_id") == team_id
    lado_do_time = "home" if em_casa else "away"
    if escopo in ("home", "away") and lado_do_time != escopo:
        casa, fora = fora, casa
        gols_casa, gols_fora = gols_fora, gols_casa
    return casa, fora, gols_casa, gols_fora, em_casa


def resumo(itens: list) -> dict:
    """Taxa e media de um conjunto de jogos ja liquidados.

    Funcao propria, e nao um trecho no fim de `serie_do_mercado`, porque a regra
    que sustenta os dois numeros e' a mesma e nao pode divergir: jogo sem dado
    nao entra na conta em nenhuma das duas pontas (taxa e media)."""
    resolvidos = [i for i in itens if i["result"] is not None]
    verdes = sum(1 for i in resolvidos if i["result"] == settlement.GREEN)
    com_valor = [i["value"] for i in itens if i["value"] is not None]
    return {
        "games": len(itens),
        "resolved": len(resolvidos),
        "greens": verdes,
        "hit_rate": round(verdes / len(resolvidos), 4) if resolvidos else None,
        "average": round(sum(com_valor) / len(com_valor), 2) if com_valor else None,
    }


def serie_do_mercado(jogos: list, market: str, market_type: str | None, line: str,
                     stat_para_mercado, team_id: int | None = None) -> dict:
    """Monta a serie do mercado sobre `jogos` (mais recente primeiro).

    `stat_para_mercado` e' routers/live.py::_stat_for_market, recebida por
    parametro em vez de importada: este modulo nao depende de rota nenhuma e da
    pra testar cada regra sem subir FastAPI -- mesma escolha de
    services/settlement.py, e pelo mesmo motivo.

    `team_id` e' de quem sao os jogos. Sem ele a serie ainda sai (comportamento
    antigo), mas nenhuma barra sabe dizer em que mando o jogo foi e a folha nao
    e' girada pra perspectiva do time.
    """
    parsed = settlement.parse_line(line)
    op, valor_linha = parsed["op"], parsed["value"]
    escopo = escopo_do_mercado(market)

    itens: list[dict] = []
    rotulo = ""
    for ms in jogos:
        casa, fora, gols_casa, gols_fora, em_casa = perspectiva_do_time(ms, team_id, escopo)
        valor, rotulo_jogo, _dir = stat_para_mercado(
            market, line, casa, fora,
            gols_casa, gols_fora,
            market_type,
        )
        rotulo = rotulo or rotulo_jogo

        resultado = None
        if valor is not None and op in ("over", "under"):
            resultado, _factor = settlement.settle_over_under(valor, valor_linha, op)
        elif valor is not None and op in ("yes", "no"):
            # Ambas marcam. NAO cai em settle_over_under com uma linha 0.5
            # inventada: quem grada BTTS e' settle_btts, com o placar, igual o
            # pick de verdade. A regua de 0.5 existe pro grafico (ver abaixo),
            # nao pra decisao -- se um dia a definicao de BTTS mudar, ela muda
            # em settlement e esta serie acompanha sozinha.
            resultado, _factor = settlement.settle_btts(
                ms.get("home_goals"), ms.get("away_goals"), op)

        itens.append({
            "fixture_id": ms.get("fixture_id"),
            "match_date": str(ms["match_date"]) if ms.get("match_date") else None,
            "value": float(valor) if valor is not None else None,
            "result": resultado,
            # None = serie sem team_id, entao nao da' pra afirmar o mando. O
            # grafico so' separa casa de fora quando isto vem preenchido.
            "is_home": em_casa,
            "opponent": ms.get("opponent"),
        })

    linha_grafico = float(valor_linha) if valor_linha is not None else None
    if op in ("yes", "no"):
        # BTTS nao tem numero no texto da linha ("Yes"), mas tem limiar: o
        # mercado paga quando o time que menos marcou faz 1 ou mais. Sobre o
        # contador que _stat_for_market devolve, isso e' 0.5 -- e' o que faz as
        # barras terem uma regua contra a qual serem lidas, em vez de flutuarem
        # sozinhas no grafico.
        linha_grafico = 0.5
        # "Ambas Marcam" nomeia o MERCADO, e serve pro ticker ao vivo. Aqui a
        # barra mostra o CONTADOR, e chamar o contador pelo nome do mercado e'
        # o que faria a regua em 0.5 parecer arbitraria.
        rotulo = "Gols do time que menos marcou"

    return {
        "label": rotulo,
        "line": linha_grafico,
        "op": op,
        "escopo": escopo,
        "matches": itens,
        **resumo(itens),
    }
