"""Assinatura do webhook do MercadoPago e reconhecimento de assinatura do site.

Existe por causa do incidente de 07/08/2026: o webhook rejeitava TODA
notificacao legitima com 403, entao quem pagava continuava free e a venda nao
entrava no relatorio. A causa era o manifesto HMAC montado fora da
especificacao -- faltava o ';' final e o id vinha do corpo em vez do query
string.

Os testes montam a assinatura do jeito que o MercadoPago monta e conferem que
a verificacao aceita. Se alguem "arrumar" o template de novo, quebra aqui em
vez de quebrar no caixa.
"""

import hashlib
import hmac

from routers.payments import (
    _apply_approved_payment,
    _e_assinatura,
    _mp_manifest,
    _verify_mp_signature,
)

SECRET = "segredo-de-webhook-para-teste"


def _assinar(data_id: str, request_id: str, ts: str = "1754500000", secret: str = SECRET) -> str:
    """Reproduz o que o MercadoPago envia no header x-signature."""
    manifesto = f"id:{data_id};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(secret.encode(), manifesto.encode(), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={v1}"


# ───────────────────────── Manifesto ─────────────────────────


def test_manifesto_termina_com_ponto_e_virgula():
    """O ';' depois do ts faz parte da mensagem assinada.

    Foi a sua ausencia que derrubou todo pagamento por webhook.
    """
    assert _mp_manifest("123", "req-1", "999") == "id:123;request-id:req-1;ts:999;"


def test_manifesto_omite_campo_ausente_inteiro():
    # Campo vazio sai junto com o seu ';', nao vira string vazia no meio.
    assert _mp_manifest("123", "", "999") == "id:123;ts:999;"


# ───────────────────────── Verificacao ─────────────────────────


def test_aceita_assinatura_montada_como_o_mercadopago_monta():
    sig = _assinar("171620546785", "req-abc")
    assert _verify_mp_signature(sig, "req-abc", "171620546785", SECRET) is True


def test_template_antigo_sem_ponto_e_virgula_nao_valida():
    """Trava a regressao: o formato antigo nao pode voltar a ser aceito."""
    ts = "1754500000"
    antigo = f"id:123;request-id:req-1;ts:{ts}"
    v1 = hmac.new(SECRET.encode(), antigo.encode(), hashlib.sha256).hexdigest()
    assert _verify_mp_signature(f"ts={ts},v1={v1}", "req-1", "123", SECRET) is False


def test_rejeita_id_trocado():
    sig = _assinar("111", "req-abc")
    assert _verify_mp_signature(sig, "req-abc", "222", SECRET) is False


def test_rejeita_segredo_errado():
    sig = _assinar("111", "req-abc")
    assert _verify_mp_signature(sig, "req-abc", "111", "outro-segredo") is False


def test_rejeita_request_id_trocado():
    sig = _assinar("111", "req-abc")
    assert _verify_mp_signature(sig, "req-outro", "111", SECRET) is False


def test_rejeita_assinatura_vazia_ou_sem_v1():
    assert _verify_mp_signature("", "req", "111", SECRET) is False
    assert _verify_mp_signature("ts=123", "req", "111", SECRET) is False
    assert _verify_mp_signature("lixo", "req", "111", SECRET) is False


def test_aceita_id_alfanumerico_em_maiuscula():
    """A doc manda usar o id minusculo; a notificacao pode trazer maiuscula."""
    sig = _assinar("abc-def", "req-1")
    assert _verify_mp_signature(sig, "req-1", "ABC-DEF", SECRET) is True


# ─────────────── Quem e assinatura do site, quem nao e ───────────────


def test_reconhece_assinatura_do_site():
    for plano in ("mensal", "trimestral", "semestral", "anual"):
        assert _e_assinatura({"external_reference": f"22:{plano}"}) is True


def test_ignora_transacao_pessoal_da_mesma_conta():
    """A conta do MercadoPago e a mesma da vida pessoal.

    Sem esse filtro a reconciliacao tentaria ativar VIP para cada
    transferencia -- sao milhares na janela de 180 dias.
    """
    for ref in ("POTS_2ff83527-b3f8-45c7_1110568427_0_2", "1775017362541", "", "22:", "22:premium", "abc:mensal"):
        assert _e_assinatura({"external_reference": ref}) is False


# ─────────────── Guardas antes de tocar no banco ───────────────


def test_nao_aprovado_nao_ativa_nada():
    """Sem conexao de banco no ambiente de teste: se tentasse ativar, estouraria."""
    r = _apply_approved_payment({"id": 1, "status": "pending"}, "teste")
    assert r["status"] == "not_approved"


def test_referencia_invalida_para_antes_do_banco():
    r = _apply_approved_payment(
        {"id": 1, "status": "approved", "external_reference": "POTS_123"}, "teste"
    )
    assert r["status"] == "error"


def test_plano_desconhecido_para_antes_do_banco():
    r = _apply_approved_payment(
        {"id": 1, "status": "approved", "external_reference": "22:vitalicio"}, "teste"
    )
    assert r["status"] == "error"


# ─────────────── Auto-reparo no login ───────────────


def test_auto_reparo_no_login_nunca_estoura(monkeypatch):
    """Nada no auto-reparo pode derrubar um login.

    Se o MercadoPago cair, o login tem que continuar acontecendo -- so' sem
    ativar VIP nenhum nessa volta.
    """
    from routers import payments

    def _explode(*_a, **_kw):
        raise RuntimeError("MercadoPago fora do ar")

    monkeypatch.setattr(payments, "_reconcile", _explode)
    assert payments.try_activate_pending(22) is None


def test_auto_reparo_devolve_a_ativacao_quando_encontra(monkeypatch):
    from routers import payments

    monkeypatch.setattr(payments, "_reconcile", lambda *_a, **_kw: {
        "encontrados": 1, "ja_registrados": 0, "falhas": [],
        "ativados": [{"payment_id": "171620546785", "user_id": 22, "plan": "mensal"}],
    })
    ativado = payments.try_activate_pending(22)
    assert ativado["payment_id"] == "171620546785"


def test_auto_reparo_devolve_none_quando_nao_ha_pagamento(monkeypatch):
    from routers import payments

    monkeypatch.setattr(payments, "_reconcile", lambda *_a, **_kw: {
        "encontrados": 0, "ja_registrados": 0, "falhas": [], "ativados": [],
    })
    assert payments.try_activate_pending(22) is None


def test_login_nao_le_checkout_started_at_na_query_principal():
    """A coluna nasce numa migration de startup.

    Se ela entrasse no SELECT do login e por algum motivo nao existisse no
    banco, o login inteiro cairia. Fora dele, a ausencia so' desliga o
    auto-reparo.
    """
    import io
    import os

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fonte = io.open(os.path.join(base, "routers", "auth.py"), encoding="utf-8").read()
    cols = fonte[fonte.index("_LOGIN_COLS = "):]
    cols = cols[:cols.index("\n")]
    assert "checkout_started_at" not in cols
