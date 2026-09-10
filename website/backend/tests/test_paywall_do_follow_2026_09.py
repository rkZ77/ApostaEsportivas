"""Paywall da ESCRITA · POST /api/banca/follow.

O BURACO QUE ISTO TRAVA (auditoria de 10/09/2026)

O follow validava duas coisas: se o `pick_type` existia em STAKE_LIMITS e se a
stake cabia na faixa. Nunca perguntou QUEM estava seguindo.

O teaser do paywall entrega o `id` do pick trancado -- e precisa entregar, e' o
que faz o card existir. Com o id na mao, o caminho completo era:

    POST /api/banca/follow  {pick_id, pick_type: "vip"|"live"|..., stake_units}
    GET  /api/live/my-picks -> market, market_type, line, odd do pick seguido

Ou seja: o gate de LEITURA existia em todo endpoint de analise, e o de ESCRITA
em nenhum. Seguir e' ler.

REGRA: `free` e' aberto; o Boost depende de o pick ser o liberado do dia; todo
o resto exige plano ativo.
"""

import os
import sys

import pytest
from fastapi import HTTPException

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import routers.banca as banca  # noqa: E402

_FREE = {"id": 7, "plan": "free"}
_VIP = {"id": 8, "plan": "vip", "plan_expires_at": None}
_TRIAL = {"id": 9, "plan": "trial", "plan_expires_at": None}
_VENCIDO = {"id": 10, "plan": "vip", "plan_expires_at": "2020-01-01T00:00:00+00:00"}


class _Cur:
    """Cursor de mentira: o unico SELECT que o gate faz e' o do Boost do dia."""

    def __init__(self, id_liberado=None):
        self._id = id_liberado

    def execute(self, *a, **kw):
        pass

    def fetchone(self):
        return {"id": self._id} if self._id is not None else None


@pytest.mark.parametrize("pick_type", sorted(banca._FOLLOW_SO_VIP))
def test_free_nao_segue_produto_pago(pick_type):
    assert banca._pode_seguir(_Cur(), _FREE, pick_type, 1) is False


#: O Bingo sai desta varredura enquanto ele for de admin (feature_flags.py):
#: e' o unico produto pago que o ASSINANTE tambem nao segue, porque ele nao
#: aparece pra esse assinante em lugar nenhum. A regra dele ganha caso proprio
#: logo abaixo, em vez de simplesmente sumir da lista.
_SO_VIP_VISIVEIS = sorted(banca._FOLLOW_SO_VIP - {"bingo"})


@pytest.mark.parametrize("pick_type", _SO_VIP_VISIVEIS)
@pytest.mark.parametrize("user", [_VIP, _TRIAL])
def test_assinante_segue(pick_type, user):
    assert banca._pode_seguir(_Cur(), user, pick_type, 1) is True


def test_o_bingo_em_teste_nem_o_assinante_segue():
    """Seguir e' ler: a Banca devolve mercado, linha e odd de todo pick
    seguido. Enquanto o Bingo roda em producao so' pra admin, o assinante com
    o id na mao leria as quatro pernas do produto inteiro."""
    from feature_flags import BINGO_BETA_ADMIN_ONLY
    if not BINGO_BETA_ADMIN_ONLY:
        pytest.skip("produto liberado pra todo mundo")
    assert banca._pode_seguir(_Cur(), _VIP, "bingo", 1) is False
    assert banca._pode_seguir(_Cur(), {"id": 1, "plan": "admin"}, "bingo", 1) is True


@pytest.mark.parametrize("pick_type", sorted(banca._FOLLOW_SO_VIP))
def test_plano_vencido_nao_segue(pick_type):
    """`is_vip_active` derruba plano expirado · o gate herda isso de graca, e e'
    por isso que ele nao le `plan` na mao."""
    assert banca._pode_seguir(_Cur(), _VENCIDO, pick_type, 1) is False


def test_o_ao_vivo_esta_na_lista():
    """Ele virou VIP puro em 10/09 · sem esta linha, o produto inteiro seguia
    seguivel pelo id do teaser."""
    assert "live" in banca._FOLLOW_SO_VIP


def test_free_e_aberto():
    assert banca._pode_seguir(_Cur(), _FREE, "free", 1) is True


def test_boost_liberado_do_dia_o_free_segue():
    assert banca._pode_seguir(_Cur(42), _FREE, "boost", 42) is True


def test_boost_do_resto_do_dia_o_free_nao_segue():
    assert banca._pode_seguir(_Cur(42), _FREE, "boost", 43) is False


def test_boost_sem_pick_no_dia_nao_libera_nada():
    """Consulta vazia nao pode virar 'pode seguir' · seria um `None == None`
    liberando o produto inteiro num dia sem publicacao."""
    assert banca._pode_seguir(_Cur(None), _FREE, "boost", 43) is False


def test_o_gate_roda_antes_de_qualquer_coisa_no_follow():
    """A checagem tem que vir antes do INSERT · depois dele o vazamento ja'
    aconteceu, e sobraria uma linha em user_followed_picks pra limpar."""
    import inspect

    src = inspect.getsource(banca.follow_pick)
    assert src.index("_pode_seguir") < src.index("INSERT INTO user_followed_picks")
