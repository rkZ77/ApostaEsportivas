from routers.auth import _resolve_identifier


def test_detects_email():
    assert _resolve_identifier("User@Example.com") == ("email", "user@example.com")


def test_detects_cpf_ignoring_punctuation():
    assert _resolve_identifier("123.456.789-09") == ("cpf", "12345678909")


def test_falls_back_to_username():
    assert _resolve_identifier("MeuUsuario") == ("username", "meuusuario")


def test_strips_surrounding_whitespace():
    assert _resolve_identifier("  user@example.com  ") == ("email", "user@example.com")
