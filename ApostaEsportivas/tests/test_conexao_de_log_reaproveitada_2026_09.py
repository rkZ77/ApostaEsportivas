"""A conexao de log e' UMA so', e sobrevive a conexao morta.

MEDIDO EM 2026-09-05: abrir conexao com o Supabase custa ~1,7s e o INSERT que
ela carrega roda em milissegundos. Os dois gravadores de log do motor abriam
uma conexao NOVA POR JOGO ANALISADO -- num dia de 57 jogos, mais de cem
conexoes e quase tres minutos so' de handshake, cada uma ocupando um slot que
o site precisa.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import utils.db_utils as db


class _Cursor:
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a):
        if self.conn.morta:
            raise RuntimeError("server closed the connection unexpectedly")
    def close(self): pass


class _Conn:
    def __init__(self): self.closed = False; self.morta = False; self.rollbacks = 0
    def cursor(self): return _Cursor(self)
    def rollback(self): self.rollbacks += 1
    def close(self): self.closed = True


def _fabrica(monkeypatch):
    abertas = []
    def _nova(env=None):
        c = _Conn(); abertas.append(c); return c
    monkeypatch.setattr(db, "get_connection", _nova)
    db.fechar_log_connection()
    return abertas


def test_abre_uma_vez_e_reaproveita(monkeypatch):
    abertas = _fabrica(monkeypatch)
    primeira = db.get_log_connection()
    for _ in range(20):
        assert db.get_log_connection() is primeira
    assert len(abertas) == 1, "abriu conexao a mais"


def test_conexao_morta_e_trocada_em_silencio(monkeypatch):
    """Servidor reinicia, rede cai, o Supabase encerra sessao ociosa. O log
    nao pode morrer junto."""
    abertas = _fabrica(monkeypatch)
    primeira = db.get_log_connection()
    primeira.morta = True
    segunda = db.get_log_connection()
    assert segunda is not primeira
    assert len(abertas) == 2


def test_vem_sempre_com_rollback(monkeypatch):
    """Sem isto, um erro anterior deixaria a transacao abortada e TODO log
    seguinte falharia junto -- o log falha aberto, entao ninguem veria."""
    _fabrica(monkeypatch)
    conn = db.get_log_connection()
    db.get_log_connection()
    assert conn.rollbacks >= 1


def test_fechar_libera(monkeypatch):
    abertas = _fabrica(monkeypatch)
    conn = db.get_log_connection()
    db.fechar_log_connection()
    assert conn.closed
    assert db.get_log_connection() is not conn
    assert len(abertas) == 2
