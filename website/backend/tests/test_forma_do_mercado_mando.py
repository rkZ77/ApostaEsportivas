"""A serie do "Entenda esta analise" tem que medir o MESMO que o motor mediu.

Duas divergencias reais, achadas em 2026-08-08 comparando os picks publicados
com o banco de producao:

1. MANDO. No pick VIP #1573 (Botafogo x Fluminense, "Escanteios Visitante Over
   4.5"), 5 das 8 barras contavam outro time -- Vasco, Bahia, Botafogo, Vitoria
   e Santos. A consulta pegava os jogos dos DOIS times e `_stat_for_market` lia
   o lado "fora" de cada jogo historico, fosse de quem fosse. A media exibida
   (3.00) nao era do Fluminense (5.20 fora de casa).

2. COMPETICAO. No pick #1572 (Coritiba x Chapecoense) dois dos oito jogos eram
   de Copa do Brasil, com 14 e 13 escanteios, e o motor -- que le so' a liga da
   fixture -- nunca os viu. Card e pick contando historias diferentes sobre o
   mesmo numero e' pior que nao mostrar serie nenhuma.

Como o resto da suite, nada aqui toca banco: verifica a forma do SQL e a regra
de escopo, que e' onde os dois bugs moravam.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_form  # noqa: E402
from tests.test_home_2026_08 import _codigo, _fonte, _front, _front_codigo  # noqa: E402


# ─────────────────────────── escopo ───────────────────────────


def test_escopo_le_o_lado_certo_do_nome_do_mercado():
    assert market_form.escopo_do_mercado("Escanteios Casa Mais/Menos") == "home"
    assert market_form.escopo_do_mercado("Escanteios Visitante Mais/Menos") == "away"
    assert market_form.escopo_do_mercado("Escanteios Fora Mais/Menos") == "away"
    assert market_form.escopo_do_mercado("Away Team Total Cards") == "away"
    assert market_form.escopo_do_mercado("Escanteios Mais/Menos") == "total"
    assert market_form.escopo_do_mercado("") == "total"
    assert market_form.escopo_do_mercado(None) == "total"


def test_regra_de_escopo_tem_UMA_definicao():
    """`_stat_for_market` escolhe de qual folha LER o contador e get_market_form
    escolhe QUAIS JOGOS entram: se as duas divergirem, a serie volta a medir o
    time errado. Uma copia inline em live.py e' exatamente como o bug nasceu."""
    live = _fonte("routers/live.py")
    assert "market_form.escopo_do_mercado" in live
    assert '"fora", "away", "visitante"' not in live, "regra duplicada inline"


# ─────────────────────────── a rota ───────────────────────────


def test_serie_de_mercado_de_time_mostra_so_o_time_do_mercado():
    """"Escanteios Casa" fala de um time so': a serie do adversario seria outro
    numero na mesma tela. Total fala do confronto, e ai os dois entram."""
    corpo = _codigo("routers/suggestions.py", "_series_da_perna")
    assert "market_form.escopo_do_mercado" in corpo
    assert 'if escopo == "home"' in corpo
    assert 'elif escopo == "away"' in corpo


def test_serie_de_total_continua_olhando_os_dois_times():
    """Mercado de total fala do CONFRONTO -- um time so' contaria metade da
    historia. Cada um com a propria serie, nao os dois numa fileira misturada
    por data (que era o que ninguem conseguia ler, corrigido em 2026-08-10)."""
    corpo = _codigo("routers/suggestions.py", "_series_da_perna")
    assert '("home", perna.get("home_team_id"), perna.get("home_team")),' in corpo
    assert '("away", perna.get("away_team_id"), perna.get("away_team")),' in corpo
    # uma chamada por time, com o dono da serie identificado
    assert "team_id=team_id" in corpo


def test_a_serie_traz_so_o_mando_que_o_time_vai_jogar():
    """Se o Flamengo joga FORA, a serie do Flamengo e' de jogos fora.

    Isto ja' foi mudado e desfeito no mesmo dia (22 e 23/08). A tentativa de
    mostrar casa E fora juntos, marcando o mando em cada barra, foi revertida a
    pedido do usuario: a serie tem que responder a pergunta do PICK, e o pick
    tem um mando so'. Os jogos do outro mando medem outra coisa (+27% de
    diferenca em escanteios na Serie A 2026) e diluem a media que o card mostra.

    O que ficou da tentativa: os 10 jogos. O recorte por mando encolhe a
    amostra, e cinco jogos de um mando so' nao se defendiam.
    """
    corpo = _codigo("routers/suggestions.py", "_jogos_do_time")
    assert 'coluna_mando = "ms.home_team_id" if mando == "home" else "ms.away_team_id"' in corpo
    assert "WHERE {coluna_mando} = %s" in corpo
    # o mando de cada serie e' o lado do time NESTA partida
    assert "lado, perna.get(\"league_id\")" in _codigo("routers/suggestions.py", "_series_da_perna")


