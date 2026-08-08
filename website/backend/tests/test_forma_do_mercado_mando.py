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

import market_form
from tests.test_home_2026_08 import _codigo, _fonte


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


def test_serie_de_mercado_de_time_filtra_por_mando():
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "market_form.escopo_do_mercado" in corpo
    # mercado do mandante olha os jogos EM CASA dele; do visitante, os de fora
    assert 'home_team_id = %s' in corpo
    assert 'away_team_id = %s' in corpo


def test_serie_de_total_continua_olhando_os_dois_times():
    """Mercado de total fala do CONFRONTO -- um time so' contaria metade da
    historia. O filtro de mando nao pode vazar pra ca."""
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "home_team_id = ANY(%s) OR away_team_id = ANY(%s)" in corpo


def test_serie_usa_a_mesma_liga_e_temporada_que_o_motor():
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "AND league_id = %s AND season = %s" in corpo
    assert "f.league_id, f.season" in corpo


def test_sem_fixture_a_serie_nao_some():
    """Pick antigo pode nao ter a fixture na tabela (join vazio). Serie um pouco
    mais larga e' melhor que secao vazia -- o filtro sai, a serie fica."""
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert 'if pick.get("league_id") and pick.get("season")' in corpo
    assert 'filtro_liga = ""' in corpo
