"""Pick liquidado sem lucro (15/10/2026): a validacao pick a pick do placar
achou tres, contando zero. A migracao preenche com a conta de sempre."""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import migrations  # noqa: E402


class _Cur:
    def __init__(self):
        self.sqls = []
        self.rowcount = 0
        self._ult = None

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        self._ult = {"existe": True} if "to_regclass" in sql else None
        self.rowcount = 1 if sql.strip().startswith("UPDATE") else 0

    def fetchone(self):
        return self._ult

    def close(self):
        pass


class _Conn:
    def __init__(self):
        self.cur = _Cur()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def test_preenche_so_lucro_vazio_com_a_conta_de_sempre(monkeypatch):
    import database
    conn = _Conn()
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    migrations._preencher_lucro_vazio(logging.getLogger("t"))
    updates = [s for s in conn.cur.sqls if s.strip().startswith("UPDATE")]
    assert len(updates) == len(migrations._ODD_DA_TABELA)
    assert all("profit IS NULL" in s for s in updates)
    assert any("UPDATE picks_multiplas" in s and "total_odd - 1" in s for s in updates)
    assert any("WHEN 'RED'       THEN -1" in s for s in updates)
    # Alavancagem tem conta por caminho: nao entra.
    assert not any("picks_alavancagem" in s for s in conn.cur.sqls)
    assert conn.commits == 1
