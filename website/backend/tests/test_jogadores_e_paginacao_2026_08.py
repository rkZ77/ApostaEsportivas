"""Jogadores na aba Dados, e paginacao nos arbitros (2026-08-27).

`player_match_stats` existe desde 01/08 e alimenta o Player Stats -- chutes,
chutes no alvo, faltas, desarmes, passes e defesas de goleiro. Nenhuma tela
mostrava o que ha' dentro dela: conferir a media de um jogador exigia abrir o
banco.

O QUE OS TESTES DAQUI TRAVAM
----------------------------
Nao e' o visual, sao as tres coisas que erram calado:

  · o CORTE DE MINUTOS e' o do motor (player_history.MIN_MINUTOS). Uma tela que
    ignorasse esse corte mostraria uma media que o motor nunca viu -- entrada de
    doze minutos e jogo inteiro nao sao a mesma observacao;
  · o MANDO sai do JOIN com `match_statistics`, porque `player_match_stats` nao
    guarda mando. O proprio motor separa casa de fora ao ler volume de
    adversario, com a justificativa de que a media misturada nao descreve nem um
    caso nem o outro;
  · `ordenar` e `mando` entram em f-string (nao da' pra parametrizar nome de
    coluna), entao os dois SO' podem vir de lista branca.

Nada toca banco: o cursor e' duble' e guarda o SQL que recebeu.
"""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.admin as admin  # noqa: E402

ADMIN = {"id": 1, "plan": "admin"}


class _FakeCursor:
    def __init__(self, linhas=None, total=3, temporadas=(2026, 2025)):
        self._linhas = linhas or []
        self._total = total
        self._temporadas = temporadas
        self._rows = []
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        self.params.append(params)
        if "DISTINCT season" in sql:
            self._rows = [{"season": s} for s in self._temporadas]
        elif "COUNT(*) AS n" in sql:
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


def _jogador(**kw):
    linha = {"player_id": 10, "nome": "Fulano", "time": "Flamengo", "posicao": "F",
             "atuacoes": 12, "minutos": 84, "ultima": "2026-08-22"}
    for chave, _rot, _col in admin.STATS_DO_JOGADOR:
        linha[f"{chave}_m"] = 2.5
        linha[f"{chave}_n"] = 12
    return {**linha, **kw}


def _rodar(monkeypatch, **kw):
    cur = _FakeCursor(linhas=kw.pop("linhas", [_jogador()]), total=kw.pop("total", 3))
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    saida = admin.lista_de_jogadores(current_user=ADMIN, **kw)
    return saida, cur


def _sql_da_lista(cur):
    for sql in cur.sqls:
        if "GROUP BY p.player_id" in sql and "ORDER BY" in sql:
            return sql
    raise AssertionError("a consulta da lista nao rodou")


# ── o corte de minutos e' o do motor ─────────────────────────────────────
class TestOCorteDeMinutos:
    def test_o_corte_entra_na_consulta(self, monkeypatch):
        saida, cur = _rodar(monkeypatch)
        assert "COALESCE(p.minutes, 0) >= %s" in _sql_da_lista(cur)
        assert saida["min_minutos"] in cur.params[-1]

    def test_o_valor_vem_do_motor_quando_ele_esta_no_path(self, monkeypatch):
        """A constante local e' fallback pra o site subir sem o pipeline · nao
        pode virar uma segunda verdade quando o motor esta' disponivel."""
        from services.player_stats_engine.player_history import MIN_MINUTOS

        saida, _ = _rodar(monkeypatch)
        assert saida["min_minutos"] == MIN_MINUTOS

    def test_a_tela_recebe_o_corte_pra_poder_dize_lo(self, monkeypatch):
        """"12 atuacoes" sem o corte e' um numero sem definicao, e e' o corte
        que explica a media nao bater com a conta feita a olho."""
        saida, _ = _rodar(monkeypatch)
        assert isinstance(saida["min_minutos"], int)


# ── o mando ──────────────────────────────────────────────────────────────
class TestOMando:
    def test_sem_mando_nao_junta_match_statistics(self, monkeypatch):
        """O JOIN so' serve pro mando · sem recorte ele sai caro a' toa numa
        tabela que cresce por jogador POR JOGO."""
        _, cur = _rodar(monkeypatch, mando="todos")
        assert "JOIN match_statistics" not in _sql_da_lista(cur)

    def test_casa_compara_com_o_mandante(self, monkeypatch):
        _, cur = _rodar(monkeypatch, mando="casa")
        sql = _sql_da_lista(cur)
        assert "JOIN match_statistics ms ON ms.fixture_id = p.fixture_id" in sql
        assert "ms.home_team_id = p.team_id" in sql

    def test_fora_compara_com_o_visitante(self, monkeypatch):
        _, cur = _rodar(monkeypatch, mando="fora")
        assert "ms.away_team_id = p.team_id" in _sql_da_lista(cur)

    def test_mando_desconhecido_vira_todos(self, monkeypatch):
        """`mando` entra em f-string · lista branca ou nada."""
        saida, cur = _rodar(monkeypatch, mando="'; DROP TABLE teams --")
        assert saida["mando"] == "todos"
        assert "DROP TABLE" not in _sql_da_lista(cur)


