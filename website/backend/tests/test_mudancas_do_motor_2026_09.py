"""Antes x depois de cada mudança do motor (/api/admin/motor/mudancas).

A janela é [início, fim): a aposta do dia da mudança já conta como DEPOIS.
Acerto é o do site: meio green vale meio, push fica fora do denominador.
"""
from datetime import date

import routers.admin as admin


def linha(dia, result, profit):
    return {"match_date": date.fromisoformat(dia), "result": result, "profit": profit}


LINHAS = [
    linha("2026-09-10", "GREEN", 0.8), linha("2026-09-12", "RED", -1),
    linha("2026-09-15", "GREEN", 0.7), linha("2026-09-15", "HALF-WIN", 0.35),
    linha("2026-09-16", "PUSH", 0), linha("2026-09-17", "RED", -1),
]


def test_antes_nao_inclui_o_dia_da_mudanca():
    r = admin._resumo_janela(LINHAS, date(2026, 9, 1), date(2026, 9, 15))
    assert r == {"apostas": 2, "acerto": 0.5, "lucro": -0.2, "lucro_por_aposta": -0.1}


def test_depois_conta_push_nas_apostas_mas_nao_no_acerto():
    r = admin._resumo_janela(LINHAS, date(2026, 9, 15), date(2026, 9, 29))
    assert r["apostas"] == 4
    assert r["acerto"] == round(1.5 / 3, 4)
    assert r["lucro"] == 0.05


def test_janela_vazia_e_none():
    assert admin._resumo_janela(LINHAS, date(2026, 10, 1), date(2026, 10, 5)) is None


# ── Registro automático no deploy ─────────────────────────────────────────
import registro_de_deploy as reg


def test_titulo_sai_da_mensagem_do_merge():
    msg = "merge: taxa com o outro mando e gols pelos chutes vao pra producao\n\nCo-Authored-By: x"
    assert reg.titulo_do_merge(msg) == "Taxa com o outro mando e gols pelos chutes"


def test_commit_que_nao_e_merge_nao_registra():
    assert reg.titulo_do_merge("fix: algo") is None
    assert reg.titulo_do_merge(None) is None


def test_so_registra_em_producao(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "no-prod")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_MESSAGE", "merge: algo vai pra producao")
    assert reg.registrar(lambda: (_ for _ in ()).throw(AssertionError("nao devia conectar")), None) is False
