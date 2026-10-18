"""Modelo condicional de defesas de goleiro (18/10/2026) · ver goalkeeper_model."""
import pytest

from services.pick_engine import goalkeeper_model as gm


def test_volume_e_a_media_do_ataque_deles_com_a_defesa_do_time():
    so_ataque = gm.expected_saves_condicional(4.0, None, None, None)
    dois_lados = gm.expected_saves_condicional(4.0, 6.0, None, None)
    assert so_ataque == pytest.approx(gm.ESCALA_DA_MEDIA * 4.0 * gm.SAVE_RATE_PER_SHOT_ON, abs=1e-3)
    assert dois_lados == pytest.approx(gm.ESCALA_DA_MEDIA * 5.0 * gm.SAVE_RATE_PER_SHOT_ON, abs=1e-3)


def test_sem_o_segundo_encolhimento_pela_amostra_do_adversario():
    # O modelo de 01/08 puxa de novo pra media da liga; o condicional nao.
    antigo = gm.expected_saves(8.0, None, sample_size=10)
    novo = gm.expected_saves_condicional(8.0, None, None, None)
    assert novo > antigo
    assert novo == pytest.approx(gm.ESCALA_DA_MEDIA * 8.0 * gm.SAVE_RATE_PER_SHOT_ON, abs=1e-3)


def test_goleiro_continua_encolhido_pela_amostra_dele():
    um_jogo = gm.expected_saves_condicional(4.0, 4.0, 6.0, keeper_sample=1)
    vinte = gm.expected_saves_condicional(4.0, 4.0, 6.0, keeper_sample=20)
    assert um_jogo < vinte


def test_mercado_condicional_usa_a_dispersao_condicional_e_o_antigo_nao_muda():
    novo = gm.analyze_saves_market(4.5, 3.5, 10, odd=1.8, line=2.5,
                                   own_shots_on_conceded_avg=5.0, condicional=True)
    antigo = gm.analyze_saves_market(4.5, 3.5, 10, odd=1.8, line=2.5)
    assert novo["dispersion_r"] == gm.DISPERSAO_CONDICIONAL_R
    assert antigo["dispersion_r"] == gm.DISPERSION_R
    # O caso que motivou: o antigo dava chance baixa demais.
    assert novo["probability"] > antigo["probability"]
    # Amostra curta do adversario continua barrando nos dois.
    assert gm.analyze_saves_market(4.5, 3.5, gm.MIN_OPPONENT_SAMPLE - 1, odd=1.8,
                                   condicional=True) is None
