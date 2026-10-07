"""Banca · quanto foi investido (07/10/2026): em jogo agora, hoje, no periodo
e o que voltou, em reais com a unidade de cada aposta."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers.banca import _resumo_investido  # noqa: E402

HOJE = dt.date(2026, 10, 7)


def test_soma_aberto_hoje_total_e_retorno():
    entries = [
        # 13:00 UTC de hoje = 10:00 em Brasilia
        {"stake_reais": 20, "result": None, "followed_at": "2026-10-07T13:00:00"},
        {"stake_reais": 30, "result": "GREEN", "followed_at": "2026-10-07T12:00:00"},
        {"stake_reais": 50, "result": "RED", "followed_at": "2026-10-05T12:00:00"},
        # 01:00 UTC de 08/10 ainda e' dia 07 em Brasilia
        {"stake_reais": 10, "result": None, "followed_at": "2026-10-08T01:00:00"},
    ]
    # GREEN de 30 @2.0 = +30, RED = -50 -> total_pnl -20
    r = _resumo_investido(entries, total_pnl=-20, hoje=HOJE)
    assert r == {"total": 110, "em_aberto": 30, "apostas_em_aberto": 2,
                 "hoje": 60, "retornou": 60}


def test_sem_apostas_tudo_zero():
    assert _resumo_investido([], 0, hoje=HOJE) == {
        "total": 0, "em_aberto": 0, "apostas_em_aberto": 0, "hoje": 0, "retornou": 0}
