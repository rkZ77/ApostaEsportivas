"""O servidor precisa responder 404 de verdade para URL que nao existe.

Todo caminho que nao e' arquivo real cai no catch-all do SPA e recebe o
index.html. Ate 2026-08-20 ele saia sempre com status 200, inclusive para
/wp-login.php e /.env: a pagina dizia "pagina nao encontrada" para a pessoa e
o servidor dizia "200 OK" para o Google -- o soft 404 classico.

A regra nova so' afirma 404 onde da' pra ter certeza: sufixo de extensao curta
nunca e' rota do React. Estes testes existem porque a regra e' facil de
quebrar sem querer -- basta alguem criar uma rota com ponto no caminho, ou
mexer no catch-all.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient


def _cliente():
    import main

    if not (pathlib.Path(main.__file__).parent / "dist" / "index.html").is_file():
        pytest.skip("build do frontend ausente: catch-all do SPA nao esta registrado")
    return TestClient(main.app)


@pytest.mark.parametrize("caminho", [
    "/wp-login.php",
    "/.env",
    "/backup.sql",
    "/site.zip",
    "/config.ini",
])
def test_caminho_de_arquivo_inexistente_responde_404(caminho):
    r = _cliente().get(caminho)
    assert r.status_code == 404, f"{caminho} deveria ser 404, veio {r.status_code}"
    # O corpo continua sendo a pagina do site, e nao um texto cru do servidor:
    # quem chegou por um link velho merece o caminho de volta.
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("caminho", [
    "/",
    "/picks",
    "/blog/kelly-criterion-apostas-esportivas",
    "/p/vip/12",
    # Typo continua 200 de proposito: separar rota valida de erro de digitacao
    # exigiria repetir a tabela de rotas do App.tsx aqui dentro. O `noindex` da
    # pagina segura a indexacao nesse caso.
    "/pickss",
    # Slug com ponto no meio nao pode ser confundido com arquivo.
    "/blog/versao-2.0-do-motor",
])
def test_rota_do_spa_continua_200(caminho):
    r = _cliente().get(caminho)
    assert r.status_code == 200, f"{caminho} deveria ser 200, veio {r.status_code}"


def test_arquivo_que_existe_no_build_continua_200():
    r = _cliente().get("/index.html")
    assert r.status_code == 200
