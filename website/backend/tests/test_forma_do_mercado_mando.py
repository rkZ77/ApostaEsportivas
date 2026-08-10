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
from tests.test_home_2026_08 import _codigo, _fonte  # noqa: E402


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
    """Se o Goias joga em casa, a serie do Goias e' de jogos em casa. Os jogos
    dele como visitante medem outra coisa (+27% de diferenca em escanteios na
    Serie A) e diluiriam a media que o card mostra."""
    corpo = _codigo("routers/suggestions.py", "_jogos_do_time")
    assert 'coluna_mando = "ms.home_team_id" if mando == "home" else "ms.away_team_id"' in corpo
    assert "WHERE {coluna_mando} = %s" in corpo
    # o mando de cada serie e' o lado do time NESTA partida
    assert "lado, perna.get(\"league_id\")" in _codigo("routers/suggestions.py", "_series_da_perna")


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
