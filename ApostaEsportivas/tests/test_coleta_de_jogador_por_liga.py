# -*- coding: utf-8 -*-
"""A coleta de estatistica de jogador nao pode servir so' duas ligas (2026-08-27).

O DEFEITO NAO ERA UM ERRO, ERA UMA ORDENACAO

`coletar_pendentes` fazia `ORDER BY match_date DESC LIMIT 50`. Com backlog isso
nao e' um limite, e' um FILTRO: as 50 partidas mais recentes do banco inteiro
caem quase todas nas ligas que jogaram ontem.

E o backlog sempre existe, por construcao: cada rodada acrescenta jogo novo no
topo enquanto o antigo espera embaixo. Entao liga que joga em outro dia da
semana nunca era alcancada -- nao por estar excluida, mas por nunca chegar a vez
dela.

O sintoma e' o que o usuario descreveu: "falta muita liga ai' de jogadores". O
banco enchia com duas ou tres ligas de calendario denso, e o Player Stats so'
publicava prop delas.

Nada toca banco nem rede: o cursor e' duble' e guarda o SQL.
"""
import pytest

from collectors.player_stats_collector_service import PlayerStatsCollectorService


class _CursorFake:
    def __init__(self, ligas_com_fila=4, linhas=None):
        self._ligas = ligas_com_fila
        self._linhas = linhas or []
        self.sqls: list[str] = []
        self.params: list[tuple] = []
        self._rows: list = []

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        self.params.append(params or ())
        if "COUNT(DISTINCT ms.league_id)" in sql:
            self._rows = [[self._ligas]]
        else:
            self._rows = list(self._linhas)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _ConnFake:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def close(self):
        pass


def _rodar(monkeypatch, **kw):
    cur = _CursorFake(ligas_com_fila=kw.pop("ligas_com_fila", 4),
                      linhas=kw.pop("linhas", []))
    monkeypatch.setattr(
        "collectors.player_stats_collector_service.get_connection",
        lambda: _ConnFake(cur))

    servico = PlayerStatsCollectorService()
    coletadas = []
    monkeypatch.setattr(servico, "coletar", lambda fx: coletadas.append(fx) or len(fx))
    servico.coletar_pendentes(**kw)
    return cur, (coletadas[0] if coletadas else [])


def _sql_da_fila(cur):
    return next(s for s in cur.sqls if "ROW_NUMBER" in s)


# ── o rodizio ────────────────────────────────────────────────────────────
def test_a_fila_e_particionada_por_liga(monkeypatch):
    """Sem o PARTITION BY, as 50 mais recentes do banco inteiro sao quase todas
    das ligas que jogaram ontem."""
    cur, _ = _rodar(monkeypatch)

    assert "PARTITION BY ms.league_id" in _sql_da_fila(cur)


def test_cada_liga_avanca_por_execucao(monkeypatch):
    """Toda liga com fila anda, mesmo que devagar · o contrario e' umas
    andarem e outras nunca comecarem."""
    cur, _ = _rodar(monkeypatch, limite=50, ligas_com_fila=10)

    por_liga, limite = cur.params[-1]
    assert por_liga == 5, "50 / 10 ligas = 5 por liga"
    assert limite == 50


def test_o_piso_e_uma_partida_por_liga(monkeypatch):
    """Com mais ligas que o limite, dividir daria zero · e zero pararia a
    coleta inteira em silencio."""
    cur, _ = _rodar(monkeypatch, limite=5, ligas_com_fila=40)

    por_liga, _limite = cur.params[-1]
    assert por_liga == 1


def test_sem_fila_nenhuma_nao_divide_por_zero(monkeypatch):
    cur, _ = _rodar(monkeypatch, limite=50, ligas_com_fila=0)

    por_liga, _limite = cur.params[-1]
    assert por_liga == 50


def test_da_pra_fixar_quantas_por_liga(monkeypatch):
    """`por_liga` explicito ignora a divisao · e' como se varre uma liga nova
    sem esperar o rodizio."""
    cur, _ = _rodar(monkeypatch, limite=100, por_liga=20, ligas_com_fila=3)

    por_liga, limite = cur.params[-1]
    assert (por_liga, limite) == (20, 100)


# ── o que NAO mudou ──────────────────────────────────────────────────────
def test_dentro_da_liga_o_mais_recente_vem_primeiro(monkeypatch):
    """A API publica folha de jogo velho cada vez menos · gastar a cota no jogo
    de ontem rende mais que no de marco. Mesma razao da recoleta em lote."""
    sql = _sql_da_fila(_rodar(monkeypatch)[0])

    assert "ORDER BY ms.match_date DESC) AS ordem" in sql


def test_o_teto_geral_continua_valendo(monkeypatch):
    """Ele e' o que protege a cota da API · o rodizio reparte, nao afrouxa."""
    sql = _sql_da_fila(_rodar(monkeypatch)[0])

    assert "LIMIT %s" in sql


def test_so_entra_partida_sem_estatistica_de_jogador(monkeypatch):
    sql = _sql_da_fila(_rodar(monkeypatch)[0])

    assert "LEFT JOIN player_match_stats p" in sql
    assert "p.fixture_id IS NULL" in sql


def test_as_fixtures_chegam_no_formato_que_coletar_espera(monkeypatch):
    linhas = [(101, 71, 2026, "2026-08-26"), (102, 13, 2026, "2026-08-25")]
    _cur, enviadas = _rodar(monkeypatch, linhas=linhas)

    assert enviadas == [
        {"fixture_id": 101, "league_id": 71, "season": 2026, "match_date": "2026-08-26"},
        {"fixture_id": 102, "league_id": 13, "season": 2026, "match_date": "2026-08-25"},
    ]
