"""Purchase pela API de Conversões do Meta (analytics.send_meta_purchase)."""
import hashlib

import analytics


class _Resp:
    status_code = 200
    text = "{}"


def _ligar(monkeypatch, enviados, pixels=("111",)):
    monkeypatch.setattr(analytics, "META_CAPI_TOKEN", "tok")
    monkeypatch.setattr(analytics, "META_PIXEL_IDS", list(pixels))
    monkeypatch.setattr(analytics, "is_production", lambda: True)
    monkeypatch.setattr(analytics.requests, "post",
                        lambda url, **kw: enviados.append((url, kw)) or _Resp())


def _enviar(**extra):
    args = dict(user_id=7, payment_id="99", plan_key="mensal", plan_title="Mensal",
                amount=29.9, email=" Fulano@Mail.com ", nome="Fulano de Tal",
                fbp="fb.1.1700000000000.123", fbc="", ip="1.2.3.4", user_agent="UA")
    args.update(extra)
    analytics.send_meta_purchase(**args)


def _sha(v):
    return hashlib.sha256(v.encode()).hexdigest()


def test_sem_token_nao_envia(monkeypatch):
    enviados = []
    _ligar(monkeypatch, enviados)
    monkeypatch.setattr(analytics, "META_CAPI_TOKEN", "")
    _enviar()
    assert enviados == []


def test_fora_de_producao_nao_envia(monkeypatch):
    enviados = []
    _ligar(monkeypatch, enviados)
    monkeypatch.setattr(analytics, "is_production", lambda: False)
    _enviar()
    assert enviados == []


def test_payload_tem_pii_em_hash_e_dedup_pelo_pagamento(monkeypatch):
    enviados = []
    _ligar(monkeypatch, enviados)
    _enviar()
    (url, kw), = enviados
    assert url.endswith("/111/events")
    evento = kw["json"]["data"][0]
    assert evento["event_name"] == "Purchase"
    assert evento["event_id"] == "purchase-99"
    ud = evento["user_data"]
    assert ud["em"] == [_sha("fulano@mail.com")]
    assert ud["fn"] == [_sha("fulano")]
    assert ud["ln"] == [_sha("tal")]
    assert ud["external_id"] == [_sha("7")]
    assert ud["fbp"] == "fb.1.1700000000000.123"
    assert "fbc" not in ud
    assert "Fulano" not in str(kw["json"])
    assert evento["custom_data"]["value"] == 29.9
    assert evento["custom_data"]["currency"] == "BRL"


def test_conta_excluida_nao_manda_email(monkeypatch):
    enviados = []
    _ligar(monkeypatch, enviados)
    _enviar(email="excluida-7@conta.invalid")
    assert "em" not in enviados[0][1]["json"]["data"][0]["user_data"]


def test_manda_pra_cada_pixel_configurado(monkeypatch):
    enviados = []
    _ligar(monkeypatch, enviados, pixels=("111", "222"))
    _enviar()
    assert [u.rsplit("/", 2)[-2] for u, _ in enviados] == ["111", "222"]


def test_erro_de_rede_nao_levanta(monkeypatch):
    _ligar(monkeypatch, [])

    def explode(*a, **k):
        raise ConnectionError("fora do ar")
    monkeypatch.setattr(analytics.requests, "post", explode)
    _enviar()


def test_cookie_fora_do_formato_e_descartado():
    assert analytics.parse_meta_cookie("fb.1.1700000000000.AbC_-9") == "fb.1.1700000000000.AbC_-9"
    assert analytics.parse_meta_cookie("<script>") == ""
    assert analytics.parse_meta_cookie("fb.1.123.x") == ""
    assert analytics.parse_meta_cookie("") == ""
