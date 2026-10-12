"""Coleta automatica de estatistica dispara de verdade (12/10/2026).

O freio procurava jogo com status FT em `fixtures`, e o sincronizador apaga o
jogo dali quando ele termina: a coleta nunca rodava, e o bilhete pessoal (que
liquida pela folha) ficava Pendente com os jogos acabados. Sem banco.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import stats_sweep  # noqa: E402


def test_jogo_pendente_sem_folha_dispara(monkeypatch):
    monkeypatch.setattr(stats_sweep, "_tentados", {})
    monkeypatch.setattr(stats_sweep, "_pendentes_sem_estatistica", lambda: {101, 202})
    assert stats_sweep._ha_jogo_sem_estatistica(agora=10_000) is True


def test_o_mesmo_jogo_so_dispara_de_novo_depois_de_uma_hora(monkeypatch):
    """Jogo que a API nunca cobre nao pode virar coleta a cada 10 minutos."""
    monkeypatch.setattr(stats_sweep, "_tentados", {})
    monkeypatch.setattr(stats_sweep, "_pendentes_sem_estatistica", lambda: {101})
    assert stats_sweep._ha_jogo_sem_estatistica(agora=10_000) is True
    assert stats_sweep._ha_jogo_sem_estatistica(agora=10_600) is False
    assert stats_sweep._ha_jogo_sem_estatistica(agora=10_000 + 3600) is True


def test_jogo_novo_dispara_mesmo_com_outro_ja_tentado(monkeypatch):
    monkeypatch.setattr(stats_sweep, "_tentados", {101: 10_000})
    monkeypatch.setattr(stats_sweep, "_pendentes_sem_estatistica", lambda: {101, 303})
    assert stats_sweep._ha_jogo_sem_estatistica(agora=10_100) is True


def test_nada_pendente_nao_dispara(monkeypatch):
    monkeypatch.setattr(stats_sweep, "_tentados", {})
    monkeypatch.setattr(stats_sweep, "_pendentes_sem_estatistica", lambda: set())
    assert stats_sweep._ha_jogo_sem_estatistica(agora=10_000) is False


def test_a_pergunta_nao_depende_do_status_em_fixtures():
    import inspect
    fonte = inspect.getsource(stats_sweep._pendentes_sem_estatistica)
    assert "f.status IN" not in fonte
    assert "bilhetes_pessoais" in fonte and "calendario_jogos" in fonte
