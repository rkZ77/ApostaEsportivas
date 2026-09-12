"""Projecao x linha e risco multifator (Free Analise V2, secoes 20/21 e 29).

Duas coisas que o motor tinha os dados pra dizer e nao dizia:

 1. A PROJECAO. `lambda_familia` virava probabilidade e morria ali. O pick
    guardava "Poisson dizia 71%" sem guardar que os 71% saiam de uma projecao
    de 5.6 numa linha de 5.5.
 2. O RISCO. Era funcao unica do confidence, um score composto ja' somado e
    teto-limitado -- um pick com amostra minima e projecao colada na linha
    podia terminar em 0.81 e sair anunciado como BAIXO.
"""
import pytest

from services.pick_engine import projection, confidence
from services.pick_engine.config import DEFAULT_CONFIG


# ---------------------------------------------------------------- projecao

def test_margem_e_medida_em_desvios_da_contagem_nao_em_unidades():
    """A MESMA margem bruta (+0.4) e' folga real em gols e quase nada em
    escanteios. Se a classificacao olhasse a unidade bruta, as duas seriam
    tratadas igual -- que e' o erro que sigma existe pra evitar."""
    gols = projection.margem(2.9, 2.5, "over", family="goals", scope="total")
    corners = projection.margem(10.4, 10.0, "over", family="corners", scope="total")

    assert gols["margem"] == corners["margem"] == 0.4
    assert gols["margem_em_sigmas"] > corners["margem_em_sigmas"]


def test_projecao_em_cima_da_linha_nao_e_folga():
    proj = projection.margem(5.52, 5.5, "over", family="corners", scope="total")
    assert proj["classe"] == "em_cima_da_linha"


def test_under_quer_projecao_abaixo_da_linha():
    """O sinal da margem e' sempre a favor do pick: em Under, projecao
    ABAIXO da linha e' margem positiva."""
    proj = projection.margem(8.0, 10.5, "under", family="corners", scope="total")
    assert proj["margem"] == 2.5
    assert proj["classe"] == "folgada"


def test_projecao_contra_a_linha_e_marcada():
    """Over comprado com projecao abaixo da linha: o que sustenta a entrada
    e' so' a contagem historica, contra o valor esperado."""
    proj = projection.margem(2.0, 2.5, "over", family="goals", scope="total")
    assert proj["margem_em_sigmas"] < 0
    assert proj["classe"] == "contra_a_linha"


@pytest.mark.parametrize("lam,linha,direcao", [
    (None, 5.5, "over"),        # familia sem valor esperado (btts/resultado)
    (5.6, None, "over"),        # linha nao numerica (handicap textual)
    (5.6, 5.5, "yes"),          # direcao que nao e' over/under
])
def test_sem_dado_nao_inventa_projecao(lam, linha, direcao):
    assert projection.margem(lam, linha, direcao, family="corners", scope="total") is None


# ------------------------------------------------------------------- risco

def _conf_de_risco_baixo():
    return DEFAULT_CONFIG.risco_baixo_min + 0.01


def test_sem_sinais_extras_o_risco_e_o_de_sempre():
    """Compatibilidade: chamador que nao tem os outros sinais em maos recebe
    exatamente o que risco_from_confidence devolvia."""
    conf = _conf_de_risco_baixo()
    assert confidence.classify_risk(conf, DEFAULT_CONFIG) == "BAIXO"
    assert confidence.classify_risk(conf, DEFAULT_CONFIG) == \
        confidence.risco_from_confidence(conf, DEFAULT_CONFIG)


def test_amostra_minima_derruba_o_risco_baixo():
    conf = _conf_de_risco_baixo()
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, amostra=6) == "MEDIO"
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, amostra=4) == "ALTO"


def test_data_quality_insuficiente_derruba_o_risco_baixo():
    conf = _conf_de_risco_baixo()
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, data_quality=75) == "MEDIO"
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, data_quality=65) == "ALTO"


def test_projecao_colada_na_linha_derruba_o_risco_baixo():
    conf = _conf_de_risco_baixo()
    colada = projection.margem(5.52, 5.5, "over", family="corners", scope="total")
    contra = projection.margem(2.0, 2.5, "over", family="goals", scope="total")
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, projecao=colada) == "MEDIO"
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, projecao=contra) == "ALTO"


def test_dispersao_alta_derruba_o_risco_baixo():
    """variance_penalty satura em 0.10 -- um mercado muito instavel com taxa
    muito alta sobrevive ao desconto de confidence. O degrau de risco e' o
    que impede esse caso de se anunciar como BAIXO."""
    conf = _conf_de_risco_baixo()
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, coeficiente_variacao=0.90) == "MEDIO"
    assert confidence.classify_risk(conf, DEFAULT_CONFIG, coeficiente_variacao=0.30) == "BAIXO"


def test_risco_nunca_melhora():
    """Nenhum sinal pode promover ALTO pra MEDIO. Confidence e' o unico lugar
    onde evidencia vira nota; aqui so' se cobra o que o score deixou passar."""
    conf_alto_risco = DEFAULT_CONFIG.risco_medio_min - 0.01
    folgada = projection.margem(12.0, 8.5, "over", family="corners", scope="total")
    assert folgada["classe"] == "folgada"
    assert confidence.classify_risk(
        conf_alto_risco, DEFAULT_CONFIG,
        data_quality=100, amostra=30, coeficiente_variacao=0.05, projecao=folgada,
    ) == "ALTO"


def test_sinal_ausente_e_neutro_nao_favoravel():
    conf = _conf_de_risco_baixo()
    assert confidence.classify_risk(
        conf, DEFAULT_CONFIG,
        data_quality=None, amostra=None, coeficiente_variacao=None, projecao=None,
    ) == "BAIXO"
