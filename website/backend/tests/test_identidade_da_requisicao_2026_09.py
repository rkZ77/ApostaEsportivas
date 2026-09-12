"""Um id liga o erro que a pessoa viu a' linha de log que explica.

O QUE FALTAVA
-------------
Quando alguem dizia "deu erro as 21h", a unica saida era vasculhar log por
horario: nao existia nada em comum entre a tela e o servidor. E a excecao sem
dono virava o 500 CRU do FastAPI -- corpo `Internal Server Error`, em ingles,
sem JSON. O interceptor de `services/api.ts` so' conseguia mostrar o aviso
generico de 5xx, sem nada pra anotar.

O QUE ESTES CASOS PROTEGEM
--------------------------
  1. toda resposta sai com `X-Request-Id`;
  2. o id da Railway e' reaproveitado quando existe, em vez de virar um
     terceiro identificador pra mesma requisicao;
  3. excecao sem dono responde JSON com `code`, `message` e `request_id`;
  4. o id do corpo e' o MESMO do cabecalho -- se divergirem, o numero que a
     pessoa le na tela nao acha nada no log;
  5. a mensagem nao vaza a excecao.
"""
import os

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "x" * 32)

import main  # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    """Cliente com uma rota que explode de proposito.

    A rota entra na POSICAO 0 porque o catch-all do SPA ja' esta' registrado e
    responderia `index.html` pra qualquer caminho -- inclusive este.
    """
    async def explode():
        raise RuntimeError("boom de teste")

    rota = APIRoute("/api/_teste_explode", explode, methods=["GET"])
    main.app.router.routes.insert(0, rota)
    try:
        yield TestClient(main.app, raise_server_exceptions=False)
    finally:
        main.app.router.routes.remove(rota)


def test_toda_resposta_leva_o_id(cliente):
    r = cliente.get("/api/payments/plans")
    assert r.headers.get("x-request-id")


def test_o_id_da_railway_e_reaproveitado(cliente):
    """Criar um segundo id pra mesma requisicao impediria justamente o cruzamento
    com o log do edge, que e' metade do motivo de isto existir."""
    r = cliente.get("/api/payments/plans",
                    headers={"x-railway-request-id": "abc123doEdge"})
    assert r.headers["x-request-id"] == "abc123doEdge"


def test_excecao_sem_dono_vira_json_com_id(cliente):
    r = cliente.get("/api/_teste_explode")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    corpo = r.json()["error"]
    assert corpo["code"] == "INTERNAL_ERROR"
    assert corpo["request_id"]


def test_o_id_do_corpo_e_o_do_cabecalho(cliente):
    """O numero que a pessoa copia da tela tem que ser o que esta' no log."""
    r = cliente.get("/api/_teste_explode")
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


def test_a_mensagem_nao_vaza_a_excecao(cliente):
    """Ela e' pra ser lida por quem usa o site, nao por quem depura."""
    r = cliente.get("/api/_teste_explode")
    msg = r.json()["error"]["message"]
    assert "boom de teste" not in msg
    assert "RuntimeError" not in msg
    assert "Traceback" not in r.text
