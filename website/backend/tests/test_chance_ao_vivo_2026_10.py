"""Chance ao vivo do pick (09/10/2026): parte da probabilidade de antes do
jogo, anda com o relogio e com o contador."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chance_ao_vivo as cav  # noqa: E402


@pytest.mark.parametrize("prob, direcao, linha", [
    (0.69, "over", 0.5), (0.62, "over", 9.5), (0.55, "under", 2.5), (0.8, "under", 10.0),
])
def test_no_apito_inicial_a_chance_e_a_de_antes(prob, direcao, linha):
    assert cav.chance_agora(prob, direcao, linha, 0, "1H", 0) == pytest.approx(prob, abs=0.01)


def test_linha_batida_e_estourada():
    assert cav.chance_agora(0.6, "over", 5.5, 6, "2H", 70) == 1.0
    assert cav.chance_agora(0.6, "under", 5.5, 6, "2H", 70) == 0.0
    assert cav.chance_agora(0.6, "under", 9.0, 9, "2H", 70) == 0.0   # empate na linha cheia nao e' vitoria


def test_over_cai_com_o_relogio_sem_o_contador_andar():
    cedo = cav.chance_agora(0.62, "over", 5.5, 4, "1H", 30)
    tarde = cav.chance_agora(0.62, "over", 5.5, 4, "2H", 80)
    assert cedo > tarde > 0


def test_under_sobe_com_o_relogio():
    cedo = cav.chance_agora(0.55, "under", 2.5, 1, "1H", 20)
    tarde = cav.chance_agora(0.55, "under", 2.5, 1, "2H", 85)
    assert tarde > cedo


def test_acabou_o_tempo_apostado():
    # Over 0.5 do 1o tempo sem gol no intervalo: perdeu.
    assert cav.chance_agora(0.69, "over", 0.5, 0, "HT", 45, "1t") == 0.0
    # 2o tempo ainda nao comecou: chance cheia de antes.
    assert cav.chance_agora(0.6, "over", 0.5, 0, "1H", 30, "2t") == pytest.approx(0.6, abs=0.01)


def test_sem_dado_nao_inventa():
    assert cav.chance_agora(None, "over", 2.5, 1, "1H", 10) is None
    assert cav.chance_agora(0.6, "result", None, None, "1H", 10) is None
    assert cav.chance_agora(0.6, "over", 2.5, None, "1H", 10) is None
    assert cav.chance_agora(0.6, "over", 2.5, 1, "NS", None) is None
