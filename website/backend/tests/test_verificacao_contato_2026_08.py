"""Verificação de contato · gate de e-mail e OTP por SMS (18/08/2026).

Duas travas que nasceram juntas, pelo mesmo motivo: o CPF saiu do cadastro e
nada mais provava quem estava do outro lado. O e-mail ganhou carência com
prazo, e o telefone ganhou código por SMS.

O que estes testes protegem é o que dói se quebrar em silêncio: e-mail
vazando inteiro numa resposta de erro, SMS que parece ter saído e não saiu, e
código de 6 dígitos previsível.
"""

import re

import pytest

from routers import auth
from routers.auth import (
    EMAIL_GATE_CARENCIA_DIAS,
    EMAIL_GATE_DESDE,
    _gerar_codigo_numerico,
    _mascarar_email,
    _reenviar_verificacao_no_gate,
)
import sms as sms_mod


# ── máscara do e-mail no 403 ─────────────────────────────────────────────────

def test_mascara_preserva_o_dominio_e_esconde_o_resto():
    """A pessoa precisa reconhecer onde procurar sem a tela entregar a conta."""
    assert _mascarar_email("fulano@gmail.com") == "fu***@gmail.com"


def test_mascara_nao_vaza_usuario_curto():
    assert _mascarar_email("ab@x.com") == "a***@x.com"


def test_mascara_aguenta_string_sem_arroba():
    assert _mascarar_email("naoehemail") == "naoehemail"


# ── carência do gate ─────────────────────────────────────────────────────────

def test_carencia_nao_e_zero():
    """Zero dias seria a trava imediata que foi descartada de propósito:
    e-mail no spam viraria cadastro perdido no dia 1."""
    assert EMAIL_GATE_CARENCIA_DIAS >= 1


def test_gate_so_vale_para_contas_novas():
    """Sem a data de corte, VIP pagante que nunca confirmou e-mail seria
    trancado fora do site que ele paga."""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", EMAIL_GATE_DESDE)


def test_data_de_corte_torta_cai_no_padrao(monkeypatch):
    """O valor entra no SQL por interpolacao (data nao cabe em placeholder
    dentro de `DATE '...'`), entao formato invalido nao pode passar adiante."""
    for lixo in ["ontem", "2026-8-1", "'; DROP TABLE users; --", ""]:
        monkeypatch.setenv("EMAIL_GATE_DESDE", lixo)
        assert auth._gate_desde() == "2026-08-18"


def test_data_de_corte_valida_e_respeitada(monkeypatch):
    monkeypatch.setenv("EMAIL_GATE_DESDE", "2026-01-01")
    assert auth._gate_desde() == "2026-01-01"


@pytest.mark.parametrize("valor", ["0", "-3", "abc", ""])
def test_carencia_invalida_cai_no_padrao(monkeypatch, valor):
    """Zero seria a trava imediata que foi descartada de proposito."""
    monkeypatch.setenv("EMAIL_GATE_CARENCIA_DIAS", valor)
    assert auth._gate_carencia_dias() == 3


def test_carencia_valida_e_respeitada(monkeypatch):
    monkeypatch.setenv("EMAIL_GATE_CARENCIA_DIAS", "7")
    assert auth._gate_carencia_dias() == 7


class CursorFalso:
    def __init__(self):
        self.executados = []

    def execute(self, sql, params=None):
        self.executados.append((sql, params))

    def fetchone(self):
        return None


class ConexaoFalsa:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class TarefasFalsas:
    def __init__(self):
        self.agendadas = []

    def add_task(self, fn, *a, **kw):
        self.agendadas.append((fn, a, kw))


@pytest.fixture(autouse=True)
def _zera_cooldown():
    auth._email_gate_ultimo_reenvio.clear()
    yield
    auth._email_gate_ultimo_reenvio.clear()


def test_reenvio_no_gate_agenda_um_email():
    cur, conn, tarefas = CursorFalso(), ConexaoFalsa(), TarefasFalsas()

    _reenviar_verificacao_no_gate(cur, conn, {"id": 1, "email": "a@b.com", "name": "A"}, tarefas)

    assert len(tarefas.agendadas) == 1
    assert conn.commits == 1


def test_reenvio_no_gate_respeita_cooldown():
    """Dez tentativas de login não podem virar dez e-mails · a reputação do
    domínio paga por isso."""
    cur, conn, tarefas = CursorFalso(), ConexaoFalsa(), TarefasFalsas()
    usuario = {"id": 1, "email": "a@b.com", "name": "A"}

    _reenviar_verificacao_no_gate(cur, conn, usuario, tarefas)
    _reenviar_verificacao_no_gate(cur, conn, usuario, tarefas)
    _reenviar_verificacao_no_gate(cur, conn, usuario, tarefas)

    assert len(tarefas.agendadas) == 1


# ── código de verificação ────────────────────────────────────────────────────