def test_a_serie_pede_dez_jogos_por_padrao():
    """Cinco jogos de um mando so' e' amostra curta demais pra sustentar a
    media e a frase que o card mostra."""
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "limit: int = Query(10" in corpo


def test_o_grafico_nao_marca_mando_por_barra():
    """Com a serie de um mando so', marcar C/F em toda barra seria repetir a
    mesma letra dez vezes -- ruido, nao informacao. O mando aparece uma vez, no
    rotulo ("ultimos 10 jogos em casa")."""
    front = _front("components/MarketForm.tsx")
    assert "C = em casa" not in front
    assert "'em casa' : t.side === 'away' ? 'fora'" in front


def test_o_time_ainda_vai_pro_lado_que_o_mercado_nomeia():
    """Segunda trava, independente do filtro: quem le a folha e'
    `_stat_for_market`, que escolhe o lado pelo NOME do mercado. Num mercado de
    visitante a serie e' de jogos fora, entao os dois ja concordam -- mas a
    garantia mora em market_form, nao no acaso da consulta."""
    assert "perspectiva_do_time" in _fonte("market_form.py")


def test_serie_usa_a_mesma_liga_e_temporada_que_o_motor():
    corpo = _codigo("routers/suggestions.py", "_jogos_do_time")
    assert "AND ms.league_id = %s AND ms.season = %s" in corpo


def test_sem_fixture_a_serie_nao_some():
    """Pick antigo pode nao ter a fixture na tabela (join vazio). Serie um pouco
    mais larga e' melhor que secao vazia -- o filtro sai, a serie fica."""
    corpo = _codigo("routers/suggestions.py", "_jogos_do_time")
    assert "if league_id and season" in corpo
    assert 'filtro_liga, params_liga = "", []' in corpo


# ─────────────────── perspectiva do time (casa e fora) ───────────────────


def test_time_vai_pro_lado_que_o_mercado_nomeia():
    """Serie de "Escanteios Casa" com os jogos FORA do time: sem girar a folha,
    `_stat_for_market` leria o lado "casa" daquele jogo, que e' o ADVERSARIO --
    o bug de 2026-08-08 de volta, agora dentro da propria serie."""
    jogo_fora = {"home_team_id": 99, "away_team_id": 7,
                 "home_corners": 3, "away_corners": 8,
                 "home_goals": 0, "away_goals": 2}
    casa, fora, gc, ga, em_casa = market_form.perspectiva_do_time(jogo_fora, 7, "home")
    assert em_casa is False
    assert casa["Corner Kicks"] == 8          # o time, nao o mandante do jogo
    assert fora["Corner Kicks"] == 3
    assert (gc, ga) == (2, 0)                 # placar gira junto


def test_jogo_no_mando_do_mercado_nao_gira():
    jogo_casa = {"home_team_id": 7, "away_team_id": 99,
                 "home_corners": 8, "away_corners": 3,
                 "home_goals": 2, "away_goals": 0}
    casa, fora, gc, ga, em_casa = market_form.perspectiva_do_time(jogo_casa, 7, "home")
    assert em_casa is True
    assert (casa["Corner Kicks"], fora["Corner Kicks"]) == (8, 3)
    assert (gc, ga) == (2, 0)


def test_mercado_de_total_nunca_gira():
    """Total soma os dois lados de qualquer jeito -- girar so' embaralharia o
    mando registrado em cada barra."""
    jogo_fora = {"home_team_id": 99, "away_team_id": 7,
                 "home_corners": 3, "away_corners": 8,
                 "home_goals": 0, "away_goals": 2}
    casa, fora, gc, ga, em_casa = market_form.perspectiva_do_time(jogo_fora, 7, "total")
    assert em_casa is False
    assert (casa["Corner Kicks"], fora["Corner Kicks"]) == (3, 8)
    assert (gc, ga) == (0, 2)


def test_sem_team_id_a_serie_nao_afirma_mando():
    """None e' "nao sei", nao "jogou fora" -- mesma regra do contador ausente."""
    jogo = {"home_team_id": 99, "away_team_id": 7, "home_corners": 3, "away_corners": 8}
    *_, em_casa = market_form.perspectiva_do_time(jogo, None, "home")
    assert em_casa is None


def test_recorte_por_mando_sai_da_mesma_regra_da_taxa():
    """Casa, fora e total tem que contar "sem dado" do mesmo jeito, senao os
    tres numeros do card nao fecham entre si."""
    itens = [
        {"result": "GREEN", "value": 12.0},
        {"result": "RED",   "value": 8.0},
        {"result": None,    "value": None},   # sem estatistica publicada
    ]
    r = market_form.resumo(itens)
    assert r["games"] == 3          # a barra aparece
    assert r["resolved"] == 2       # mas fora da taxa
    assert r["greens"] == 1
    assert r["hit_rate"] == 0.5
    assert r["average"] == 10.0     # e fora da media


