"""Paywall dos endpoints de analise de pick · /market-form e /amostra.

O BURACO QUE ISTO TRAVA (achado em auditoria, 2026-08-30)

O /today entrega de proposito o `id` do pick VIP pro usuario free, dentro de
`result["bloqueados"]` -- o teaser mostra times, liga, horario e odd, mas NUNCA
market/line/reasoning, "que e' a analise que se paga". So' que dois endpoints
mais novos liam esse mesmo pick sem checar plano:

  · /{id}/market-form  devolvia `legs[].market` e `legs[].line` -- ou seja, o
    proprio palpite pago, exatamente o que o teaser esconde;
  · /{id}/amostra      devolvia a analise interna que decidiu o pick.

Bastava pegar o id no teaser e trocar de endpoint. O /detail sempre teve o gate
(`if not is_vip: 403`); estes dois nasceram depois (10/08 e 27/08) sem ele.

REGRA: so' `pick_type == "free"` e' publico. Todo o resto exige plano ativo, e o
gate roda ANTES de qualquer ida ao banco -- por isso o teste consegue provar o
corte sem tocar em Postgres.
"""

import os
import sys

import pytest
from fastapi import HTTPException

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.suggestions as sug  # noqa: E402

_FREE = {"id": 7, "plan": "free"}
_VIP = {"id": 8, "plan": "vip", "plan_expires_at": None}


class _BancoProibido(Exception):
    """Marcador: se isto sobe, o codigo passou do gate e tentou o banco."""


@pytest.fixture(autouse=True)
def _sem_banco(monkeypatch):
    def _estoura():
        raise _BancoProibido("o gate deixou passar e tentou abrir conexao")
    monkeypatch.setattr(sug, "get_connection", _estoura)


# Tipos pagos que CADA endpoint realmente serve. amostra so' cataloga picks de
# mercado unico (multipla/alavancagem devolvem available:False antes do gate,
# entao nao ha' o que vazar la'); market-form monta serie por perna e cobre os
# compostos tambem.
_PAGOS_MARKET_FORM = ["vip", "multipla", "alavancagem", "faltas",
                      "goleiros", "player_stats", "boost"]
_PAGOS_AMOSTRA = ["vip", "faltas", "goleiros", "player_stats", "boost"]


@pytest.mark.parametrize("pick_type", _PAGOS_MARKET_FORM)
def test_market_form_free_leva_403(pick_type):
    """Free pedindo serie de tipo pago leva 403 · e nem chega no banco."""
    with pytest.raises(HTTPException) as ei:
        sug.get_market_form(1, pick_type=pick_type, current_user=_FREE)
    assert ei.value.status_code == 403


@pytest.mark.parametrize("pick_type", _PAGOS_AMOSTRA)
def test_amostra_free_leva_403(pick_type):
    """Free pedindo amostra de tipo pago leva 403 · e nem chega no banco."""
    with pytest.raises(HTTPException) as ei:
        sug.get_amostra(1, pick_type=pick_type, current_user=_FREE)
    assert ei.value.status_code == 403


@pytest.mark.parametrize("endpoint", [sug.get_market_form, sug.get_amostra])
def test_vip_passa_do_gate(endpoint):
    """VIP nao e' barrado pelo paywall · para no banco (proibido no teste)."""
    with pytest.raises(_BancoProibido):
        endpoint(1, pick_type="vip", current_user=_VIP)


@pytest.mark.parametrize("endpoint", [sug.get_market_form, sug.get_amostra])
def test_free_type_e_publico(endpoint):
    """`free` nao exige plano · o gate deixa seguir ate' o banco."""
    with pytest.raises(_BancoProibido):
        endpoint(1, pick_type="free", current_user=_FREE)
