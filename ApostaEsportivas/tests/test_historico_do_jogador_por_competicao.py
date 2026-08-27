# -*- coding: utf-8 -*-
"""O historico do JOGADOR passa a respeitar competicao e temporada (2026-08-27).

A INCOERENCIA DENTRO DO MESMO PICK
----------------------------------
`player_history.volume_do_adversario` sempre filtrou por `league_id` e
`season`, com a justificativa escrita la': mandante e visitante produzem chute
no alvo em taxas diferentes, e a media misturada nao descreve nem um caso nem o
outro.

`player_history.carregar`, que le o historico do PROPRIO jogador e alimenta o
mesmo pick, nao filtrava por nada. Lia as 15 ultimas atuacoes em qualquer
competicao e qualquer temporada. O mesmo atacante entrava na conta com jogo de
Brasileirao, de Libertadores e da temporada passada -- de outro clube, se tinha
sido transferido.

A REGRA NAO E' NOVA
-------------------
E' a mesma de `competition_profile.uses_all_competitions_history`, que o lado
dos times ja' usa: fixture de liga le' aquela liga; copa de clube e selecao leem
todas as competicoes, porque a propria competicao nao acumula jogo suficiente e
travar nela reprova a fixture inteira em silencio.

A TEMPORADA E' SEPARADA DA COMPETICAO, e este teste trava isso: "todas as
competicoes" e' sobre COMPETICAO, nunca sobre ANO. Um jogador com poucos jogos
na copa puxaria a temporada passada se o filtro de season caisse junto.
"""
import pytest

from services.player_stats_engine import player_history

#: Brasileirao Serie A -- liga. Libertadores -- copa de clube.
LIGA = 71
COPA = 13


class _CursorFake:
    def __init__(self, linhas=None):
        self._linhas = linhas or []
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params or ()

    def fetchall(self):
        return list(self._linhas)


def _carregar(**kw):
    cur = _CursorFake()
    player_history.carregar(cur, 99, "shots_on", **kw)
    return cur


# ── fixture de LIGA: recorta na propria liga ─────────────────────────────
def test_fixture_de_liga_le_so_aquela_liga():
    cur = _carregar(league_id=LIGA, season=2026)

    assert "AND league_id = %s" in cur.sql
    assert LIGA in cur.params


def test_fixture_de_liga_tambem_recorta_a_temporada():
    cur = _carregar(league_id=LIGA, season=2026)

    assert "AND season = %s" in cur.sql
    assert 2026 in cur.params


# ── fixture de COPA: todas as competicoes, mesma temporada ───────────────
def test_copa_le_todas_as_competicoes():
    """Mata-mata nao acumula jogo suficiente · travar nele reprovaria a fixture
    inteira em silencio. Mesma decisao do lado dos times."""
    cur = _carregar(league_id=COPA, season=2026)

    assert "AND league_id = %s" not in cur.sql
    assert COPA not in cur.params


def test_copa_nao_afrouxa_a_temporada():
    """"Todas as competicoes" e' sobre COMPETICAO, nunca sobre ANO · sem isso o
    jogador com poucos jogos na copa puxaria a temporada passada, possivelmente
    de outro clube."""
    cur = _carregar(league_id=COPA, season=2026)

    assert "AND season = %s" in cur.sql
    assert 2026 in cur.params


# ── compatibilidade ──────────────────────────────────────────────────────
def test_sem_liga_le_tudo_como_antes():
    """Backtest e teste antigo dependem do comportamento anterior · o recorte
    so' existe quando o chamador diz de qual partida esta' falando."""
    cur = _carregar()

    assert "AND league_id = %s" not in cur.sql
    assert "AND season = %s" not in cur.sql


def test_o_corte_de_minutos_continua_valendo_em_todos_os_casos():
    for kw in ({}, {"league_id": LIGA, "season": 2026}, {"league_id": COPA, "season": 2026}):
        cur = _carregar(**kw)
        assert "COALESCE(minutes, 0) >= %s" in cur.sql
        assert player_history.MIN_MINUTOS in cur.params


def test_o_limite_e_sempre_o_ultimo_parametro():
    """Ele entra depois dos filtros · trocar a ordem faria o LIMIT receber um
    league_id, e a consulta devolveria dezenas de linhas em silencio."""
    cur = _carregar(league_id=LIGA, season=2026)

    assert cur.params[-1] == player_history.LIMITE_ATUACOES


# ── a composicao ─────────────────────────────────────────────────────────
class TestComposicao:
    """Sem isto, media tirada de duas competicoes e media tirada de uma sao o
    mesmo numero na tela, e so' reproduzindo a consulta da' pra saber qual e'
    qual. Mesmo papel de `multi_competicao` na amostra do time."""

    def test_uma_competicao_nao_e_multi(self):
        c = player_history.composicao([{"league_id": LIGA}] * 5)
        assert c["multi_competicao"] is False
        assert c["competicoes"] == [LIGA]
        assert c["atuacoes"] == 5

    def test_duas_competicoes_sao_marcadas_e_contadas(self):
        c = player_history.composicao(
            [{"league_id": LIGA}] * 7 + [{"league_id": COPA}] * 3)
        assert c["multi_competicao"] is True
        assert c["competicoes"] == sorted([LIGA, COPA])
        assert c["por_competicao"] == {LIGA: 7, COPA: 3}

    def test_lista_vazia_nao_estoura(self):
        c = player_history.composicao([])
        assert c["atuacoes"] == 0
        assert c["multi_competicao"] is False
