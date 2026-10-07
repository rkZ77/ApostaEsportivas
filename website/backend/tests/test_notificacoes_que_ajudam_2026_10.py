"""Notificacoes que faltavam (07/10/2026): pagamento aprovado, credito de
indicacao, push no celular dos avisos pessoais e do bilhete pessoal."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import routers.notifications as nt  # noqa: E402


# ── push individual ────────────────────────────────────────────────────────
def test_push_individual_respeita_o_staging(monkeypatch):
    disparos = []
    monkeypatch.setattr(nt, "VAPID_PRIVATE_KEY", "chave")
    monkeypatch.setattr(nt, "_enviar_push_do_usuario", lambda uid, data: disparos.append(uid))
    monkeypatch.setenv("SIDE_EFFECTS", "off")
    nt.push_para_usuario(7, "Oi")
    assert disparos == [], "noprod aponta pro banco de producao: nao manda push pra cliente"

    monkeypatch.setenv("SIDE_EFFECTS", "on")
    nt.push_para_usuario(7, "Oi")
    import time
    for _ in range(50):
        if disparos:
            break
        time.sleep(0.01)
    assert disparos == [7]


def test_push_sem_chave_vapid_nao_faz_nada(monkeypatch):
    disparos = []
    monkeypatch.setattr(nt, "VAPID_PRIVATE_KEY", "")
    monkeypatch.setattr(nt, "_enviar_push_do_usuario", lambda uid, data: disparos.append(uid))
    nt.push_para_usuario(7, "Oi")
    assert disparos == []


# ── pagamento e indicacao ──────────────────────────────────────────────────
class Cur:
    def __init__(self):
        self.criadas = []

    def execute(self, sql, params=None):
        if "INSERT INTO notifications" in sql:
            self.criadas.append(params)

    def close(self):
        pass


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def close(self):
        pass


def test_ativacao_avisa_quem_pagou_e_quem_indicou(monkeypatch):
    import routers.payments as pg
    cur = Cur()
    pushes = []
    monkeypatch.setattr(pg, "get_connection", lambda: Conn(cur))
    monkeypatch.setattr(nt, "push_para_usuario", lambda uid, t, b="", u="/": pushes.append((uid, t)))

    pg._avisar_ativacao(10, "mp-1", "Pick IA Mensal", dt.datetime(2026, 11, 7), 99, "Ana Souza")

    tipos = {(p[0], p[1]) for p in cur.criadas}
    assert (10, nt.TYPE_PAGAMENTO_OK) in tipos
    assert (99, nt.TYPE_INDICACAO) in tipos
    corpo_pagamento = next(p for p in cur.criadas if p[1] == nt.TYPE_PAGAMENTO_OK)[3]
    assert "07/11/2026" in corpo_pagamento
    corpo_indicacao = next(p for p in cur.criadas if p[1] == nt.TYPE_INDICACAO)[3]
    assert corpo_indicacao.startswith("Ana assinou")
    # dedupe pelo id do pagamento: reprocessar nao avisa de novo
    assert next(p for p in cur.criadas if p[1] == nt.TYPE_PAGAMENTO_OK)[-1] == "pagamento:mp-1"
    assert [u for u, _ in pushes] == [10, 99]


def test_ativacao_sem_indicador_avisa_so_quem_pagou(monkeypatch):
    import routers.payments as pg
    cur = Cur()
    monkeypatch.setattr(pg, "get_connection", lambda: Conn(cur))
    monkeypatch.setattr(nt, "push_para_usuario", lambda *a, **k: None)
    pg._avisar_ativacao(10, "mp-2", "Pick IA", dt.datetime(2026, 11, 7), None, None)
    assert [p[1] for p in cur.criadas] == [nt.TYPE_PAGAMENTO_OK]


def test_aviso_de_ativacao_nunca_derruba_a_ativacao(monkeypatch):
    import routers.payments as pg

    def quebra():
        raise RuntimeError("banco fora")
    monkeypatch.setattr(pg, "get_connection", quebra)
    pg._avisar_ativacao(10, "mp-3", "Pick IA", dt.datetime(2026, 11, 7), None, None)  # nao levanta


# ── resultado com push uma vez so' ─────────────────────────────────────────
def test_resultado_do_pick_manda_push_so_na_primeira_vez(monkeypatch):
    import routers.banca as banca
    pushes = []
    monkeypatch.setattr(nt, "push_para_usuario", lambda uid, t, b="", u="/": pushes.append(t))
    monkeypatch.setattr(nt, "avisar_resultado_no_whatsapp", lambda *a, **k: None)
    monkeypatch.setattr(banca, "_resolve_pick", lambda cur, i, t: {
        "result": "GREEN", "odd": 2.0, "home_team_name": None, "away_team_name": None,
        "market": "Meu bilhete · 2 seleções", "line": None})

    class CurResultado:
        def __init__(self, ja_existe):
            self.ja_existe = ja_existe
            self._r = []

        def execute(self, sql, params=None):
            if "FROM user_followed_picks" in sql:
                self._r = [{"user_id": 5, "stake_units": 1, "actual_odd": 2.5,
                            "cashout_amount": None, "unit_value": 20}]
            elif "SELECT 1 FROM notifications" in sql:
                self._r = [{"x": 1}] if self.ja_existe else []
            else:
                self._r = []

        def fetchall(self):
            return self._r

        def fetchone(self):
            return self._r[0] if self._r else None

    nt.notify_pick_result(CurResultado(ja_existe=False), 3, "pessoal", "GREEN")
    nt.notify_pick_result(CurResultado(ja_existe=True), 3, "pessoal", "GREEN")
    assert pushes == ["GREEN: Meu bilhete"]
