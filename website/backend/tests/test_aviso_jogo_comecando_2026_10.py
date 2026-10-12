"""Aviso de jogo de bilhete comecando (12/10/2026): um por pessoa por jogo,
so' banco, e falha nao derruba o agendador."""
from datetime import datetime

import bilhete_pessoal


class _Cur:
    def __init__(self, linhas, quebra=False):
        self.linhas, self.quebra = linhas, quebra
        self.sqls, self.notificacoes = [], []

    def execute(self, sql, params=None):
        if self.quebra:
            raise RuntimeError("banco fora")
        self.sqls.append((sql, params))

    def fetchall(self):
        return self.linhas

    def close(self): pass


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits, self.rollbacks = cur, 0, 0

    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


def test_cria_um_aviso_por_pessoa_e_jogo(monkeypatch):
    feitas = []
    from routers import notifications
    monkeypatch.setattr(notifications, "create_notification",
                        lambda cur, uid, tipo, titulo, chave, **kw: feitas.append((uid, tipo, titulo, chave, kw)))
    linhas = [{"user_id": 7, "fixture_id": 99, "home_team": "Atalanta", "away_team": "Venezia",
               "home_team_id": 499, "away_team_id": 517,
               "match_datetime": datetime(2026, 10, 12, 16, 0)}]
    conn = _Conn(_Cur(linhas))
    assert bilhete_pessoal.avisar_jogos_comecando(conn) == 1
    uid, tipo, titulo, chave, kw = feitas[0]
    assert (uid, tipo, titulo, chave) == (7, "jogo_comecando", "Atalanta x Venezia", "comecando:99")
    assert "16:00" in kw["body"] and kw["payload"]["fixture_id"] == 99
    assert conn.commits == 1
    sql, params = conn.cur.sqls[0]
    assert "result IS NULL" in sql and params == (bilhete_pessoal.JANELA_DO_AVISO_MIN,)


def test_falha_do_banco_nao_levanta():
    conn = _Conn(_Cur([], quebra=True))
    assert bilhete_pessoal.avisar_jogos_comecando(conn) == 0
    assert conn.rollbacks == 1
