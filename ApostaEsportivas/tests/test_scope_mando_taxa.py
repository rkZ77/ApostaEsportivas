"""Escopo home/away: a taxa tem que ler a coluna DO TIME analisado.

MatchStatsService.get_all_matches_full() filtra por
`(home_team_id = X OR away_team_id = X)` -- o pool de um time mistura jogos em
casa e fora. _extract_stat() lia o campo fixo do escopo (`home_corners` pra
scope='home') em TODOS eles, entao nos jogos em que o time era visitante a
taxa contava a estatistica DO ADVERSARIO.

scored_conceded_avg() e offensive_efficiency() ja tinham corrigido esse mesmo
bug cada uma por conta propria (ver tests/test_scored_conceded.py); a taxa em
si -- o numero que vira edge, EV e pick -- nao tinha.
"""
from datetime import date, timedelta

import pytest

from services.pick_engine import stats_model, variance_model, data_validation


REF = date(2026, 8, 5)
TIME = 100


def _jogo(i, em_casa, feitos_do_time, feitos_do_adversario, **extra):
    """Uma partida do historico do TIME, com o mando explicito."""
    d = REF - timedelta(days=7 * (i + 1))
    if em_casa:
        base = {"home_team_id": TIME, "away_team_id": 200 + i,
                "home_corners": feitos_do_time, "away_corners": feitos_do_adversario,
                "home_yellow_cards": feitos_do_time, "away_yellow_cards": feitos_do_adversario,
                "home_red_cards": 0, "away_red_cards": 0}
    else:
        base = {"home_team_id": 200 + i, "away_team_id": TIME,
                "home_corners": feitos_do_adversario, "away_corners": feitos_do_time,
                "home_yellow_cards": feitos_do_adversario, "away_yellow_cards": feitos_do_time,
                "home_red_cards": 0, "away_red_cards": 0}
    base.update({"match_date": d, "opponent_rank": 10, **extra})
    return base


def _historico_mando_alternado(feitos=9, adversario=2, n=8):
    """Time faz sempre `feitos`; adversario sempre `adversario`. Mando alterna."""
    return [_jogo(i, i % 2 == 0, feitos, adversario) for i in range(n)]


def test_taxa_de_escopo_home_le_o_time_certo_no_historico_misto():
    hist = _historico_mando_alternado(feitos=9, adversario=2)
    # O time faz 9 escanteios em todo jogo -> Over 5.5 tem que dar 100%.
    taxa = stats_model.compute_taxa(
        "corners", "home", "Over", "5.5", hist, [], REF, team_id=TIME,
    )
    assert taxa["taxa_ponderada"] == pytest.approx(1.0)


def test_sem_team_id_a_taxa_de_escopo_home_le_metade_no_adversario():
    """Comportamento ANTIGO, preservado quando o chamador nao passa team_id --
    documenta o bug pra ninguem 'consertar' o default achando que e' inofensivo."""
    hist = _historico_mando_alternado(feitos=9, adversario=2)
    taxa = stats_model.compute_taxa("corners", "home", "Over", "5.5", hist, [], REF)
    assert taxa["taxa_ponderada"] == pytest.approx(0.5)


def test_taxa_de_escopo_away_le_o_time_certo():
    hist = _historico_mando_alternado(feitos=9, adversario=2)
    taxa = stats_model.compute_taxa(
        "corners", "away", "Over", "5.5", [], hist, REF, team_id=TIME,
    )
    assert taxa["taxa_ponderada"] == pytest.approx(1.0)


def test_cartoes_de_escopo_home_tambem_resolvem_o_mando():
    hist = _historico_mando_alternado(feitos=4, adversario=1)
    taxa = stats_model.compute_taxa(
        "cards", "home", "Over", "2.5", hist, [], REF, team_id=TIME,
    )
    assert taxa["taxa_ponderada"] == pytest.approx(1.0)


def test_variancia_de_escopo_home_mede_a_dispersao_do_time_nao_o_vai_e_vem():
    """Time totalmente constante (9 em todo jogo): desvio real e' 0. Sem o
    team_id, o pool alterna 9/2 e o CV sai alto o bastante pra cobrar
    penalidade de confidence que o historico nao justifica."""
    hist = _historico_mando_alternado(feitos=9, adversario=2)

    com_fix = variance_model.variance_stats("corners", "home", hist, [], team_id=TIME)
    assert com_fix["std_dev"] == pytest.approx(0.0)
    assert variance_model.variance_penalty(com_fix["coefficient_of_variation"]) == 0.0

    sem_fix = variance_model.variance_stats("corners", "home", hist, [])
    assert sem_fix["std_dev"] > 3.0
    assert variance_model.variance_penalty(sem_fix["coefficient_of_variation"]) > 0.0


def test_outlier_de_escopo_home_olha_os_valores_do_time():
    """Um jogo destoante DO TIME (20 escanteios) tem que ser o outlier.

    Sem o team_id o pool alterna entre os escanteios do time e os do
    adversario: mediana e MAD passam a descrever esse vai-e-vem, e o jogo
    realmente atipico se esconde dentro dele.

    Historico com dispersao real de proposito -- a deteccao usa MAD, que fica
    0 (e nao acusa nada) quando mais da metade dos valores e' identica.
    """
    feitos = [8, 9, 10, 9, 8, 10, 9, 11]          # o time, variando de verdade
    adversarios = [3, 2, 4, 2, 3, 2, 4, 3]
    hist = [_jogo(i, i % 2 == 0, f, a) for i, (f, a) in enumerate(zip(feitos, adversarios))]
    # Um jogo em casa (i=0) com valor claramente fora da faixa do time.
    hist[0]["home_corners"] = 20

    com_fix = data_validation.detect_outliers("corners", "home", hist, [], team_id=TIME)
    assert [o["value"] for o in com_fix["outliers"]] == [20]

    # Sem o fix, o 20 deixa de ser detectado: metade do pool sao os valores
    # baixos do adversario, o MAD explode e o jogo atipico cabe dentro dele.
    sem_fix = data_validation.detect_outliers("corners", "home", hist, [])
    assert sem_fix["outlier_count"] == 0


def test_escopo_total_nao_depende_de_team_id():
    """scope='total' le o total da partida -- nao ha lado a resolver, o
    resultado tem que ser identico com e sem team_id."""
    hist = _historico_mando_alternado(feitos=9, adversario=2)
    for m in hist:
        m["total_corners"] = m["home_corners"] + m["away_corners"]

    com = stats_model.compute_taxa("corners", "total", "Over", "10.5", hist, [], REF, team_id=TIME)
    sem = stats_model.compute_taxa("corners", "total", "Over", "10.5", hist, [], REF)
    assert com["taxa_ponderada"] == sem["taxa_ponderada"] == pytest.approx(1.0)


def test_estabilidade_de_linha_tambem_resolve_o_mando():
    """line_stability compara metade recente vs antiga -- com o mando
    alternado e sem team_id, cada metade pega uma mistura diferente de
    time/adversario e a 'instabilidade' medida e' artefato do bug."""
    hist = _historico_mando_alternado(feitos=9, adversario=2)
    est = stats_model.line_stability("corners", "home", "Over", "5.5", hist, [], team_id=TIME)
    assert est["instability"] == pytest.approx(0.0)


def test_scope_team_id_mapeia_o_lado_certo():
    assert stats_model.scope_team_id("home", 1, 2) == 1
    assert stats_model.scope_team_id("away", 1, 2) == 2
    assert stats_model.scope_team_id("total", 1, 2) is None
