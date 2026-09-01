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
   `password_hash NULL`. `verify_password(senha, None)` estoura -- login e
   troca de senha têm que responder com instrução, não com 500.
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


def test_login_consulta_as_duas_colunas_no_caminho_do_telefone():
    """Username só de dígitos é permitido pelo `_USERNAME_RE`, e a detecção de
    telefone rouba esse formato. O `OR` é o que impede que essa pessoa fique
    trancada do lado de fora."""
    from tests.test_home_2026_08 import _fonte

    fonte = _fonte("routers/auth.py")
    assert "WHERE phone = %s OR username = %s" in fonte


# ── conta sem senha (nascida no Google) ──────────────────────────────────────

def test_conta_sem_senha_nao_chega_no_verify_password():
    """`verify_password(senha, None)` estoura dentro do passlib · seriam 500 no
    login e na troca de senha, nos dois pontos em que a pessoa que entrou pelo
    Google é mais provável de aparecer."""
    from tests.test_home_2026_08 import _fonte

    fonte = _fonte("routers/auth.py")
    assert 'if not user["password_hash"]:' in fonte
    assert 'if not row["password_hash"]:' in fonte


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


def test_google_nao_usa_o_gate_de_email_do_login():
    """O gate de e-mail existe pra quem nunca confirmou o endereço. Aplicá-lo a
    quem entrou pelo Google barraria justamente quem tem o e-mail mais provado
    da base."""
    from tests.test_home_2026_08 import _fonte

    fonte = _fonte("routers/auth.py")
    google = fonte.split('@router.post("/google")')[1].split('@router.post("/verify-email")')[0]
    assert "_deve_barrar_por_email" not in google
    # E a sessão única continua valendo: entrar pelo Google derruba a sessão
    # anterior igual ao login por senha.
    assert "session_token=%s, last_login_device=%s" in google


# ── fluxo de codigo de autorizacao (o botao proprio da tela) ─────────────────
#
# O site deixou de usar o widget do Google em 01/09/2026: ele vive num iframe
# que nao aceita CSS de fora, e o botao destoava do resto da tela. Com o fluxo
# de codigo, o navegador manda um `code` e QUEM FALA COM O GOOGLE E' O SERVIDOR
# -- o client_secret nunca chega ao front.

def test_config_nao_anuncia_client_id_sem_secret(monkeypatch):
    """Meio configurado é pior que desligado: o botão apareceria, a pessoa
    escolheria a conta no popup e só então levaria erro."""
    from routers.auth import google_config

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert google_config() == {"client_id": ""}

    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "segredo")
    assert google_config() == {"client_id": "abc.apps.googleusercontent.com"}


class _RespostaFalsa:
    def __init__(self, status, dados=None, texto=""):
        self.status_code = status
        self._dados = dados or {}
        self.text = texto

    def json(self):
        return self._dados


def _finge_post(monkeypatch, resposta):
    enviados = {}

    def _post(url, data=None, timeout=None):
        enviados["url"] = url
        enviados["data"] = data
        return resposta

    monkeypatch.setattr(auth_mod.httpx, "post", _post)
    return enviados


def test_troca_de_code_manda_o_secret_e_o_postmessage(monkeypatch):
    """`redirect_uri=postmessage` é o que o Google exige quando o code veio do
    popup. Errar isso dá `invalid_grant` e nenhum login funciona."""
    from routers.auth import _trocar_code_por_id_token

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "segredo-do-servidor")
    enviados = _finge_post(monkeypatch, _RespostaFalsa(200, {"id_token": "eyJ.token.aqui"}))

    assert _trocar_code_por_id_token("codigo-do-popup") == "eyJ.token.aqui"
    assert enviados["url"] == "https://oauth2.googleapis.com/token"
    assert enviados["data"]["redirect_uri"] == "postmessage"
    assert enviados["data"]["grant_type"] == "authorization_code"
    assert enviados["data"]["client_secret"] == "segredo-do-servidor"


def test_code_recusado_pelo_google_vira_401(monkeypatch):
    from routers.auth import _trocar_code_por_id_token

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s")
    _finge_post(monkeypatch, _RespostaFalsa(400, texto='{"error":"invalid_grant"}'))
    with pytest.raises(HTTPException) as e:
        _trocar_code_por_id_token("code-velho")
    assert e.value.status_code == 401
    assert "invalid_grant" not in str(e.value.detail)


def test_resposta_sem_id_token_nao_passa_por_login(monkeypatch):
    from routers.auth import _trocar_code_por_id_token

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s")
    _finge_post(monkeypatch, _RespostaFalsa(200, {"access_token": "so-isso"}))
    with pytest.raises(HTTPException) as e:
        _trocar_code_por_id_token("code")
    assert e.value.status_code == 502


def test_sem_secret_a_troca_nem_tenta(monkeypatch):
    from routers.auth import _trocar_code_por_id_token

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with pytest.raises(HTTPException) as e:
        _trocar_code_por_id_token("code")
    assert e.value.status_code == 503


def test_o_secret_nunca_sai_do_servidor():
    """O client_secret só pode aparecer no ponto que fala com o Google. Se ele
    vazar pro corpo de uma resposta ou pro front, o login inteiro é forjável."""
    from tests.test_home_2026_08 import _fonte, _front

    fonte = _fonte("routers/auth.py")
    assert fonte.count("GOOGLE_CLIENT_SECRET") == 1
    assert "client_secret" not in _front("components/GoogleSignInButton.tsx")
