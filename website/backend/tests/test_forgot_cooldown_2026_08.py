"""Cooldown por conta no /forgot-password · anti email-bombing.

O limite por IP (main.py, FORGOT_LIMIT) e' o unico outro freio e e' burlavel:
CF-Connecting-IP e' aceito sem validacao, entao trocar de IP zera o balde e da'
pra encher a caixa da vitima e queimar cota do Resend. Este teste trava o
cooldown POR CONTA: dentro da janela nao reenvia, fora dela reenvia. Sempre
responde 200, pra nao revelar existencia do email nem o proprio cooldown.

Nada toca banco: cursor e conexao sao dubles.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.auth as auth  # noqa: E402


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.updates = 0

    def execute(self, sql, params=None):
        self._last = sql

    def fetchone(self):
        return self._row

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _rodar(monkeypatch, reset_exp):
    """Chama forgot_password com uma linha cujo reset_token_expires_at = reset_exp.
    Retorna quantas vezes _send_email foi chamado."""
    row = {"id": 1, "name": "Fulano", "reset_token_expires_at": reset_exp}
    cur = _FakeCursor(row)
    conn = _FakeConn(cur)
    monkeypatch.setattr(auth, "get_connection", lambda: conn)

    enviados = []
    monkeypatch.setattr(auth, "_send_email", lambda **kw: enviados.append(kw))

    resp = auth.forgot_password(auth.ForgotPasswordBody(email="v@v.com"))
    assert resp == {"ok": True}  # nunca vaza estado
    return len(enviados), conn.commits


def test_reenvio_dentro_da_janela_e_bloqueado(monkeypatch):
    """Codigo emitido agora (expira em 15) · pedir de novo nao manda email."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=auth._CODIGO_SENHA_EXPIRA_MIN)
    enviados, commits = _rodar(monkeypatch, exp)
    assert enviados == 0
    assert commits == 0


def test_reenvio_apos_cooldown_passa(monkeypatch):
    """Emitido ha' mais que o cooldown · manda o novo codigo."""
    # emitido_em = exp - 15min. Pra emitido_em ficar > cooldown atras, o exp
    # tem que estar (15 - cooldown - folga) minutos no futuro.
    minutos = auth._CODIGO_SENHA_EXPIRA_MIN - auth._RESET_COOLDOWN_MIN - 1
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    enviados, commits = _rodar(monkeypatch, exp)
    assert enviados == 1
    assert commits == 1


def test_sem_codigo_anterior_manda(monkeypatch):
    """Primeira vez (sem token) · manda normalmente."""
    enviados, commits = _rodar(monkeypatch, None)
    assert enviados == 1
    assert commits == 1


def test_expira_naive_tratado_como_utc(monkeypatch):
    """Coluna timestamp sem fuso nao pode explodir na comparacao."""
    exp = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)
    enviados, _ = _rodar(monkeypatch, exp)
    assert enviados == 0  # recem-emitido, bloqueia
