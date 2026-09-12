"""Excluir a propria conta (LGPD art. 18, inciso VI) -- 12/09/2026.

O site nao tinha porta de saida: dava pra criar conta, trocar e-mail, trocar
senha, mas nao dava pra sumir. A LGPD obriga a eliminacao dos dados pessoais a
pedido do titular, entao o endpoint nasceu.

A decisao que este arquivo protege e' a FORMA da exclusao. A linha de `users`
NAO e' apagada, e isso e' de proposito: `payments` referencia users com ON
DELETE CASCADE, entao um DELETE levaria junto a trilha fiscal que precisa ser
guardada. O caminho e' anonimizar a linha, apagar as tabelas pessoais e
desligar `active` -- o mesmo campo que get_current_user e o login ja checam, de
modo que a exclusao derruba a sessao sem codigo novo.

Os riscos que os testes prendem:

  1. exclusao sem confirmacao explicita (clique acidental);
  2. exclusao sem a senha, quando a conta tem senha (sessao roubada);
  3. `payments` entrando na lista de tabelas apagadas (perda fiscal);
  4. PII sobrevivendo ao UPDATE de anonimizacao;
  5. admin se excluindo pelo perfil e derrubando o acesso do site.
"""

import pytest
from fastapi import HTTPException, Response

from routers import auth as auth_mod
from routers.auth import _TABELAS_PESSOAIS, DeleteAccountBody, delete_account
from auth_utils import hash_password

SENHA = "SenhaCerta123"


class _CursorFalso:
    def __init__(self, linha):
        self.linha = linha
        self.sql = []
        self._ultimo = None

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))
        alvo = sql.strip().upper()
        if alvo.startswith("SELECT TO_REGCLASS"):
            self._ultimo = {"t": params[0]}       # toda tabela existe
        elif alvo.startswith("SELECT PASSWORD_HASH"):
            self._ultimo = self.linha
        else:
            self._ultimo = None

    def fetchone(self):
        return self._ultimo

    def close(self):
        pass


class _ConexaoFalsa:
    def __init__(self, cur):
        self._cur = cur
        self.commitou = False

    def cursor(self):
        return self._cur

    def commit(self):
        self.commitou = True

    def close(self):
        pass


@pytest.fixture
def banco(monkeypatch):
    """Monta a conta que o endpoint vai encontrar. Sem banco de verdade."""
    def _montar(linha=None):
        linha = linha or {"password_hash": hash_password(SENHA), "plan": "free"}
        cur = _CursorFalso(linha)
        conn = _ConexaoFalsa(cur)
        monkeypatch.setattr(auth_mod, "get_connection", lambda: conn)
        monkeypatch.setattr(auth_mod, "invalidar_cache_usuario", lambda _id: None)
        monkeypatch.setattr(auth_mod, "_check_profile_rate", lambda _id: None)
        return conn, cur
    return _montar


def _chamar(body):
    return delete_account(body, Response(), {"sub": 42})


# -- as duas travas antes de apagar qualquer coisa --------------------------

@pytest.mark.parametrize("confirmacao", [None, "", "excluir minha conta", "sim", "DELETE"])
def test_sem_a_palavra_exata_nao_exclui(banco, confirmacao):
    conn, cur = banco()
    with pytest.raises(HTTPException) as e:
        _chamar(DeleteAccountBody(current_password=SENHA, confirmacao=confirmacao))
    assert e.value.status_code == 400
    assert not conn.commitou
    assert not any("DELETE FROM" in s for s, _ in cur.sql)


def test_confirmacao_aceita_minuscula_e_espaco(banco):
    """A palavra e' trava contra clique acidental, nao teste de digitacao."""
    conn, _ = banco()
    assert _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="  excluir  ")) == {"ok": True}
    assert conn.commitou


