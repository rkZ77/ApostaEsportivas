"""O encolhimento bayesiano estava desarmando o alarme de desacordo.

A ordem das operacoes em orchestrator.py era:

    taxa_ajustada = shrink_taxa(taxa_bruta, amostra, prob_mercado)  # encolhe
    fit           = model_fit(taxa_ajustada, poisson)               # compara O ENCOLHIDO
    if fit > 0.15: rebaixa

O encolhimento puxa a taxa em direcao ao mercado, e o Poisson normalmente esta'
do MESMO lado que o mercado. Logo o encolhimento reduz justamente a distancia que
a regra procura: quanto mais violento o desacordo original, melhor ele fica
escondido. Medido nos 8 RED de pick simples de 14-16/08/2026 (VIP+Free, todos):
em 8 de 8 a taxa bruta estava acima do Poisson, em 7 de 8 por mais de 13 pontos,
e a regra nao disparou nenhuma vez.

O caso que da' nome ao arquivo, com os numeros de producao: Atletico-MG x Gremio,
"Escanteios Menos de 10" @1.86. Taxa bruta 92.7% em ~6 jogos, mercado ~50.5%,
Poisson 60.4%. Publicado: 66.3% com edge de +15.8%. Saiu 14 escanteios.
"""
import pytest

from services.pick_engine import orchestrator, probability_model
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


def _jogo(match_date, total_corners):
    return {
        "match_date": match_date, "home_team_id": 1, "away_team_id": 2,
        "home_corners": total_corners, "away_corners": 0,
        "total_corners": total_corners, "opponent_rank": None,
    }


def _odds(linha="9.5", odd_over=2.00, odd_under=2.00):
    base = {"market_id": 1, "market_name": "Corners Over/Under",
            "line": linha, "bookmakers_count": 3}
    return [
        {**base, "value": "Over", "best_odd": odd_over},
        {**base, "value": "Under", "best_odd": odd_under},
    ]


#: 6 jogos com 8 escanteios. Contra "Under 9.5" a contagem direta bate 100%,
#: mas lambda 8 num Poisson da' P(X<=9) ~ 71.7% -- a contagem so' parece perfeita
#: porque nenhum dos 6 caiu do outro lado de uma linha proxima da media. E' o
#: formato exato do caso Atletico-MG x Gremio, com n pequeno e taxa saturada.
_HIST = [_jogo(f"2026-07-{i + 1:02d}", 8) for i in range(6)]


def _candidato(config, direcao="Under"):
    candidatos = orchestrator.analyze_fixture_markets(
        _odds(), _HIST, _HIST,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2, config=config,
    )
    return next(c for c in candidatos if c["value"] == direcao)


def test_o_encolhimento_esconde_o_desacordo_no_modo_de_producao():
    """Trava o DEFEITO, pra a correcao nao poder ser revertida em silencio.

    Com o padrao atual (compara o encolhido) o desacordo medido fica ABAIXO do
    limiar mesmo com a taxa bruta a mais de 20 pontos do Poisson."""
    c = _candidato(PickEngineConfig(disagreement_on_raw_rate=False))
    assert c["taxa_bruta_pre_bayes"] == 1.0
    # o encolhimento levou 100% pra perto do mercado (50%)
    assert c["taxa_real"] < c["taxa_bruta_pre_bayes"]
    # e ao encolher, aproximou a taxa do Poisson: o desacordo aparente encolheu junto
    assert c["model_fit_diff_bruta"] > c["model_fit_diff"]
    assert c["model_fit_diff"] < DEFAULT_CONFIG.model_disagreement_threshold
    assert c["model_fit_diff_bruta"] > DEFAULT_CONFIG.model_disagreement_threshold
    # consequencia: nada foi rebaixado
    assert "taxa_real_pre_desacordo" not in c


def test_comparando_o_bruto_a_regra_dispara_e_publica_o_poisson():
    c = _candidato(PickEngineConfig(disagreement_on_raw_rate=True))
    assert c["model_fit_diff_bruta"] > DEFAULT_CONFIG.model_disagreement_threshold
    assert "taxa_real_pre_desacordo" in c, "a regra tinha que ter disparado"
    assert c["taxa_real"] == c["poisson_probability"]
    # edge e EV SEMPRE derivados da probabilidade final -- se saem de sincronia,
    # o site anuncia um EV que nao corresponde a probabilidade mostrada do lado
    assert c["edge"] == pytest.approx(c["taxa_real"] - c["prob_baseline_value"], abs=1e-4)
    assert c["ev"] == pytest.approx(c["taxa_real"] * c["odd"] - 1, abs=1e-4)


