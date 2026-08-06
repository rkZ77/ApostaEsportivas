"""Ancoragem de mercado e correcao de vies de selecao.

Os dois modulos atacam a mesma familia de falso positivo por caminhos
diferentes: a ancora impede que uma taxa extrema de amostra pequena vire pick
so' porque discorda do mercado, e o vies de selecao desconta a vantagem
aparente de quem venceu uma disputa entre muitos candidatos ruidosos.
"""
import math

import pytest

from services.pick_engine import market_anchor as ma
from services.pick_engine import selection_bias as sb


# ======================================================================
# Ancoragem
# ======================================================================
def test_logit_e_expit_sao_inversas():
    for p in (0.05, 0.3, 0.5, 0.77, 0.95):
        assert ma.expit(ma.logit(p)) == pytest.approx(p, abs=1e-6)


def test_expit_nao_estoura_em_argumento_grande():
    assert ma.expit(800) == pytest.approx(1.0)
    assert ma.expit(-800) == pytest.approx(0.0)


def test_logit_recorta_as_pontas_em_vez_de_estourar():
    assert math.isfinite(ma.logit(0.0))
    assert math.isfinite(ma.logit(1.0))


def test_blend_com_peso_zero_devolve_o_mercado():
    assert ma.blend(0.80, 0.45, w=0.0) == pytest.approx(0.45, abs=1e-3)


def test_blend_com_peso_um_devolve_o_modelo():
    assert ma.blend(0.80, 0.45, w=1.0) == pytest.approx(0.80, abs=1e-3)


def test_blend_fica_entre_as_duas_opinioes():
    combinado = ma.blend(0.80, 0.45, w=0.5)
    assert 0.45 < combinado < 0.80


def test_blend_none_sem_preco_de_mercado():
    """Sem fechamento nao se finge que o mercado concordou."""
    assert ma.blend(0.80, None, w=0.5) is None
    assert ma.blend(None, 0.45, w=0.5) is None


def test_peso_default_sem_historico():
    assert ma.peso_por_clv(None, amostra=0) == ma.W_INICIAL
    assert ma.peso_por_clv(0.05, amostra=3) == ma.W_INICIAL


def test_clv_positivo_significativo_aumenta_a_confianca_no_modelo():
    w = ma.peso_por_clv(0.03, amostra=100, significativo=True)
    assert w > ma.W_INICIAL
    assert w <= ma.W_MAX


def test_clv_positivo_sem_significancia_nao_aumenta():
    """Subir confianca com base em ruido e' o erro caro."""
    assert ma.peso_por_clv(0.03, amostra=100, significativo=False) == ma.W_INICIAL


def test_clv_negativo_derruba_mesmo_sem_significancia():
    """Assimetria deliberada: reduzir confianca por ruido custa so'
    oportunidade, aumentar custa dinheiro."""
    w = ma.peso_por_clv(-0.03, amostra=100, significativo=False)
    assert w < ma.W_INICIAL
    assert w >= ma.W_MIN


def test_peso_respeita_piso_e_teto():
    assert ma.peso_por_clv(10.0, amostra=500, significativo=True) <= ma.W_MAX
    assert ma.peso_por_clv(-10.0, amostra=500, significativo=True) >= ma.W_MIN


def test_ancora_segura_taxa_extrema_sem_historico():
    """O caso que motiva o modulo: motor diz 85%, mercado precifica 45%, e
    nao ha CLV que sustente a ousadia. A combinacao tem que ficar bem mais
    perto do mercado que do motor."""
    r = ma.anchor(p_modelo=0.85, p_mercado=0.45)
    assert r["p_final"] < 0.65
    assert r["divergencia_logit"] > 0


def test_ancora_deixa_o_modelo_falar_quando_ele_provou_valor():
    r = ma.anchor(p_modelo=0.85, p_mercado=0.45,
                  clv_medio=0.03, amostra_clv=200, clv_significativo=True)
    sem_historico = ma.anchor(p_modelo=0.85, p_mercado=0.45)
    assert r["p_final"] > sem_historico["p_final"]


def test_ancora_expoe_todos_os_componentes():
    r = ma.anchor(0.7, 0.6, clv_medio=0.01, amostra_clv=50, clv_significativo=True)
    for chave in ("p_modelo", "p_mercado", "peso_modelo", "p_final",
                  "divergencia_logit", "clv_medio", "clv_amostra"):
        assert chave in r


