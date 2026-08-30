"""Entrar com Google e entrar pelo telefone (30/08/2026).

Duas entradas novas na mesma tela de login, e as duas mexem em invariantes que
já existiam:

1. **Google.** O front manda um ID token e o backend valida. O teste que
   importa aqui não é o do caminho feliz -- é o dos caminhos que NÃO podem
   passar: token de outro `aud` (qualquer app do mundo consegue um ID token do
   Google assinado por chave legítima), emissor inesperado, e e-mail que o
   próprio Google não verificou. Se qualquer um desses passar, o botão vira uma
   porta de entrada para a conta alheia.

2. **Telefone.** O identificador ganhou um terceiro tipo. O risco é o simétrico
   do CPF que saiu em 18/08: um username só de dígitos não pode ser sequestrado
   pela detecção de telefone.

3. **Conta sem senha.** Existe desde que o Google cria conta com
   `password_hash NULL`. `verify_password(senha, None)` estoura -- o login tem
   que responder com instrução, não com 500.
"""

import pytest

from fastapi import HTTPException

from routers import auth as auth_mod
from routers.auth import _resolve_identifier, _verificar_id_token_google


# ── telefone como identificador ──────────────────────────────────────────────

def test_celular_com_ddd_vira_identificador_de_telefone():
    assert _resolve_identifier("11987654321") == ("phone", "+5511987654321")


def test_telefone_mascarado_tambem_e_reconhecido():
    assert _resolve_identifier("(11) 98765-4321") == ("phone", "+5511987654321")


def test_telefone_com_prefixo_do_pais():
    assert _resolve_identifier("+55 11 98765-4321") == ("phone", "+5511987654321")


@pytest.mark.parametrize("entrada", [
    "12345678909",   # CPF: DDD 12 existe, mas o terceiro dígito não é 9
    "00987654321",   # DDD 00 não existe
    "123",           # curto demais
])
def test_numero_que_nao_e_celular_valido_continua_username(entrada):
    """A detecção é conservadora: o que não passa em `_validate_phone_br` cai
    de volta em username, e nunca vaza o erro de telefone pra tela de login."""
    tipo, valor = _resolve_identifier(entrada)
    assert tipo == "username"
    assert valor == entrada.lower()


def test_username_com_letra_nunca_e_lido_como_telefone():
    assert _resolve_identifier("user11987654321")[0] == "username"


def test_email_continua_ganhando_de_tudo():
    assert _resolve_identifier(" User@Example.com ") == ("email", "user@example.com")


# ── validação do ID token do Google ──────────────────────────────────────────

_CLAIMS_OK = {
    "sub": "1029384756",
    "iss": "https://accounts.google.com",
    "email": "Pessoa@Gmail.com",
    "email_verified": True,
    "name": "Pessoa Teste",
}


@pytest.fixture
def google_ligado(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-de-teste.apps.googleusercontent.com")
    monkeypatch.setattr(auth_mod, "_google_jwks", lambda forcar=False: {"keys": []})


def _finge_decode(monkeypatch, claims=None, erro=None):
    """Dubla `jose.jwt.decode` -- o que se testa aqui são as regras DEPOIS da
    assinatura, não a criptografia do jose."""
    from jose import jwt as jose_jwt

    def _decode(token, chaves, algorithms=None, audience=None, options=None):
        if erro is not None:
            raise erro
        return dict(claims)

    monkeypatch.setattr(jose_jwt, "decode", _decode)


def test_token_valido_devolve_claims_com_email_normalizado(google_ligado, monkeypatch):
    _finge_decode(monkeypatch, _CLAIMS_OK)
    claims = _verificar_id_token_google("token.qualquer.coisa")
    assert claims["email"] == "pessoa@gmail.com"
    assert claims["sub"] == "1029384756"


def test_assinatura_invalida_vira_401(google_ligado, monkeypatch):
    from jose.exceptions import JWTError
    _finge_decode(monkeypatch, erro=JWTError("assinatura nao confere"))
    with pytest.raises(HTTPException) as e:
        _verificar_id_token_google("token.forjado")
    assert e.value.status_code == 401


def test_emissor_inesperado_e_recusado(google_ligado, monkeypatch):
    _finge_decode(monkeypatch, {**_CLAIMS_OK, "iss": "https://accounts.evil.com"})
    with pytest.raises(HTTPException) as e:
        _verificar_id_token_google("token")
    assert e.value.status_code == 401


def test_email_nao_verificado_no_google_e_recusado(google_ligado, monkeypatch):
    """`email_verified=False` é conta Google que ninguém provou. Ela não pode
    entrar, e muito menos ganhar o trial -- é justamente esse campo que paga os
    2 dias em `_ativar_trial_se_elegivel`."""
    _finge_decode(monkeypatch, {**_CLAIMS_OK, "email_verified": False})
    with pytest.raises(HTTPException) as e:
        _verificar_id_token_google("token")
    assert e.value.status_code == 403


def test_sem_email_nas_claims_e_recusado(google_ligado, monkeypatch):
    _finge_decode(monkeypatch, {k: v for k, v in _CLAIMS_OK.items() if k != "email"})
    with pytest.raises(HTTPException) as e:
        _verificar_id_token_google("token")
    assert e.value.status_code == 400


def test_ambiente_sem_client_id_responde_503(monkeypatch):
    """Sem `GOOGLE_CLIENT_ID` o recurso simplesmente não existe -- e não pode
    virar um caminho que aceita qualquer token porque a checagem de `aud` foi
    pulada por falta de valor."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(HTTPException) as e:
        _verificar_id_token_google("token")
    assert e.value.status_code == 503


def test_audience_e_sempre_o_nosso_client_id(google_ligado, monkeypatch):
    """O `aud` é a única coisa que separa "token do Google" de "token do Google
    PRA NÓS". Um ID token de outro app é assinado pela mesma chave."""
    vistos = {}
    from jose import jwt as jose_jwt

    def _decode(token, chaves, algorithms=None, audience=None, options=None):
        vistos["audience"] = audience
        vistos["algorithms"] = algorithms
        return dict(_CLAIMS_OK)

    monkeypatch.setattr(jose_jwt, "decode", _decode)
    _verificar_id_token_google("token")
    assert vistos["audience"] == "client-de-teste.apps.googleusercontent.com"
    assert vistos["algorithms"] == ["RS256"]