# ─────────────────── serie do arbitro (cartoes) ───────────────────


def test_arbitro_so_entra_em_mercado_de_cartoes():
    """Cartao e' o unico contador em que quem apita responde por parte do
    numero -- o motor ja' VETA o mercado quando o arbitro nao tem amostra
    (referee_model.cards_market_eligible). Em escanteios ou gols o arbitro nao
    e' causa, e uma fileira de barras ali sugeriria relacao que nao existe."""
    corpo = _codigo("routers/suggestions.py", "_serie_do_arbitro")
    assert "market_form.e_mercado_de_cartoes" in corpo
    assert 'escopo != "total"' in corpo


def test_reconhecimento_de_mercado_de_cartoes_tem_UMA_definicao():
    """A mesma pergunta que routers/live.py faz pra escolher o contador."""
    assert market_form.e_mercado_de_cartoes("Cartões Mais/Menos", None)
    assert market_form.e_mercado_de_cartoes("Total Cards", "cards")
    assert market_form.e_mercado_de_cartoes(None, "handicap_cards")
    assert not market_form.e_mercado_de_cartoes("Escanteios Mais/Menos", "corners")
    assert not market_form.e_mercado_de_cartoes("Ambas as Equipes Marcam", "btts")


def test_serie_do_arbitro_nao_filtra_por_liga():
    """Arbitro nao pertence a competicao: apita estadual, serie A e copa na
    mesma temporada. E' o mesmo recorte de RefereeStatsService.get_stats
    (arbitro + temporada), entao card e motor olham a mesma amostra."""
    corpo = _codigo("routers/suggestions.py", "_jogos_do_arbitro")
    # O nome casa NORMALIZADO desde 04/09: a API grava ora "Fulano" ora
    # "Fulano, Brazil", e com `=` cru a serie sumia sem dizer por que.
    assert "split_part(ms.referee" in corpo
    assert "AND ms.season = %s" in corpo
    assert "league_id" not in corpo


def test_arbitro_completa_a_amostra_fora_da_temporada():
    """No comeco de temporada o arbitro tem 1 ou 2 jogos na season atual, e a
    serie inteira sumia -- justo quando a media de cartoes dele e' o dado mais
    dificil de obter de outro jeito. Temporada virou preferencia."""
    corpo = _codigo("routers/suggestions.py", "_jogos_do_arbitro")
    assert "_buscar(False)" in corpo


def test_arbitro_sobrevive_a_fixture_apagada():
    """`fixtures` e' fila operacional e a linha pode sumir; match_statistics e'
    o registro permanente. Sem o fallback, pick antigo de cartoes perderia a
    serie de quem apitou."""
    corpo = _codigo("routers/suggestions.py", "_pernas_de_pick_simples")
    assert "COALESCE(f.referee, ms.referee)" in corpo


# ─────────── nome de time nunca por JOIN (achado 2026-08-10) ───────────


def test_nome_do_time_sai_por_subconsulta_nao_por_join():
    """`teams` tem ate' 3 linhas pro mesmo team_id (uma por liga). LEFT JOIN em
    teams multiplica a PARTIDA por esse numero, e com os dois lados o fator vira
    2x2, 2x3...

    Medido em producao no dia: a serie do pick VIP #1581 (Goias x Londrina)
    mostrou o jogo contra o Sport 4 vezes nas 5 barras, e a media do Londrina
    fora saiu 14.4 (dois jogos repetidos) quando os 5 jogos reais dao 11.4. A
    mesma consulta em /liga/jogos devolvia 706 linhas pros 207 jogos reais da
    Serie B 2026."""
    fonte = _fonte("routers/suggestions.py")
    assert "LEFT JOIN teams" not in fonte, "JOIN em teams duplica a partida"
    corpo = _codigo("routers/suggestions.py", "_nome_do_time")
    assert "SELECT t.name FROM teams t WHERE t.team_id" in corpo
    assert "LIMIT 1" in corpo


def test_amostra_curta_e_avisada_na_tela():
    """Filtrar por mando deixou amostra curta comum: um time tem ~7 jogos em
    casa numa fase inteira, e no comeco de temporada tem 2. Tres barras verdes
    lidas como "100%" sao muito menos do que parecem, e a regua e as cores sao
    identicas as de uma serie cheia -- quem le nao tem como saber sozinho.

    A regra fica no servidor: a tela nao precisa saber quantos jogos foram
    pedidos pra decidir se avisa."""
    corpo = _codigo("routers/suggestions.py", "_series_da_perna")
    assert '"amostra_curta": len(jogos) < limit' in corpo
    arb = _codigo("routers/suggestions.py", "_serie_do_arbitro")
    assert '"amostra_curta": len(jogos) < limit' in arb
    tela = _front_codigo("components/MarketForm.tsx")
    assert "serie.amostra_curta" in tela
    assert "Histórico curto" in _front("components/MarketForm.tsx")
