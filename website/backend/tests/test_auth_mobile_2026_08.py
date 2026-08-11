"""O app nativo recebe token no corpo; o site NAO recebe nada a mais.

Esta e' a unica mudanca que o app mobile pediu no backend, e ela mexe em
login/cadastro/refresh -- que sao exatamente as rotas onde um descuido vira
vazamento de credencial. Os dois lados do contrato ficam presos aqui:

  1. sem o header, a resposta e' byte a byte a de sempre (o site nao muda);
  2. com o header, e' so' o app que recebe access/refresh para guardar no
     keystore do aparelho.

Sao helpers puros, sem banco -- roda na suite normal, que proibe conexao.
"""
import pytest

from routers.auth import _e_cliente_nativo, _tokens_no_corpo


class _RequisicaoFalsa:
    """So' precisa de `.headers.get`, que e' tudo que os helpers usam."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


# ── quem e' considerado app nativo ──────────────────────────────────────

@pytest.mark.parametrize("valor", ["android", "ios", "Android", "IOS", " android "])
def test_reconhece_o_app_nativo(valor):
    req = _RequisicaoFalsa({"x-client-platform": valor})
    assert _e_cliente_nativo(req) is True


@pytest.mark.parametrize("headers", [
    {},                                     # navegador comum
    {"x-client-platform": "web"},           # declarado, mas nao e' app
    {"x-client-platform": ""},              # header vazio
    {"user-agent": "Mozilla/5.0"},          # so' UA, sem o header
])
def test_nao_confunde_navegador_com_app(headers):
    assert _e_cliente_nativo(_RequisicaoFalsa(headers)) is False


# ── o que sai no corpo ──────────────────────────────────────────────────

def test_site_nao_recebe_token_no_corpo():
    """A garantia principal: nada muda para quem usa o navegador."""
    corpo = _tokens_no_corpo(_RequisicaoFalsa(), "access-123", "refresh-456")
    assert corpo == {}


def test_app_recebe_access_e_refresh():
    req = _RequisicaoFalsa({"x-client-platform": "android"})
    corpo = _tokens_no_corpo(req, "access-123", "refresh-456")
    assert corpo == {
        "access_token": "access-123",
        "token_type": "bearer",
        "refresh_token": "refresh-456",
    }


def test_refresh_sozinho_nao_reemite_refresh_token():
    """`/auth/refresh` renova so' o access -- o refresh continua o mesmo.

    Se este teste passar a devolver refresh_token, a sessao do app virou
    deslizante infinita e deixou de expirar em 30 dias como a do site.
    """
    req = _RequisicaoFalsa({"x-client-platform": "ios"})
    corpo = _tokens_no_corpo(req, "access-novo", None)
    assert corpo == {"access_token": "access-novo", "token_type": "bearer"}
    assert "refresh_token" not in corpo
