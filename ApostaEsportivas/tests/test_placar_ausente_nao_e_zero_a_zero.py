# -*- coding: utf-8 -*-
"""Placar ausente na API nao pode virar 0x0 no banco (2026-08-27).

O DEFEITO
---------
Os tres leitores de /fixtures do projeto montavam a linha assim:

    "home_goals": goals["home"] or 0,
    "away_goals": goals["away"] or 0,

`or 0` nao distingue "a API disse zero" de "a API nao disse nada". Quando o
campo vinha nulo, o jogo entrava em `match_statistics` como se tivesse
terminado 0x0.

E' o mesmo defeito do cartao vermelho (ver test_folha_publicada_vermelho_zero),
com dois agravantes:

  1. gol e' a familia mais usada do motor -- baseline de liga, media de time,
     confronto direto e a maior parte dos mercados saem dai';
  2. zero nao e' nulo, entao o 0x0 falso passa por "preenchido" em TODA
     contagem de cobertura do /admin e some da varredura, que procura jogo
     ENCERRADO SEM LINHA.

Foi assim que ele apareceu: um 0-0 na amostra ("Jogos que o motor leu") de um
jogo que nao terminou 0x0.

A REGRA
-------
Sem placar, NAO GRAVA. E' a mesma regra que a folha ja' seguia desde 26/08 --
"linha oca esconde a partida pra sempre" -- agora aplicada ao placar. A partida
continua na lista de buracos do /admin, que e' onde ela deve estar.
"""
import pytest

from collectors.match_statistics_sync_service import MatchStatisticsSyncService


class _CursorFake:
    def __init__(self):
        self.execucoes = []

    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))


class _ConnFake:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def _servico():
    s = MatchStatisticsSyncService()
    s.cur = _CursorFake()
    s.conn = _ConnFake()
    return s


def _fx(home, away):
    return {
        "fixture_id": 1, "league_id": 71, "season": 2026,
        "home_id": 100, "away_id": 200,
        "match_date": "2026-08-20", "status": "FT",
        "home_goals": home, "away_goals": away,
        "home_goals_ht": None, "away_goals_ht": None,
        "home_goals_90": None, "away_goals_90": None,
        "referee": "Fulano",
    }


def _folha():
    return [
        {"type": "Corner Kicks", "value": 5},
        {"type": "Fouls", "value": 12},
        {"type": "Yellow Cards", "value": 2},
        {"type": "Red Cards", "value": None},
        {"type": "Shots on Goal", "value": 4},
    ]


# ── sem placar: nao grava ────────────────────────────────────────────────
@pytest.mark.parametrize("home,away", [(None, 1), (2, None), (None, None)])
def test_sem_placar_a_linha_nao_e_gravada(home, away):
    s = _servico()

    assert s._save_stats(_fx(home, away), _folha(), _folha()) is False
    assert s.cur.execucoes == []
    assert s.conn.commits == 0


# ── 0x0 de verdade: grava ────────────────────────────────────────────────
def test_zero_a_zero_de_verdade_continua_gravando():
    """O contrario do teste acima, e a razao de ele nao poder ser um `if not`:
    0x0 acontece, e recusar a linha nesse caso apagaria jogo real."""
    s = _servico()

    assert s._save_stats(_fx(0, 0), _folha(), _folha()) is True
    assert len(s.cur.execucoes) == 1
    assert s.conn.commits == 1


def test_o_total_de_gols_sai_da_soma_real():
    s = _servico()
    s._save_stats(_fx(3, 1), _folha(), _folha())

    _, params = s.cur.execucoes[0]
    # home_goals, away_goals, total_goals sao os parametros 6, 7 e 8 (a ordem
    # das colunas no INSERT), logo depois de fixture/liga/season/times.
    assert params[5] == 3
    assert params[6] == 1
    assert params[7] == 4


def test_o_upsert_nao_apaga_um_placar_bom():
    """Recoleta que volte sem placar nao pode zerar o que ja' estava certo ·
    mesmo COALESCE que as outras 40 colunas ja' tinham."""
    s = _servico()
    s._save_stats(_fx(2, 2), _folha(), _folha())

    sql, _ = s.cur.execucoes[0]
    assert "home_goals = COALESCE(EXCLUDED.home_goals, match_statistics.home_goals)" in sql
    assert "away_goals = COALESCE(EXCLUDED.away_goals, match_statistics.away_goals)" in sql