def test_ligar_a_flag_derruba_a_probabilidade_publicada():
    """A comparacao lado a lado, que e' o efeito que o backtest vai medir."""
    producao = _candidato(PickEngineConfig(disagreement_on_raw_rate=False))
    corrigido = _candidato(PickEngineConfig(disagreement_on_raw_rate=True))
    assert corrigido["taxa_real"] < producao["taxa_real"]
    assert corrigido["ev"] < producao["ev"]


def test_a_regra_continua_nunca_subindo_a_probabilidade():
    """A invariante mais importante: detectar no bruto nao pode virar licenca pra
    INFLAR um pick.

    6 jogos de 10 escanteios e 4 de 3, contra Over 4.5. A contagem direta da'
    60% (56.7% depois do encolhimento) e o modelo, com lambda 7.2, da' ~75.8%.
    O desacordo bruto (15.8pp) passa do limiar e a DETECCAO dispara -- mas a
    ACAO exige que a outra estimativa seja mais PESSIMISTA que a publicada, e
    75.8% e' mais otimista. Nada pode acontecer.

    E' por isso que a correcao mudou so' a deteccao e deixou a acao comparando
    contra taxa_ajustada: trocar as duas por taxa_bruta_raw faria a regra subir
    a probabilidade justamente onde o encolhimento tinha corrigido pra baixo.

    O historico era 8 e 4 ate' 2026-08-20; ver a nota gemea em
    test_mando_prior_desacordo.test_desacordo_nunca_sobe_a_probabilidade."""
    hist = ([_jogo(f"2026-07-{i + 1:02d}", 10) for i in range(6)]
            + [_jogo(f"2026-07-{i + 10:02d}", 3) for i in range(4)])
    candidatos = orchestrator.analyze_fixture_markets(
        _odds(linha="4.5"), hist, hist,
        calibration_data={"by_market": {}, "by_market_league": {}},
        home_team_id=1, away_team_id=2,
        config=PickEngineConfig(disagreement_on_raw_rate=True),
    )
    over = next(c for c in candidatos if c["value"] == "Over")
    assert over["taxa_bruta_pre_bayes"] == pytest.approx(0.6, abs=1e-3)
    assert over["model_fit_diff_bruta"] > DEFAULT_CONFIG.model_disagreement_threshold
    assert over["poisson_probability"] > over["taxa_real"]
    assert "taxa_real_pre_desacordo" not in over, "rebaixou pra cima"


def test_o_rastro_bruto_e_gravado_mesmo_quando_nao_decide_nada():
    """Instrumentacao: os dois numeros existem nos dois modos, senao nao da' pra
    medir depois quanto o encolhimento estava escondendo."""
    for flag in (False, True):
        c = _candidato(PickEngineConfig(disagreement_on_raw_rate=flag))
        assert c["model_fit_diff_bruta"] is not None
        assert c["model_fit_diff"] is not None
        esperado = probability_model.model_fit(
            c["taxa_bruta_pre_bayes"], c["poisson_probability"])
        assert c["model_fit_diff_bruta"] == pytest.approx(esperado, abs=1e-4)


def test_padrao_de_producao_nao_mudou():
    """A flag nasce desligada: o motor tem que produzir o MESMO resultado de
    antes dela existir. Mesmo papel de
    test_camada_probabilistica.py::test_flags_desligadas_nao_mudam_nada."""
    assert DEFAULT_CONFIG.disagreement_on_raw_rate is False
    c = _candidato(DEFAULT_CONFIG)
    # sem rebaixamento, a taxa publicada e' exatamente a encolhida
    assert "taxa_real_pre_desacordo" not in c
    from services.pick_engine import bayesian_model
    assert c["taxa_real"] == pytest.approx(
        bayesian_model.shrink_taxa(
            c["taxa_bruta_pre_bayes"], c["amostra"], c["prob_baseline_value"]),
        abs=1e-4)
