"""Card de pick com jogo encerrado mantem liga e horario (11/10/2026).

O motor apaga de `fixtures` o jogo que terminou; o card lia liga e horario so'
dali. Agora a listagem le' a view `fixtures_todas` (fixtures + arquivo) e, no
VIP, cai na liga gravada no proprio pick. Nenhum teste toca banco.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import migrations  # noqa: E402

_AQUI = os.path.dirname(__file__)
_SUGESTOES = open(os.path.join(_AQUI, "..", "routers", "suggestions.py"), encoding="utf-8").read()
_MOTOR = open(os.path.join(_AQUI, "..", "..", "..", "ApostaEsportivas", "src", "collectors",
                           "fixture_status_sync_service.py"), encoding="utf-8").read()


def _corpo(nome: str) -> str:
    inicio = _SUGESTOES.index(f"def {nome}(")
    fim = _SUGESTOES.find("\n@router.", inicio)
    return _SUGESTOES[inicio:fim]


def test_rotas_de_exibicao_leem_a_view():
    for rota in ("get_today_suggestions", "get_suggestion_detail",
                 "get_recent_results", "get_picks_free_history"):
        corpo = _corpo(rota)
        assert "JOIN fixtures_todas" in corpo, rota
        assert not re.search(r"JOIN fixtures f[12]?\b", corpo), rota


def test_vip_cai_na_liga_do_proprio_pick():
    corpo = _corpo("get_today_suggestions")
    assert corpo.count("COALESCE(l.name, s.league_name) AS league_name") == 3
    assert corpo.count("COALESCE(f.league_id, s.league_id) AS league_id") == 3


def test_a_mesma_tabela_de_arquivo_nos_dois_lados():
    ddl = lambda s: re.sub(r"\s+", " ", s).strip()
    m = re.search(r'SQL_TABELA_DE_ARQUIVO = """(.*?)"""', _MOTOR, re.S)
    assert ddl(m.group(1)) == ddl(migrations._SQL_FIXTURES_ARQUIVO)


def test_view_minima_existe_mesmo_sem_arquivo():
    minima = migrations._SQL_FIXTURES_TODAS.split("UNION ALL")[0]
    assert "CREATE OR REPLACE VIEW fixtures_todas" in minima
    assert "fixtures_arquivo" not in minima


class _Cur:
    def __init__(self, falhar_na_view_completa):
        self.falhar, self.sqls = falhar_na_view_completa, []

    def execute(self, sql, args=None):
        self.sqls.append(sql)
        if self.falhar and "UNION ALL" in sql:
            raise RuntimeError("tipo incompativel")

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.c = cur

    def cursor(self):
        return self.c

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_view_completa_quebrada_cai_na_minima(monkeypatch):
    import logging

    import database
    cur = _Cur(falhar_na_view_completa=True)
    monkeypatch.setattr(database, "get_connection", lambda: _Conn(cur))
    migrations._migrar_arquivo_de_fixtures(logging.getLogger("t"))
    assert "UNION ALL" not in cur.sqls[-1]
    assert "CREATE OR REPLACE VIEW fixtures_todas" in cur.sqls[-1]
