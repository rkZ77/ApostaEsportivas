"""Historico da aba Dados: por PARTIDA, com teto no banco e paginacao.

A aba mostrava um agregado por liga ("N partidas com estatistica"), que nao
responde a pergunta que se faz olhando pra ela: o motor enxergou o jogo de
ontem? Liga com 3.000 jogos e liga com 4 apareciam iguais, uma linha cada, e
nenhuma das duas dizia QUAL jogo entrou.

O que os testes daqui travam nao e' o visual, e' o custo e a contagem:

  · o teto de 40 corta no SQL, ANTES do OFFSET -- senao a pagina 4 fica mais
    cara que a 1 e a rota envelhece junto com `match_statistics`
  · o nome do time sai por LATERAL, porque `teams` tem uma linha POR
    TEMPORADA e um JOIN direto multiplicaria a partida
  · pagina alem do teto nao chega a consultar nada

Nada toca banco: o cursor e' dublê e guarda o SQL que recebeu.
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.admin as admin  # noqa: E402


class _FakeCursor:
    def __init__(self, total=40, linhas=None, explode=False):
        self._total = total
        self._linhas = linhas if linhas is not None else []
        self._explode = explode
        self._rows = []
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def execute(self, sql, params=None):
        if self._explode:
            raise RuntimeError("banco fora do ar")
        self.sqls.append(sql)
        self.params.append(params)
        if "COUNT(*)" in sql:
            self._rows = [{"n": self._total}]
        else:
            self._rows = list(self._linhas)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *_a, **_kw):
        return self._cursor

    def rollback(self):
        pass

    def close(self):
        pass


def _rodar(monkeypatch, pagina=0, por_pagina=10, total=40, linhas=None, explode=False):
    cur = _FakeCursor(total=total, linhas=linhas, explode=explode)
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    saida = admin.partidas_coletadas(
        pagina=pagina, por_pagina=por_pagina,
        current_user={"id": 1, "plan": "admin"},
    )
    return saida, cur


def _sql_das_partidas(cur):
    for sql in cur.sqls:
        if "match_statistics ms" in sql:
            return sql
    raise AssertionError("a consulta de partidas nao rodou")


def _partida(**kw):
    base = {
        "fixture_id": 1, "data": "2026-08-22", "status": "FT",
        "liga": "Brasileirao A", "mandante": "Flamengo", "visitante": "Palmeiras",
        "home_goals": 1, "away_goals": 0,
        "escanteios": 9, "cartoes": 4, "faltas": 22,
    }
    return {**base, **kw}


class TestOTetoEDoBanco:
    def test_a_contagem_para_no_quadragesimo(self, monkeypatch):
        """COUNT na tabela inteira seria varredura completa a cada troca de
        pagina pra devolver, no maximo, 40."""
        _, cur = _rodar(monkeypatch, linhas=[_partida()])
        contagem = next(s for s in cur.sqls if "COUNT(*)" in s)
        assert "LIMIT 40" in contagem
        assert "FROM (SELECT 1 FROM match_statistics" in contagem

    def test_ultima_pagina_encolhe_em_vez_de_passar_do_teto(self, monkeypatch):
        """Pagina 3 de 15 comecaria no item 45. O LIMIT tem que virar 10, nao
        15, senao o "ultimas 40" mostra 45."""
        _, cur = _rodar(monkeypatch, pagina=2, por_pagina=15, linhas=[_partida()])
        limite, offset = cur.params[-1]
        assert (limite, offset) == (10, 30)

    def test_pagina_alem_do_teto_nao_consulta_partida_nenhuma(self, monkeypatch):
        """Nao e' so' devolver lista vazia: a consulta cara nao pode rodar."""
        saida, cur = _rodar(monkeypatch, pagina=4, por_pagina=10)
        assert saida["partidas"] == []
        assert not any("match_statistics ms" in s for s in cur.sqls)

    def test_total_nunca_passa_do_teto(self, monkeypatch):
        saida, _ = _rodar(monkeypatch, total=40, linhas=[_partida()])
        assert saida["total"] == 40
        assert saida["teto"] == 40


class TestEntradaDaQueryString:
    @pytest.mark.parametrize("pedido,esperado", [(999, 20), (0, 1), (-5, 1)])
    def test_por_pagina_fica_dentro_da_faixa(self, monkeypatch, pedido, esperado):
        """`por_pagina` vem da URL. Sem teto, `?por_pagina=100000` transforma a
        rota do painel numa varredura de tabela."""
        saida, _ = _rodar(monkeypatch, por_pagina=pedido, linhas=[_partida()])
        assert saida["por_pagina"] == esperado

    def test_pagina_negativa_vira_a_primeira(self, monkeypatch):
        """OFFSET negativo e' erro de SQL, nao pagina anterior."""
        saida, cur = _rodar(monkeypatch, pagina=-3, linhas=[_partida()])
        assert saida["pagina"] == 0
        assert cur.params[-1][1] == 0


class TestAConsulta:
    def test_nome_do_time_sai_por_lateral(self, monkeypatch):
        """`teams` tem UMA LINHA POR TEMPORADA por time. Um `JOIN teams ON
        team_id = ...` multiplica a partida por quantas temporadas o time
        tiver, e a pagina de 10 volta com 34 linhas."""
        _, cur = _rodar(monkeypatch, linhas=[_partida()])
        sql = _sql_das_partidas(cur)
        assert sql.count("LATERAL") == 2
        assert "ORDER BY season DESC LIMIT 1" in sql

    def test_ordem_desempata_pelo_fixture(self, monkeypatch):
        """`match_date` e' DATE pura: uma rodada inteira empata no mesmo dia. Sem
        desempate a paginacao repete e pula partida entre uma pagina e outra."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "ORDER BY ms.match_date DESC, ms.fixture_id DESC" in sql

    def test_nao_filtra_status(self, monkeypatch):
        """"Coletada" aqui e' ter linha na tabela. Jogo interrompido com
        estatistica gravada conta nas medias do motor igual aos outros ·
        esconder justo a linha esquisita e' esconder o problema."""
        sql = _sql_das_partidas(_rodar(monkeypatch, linhas=[_partida()])[1])
        assert "status IN" not in sql
        assert "ms.status" in sql, "o status precisa VIR, so' nao filtra"


class TestFalha:
    def test_banco_fora_do_ar_nao_derruba_a_aba(self, monkeypatch):
        """A aba serve justamente pra quando alguma coisa esta errada."""
        saida, _ = _rodar(monkeypatch, explode=True)
        assert saida["partidas"] == []
        assert saida["total"] == 0
        assert "erro" in saida


def test_dados_nao_devolve_mais_agregado_por_liga(monkeypatch):
    """O bloco por liga saiu da tela; a consulta que o alimentava tambem.
    Agregar `match_statistics` por liga varria a tabela inteira a cada
    abertura da aba pra desenhar uma lista que ninguem acionava."""
    cur = _FakeCursor(linhas=[])
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    saida = admin.dados_do_banco(current_user={"id": 1, "plan": "admin"})
    assert "por_liga" not in saida
    assert not any("GROUP BY l.league_id" in s for s in cur.sqls)
