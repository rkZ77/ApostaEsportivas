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
# `boost` SAIU DAS DUAS LISTAS em 10/09/2026, e nao por ter deixado de ser
# pago: ele tem um pick liberado por dia, entao "este free pode ver?" deixou de
# ser resposta de tipo e passou a ser resposta de PICK -- e saber qual e' o
# liberado custa uma consulta. O corte dele esta' logo abaixo, com banco falso.
_PAGOS_MARKET_FORM = ["vip", "multipla", "alavancagem", "faltas",
                      "goleiros", "player_stats"]
_PAGOS_AMOSTRA = ["vip", "faltas", "goleiros", "player_stats"]


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


# ── Pick Boost: o gate depende de QUAL pick, nao do tipo ──────────────────
class _CurFake:
    def __init__(self, id_liberado):
        self._id = id_liberado
    def execute(self, *a, **kw):
        pass
    def fetchone(self):
        return {"id": self._id}
    def close(self):
        pass


class _ConnFake:
    def __init__(self, id_liberado):
        self._id = id_liberado
    def cursor(self):
        return _CurFake(self._id)
    def close(self):
        pass


@pytest.fixture
def _banco_do_boost(monkeypatch):
    """Devolve um banco onde o pick liberado do dia e' o que o teste escolher."""
    def _usar(id_liberado):
        # A PRIMEIRA conexao e' a do gate (ele precisa saber qual pick e' o
        # liberado do dia). Da' segunda em diante e' o corpo do endpoint, e ai'
        # vale o mesmo marcador dos outros testes: passou do paywall.
        estado = {"n": 0}
        def _abrir():
            estado["n"] += 1
            if estado["n"] == 1:
                return _ConnFake(id_liberado)
            raise _BancoProibido("passou do gate")
        monkeypatch.setattr(sug, "get_connection", _abrir)
    return _usar


@pytest.mark.parametrize("endpoint", [sug.get_market_form, sug.get_amostra])
def test_boost_liberado_abre_pro_free(endpoint, _banco_do_boost):
    """O pick gratuito do dia ABRE a propria analise.

    Ate' 10/09 ele levava 403: o gate tratava `boost` como 100% VIP, e o
    produto de captacao entregava ao free um card que nao abria.
    """
    _banco_do_boost(42)
    with pytest.raises(_BancoProibido):
        endpoint(42, pick_type="boost", current_user=_FREE)


@pytest.mark.parametrize("endpoint", [sug.get_market_form, sug.get_amostra])
def test_boost_do_resto_do_dia_continua_trancado(endpoint, _banco_do_boost):
    """Um por dia e' um. O segundo card do Boost segue pago."""
    _banco_do_boost(42)
    with pytest.raises(HTTPException) as ei:
        endpoint(43, pick_type="boost", current_user=_FREE)
    assert ei.value.status_code == 403


@pytest.mark.parametrize("endpoint", [sug.get_market_form, sug.get_amostra])
def test_vip_no_boost_nem_consulta_o_liberado(endpoint):
    """Assinante ve' todos, entao a pergunta "qual e' o gratuito?" nem e' feita
    -- o gate sai antes de abrir conexao (a fixture `_sem_banco` estoura se
    alguem tentar)."""
    with pytest.raises(_BancoProibido):
        # O _BancoProibido aqui vem do CORPO do endpoint, nao do gate: e' o
        # mesmo sinal de "passou do paywall" usado em test_vip_passa_do_gate.
        endpoint(43, pick_type="boost", current_user=_VIP)