def test_senha_errada_nao_exclui(banco):
    conn, cur = banco()
    with pytest.raises(HTTPException) as e:
        _chamar(DeleteAccountBody(current_password="outra", confirmacao="EXCLUIR"))
    assert e.value.status_code == 400
    assert not conn.commitou
    assert not any("DELETE FROM" in s for s, _ in cur.sql)


def test_conta_sem_senha_nao_pede_senha(banco):
    """Conta nascida no Google tem password_hash NULL.

    Exigir senha ali seria trancar a pessoa do lado de dentro: ela nao tem
    nenhuma pra digitar. O login valido + a confirmacao bastam.
    """
    conn, _ = banco({"password_hash": None, "plan": "free"})
    assert _chamar(DeleteAccountBody(confirmacao="EXCLUIR")) == {"ok": True}
    assert conn.commitou


def test_admin_nao_se_exclui_pelo_perfil(banco):
    conn, _ = banco({"password_hash": hash_password(SENHA), "plan": "admin"})
    with pytest.raises(HTTPException) as e:
        _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    assert e.value.status_code == 403
    assert not conn.commitou


# -- o que e' apagado, e o que nao pode ser ---------------------------------

def test_apaga_todas_as_tabelas_pessoais(banco):
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    apagadas = {s.split("DELETE FROM ")[1].split(" ")[0]
                for s, _ in cur.sql if s.startswith("DELETE FROM")}
    assert apagadas == set(_TABELAS_PESSOAIS)


@pytest.mark.parametrize("fiscal", ["payments", "payment_events"])
def test_trilha_fiscal_nunca_entra_na_lista(fiscal):
    """`payments` tem ON DELETE CASCADE pra users.

    Se um dia alguem trocar a anonimizacao por `DELETE FROM users`, a trilha
    fiscal vai junto sem aviso. Este teste e a lista sao a defesa.
    """
    assert fiscal not in _TABELAS_PESSOAIS


def test_nao_apaga_a_linha_de_users(banco):
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    assert not any(s.startswith("DELETE FROM users") for s, _ in cur.sql)


def test_todo_delete_e_escopado_no_usuario(banco):
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    for sql, params in cur.sql:
        if sql.startswith("DELETE FROM"):
            assert "WHERE user_id = %s" in sql
            assert params == (42,)


# -- a anonimizacao ---------------------------------------------------------

def _update_de_users(cur):
    return next(s for s, _ in cur.sql if s.startswith("UPDATE users SET"))


@pytest.mark.parametrize("campo", [
    "name", "email", "username", "phone", "cpf", "google_sub",
    "avatar_url", "ga_client_id", "password_hash", "pending_password_hash",
    "reset_token", "email_verification_token", "referral_code",
])
def test_cada_campo_identificavel_e_limpo(banco, campo):
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    assert f"{campo} =" in _update_de_users(cur)


def test_conta_sai_inativa_e_datada(banco):
    """`active = FALSE` e' o que derruba a sessao: e o campo que
    get_current_user checa a cada requisicao. `deleted_at` distingue conta
    excluida pelo dono de conta desativada pelo admin."""
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    update = _update_de_users(cur)
    assert "active = FALSE" in update
    assert "deleted_at = NOW()" in update


def test_email_vira_dominio_reservado(banco):
    """.invalid e' reservado por RFC 2606: nao colide com conta real, mantem o
    UNIQUE da coluna e libera o e-mail original pra um cadastro novo depois."""
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    params = next(p for s, p in cur.sql if s.startswith("UPDATE users SET"))
    assert params[0] == "excluido+42@pickia.invalid"
    assert params[-1] == 42


def test_session_token_e_girado(banco):
    """Sem girar, um access token ja emitido continuaria batendo na sessao."""
    _, cur = banco()
    _chamar(DeleteAccountBody(current_password=SENHA, confirmacao="EXCLUIR"))
    params = next(p for s, p in cur.sql if s.startswith("UPDATE users SET"))
    assert len(params[1]) == 64          # sha256 hex
