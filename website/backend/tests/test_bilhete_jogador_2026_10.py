"""Perna de JOGADOR do bilhete pessoal fecha pela ficha da API (12/10/2026).

Antes ela so' fechava com `player_match_stats`, que o site nao preenche, e o
bilhete ficava Pendente com os jogos acabados. Sem rede: a ficha e' dublada.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import bilhete_pessoal  # noqa: E402
from routers import live  # noqa: E402

FID, JOGADOR = 777, 55
JOGO_FT = {"status": "FT"}


def _perna(minimo=2, estat="chutes_alvo"):
    return {"tipo": "jogador", "fixture_id": FID, "player_id": JOGADOR,
            "estat": estat, "minimo": minimo}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(live, "_varredura_habilitada", lambda: True)
    monkeypatch.setattr(bilhete_pessoal, "_ficha_vazia_em", {})
    chamadas = []

    def _instalar(ficha=True, valor=3, minutos=90):
        monkeypatch.setattr(live, "_fetch_player_sheet",
                            lambda fid: chamadas.append(fid) or ([{"players": []}] if ficha else []))
        monkeypatch.setattr(live, "_valor_do_jogador", lambda fid, pid, col: (valor, minutos))
        return chamadas
    return _instalar


def test_bateu_e_nao_bateu(api):
    api(valor=3)
    assert bilhete_pessoal.veredito_do_jogador(_perna(2), JOGO_FT) == ("GREEN", 3, None)
    assert bilhete_pessoal.veredito_do_jogador(_perna(4), JOGO_FT)[0] == "RED"


def test_em_campo_com_contador_em_branco_e_zero(api):
    api(valor=None, minutos=30)
    assert bilhete_pessoal.veredito_do_jogador(_perna(1, "gols"), JOGO_FT) == ("RED", 0, None)


def test_nao_entrou_anula(api):
    api(valor=None, minutos=None)
    res, _, motivo = bilhete_pessoal.veredito_do_jogador(_perna(), JOGO_FT)
    assert res == "VOID" and "nao entrou" in motivo


def test_jogo_em_andamento_espera(api):
    chamadas = api()
    assert bilhete_pessoal.veredito_do_jogador(_perna(), {"status": "2H"}) == (None, None, None)
    assert chamadas == []                    # nem pede a ficha


def test_ficha_vazia_nao_e_pedida_de_novo_na_mesma_meia_hora(api):
    chamadas = api(ficha=False)
    assert bilhete_pessoal.veredito_do_jogador(_perna(), JOGO_FT, agora=10_000)[0] is None
    assert bilhete_pessoal.veredito_do_jogador(_perna(), JOGO_FT, agora=10_600)[0] is None
    assert chamadas == [FID]
    bilhete_pessoal.veredito_do_jogador(_perna(), JOGO_FT, agora=10_000 + 1800)
    assert chamadas == [FID, FID]


def test_fora_da_producao_nao_gasta_cota(api, monkeypatch):
    chamadas = api()
    monkeypatch.setattr(live, "_varredura_habilitada", lambda: False)
    assert bilhete_pessoal.veredito_do_jogador(_perna(), JOGO_FT)[0] is None
    assert chamadas == []
