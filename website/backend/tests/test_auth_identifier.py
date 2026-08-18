from routers.auth import _resolve_identifier


def test_detects_email():
    assert _resolve_identifier("User@Example.com") == ("email", "user@example.com")


def test_cpf_deixou_de_ser_identificador():
    """O login por CPF saiu em 18/08/2026 junto com o campo do cadastro.

    Onze digitos agora caem em 'username' e simplesmente nao acham conta --
    o importante e' que NUNCA mais consultem a coluna cpf.
    """
    assert _resolve_identifier("123.456.789-09")[0] != "cpf"
    assert _resolve_identifier("12345678909") == ("username", "12345678909")


def test_falls_back_to_username():
    assert _resolve_identifier("MeuUsuario") == ("username", "meuusuario")


def test_strips_surrounding_whitespace():
    assert _resolve_identifier("  user@example.com  ") == ("email", "user@example.com")
