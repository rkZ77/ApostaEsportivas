"""Feitos x cedidos: leitura do lado certo e uso de `team_statistics`.

MatchStatsService.get_all_matches_full() filtra por
`(home_team_id = X OR away_team_id = X)` -- devolve os 15 jogos do time
MISTURANDO casa e fora. scored_conceded_avg() recebia um unico is_home_ctx pra
a lista inteira, entao pro mandante lia `home_corners` tambem nos jogos em que
ele jogou FORA: os escanteios do adversario entravam como "feitos" dele.
"""
import pytest

from services.pick_engine.stats_model import (
    expected_value_convergence,
    scored_conceded_avg,
    scored_conceded_from_team_stats,
    shrink_to_baseline,
)

TIME = 100
RIVAL = 200


def _jogo(home_id, away_id, home_corners, away_corners):
    return {
        "home_team_id": home_id, "away_team_id": away_id,
        "home_corners": home_corners, "away_corners": away_corners,
    }


# Time 100 faz 8 escanteios e cede 2 -- sempre, jogando em casa OU fora.
HISTORICO_MISTO = [
    _jogo(TIME, RIVAL, 8, 2),   # 100 em casa: feitos=home_corners=8
    _jogo(RIVAL, TIME, 2, 8),   # 100 fora:    feitos=away_corners=8
    _jogo(TIME, RIVAL, 8, 2),
    _jogo(RIVAL, TIME, 2, 8),
]


def test_resolve_o_mando_por_partida_quando_recebe_team_id():
    feitos, cedidos = scored_conceded_avg(HISTORICO_MISTO, True, "corners", team_id=TIME)

    assert feitos == 8.0
    assert cedidos == 2.0


def test_sem_team_id_a_leitura_se_perde_no_historico_misto():
    """Comportamento antigo, preservado so' como fallback: com mando misto ele
    le a coluna errada em metade dos jogos e a media vira 5/5 -- o time deixa
    de parecer ofensivo e passa a parecer medio."""
    feitos, cedidos = scored_conceded_avg(HISTORICO_MISTO, True, "corners")

    assert feitos == 5.0
    assert cedidos == 5.0


def test_historico_de_mando_unico_da_o_mesmo_resultado_das_duas_formas():
    """Se todos os jogos sao em casa, is_home_ctx sozinho ja' bastava --
    a correcao nao muda nada nesse caso."""
    so_casa = [_jogo(TIME, RIVAL, 7, 3), _jogo(TIME, RIVAL, 5, 1)]

    assert scored_conceded_avg(so_casa, True, "corners", team_id=TIME) == \
           scored_conceded_avg(so_casa, True, "corners")


def test_cartoes_contam_vermelho_como_2_pontos():
    jogos = [{"home_team_id": TIME, "away_team_id": RIVAL,
              "home_yellow_cards": 3, "away_yellow_cards": 1,
              "home_red_cards": 1, "away_red_cards": 0}]

    feitos, cedidos = scored_conceded_avg(jogos, True, "cards", team_id=TIME)

    assert feitos == 5.0   # 3 amarelos + 1 vermelho (2 pontos)
    assert cedidos == 1.0


# ── team_statistics ──────────────────────────────────────────────────────────

def _stats(**kw):
    base = {"games_count": 9, "avg_corners_for": 4.78, "avg_corners_against": 4.89,
            "avg_goals_for": 1.89, "avg_goals_against": 1.44,
            "avg_yellow_for": 2.56, "avg_yellow_against": 2.22,
            "avg_red_for": 0.11, "avg_red_against": 0.0}
    base.update(kw)
    return base


def test_le_feitos_e_cedidos_da_tabela_agregada():
    feitos, cedidos, n = scored_conceded_from_team_stats(_stats(), "corners")

    assert feitos == 4.78
    assert cedidos == 4.89
    assert n == 9


def test_tabela_agregada_sem_jogos_nao_serve():
    assert scored_conceded_from_team_stats(_stats(games_count=0), "corners") == (None, None, 0)
    assert scored_conceded_from_team_stats(None, "corners") == (None, None, 0)


