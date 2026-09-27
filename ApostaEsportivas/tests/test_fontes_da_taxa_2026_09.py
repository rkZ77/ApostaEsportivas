# -*- coding: utf-8 -*-
"""Fontes da taxa do pre-jogo (2026-09-27).

Medido em ~1.700 partidas de PROD pelo codigo do motor
(scripts/validar_motor_antes_depois.py), nos seis mercados:
  - o jogo do OUTRO mando entra com peso 0.5;
  - minimo de 5 jogos NO MANDO de cada lado;
  - metade da probabilidade vem do modelo por causa (gols pelos chutes no alvo).
Estes testes travam a mecanica; os numeros de outras camadas continuam nos
testes antigos, que rodam com a configuracao anterior.
"""
from dataclasses import replace

import pytest

from services.pick_engine import ranking, stats_model, variance_model
from services.pick_engine.config import DEFAULT_CONFIG

CASA, FORA = 1, 2


def jogo(mandante, visitante, esc_m, esc_v, dia="2026-09-01"):
    return {"match_date": dia, "status": "FT", "home_team_id": mandante, "away_team_id": visitante,
            "home_goals": 1, "away_goals": 1, "home_corners": esc_m, "away_corners": esc_v,
            "total_corners": esc_m + esc_v}


def test_configuracao_de_producao():
    assert DEFAULT_CONFIG.peso_outro_mando == 0.5
    assert DEFAULT_CONFIG.min_jogos_mando_por_lado == 5
    assert DEFAULT_CONFIG.peso_modelo_na_taxa == 0.5


def test_o_outro_mando_entra_com_peso_menor():
    """Mandante: 2 jogos em casa com 11-12 escanteios dele (Over 10.5) e 2 fora
    com 3-4 (Under). So' mando da' 100%; com o outro mando a 0.5, 2/3."""
    hist = [jogo(CASA, 9, 12, 4), jogo(CASA, 9, 11, 5), jogo(9, CASA, 3, 3), jogo(9, CASA, 2, 4)]
    so_mando = stats_model.market_taxa("corners", "home", "Over", "10.5", hist, [],
                                       config=replace(DEFAULT_CONFIG, peso_outro_mando=0.0),
                                       team_id=CASA, home_team_id=CASA)
    misto = stats_model.market_taxa("corners", "home", "Over", "10.5", hist, [],
                                    team_id=CASA, home_team_id=CASA)
    assert so_mando["taxa_bruta"] == 1.0
    assert misto["taxa_ponderada"] == pytest.approx(2 / 3, abs=1e-3)
    assert misto["amostra"] == 3                    # 2 + 2 x 0.5
    assert misto["amostra_mando_min_lado"] == 2


def test_amostra_efetiva_nao_deixa_o_outro_mando_encher_o_piso():
    hist = [jogo(CASA, 9, 5, 5) for _ in range(4)] + [jogo(9, CASA, 5, 5) for _ in range(8)]
    t = stats_model.market_taxa("corners", "home", "Over", "4.5", hist, [],
                                team_id=CASA, home_team_id=CASA)
    assert t["amostra"] == 8                        # 4 + 8 x 0.5
    assert t["amostra_mando_min_lado"] == 4


@pytest.mark.parametrize("no_mando, passa", [(4, False), (5, True), (None, True)])
def test_minimo_de_jogos_no_mando_por_lado(no_mando, passa):
    assert ranking._mando_suficiente({"amostra_mando_min_lado": no_mando}, DEFAULT_CONFIG) is passa


def test_total_olha_o_menor_dos_dois_lados():
    mandante = [jogo(CASA, 9, 5, 5) for _ in range(6)]
    visitante = [jogo(9, FORA, 5, 5) for _ in range(3)]
    t = stats_model.market_taxa("corners", "total", "Over", "8.5", mandante, visitante,
                                home_team_id=CASA, away_team_id=FORA)
    assert t["amostra_mando_min_lado"] == 3


def test_lambda_por_causa_converte_chute_no_alvo_em_gol():
    def j(m, v, sm, sv):
        return {**jogo(m, v, 5, 5), "home_shots_on": sm, "away_shots_on": sv}
    casa = [j(CASA, 9, 6, 3) for _ in range(4)]      # mandante chuta 6, cede 3
    fora = [j(9, FORA, 5, 4) for _ in range(4)]      # visitante chuta 4, cede 5
    lam = stats_model.lambda_por_causa(casa, fora, "goals", "total", CASA, FORA,
                                       {"conv_gols_por_chute_no_alvo": 0.3})
    # lado casa (6 + 5)/2 = 5.5 ; lado fora (4 + 3)/2 = 3.5 ; 0.3 x 9 = 2.7
    assert lam == pytest.approx(2.7)


def test_sem_conversao_da_liga_o_lambda_e_so_o_contador():
    assert stats_model.lambda_por_causa([], [], "goals", "total", CASA, FORA, {}) is None


def test_variancia_mede_o_mesmo_pool_e_a_mesma_amostra_da_taxa():
    mandante = [jogo(CASA, 9, 8, 5), jogo(CASA, 9, 4, 4), jogo(9, CASA, 6, 6)]
    visitante = [jogo(9, FORA, 5, 5), jogo(9, FORA, 7, 7), jogo(FORA, 9, 3, 3)]
    var = variance_model.variance_stats("corners", "total", mandante, visitante,
                                        home_team_id=CASA, away_team_id=FORA,
                                        peso_outro_mando=DEFAULT_CONFIG.peso_outro_mando)
    taxa = stats_model.market_taxa("corners", "total", "Under", "11.5", mandante, visitante,
                                   home_team_id=CASA, away_team_id=FORA)
    assert var["amostra"] == taxa["amostra"] == 5    # 4 no mando + 2 x 0.5
