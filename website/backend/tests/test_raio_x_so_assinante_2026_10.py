"""Os dados do Raio-X sao do plano pago (12/10/2026): o Free ve a lista e as
abas trancadas, e o servidor nao entrega os numeros."""
import inspect

import pytest
from fastapi import HTTPException

from routers import fixtures


def test_free_recebe_403_e_assinante_passa():
    with pytest.raises(HTTPException) as e:
        fixtures._assinante({"plan": "free"})
    assert e.value.status_code == 403
    assert fixtures._assinante({"plan": "admin"})["plan"] == "admin"
    assert fixtures._assinante({"plan": "vip", "plan_expires_at": None})["plan"] == "vip"


@pytest.mark.parametrize("rota", ["get_raio_x", "get_escalacao", "get_classificacao", "get_odds_do_jogo"])
def test_rotas_de_dados_do_raio_x_exigem_assinatura(rota):
    padrao = inspect.signature(getattr(fixtures, rota)).parameters["current_user"].default
    assert padrao.dependency is fixtures._assinante
