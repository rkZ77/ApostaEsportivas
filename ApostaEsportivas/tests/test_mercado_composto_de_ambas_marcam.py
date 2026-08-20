"""Mercado COMPOSTO com "both teams score" nao e' ambas marcam.

A API-Football manda, alem do "Both Teams Score" simples:

    "Results/Both Teams Score"            1X2 + BTTS   ("Home/Yes", "Away/No", "Draw/Yes")
    "Total Goals/Both Teams To Score"     O/U + BTTS   ("o/yes 2.5", "u/no 2.5")

Os dois contem "both teams" e "score" e caiam em ("btts", "total").

JA ERAM descartados, mas por ACIDENTE de parse: _build_market_hit_fn exige
direction em (yes/sim/no/nao), "Home/Yes" nao bate, compute_taxa devolvia None e
a entrada morria rotulada "sem taxa calculavel (amostra insuficiente)". Mesma
situacao de "Goalkeeper Saves" antes de 2026-08-01, e a decisao aqui e' a mesma
que foi tomada la': descartar por DECISAO, nao por acidente.

Nao e' cosmetico. Achado em 2026-08-17 rodando o modo debug contra 44 fixtures
reais: sao ~10 entradas fantasma POR FIXTURE rotuladas "btts" no rastro, e foi
isso que fez um relatorio de auditoria afirmar "btts apareceu 440x e publicou 0x"
enquanto o motor publicava ambas marcam normalmente. Rastro sujo produz conclusao
errada mesmo com o motor certo.

Combinado de 1X2+BTTS ainda seria mercado de RESULTADO, fora do pool por decisao
de produto desde 2026-07-24 -- aceita-lo seria furar aquela regra por uma porta
lateral.
"""
import pytest

from services.pick_engine.stats_model import classify_market


@pytest.mark.parametrize("nome", [
    "Both Teams Score",
    "Both Teams To Score",
    "both teams score",
])
def test_ambas_marcam_simples_continua_reconhecida(nome):
    assert classify_market(nome) == ("btts", "total")


@pytest.mark.parametrize("nome", [
    "Results/Both Teams Score",
    "Total Goals/Both Teams To Score",
    "Both Teams Score/Total Goals",      # ordem invertida, mesma coisa
    "Double Chance/Both Teams To Score",
])
def test_composto_com_ambas_marcam_sai_do_pool(nome):
    assert classify_market(nome) is None, f"{nome!r} e' composto, nao BTTS"


def test_a_regra_e_a_barra_e_nao_uma_lista_de_nomes():
    """Trava o MECANISMO, nao os nomes vistos ate hoje.

    Nome de BTTS simples nunca tem barra (ver as chaves de marketTranslate.ts).
    Um composto novo que a API inventar amanha ja nasce excluido, sem precisar
    de outra linha aqui -- que e' o oposto do padrao "lista de excecoes" que
    precisa ser atualizada a cada mercado novo."""
    assert classify_market("Anything/Both Teams Score") is None
    assert classify_market("Both Teams Score/Anything") is None


def test_primeiro_tempo_continua_fora():
    """Regra anterior, nao pode ter sido quebrada pelo guard novo."""
    assert classify_market("Both Teams Score - First Half") is None
    assert classify_market("Both Teams To Score - First Half") is None


def test_o_composto_nao_vira_mercado_de_resultado_por_acidente():
    """"Results/Both Teams Score" contem "result". Se o guard de BTTS deixasse
    passar, a checagem seguinte poderia classificar como outcome e reabrir um
    mercado de resultado -- que esta' fora do pool por decisao de produto."""
    assert classify_market("Results/Both Teams Score") is None


# ─────────── combinados com RESULTADO, e o "Own Goal" (2026-08-17) ───────────
#
# Mesma familia de acidente, achada medindo o que min_bookmakers_count=2
# descartava: 100% do que aquele gate derruba e' formato exotico como estes,
# porque load_odds_structured JA derruba over/under com menos de 2 casas antes.
# Sao ~300 entradas fantasma em 20 fixtures, todas rotuladas `goals` no rastro --
# e foi essa poluicao que quase fez uma auditoria propor baixar o limiar.


@pytest.mark.parametrize("nome", [
    "Result/Total Goals",
    "Results/Total Goals",
    "Result/Both Teams Score",
])
def test_combinado_com_resultado_sai_do_pool(nome):
    assert classify_market(nome) is None, f"{nome!r} e' combo com 1X2"


def test_own_goal_nao_e_mercado_de_gols():
    """"Own Goal" (houve gol contra?) contem "goal" e caia em ("goals","total"),
    comparado contra o total de gols da partida. E' um sim/nao sobre evento raro.
    Mesma classe do bug ja corrigido de "Goalkeeper Saves" caindo em gols."""
    assert classify_market("Own Goal") is None
    assert classify_market("own goal") is None


def test_gols_de_verdade_continuam_passando():
    """A regressao que importa: os guards novos nao podem cortar o mercado real."""
    assert classify_market("Goals Over/Under") == ("goals", "total")
    assert classify_market("Home Team Total Goals") == ("goals", "home")
    assert classify_market("Away Team Total Goals") == ("goals", "away")
    assert classify_market("Total Goals") == ("goals", "total")


# ═════════════════════════════════════════════════════════════════════════
# market_type PROPRIO PARA BTTS (2026-08-20)
# ═════════════════════════════════════════════════════════════════════════
def test_btts_tem_market_type_proprio():
    """Ate 2026-08-20 o BTTS era gravado como market_type="goals", e isso
    escondia o melhor mercado do motor dentro do balde do segundo melhor.
    Medido em PROD, separando os dois pelo NOME (porque o market_type nao
    separava): Ambas Marcam 80,6% de acerto e +12,12 u em 31 picks, contra
    69,7% e +7,71 u em 119 de over/under de gols.

    Sao dinamicas diferentes e estavam sendo calibrados juntos."""
    from services.pick_engine import stats_model
    assert stats_model.classify_market("Both Teams Score") == ("btts", "total")


def test_correlacao_de_btts_com_gols_sobrevive_ao_tipo_proprio():
    """A protecao que impede "Over 1.5 gols" + "Ambas Marcam" no mesmo bilhete
    e' por correlation_group, nao por market_type. Se ela cair junto com a
    mudanca de tipo, a multipla volta a multiplicar duas pernas correlacionadas
    como se fossem independentes."""
    from services.pick_engine import ranking
    assert ranking.correlation_group("btts") == "goals"
    assert ranking.correlation_group("goals") == "goals"


def test_btts_continua_lendo_o_matchup_de_gols():
    """compare_matchup so' produz goals/corners/cards. Com tipo proprio, a
    busca por "btts" devolveria None e o BTTS perderia o termo de Perfil no
    Score Final em silencio."""
    from services.pick_engine import team_profile_model
    matchup = {"goals": {"delta": 1.5, "label": "over"}}
    assert (team_profile_model.profile_score_for_market(matchup, "btts")
            == team_profile_model.profile_score_for_market(matchup, "goals"))
    assert team_profile_model.profile_score_for_market(matchup, "btts") is not None


def test_liquidacao_ja_esperava_o_tipo_btts():
    """O hint so' entra quando o TEXTO do mercado nao decide. Antes, nesse caso
    de borda, um pick de BTTS carregava o hint errado ("goals")."""
    from services.ai_result_checker_service import AIResultCheckerService
    assert AIResultCheckerService._MARKET_TYPE_HINTS.get("btts") == "btts"