def test_codigo_tem_sempre_seis_digitos():
    """Inclui os casos com zero à esquerda, que um int puro comeria."""
    for _ in range(200):
        codigo = _gerar_codigo_numerico()
        assert len(codigo) == 6
        assert codigo.isdigit()


# ── normalização do telefone para a operadora ────────────────────────────────

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("+5511999998888", "11999998888"),
        ("5511999998888", "11999998888"),
        ("11999998888", "11999998888"),
        ("+55 (11) 99999-8888", "11999998888"),
    ],
)
def test_tira_o_codigo_do_pais(entrada, esperado):
    """O banco guarda E.164 e a Comtele espera DDD + número."""
    assert sms_mod._so_digitos_br(entrada) == esperado


def test_fixo_de_dez_digitos_nao_perde_o_ddd():
    """`5511` no começo de um celular é código do país + DDD, mas um número de
    10 dígitos que comece com 55 é DDD 55 (RS) · cortar seria mutilar."""
    assert sms_mod._so_digitos_br("5511998888") == "5511998888"


# ── envio ────────────────────────────────────────────────────────────────────

def test_sem_provedor_o_sms_conta_como_indisponivel(monkeypatch):
    """`log` e' modo de desenvolvimento, nao canal.

    Trata-lo como disponivel faria a tela do perfil oferecer um botao que
    responde "codigo enviado" com o codigo indo so' pro log do servidor. E' o
    estado padrao hoje: o SMS fica desligado ate haver credito no provedor.
    """
    monkeypatch.delenv("SMS_PROVIDER", raising=False)
    assert sms_mod.sms_configurado() is False


def test_com_provedor_o_sms_fica_disponivel(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "comtele")
    assert sms_mod.sms_configurado() is True


def test_modo_log_nao_estoura_e_nao_chama_rede(monkeypatch):
    """É o que faz o fluxo inteiro ser testável em dev sem chave nem crédito."""
    monkeypatch.delenv("SMS_PROVIDER", raising=False)

    def _proibido(*_a, **_kw):
        raise AssertionError("modo log não pode falar com a rede")

    monkeypatch.setattr(sms_mod.httpx, "post", _proibido)
    sms_mod.enviar_sms("+5511999998888", "teste")


def test_comtele_sem_chave_avisa_em_vez_de_fingir(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "comtele")
    monkeypatch.delenv("SMS_COMTELE_AUTH_KEY", raising=False)

    with pytest.raises(sms_mod.SMSNaoEnviado):
        sms_mod.enviar_sms("+5511999998888", "teste")


class RespostaFalsa:
    def __init__(self, status=200, dados=None, texto=""):
        self.status_code = status
        self._dados = dados
        self.text = texto

    def json(self):
        if self._dados is None:
            raise ValueError("sem json")
        return self._dados


def test_comtele_http_200_com_success_false_e_falha(monkeypatch):
    """O caso que mais engana: HTTP 200, crédito acabado, SMS nenhum. Sem esta
    checagem a tela diria 'código enviado' e o usuário esperaria pra sempre."""
    monkeypatch.setenv("SMS_PROVIDER", "comtele")
    monkeypatch.setenv("SMS_COMTELE_AUTH_KEY", "chave")
    monkeypatch.setattr(
        sms_mod.httpx, "post",
        lambda *a, **kw: RespostaFalsa(200, {"Success": False, "Message": "Sem credito"}),
    )

    with pytest.raises(sms_mod.SMSNaoEnviado):
        sms_mod.enviar_sms("+5511999998888", "teste")


def test_comtele_sucesso_manda_ddd_sem_codigo_do_pais(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "comtele")
    monkeypatch.setenv("SMS_COMTELE_AUTH_KEY", "chave")
    capturado = {}

    def _post(url, json=None, headers=None, timeout=None):
        capturado["url"] = url
        capturado["json"] = json
        capturado["headers"] = headers
        return RespostaFalsa(200, {"Success": True})

    monkeypatch.setattr(sms_mod.httpx, "post", _post)
    sms_mod.enviar_sms("+5511999998888", "codigo 123456")

    assert capturado["json"]["Receivers"] == "11999998888"
    assert capturado["headers"]["auth-key"] == "chave"
    assert "codigo 123456" == capturado["json"]["Content"]


def test_erro_de_rede_vira_sms_nao_enviado(monkeypatch):
    """Exceção crua do httpx viraria 500 · o usuário precisa de recado."""
    monkeypatch.setenv("SMS_PROVIDER", "comtele")
    monkeypatch.setenv("SMS_COMTELE_AUTH_KEY", "chave")

    def _explode(*_a, **_kw):
        raise OSError("conexão caiu")

    monkeypatch.setattr(sms_mod.httpx, "post", _explode)

    with pytest.raises(sms_mod.SMSNaoEnviado):
        sms_mod.enviar_sms("+5511999998888", "teste")