# ── ordenacao ────────────────────────────────────────────────────────────
class TestAOrdenacao:
    @pytest.mark.parametrize("chave", [c for c, _r, _x in admin.STATS_DO_JOGADOR])
    def test_toda_coluna_do_catalogo_ordena(self, monkeypatch, chave):
        saida, cur = _rodar(monkeypatch, ordenar=chave)
        assert saida["ordenar"] == chave
        coluna = dict((c, col) for c, _r, col in admin.STATS_DO_JOGADOR)[chave]
        assert f"ORDER BY AVG(p.{coluna})" in _sql_da_lista(cur)

    def test_coluna_desconhecida_cai_no_padrao(self, monkeypatch):
        saida, cur = _rodar(monkeypatch, ordenar="p.senha; DROP TABLE users --")
        assert saida["ordenar"] == "chutes"
        assert "DROP TABLE" not in _sql_da_lista(cur)


# ── a contagem e' POR COLUNA ─────────────────────────────────────────────
def test_cada_contador_tem_a_propria_amostra(monkeypatch):
    """Defesa aparece em 0,86% das atuacoes e passe em todas · um "12 jogos"
    unico ao lado das oito medias mentiria sobre pelo menos uma delas."""
    saida, cur = _rodar(monkeypatch)
    sql = _sql_da_lista(cur)
    for chave, _rot, coluna in admin.STATS_DO_JOGADOR:
        assert f"COUNT(p.{coluna}) AS {chave}_n" in sql
    assert all(f"{c}_n" in saida["jogadores"][0] for c, _r, _x in admin.STATS_DO_JOGADOR)


def test_as_colunas_agregadas_sao_qualificadas(monkeypatch):
    """Com mando o JOIN traz `match_statistics` junto · coluna sem qualificar
    num SELECT de duas tabelas e' erro esperando a proxima coluna homonima."""
    _, cur = _rodar(monkeypatch, mando="casa")
    sql = _sql_da_lista(cur)
    for _chave, _rot, coluna in admin.STATS_DO_JOGADOR:
        assert f"AVG(p.{coluna})" in sql


def test_o_time_vem_do_jogo_mais_recente(monkeypatch):
    """Jogador transferido no meio da temporada so' pode representar o time em
    que esta' agora · mesma escolha de player_history.jogadores_dos_times."""
    _, cur = _rodar(monkeypatch)
    assert "ARRAY_AGG(p.team_name ORDER BY p.match_date DESC))[1]" in _sql_da_lista(cur)


# ── paginacao ────────────────────────────────────────────────────────────
def test_jogadores_pagina(monkeypatch):
    saida, cur = _rodar(monkeypatch, pagina=2, por_pagina=15, total=97)
    assert cur.params[-1][-2:] == (15, 30)
    assert saida["total"] == 97


def test_arbitros_pagina_e_conta(monkeypatch):
    """Vinha com `limite=60` e a tela desenhava os 60 · numa temporada com 14
    ligas isso e' uma tabela que nao acaba no celular."""
    cur = _FakeCursor(linhas=[{"referee_id": 1, "name": "Daronco"}], total=88)
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    saida = admin.lista_de_arbitros(season=2026, pagina=3, por_pagina=15,
                                    current_user=ADMIN)
    assert saida["total"] == 88
    assert cur.params[-1][-2:] == (15, 45)


def test_arbitros_busca_por_nome(monkeypatch):
    """Paginar sem poder procurar so' troca rolagem por clique: o arbitro que
    interessa quase nunca esta' na primeira pagina."""
    cur = _FakeCursor(linhas=[], total=1)
    monkeypatch.setattr(admin, "get_connection", lambda: _FakeConn(cur))
    admin.lista_de_arbitros(season=2026, busca="daronco", current_user=ADMIN)
    sql = next(s for s in cur.sqls if "ORDER BY rs.games" in s)
    assert "r.name ILIKE %s" in sql
    assert "%daronco%" in cur.params[-1]
