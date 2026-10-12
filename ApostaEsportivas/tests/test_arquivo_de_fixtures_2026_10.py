"""Jogo encerrado vai pro arquivo antes de sair de `fixtures` (11/10/2026).

O card de pick perdia liga e horario porque o jogo era apagado no fim. Nenhum
teste toca banco: a conexao e' um duble que grava o SQL.
"""
from collectors import fixture_status_sync_service as svc


class _Cur:
    def __init__(self, falhar_no_arquivo=False):
        self.sqls = []
        self.falhar = falhar_no_arquivo

    def execute(self, sql, args=None):
        self.sqls.append(" ".join(sql.split()))
        if self.falhar and "INSERT INTO fixtures_arquivo" in sql:
            raise RuntimeError("sem permissao")

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits = cur, 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _rodar(monkeypatch, falhar=False):
    cur = _Cur(falhar)
    conn = _Conn(cur)
    monkeypatch.setattr(svc, "get_connection", lambda: conn)
    svc.FixtureStatusSyncService().delete_fixtures([10, 20])
    return cur, conn


def test_arquiva_antes_de_apagar(monkeypatch):
    cur, conn = _rodar(monkeypatch)
    ordem = [s.split()[0] + " " + s.split()[1] for s in cur.sqls]
    i_arq = next(i for i, s in enumerate(cur.sqls) if "INSERT INTO fixtures_arquivo" in s)
    i_del = next(i for i, s in enumerate(cur.sqls) if s.startswith("DELETE FROM fixtures"))
    assert i_arq < i_del, ordem
    assert conn.commits == 1


def test_arquivo_quebrado_nao_impede_o_delete(monkeypatch):
    cur, conn = _rodar(monkeypatch, falhar=True)
    assert any(s.startswith("ROLLBACK TO SAVEPOINT") for s in cur.sqls)
    assert any(s.startswith("DELETE FROM fixtures") for s in cur.sqls)
    assert conn.commits == 1
