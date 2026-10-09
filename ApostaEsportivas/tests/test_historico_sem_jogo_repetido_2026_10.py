"""Jogo repetido no historico (2026-10-09).

Achado num pick Free de Instituto x Boca: "Os jogos que o motor olhou" listava
a mesma partida duas vezes. A classificacao e' gravada uma linha por GRUPO, e
a Argentina tem torneio + tabela anual na mesma temporada; o LEFT JOIN com
league_standings devolvia cada jogo uma vez por tabela -- taxa e amostra
infladas em todos os motores que leem o historico por MatchStatsService.

A regra que fica: toda leitura de classificacao pega UMA linha por time, a
de mais jogos (a geral).
"""
import os
import re

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _fonte(caminho):
    with open(os.path.join(SRC, caminho), encoding="utf-8") as fh:
        return fh.read()


def test_historico_nunca_faz_join_solto_com_a_classificacao():
    fonte = _fonte("services/match_stats_service.py")
    assert not re.search(r"LEFT JOIN league_standings ls\s+ON", fonte)
    blocos = fonte.count("LEFT JOIN LATERAL (")
    assert blocos == 4
    assert fonte.count("LIMIT 1) ls ON TRUE") == 4
    assert fonte.count("ORDER BY x.played DESC NULLS LAST") == 4


def test_classificacao_do_time_e_da_liga_tem_uma_linha_por_time():
    fonte = _fonte("services/standings_service.py")
    assert "ORDER BY played DESC NULLS LAST, updated_at DESC NULLS LAST\n        LIMIT 1" in fonte
    assert "SELECT DISTINCT ON (team_id) *" in fonte
