"""Alerta de falha da IA no /admin (/api/admin/ia/alertas).

Em 27/09/2026 o Claude falhou em Free, Alavancagem e Boost e o único rastro era
"unavailable" no evento. A rota avisa quando a ÚLTIMA chamada de um gate falhou,
e some quando ele volta a responder. Nada toca banco.
"""
from datetime import datetime

import routers.admin as admin


class _Cursor:
    def __init__(self, ultimas, falhas=3):
        self._ultimas = ultimas
        self._falhas = falhas
        self._rows = []

    def execute(self, sql, params=None):
        if "DISTINCT ON" in sql:
            self._rows = list(self._ultimas)
        elif "COUNT(*)" in sql:
            self._rows = [{"n": self._falhas}]
        else:
            raise AssertionError(f"consulta inesperada: {sql[:80]}")

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def rollback(self):
        pass

    def close(self):
        pass


def _evento(pipeline, status, erro_tipo=None, erro=None):
    return {"pipeline": pipeline, "provider": "anthropic", "model": "claude-sonnet-5",
            "mode": "shadow", "status": status, "erro_tipo": erro_tipo, "erro": erro,
            "created_at": datetime(2026, 9, 27, 9, 30)}


def _rodar(monkeypatch, ultimas):
    monkeypatch.setattr(admin, "get_connection", lambda: _Conn(_Cursor(ultimas)))
    return admin.ia_alertas(current_user={"role": "admin"})["alertas"]


def test_ultima_chamada_com_falha_vira_alerta_com_a_acao(monkeypatch):
    alertas = _rodar(monkeypatch, [
        _evento("dica", "unavailable", "sem_credito", "credit balance is too low"),
    ])
    assert len(alertas) == 1
    assert alertas[0]["erro_tipo"] == "sem_credito"
    assert "créditos" in alertas[0]["acao"]
    assert alertas[0]["falhas_24h"] == 3


def test_gate_que_voltou_a_responder_nao_alerta(monkeypatch):
    assert _rodar(monkeypatch, [_evento("vip", "ok"), _evento("bingo", "disabled")]) == []


def test_evento_antigo_sem_tipo_ainda_alerta(monkeypatch):
    """Eventos gravados antes de 27/09 não têm `erro_tipo`."""
    alertas = _rodar(monkeypatch, [_evento("boost", "unavailable")])
    assert alertas[0]["erro_tipo"] == "erro"