def test_divergencia_zero_quando_as_opinioes_batem():
    assert ma.divergencia(0.6, 0.6) == pytest.approx(0.0)


# ======================================================================
# Vies de selecao
# ======================================================================
def test_sem_concorrencia_nao_ha_vies():
    assert sb.corrigir([{"edge": 0.20}])["desconto"] == 0.0
    assert sb.corrigir([])["desconto"] == 0.0


def test_desconto_cresce_com_o_numero_de_candidatos():
    poucos = sb.desconto_por_contagem(3, desvio=0.05)
    muitos = sb.desconto_por_contagem(40, desvio=0.05)
    assert muitos > poucos > 0


def test_desconto_cresce_devagar_por_ser_logaritmico():
    """Dobrar os mercados nao dobra o vies."""
    d10 = sb.desconto_por_contagem(10, desvio=0.05)
    d20 = sb.desconto_por_contagem(20, desvio=0.05)
    assert d20 < 2 * d10


def test_desconto_zero_sem_dispersao():
    """Candidatos identicos: o vencedor nao ganhou no ruido."""
    assert sb.desconto_por_contagem(20, desvio=0.0) == 0.0


def test_desconto_respeita_o_teto():
    assert sb.desconto_por_contagem(500, desvio=5.0) == sb.DESCONTO_MAX


def test_vencedor_colado_no_segundo_recebe_desconto():
    """Folga minima entre 1o e 2o de muitos candidatos: quase tudo e' ruido."""
    candidatos = [{"edge": 0.10 + i * 0.001} for i in range(25)]
    r = sb.corrigir(candidatos)
    assert r["desconto"] > 0
    assert r["n_candidatos"] == 25


def test_vencedor_destacado_recebe_desconto_menor_que_o_colado():
    """A propriedade central do metodo por destaque.

    A primeira versao deste calculo errava justamente aqui: punia MAIS o
    vencedor destacado que o colado, porque a folga crescia mais rapido que o
    fator de ruido encolhia. Este teste existe pra travar a direcao.
    """
    colados = [{"edge": 0.10 + i * 0.001} for i in range(20)]
    destacado = [{"edge": 0.05 + i * 0.001} for i in range(19)] + [{"edge": 0.40}]

    d_colado = sb.corrigir(colados)["desconto"]
    d_destacado = sb.corrigir(destacado)["desconto"]

    assert d_destacado < d_colado
    assert sb.corrigir(destacado)["folga_1o_2o"] > sb.corrigir(colados)["folga_1o_2o"]


def test_desvio_e_medido_sem_o_vencedor():
    """Incluir o extremo selecionado infla o desvio e faria o vencedor
    justificar a propria penalidade."""
    candidatos = [{"edge": 0.10} for _ in range(9)] + [{"edge": 0.90}]
    r = sb.corrigir(candidatos)
    # Os 9 perdedores sao identicos -> desvio do resto e' zero.
    assert r["desvio"] == 0.0
    assert r["desconto"] == 0.0


def test_desconto_por_destaque_zero_sem_resto():
    assert sb.desconto_por_destaque(0.5, []) == 0.0


def test_correcao_usa_o_menor_dos_dois_metodos():
    """Postura conservadora: descontar de menos custa menos que matar pick boa."""
    candidatos = [{"edge": 0.05 + i * 0.01} for i in range(15)]
    r = sb.corrigir(candidatos)
    assert r["desconto"] == min(r["por_contagem"], r["por_destaque"])


def test_correcao_ignora_candidato_sem_o_campo():
    candidatos = [{"edge": 0.10}, {"edge": None}, {"edge": 0.08}, {}]
    r = sb.corrigir(candidatos)
    assert r["n_candidatos"] == 2


def test_correcao_expoe_o_rastro_para_a_explicacao():
    candidatos = [{"edge": 0.10 + i * 0.005} for i in range(12)]
    r = sb.corrigir(candidatos)
    for chave in ("desconto", "n_candidatos", "desvio", "folga_1o_2o",
                  "por_contagem", "por_destaque", "metodo"):
        assert chave in r


def test_desconto_nunca_e_negativo():
    for n in (2, 5, 30):
        candidatos = [{"edge": 0.1} for _ in range(n)]
        assert sb.corrigir(candidatos)["desconto"] >= 0.0
