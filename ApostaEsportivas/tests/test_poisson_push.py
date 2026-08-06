"""Linha redonda: Poisson e taxa empirica tem que medir a MESMA coisa.

Numa linha sem .5 ("Under 10"), o jogo que empata exato com a linha e' PUSH na
graduacao real (ai_result_checker_service.evaluate_asian devolve a stake).
stats_model.weighted_rate() ja excluia esse jogo da amostra desde 2026-07-25;
probability_model continuava contando P(X<=10) pro Under, ou seja somava ao
"acerto" justamente a massa que vira devolucao.

Resultado: as duas estimativas discordavam por construcao, e o termo M
(confidence.model_fit_adjustment) cobrava -0.05 de confidence por uma
divergencia que era diferenca de convencao, nao modelo errado.
"""
import pytest

from services.pick_engine import probability_model as pm


LAM = 2.5


def test_linha_meia_nao_muda_nada():
    """Em linha .5 nao existe push -- comportamento identico ao de sempre."""
    assert pm.poisson_prob_for_line(LAM, 2.5, "over") == pytest.approx(
        round(pm.prob_over(2.5, LAM), 4))
    assert pm.poisson_prob_for_line(LAM, 2.5, "under") == pytest.approx(
        round(pm.prob_under(2.5, LAM), 4))


def test_over_e_under_de_linha_redonda_somam_1():
    """Condicionado a nao dar push, os dois lados particionam o espaco --
    e' o que a graduacao real faz e o que a taxa empirica ja media."""
    over = pm.poisson_prob_for_line(LAM, 2.0, "over")
    under = pm.poisson_prob_for_line(LAM, 2.0, "under")
    assert over + under == pytest.approx(1.0, abs=1e-3)


def test_linha_redonda_exclui_a_massa_de_push():
    """'Under 2' NAO pode incluir P(X=2): esse jogo e' devolucao."""
    push = pm.poisson_pmf(2, LAM)
    esperado = (pm.poisson_cdf(1, LAM)) / (1 - push)
    assert pm.poisson_prob_for_line(LAM, 2.0, "under") == pytest.approx(round(esperado, 4), abs=1e-3)


def test_over_de_linha_redonda_renormaliza():
    push = pm.poisson_pmf(2, LAM)
    esperado = (1 - pm.poisson_cdf(2, LAM)) / (1 - push)
    assert pm.poisson_prob_for_line(LAM, 2.0, "over") == pytest.approx(round(esperado, 4), abs=1e-3)


def test_versao_antiga_inflava_o_under():
    """Guarda o tamanho do erro que foi corrigido: com lambda 2.5 e linha 2,
    P(X<=2) e' bem maior que a probabilidade condicional real."""
    antigo = pm.poisson_cdf(2, LAM)          # o que era devolvido antes
    novo = pm.poisson_prob_for_line(LAM, 2.0, "under")
    assert antigo - novo > 0.05


def test_concordancia_com_a_taxa_empirica_em_linha_redonda():
    """Um historico onde metade dos jogos empata a linha: a taxa empirica
    (que exclui push) e o Poisson corrigido tem que ficar do mesmo lado --
    antes o model_fit acusava divergencia e descontava confidence."""
    # 3 jogos com 1 gol (Under bate), 3 com 3 gols (Over bate), 4 com 2 (push).
    from datetime import date
    hist = []
    for i, total in enumerate([1, 1, 1, 3, 3, 3, 2, 2, 2, 2]):
        hist.append({
            "match_date": date(2026, 7, 1), "opponent_rank": 10,
            "home_team_id": 1, "away_team_id": 2,
            "home_goals": total, "away_goals": 0, "total_goals": total,
        })

    from services.pick_engine import stats_model
    taxa = stats_model.compute_taxa("goals", "total", "Under", "2", hist, [], date(2026, 8, 5))
    # 6 jogos contam (4 push fora), 3 batem Under -> 50%
    assert taxa["amostra"] == 6
    assert taxa["taxa_ponderada"] == pytest.approx(0.5)

    # Poisson com lambda igual a media dos jogos NAO-push segue a mesma
    # convencao agora: nem Over nem Under recebem a massa de empate.
    over = pm.poisson_prob_for_line(2.0, 2.0, "over")
    under = pm.poisson_prob_for_line(2.0, 2.0, "under")
    assert over + under == pytest.approx(1.0, abs=1e-3)
