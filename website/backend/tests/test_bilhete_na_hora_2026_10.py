"""Bilhete pessoal fecha na hora, pelo cache (11/10/2026).

Antes ele esperava `match_statistics`, que a coleta grava minutos depois do
apito. Agora a perna de time ja' decidida fecha pela mesma regra dos picks,
lida so' do cache. Nenhum teste toca rede: qualquer chamada a API quebra.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import bilhete_pessoal  # noqa: E402
from routers import live  # noqa: E402

FID = 555


def _fixture(status, gols=(2, 1), ht=(0, 0)):
    return {
        "fixture": {"id": FID, "status": {"short": status, "elapsed": 60}, "timestamp": 1_700_000_000},
        "goals": {"home": gols[0], "away": gols[1]},
        "score": {"halftime": {"home": ht[0], "away": ht[1]}},
        "teams": {"home": {"id": 10}, "away": {"id": 20}},
        "league": {"id": 71},
    }


def _folha(esc_casa, esc_fora):
    return [
        {"team": {"id": 10}, "statistics": [{"type": "Corner Kicks", "value": esc_casa}]},
        {"team": {"id": 20}, "statistics": [{"type": "Corner Kicks", "value": esc_fora}]},
    ]


@pytest.fixture
def cache(monkeypatch):
    def _proibido(*a, **k):
        raise AssertionError("liquidar do cache nao pode chamar a API")
    monkeypatch.setattr(live.requests, "get", _proibido)
    monkeypatch.setattr(live, "_fix_cache", {})
    monkeypatch.setattr(live, "_stats_cache", {})

    def _por(status, folha=None, folha_status=None, idade_folha=0, **kw):
        live._fix_cache[FID] = (time.time(), _fixture(status, **kw))
        if folha is not None:
            live._stats_cache[FID] = (time.time() - idade_folha, folha, folha_status or status)
    return _por


def _perna(**kw):
    p = {"tipo": "time", "fixture_id": FID, "mercado": "gols", "direcao": "mais",
         "linha": 2.5, "periodo": "total", "odd": 1.8}
    p.update(kw)
    return p


def test_gols_fecham_no_apito_sem_esperar_a_coleta(cache):
    cache("FT", gols=(2, 1))
    assert bilhete_pessoal.veredito_ao_vivo(_perna()) == "GREEN"
    assert bilhete_pessoal.veredito_ao_vivo(_perna(direcao="menos")) == "RED"


def test_over_ja_batido_fecha_com_a_bola_rolando(cache):
    cache("2H", gols=(2, 1))
    assert bilhete_pessoal.veredito_ao_vivo(_perna()) == "GREEN"
    assert bilhete_pessoal.veredito_ao_vivo(_perna(linha=3.5)) is None


def test_1o_tempo_fecha_no_intervalo(cache):
    cache("HT", gols=(0, 0), ht=(0, 0))
    assert bilhete_pessoal.veredito_ao_vivo(_perna(direcao="menos", linha=1.5, periodo="1t")) == "GREEN"


def test_linha_cheia_empatada_e_void(cache):
    cache("FT", gols=(2, 1))
    assert bilhete_pessoal.veredito_ao_vivo(_perna(linha=3)) == "VOID"


def test_escanteio_com_folha_fresca_do_mesmo_status(cache):
    cache("FT", folha=_folha(6, 4))
    assert bilhete_pessoal.veredito_ao_vivo(_perna(mercado="escanteios", linha=9.5)) == "GREEN"


def test_folha_do_jogo_em_andamento_nao_liquida_o_fim(cache):
    """A folha foi tirada no 2o tempo e o jogo ja' acabou: os escanteios dos
    acrescimos podem faltar. Espera a folha do apito."""
    cache("FT", folha=_folha(6, 4), folha_status="2H")
    assert bilhete_pessoal.veredito_ao_vivo(_perna(mercado="escanteios", linha=9.5)) is None


def test_folha_velha_nao_liquida(cache):
    cache("FT", folha=_folha(6, 4), idade_folha=600)
    assert bilhete_pessoal.veredito_ao_vivo(_perna(mercado="escanteios", linha=9.5)) is None


def test_contador_em_branco_nao_vira_zero(cache):
    cache("FT", folha=[{"team": {"id": 10}, "statistics": []}, {"team": {"id": 20}, "statistics": []}])
    assert bilhete_pessoal.veredito_ao_vivo(_perna(mercado="escanteios", direcao="menos", linha=9.5)) is None


def test_sem_cache_espera_o_caminho_antigo(cache):
    assert bilhete_pessoal.veredito_ao_vivo(_perna()) is None


def test_cartao_e_jogador_ficam_de_fora(cache):
    cache("FT", gols=(2, 1))
    assert bilhete_pessoal.veredito_ao_vivo(_perna(mercado="cartoes")) is None
    assert bilhete_pessoal.veredito_ao_vivo({"tipo": "jogador", "fixture_id": FID}) is None