def test_cartoes_da_tabela_agregada_somam_vermelho_como_2():
    feitos, cedidos, _n = scored_conceded_from_team_stats(_stats(), "cards")

    assert feitos == pytest.approx(2.56 + 2 * 0.11, abs=1e-3)
    assert cedidos == pytest.approx(2.22, abs=1e-3)


# ── encolhimento pra media da liga ───────────────────────────────────────────

def test_encolhimento_puxa_amostra_curta_pro_baseline():
    """Time com 2 jogos e media 8.0 numa liga que faz 5.0: com k=4 a estimativa
    fica bem mais perto da liga do que do proprio time."""
    assert shrink_to_baseline(8.0, 2, 5.0, k=4) == pytest.approx((2 * 8 + 4 * 5) / 6, abs=1e-3)


def test_encolhimento_quase_nao_move_amostra_longa():
    """Com 30 jogos o time ja' fala por si -- o baseline mal encosta."""
    encolhido = shrink_to_baseline(8.0, 30, 5.0, k=4)

    assert encolhido == pytest.approx((30 * 8 + 4 * 5) / 34, abs=1e-3)
    assert abs(encolhido - 8.0) < 0.4


def test_sem_baseline_devolve_o_valor_cru():
    """Liga sem dado agregado nao pode inventar alvo de encolhimento."""
    assert shrink_to_baseline(8.0, 2, None) == 8.0
    assert shrink_to_baseline(None, 2, 5.0) is None


def test_convergencia_aplica_encolhimento_quando_ha_baseline():
    """Regressao do achado de 2026-08-03: cruzar feitos-x-cedidos SEM encolher
    mede pior que a media dos 15 jogos crus (corners -1.1%, fouls -2.9%).
    Com encolhimento passa a ganhar nas tres familias medidas."""
    liga = {"home_corners": 5.0, "away_corners": 4.0}
    kw = dict(home_team_id=TIME, away_team_id=RIVAL,
              team_stats_home=_stats(avg_corners_for=9.0, games_count=2),
              team_stats_away=_stats(avg_corners_against=9.0, games_count=2))

    cru = expected_value_convergence(HISTORICO_MISTO, HISTORICO_MISTO, "corners", "home", **kw)
    encolhido = expected_value_convergence(
        HISTORICO_MISTO, HISTORICO_MISTO, "corners", "home", league_baseline=liga, **kw)

    assert cru["estimate_feitos"] == 9.0, "sem baseline, entra cru"
    # (2*9 + 4*5)/6 = 6.33 -- puxado pra liga porque so' ha 2 jogos
    assert encolhido["estimate_feitos"] == pytest.approx(6.333, abs=1e-2)
    assert encolhido["expected_value"] < cru["expected_value"]


def test_convergencia_prefere_a_tabela_agregada():
    conv = expected_value_convergence(
        HISTORICO_MISTO, HISTORICO_MISTO, "corners", "home",
        home_team_id=TIME, away_team_id=RIVAL,
        team_stats_home=_stats(avg_corners_for=6.0, games_count=12),
        team_stats_away=_stats(avg_corners_against=5.8, games_count=11),
    )

    assert conv["source"] == "team_statistics"
    assert conv["estimate_feitos"] == 6.0
    assert conv["estimate_cedidos"] == 5.8
    assert conv["amostra"] == 11, "amostra e' a do lado mais fraco"


def test_convergencia_cai_pro_historico_cru_sem_a_tabela():
    conv = expected_value_convergence(
        HISTORICO_MISTO, HISTORICO_MISTO, "corners", "home",
        home_team_id=TIME, away_team_id=RIVAL,
    )

    assert conv["source"] == "historico_cru"
    assert conv["estimate_feitos"] == 8.0, "com team_id, le o lado certo mesmo no fallback"


def test_convergencia_cai_pro_cru_se_a_tabela_vier_so_de_um_lado():
    conv = expected_value_convergence(
        HISTORICO_MISTO, HISTORICO_MISTO, "corners", "home",
        home_team_id=TIME, away_team_id=RIVAL,
        team_stats_home=_stats(), team_stats_away=None,
    )

    assert conv["source"] == "historico_cru"
