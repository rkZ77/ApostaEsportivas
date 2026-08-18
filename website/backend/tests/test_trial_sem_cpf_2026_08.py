"""Trial sem CPF · o contato verificado virou a barreira (18/08/2026).

O CPF era obrigatório no cadastro e disparava os 2 dias de VIP no próprio
INSERT. Ele saiu porque afundava a conversão e nunca teve função fiscal aqui.
Quem segura o trial agora é o par telefone único + contato verificado, e a
regra mora inteira em `_ativar_trial_se_elegivel`.

Estes testes existem porque a regra é a única coisa entre "2 dias de VIP por
conta" e "2 dias de VIP por e-mail digitado", e ela é chamada de três lugares
(link do e-mail, botão do perfil e, quando a WABA sair, o código do WhatsApp).
"""

from datetime import datetime, timedelta, timezone

import pytest

from routers.auth import RegisterBody, UpdateProfileBody, _ativar_trial_se_elegivel


class CursorFalso:
    """Cursor mínimo: devolve a linha combinada e guarda o que foi executado."""

    def __init__(self, linha):
        self._linha = linha
        self.executados = []

    def execute(self, sql, params=None):
        self.executados.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._linha

    @property
    def updates(self):
        return [sql for sql, _ in self.executados if sql.upper().startswith("UPDATE")]


def _conta(**campos):
    base = {
        "plan": "free",
        "trial_used": False,
        "email_verified": False,
        "phone_verified": False,
    }
    base.update(campos)
    return base


# ── quem ganha o trial ───────────────────────────────────────────────────────

def test_email_verificado_libera_o_trial():
    cur = CursorFalso(_conta(email_verified=True))
    antes = datetime.now(timezone.utc)

    expira = _ativar_trial_se_elegivel(cur, 7)

    assert expira is not None
    # Dois dias, com folga pro tempo de execução do próprio teste.
    assert timedelta(days=2) - timedelta(seconds=30) <= expira - antes <= timedelta(days=2, seconds=30)
    assert len(cur.updates) == 1
    assert "plan='trial'" in cur.updates[0]
    assert "trial_used=TRUE" in cur.updates[0]


def test_telefone_verificado_tambem_libera():
    """A porta do WhatsApp precisa valer sozinha.

    Se só o e-mail contasse, o OTP do WhatsApp não teria como pagar o trial e
    a Meta reprovar o template levaria o trial junto.
    """
    cur = CursorFalso(_conta(phone_verified=True))

    assert _ativar_trial_se_elegivel(cur, 7) is not None
    assert len(cur.updates) == 1


# ── quem não ganha ───────────────────────────────────────────────────────────

def test_sem_contato_verificado_nao_libera():
    """O buraco que o CPF tapava: cadastro cru não vale VIP."""
    cur = CursorFalso(_conta())

    assert _ativar_trial_se_elegivel(cur, 7) is None
    assert cur.updates == []


def test_trial_ja_usado_nao_repete():
    cur = CursorFalso(_conta(email_verified=True, trial_used=True))

    assert _ativar_trial_se_elegivel(cur, 7) is None
    assert cur.updates == []


@pytest.mark.parametrize("plano", ["vip", "trial", "admin"])
def test_quem_nao_e_free_nao_recebe(plano):
    """Rebaixar um VIP pagante pra 'trial' seria cortar dias comprados."""
    cur = CursorFalso(_conta(plan=plano, email_verified=True))

    assert _ativar_trial_se_elegivel(cur, 7) is None
    assert cur.updates == []


def test_usuario_inexistente_nao_estoura():
    cur = CursorFalso(None)

    assert _ativar_trial_se_elegivel(cur, 999) is None
    assert cur.updates == []


# ── o CPF saiu mesmo dos contratos de entrada ────────────────────────────────

def test_cadastro_nao_pede_mais_cpf():
    corpo = RegisterBody(
        name="Fulano de Tal",
        email="fulano@example.com",
        password="SenhaForte1",
        phone="(11) 98888-7777",
        username="fulano",
        accepted_terms=True,
    )

    assert not hasattr(corpo, "cpf")


def test_perfil_nao_aceita_mais_cpf():
    """Sem isso o campo voltaria pela porta do perfil sem ninguém notar."""
    corpo = UpdateProfileBody(name="Fulano de Tal")

    assert not hasattr(corpo, "cpf")
