"""Valor estatistico dentro da faixa, em vez de casa desalinhada (2026-08-14).

Tres mudancas, medidas contra producao antes de entrar (ver os numeros nos
comentarios de config.py e odds_service.py):

  1. o motor julga a linha pela MEDIANA das casas, nao pela mais generosa --
     a odd da casa mais alta era usada em 18 dos 24 ultimos picks e o premio
     dela ia inteiro pro edge;
  2. a faixa de odd de cada pipeline virou FILTRO em VIP/Dica, nao mais um
     peso de 0.15 que a odd alta atropelava;
  3. dentro da faixa, descer um degrau de linha passa a valer pontos.
"""
import pytest

from services.pick_engine import ranking, market_model
from services.pick_engine.config import (
    PickEngineConfig, DEFAULT_CONFIG, VIP_CONFIG, DICA_CONFIG, ALAVANCAGEM_CONFIG,
)


def _linha(odd, taxa=0.70, edge=0.10, ev=0.15, **extra):
    return {"odd": odd, "taxa_real": taxa, "edge": edge, "ev": ev,
            "amostra": 10, "confidence": 0.80, "bookmakers_count": 3,
            "market_type": "corners", **extra}


# ─────────────────── 1. odd de avaliacao (mediana, nao maxima) ───────────────


def test_avaliacao_usa_a_mediana_das_casas_e_nao_a_mais_generosa():
    entry = {"best_odd": 2.00, "consensus_odd": 1.79, "bookmakers_count": 3}
    assert market_model.evaluation_odd(entry, DEFAULT_CONFIG) == 1.79
    assert market_model.evaluation_odd(entry, PickEngineConfig(odd_evaluation="best")) == 2.00


def test_sem_consenso_no_dict_cai_pra_melhor_odd():
    """Chamadores antigos (e odds gravadas antes de 14/08) nao trazem
    consensus_odd -- o motor nao pode parar por causa disso."""
    assert market_model.evaluation_odd({"best_odd": 1.80}, DEFAULT_CONFIG) == 1.80


def test_edge_encolhe_quando_a_odd_alta_e_de_uma_casa_so():
    """Caso real: Bolivar x Sao Paulo, Escanteios Over 9.5 -- 2.00 na Bet365
    contra 1.57 na outra casa. Com a odd maxima o mercado parecia valer 50%;
    com a mediana ele vale 56%, e 6 pontos de edge somem."""
    caro = {"best_odd": 2.00, "consensus_odd": 1.79, "bookmakers_count": 2}
    taxa = 0.6115
    edge_antigo = market_model.edge_and_ev(
        taxa, 2.00, market_model.implied_prob(2.00))["edge"]
    edge_novo = market_model.edge_and_ev(
        taxa, market_model.evaluation_odd(caro, DEFAULT_CONFIG),
        market_model.resolve_prob_baseline(caro, None, DEFAULT_CONFIG)["prob"])["edge"]
    assert edge_antigo > edge_novo
    assert edge_novo == pytest.approx(0.6115 - 1 / 1.79, abs=1e-3)


def test_no_vig_le_os_dois_lados_pela_mesma_regra_de_preco():
    """Com a melhor odd dos dois lados, cada um podia vir de uma casa
    diferente e a soma das implicitas caia abaixo de 1 -- os DOIS lados
    pareciam baratos ao mesmo tempo. Pela mediana isso nao acontece."""
    over = {"best_odd": 2.10, "consensus_odd": 1.95, "bookmakers_count": 3}
    under = {"best_odd": 2.10, "consensus_odd": 1.95, "bookmakers_count": 3}
    baseline = market_model.resolve_prob_baseline(over, under, DEFAULT_CONFIG)
    assert baseline["source"] == "no_vig"
    assert baseline["prob"] == pytest.approx(0.50, abs=1e-4)


# ─────────────────────── 2. faixa de odd como filtro ────────────────────────


def test_vip_rejeita_linha_acima_do_teto_da_faixa():
    """Lido do teto da config pelo mesmo motivo do teste do piso logo abaixo:
    o numero e' decisao de produto e ja' mudou tres vezes (1.90 -> 1.99 -> 2.00).
    O que o teste protege e' que existe teto e que ele corta."""
    acima = round(VIP_CONFIG.conservative_odd_high + 0.05, 2)
    fora = ranking.evaluate_all_lines([_linha(acima)], VIP_CONFIG)[0]
    assert "fora da faixa" in fora["reject_reason"]


def test_vip_rejeita_linha_abaixo_do_piso_da_faixa():
    """A faixa corta dos DOIS lados, e o piso e' o lado que so' passou a existir
    em 14/08 (antes, `min_odd=1.39` era o unico corte de baixo).

    Lido da config e nao cravado: o piso ja' mudou uma vez (1.50 -> 1.30 em
    28/08), e o teste tem que continuar medindo A REGRA, nao o numero do mes.
    """
    abaixo = round(VIP_CONFIG.conservative_odd_low - 0.05, 2)
    fora = ranking.evaluate_all_lines([_linha(abaixo)], VIP_CONFIG)[0]
    assert fora["reject_reason"], f"odd {abaixo} devia cair pelo piso"
    # O motivo pode ser "fora da faixa" OU "odd abaixo do minimo": desde 28/08
    # os dois cortes coincidem no VIP (min_odd == conservative_odd_low), e essa
    # coincidencia e' desejada -- e' ela que garante que nao existe faixa entre
    # os dois gates por onde uma linha escape. O que o teste protege e' que a
    # linha CAI, e que cai por ODD.
    assert "odd" in fora["reject_reason"]


def test_linha_dentro_da_faixa_passa():
    assert ranking.evaluate_all_lines([_linha(1.70)], VIP_CONFIG)[0]["reject_reason"] is None


def test_faixa_tambem_barra_no_gate_de_aprovacao():
    """select_smart_safe_line tem fallback que ressuscita linha reprovada --
    rank_all_candidates precisa reconferir, senao a linha fora da faixa vira
    pick por esse caminho (o mesmo motivo que ja obrigava reconferir min_odd)."""
    assert ranking.rank_all_candidates([_linha(2.40)], VIP_CONFIG) == []
    assert len(ranking.rank_all_candidates([_linha(1.70)], VIP_CONFIG)) == 1


def test_faixa_desligada_mantem_o_comportamento_antigo():
    """DEFAULT_CONFIG (multipla, faltas, goleiros) nao muda: a faixa segue
    sendo preferencia, nao filtro."""
    assert not DEFAULT_CONFIG.enforce_odd_band
    assert ranking.evaluate_all_lines([_linha(2.00)], DEFAULT_CONFIG)[0]["reject_reason"] is None


def test_cada_pipeline_tem_a_propria_faixa():
    """Os NUMEROS aqui sao decisao de produto e mudam · o que este teste protege
    e' que cada pipeline tenha a SUA, e nao herde a do vizinho por descuido.

    Em 02/09 VIP e Dica passaram a dividir a MESMA faixa (1.45-2.00, decisao do
    usuario) -- o que separa free de VIP hoje e' o `min_confidence` de 0.72 da
    Dica, nao a largura da faixa. A alavancagem e' que ficou sozinha embaixo,
    de proposito: ela e' o complemento dessas duas, entao perdeu o piso.
    """
    assert (VIP_CONFIG.conservative_odd_low, VIP_CONFIG.conservative_odd_high) == (1.45, 2.00)
    assert (DICA_CONFIG.min_odd, DICA_CONFIG.max_odd) == (1.45, 2.00)
    assert DICA_CONFIG.enforce_odd_band
    assert DICA_CONFIG.min_confidence > VIP_CONFIG.min_confidence
    # Alavancagem e' o produto de perna barata: a faixa dela e' a dela, e desde
    # 02/09 ela nao tem piso -- 1.01 e' o menor preco cotado, nao um limiar.
    assert (ALAVANCAGEM_CONFIG.conservative_odd_low,
            ALAVANCAGEM_CONFIG.conservative_odd_high) == (1.01, 1.55)
    assert ALAVANCAGEM_CONFIG.min_odd == 1.01


def test_o_piso_de_sanidade_acompanha_a_faixa_do_vip():
    """`min_odd` e' um gate INDEPENDENTE da faixa (ranking.motivo_de_odd_fora
    testa os dois), entao deixa-lo no default de 1.39 cortaria tudo entre 1.30 e
    1.39 e a faixa nova valeria pela metade -- em silencio, porque o motivo de
    rejeicao diria "odd abaixo do minimo" e nao "fora da faixa"."""
    assert VIP_CONFIG.min_odd <= VIP_CONFIG.conservative_odd_low
    assert VIP_CONFIG.max_odd >= VIP_CONFIG.conservative_odd_high


# ──────────────────── 3. degrau seguro dentro da faixa ──────────────────────


def test_dentro_da_faixa_a_linha_mais_barata_e_a_mais_segura():
    """Lido das BORDAS da config e nao de numeros fixos · a faixa e' decisao de
    produto e ja' mudou uma vez (1.50-1.90 -> 1.30-1.99 em 28/08). O que nao
    muda e' a forma: piso vale 1.0, teto vale menos, e o meio fica no meio."""
    piso = VIP_CONFIG.conservative_odd_low
    teto = VIP_CONFIG.conservative_odd_high
    meio = round((piso + teto) / 2, 2)

    assert ranking._safety_bonus(piso, VIP_CONFIG) == 1.0
    assert ranking._safety_bonus(teto, VIP_CONFIG) == pytest.approx(
        1.0 - VIP_CONFIG.safety_band_tilt, abs=1e-4)
    # Monotona: mais cara dentro da faixa nunca vale mais que mais barata.
    assert (ranking._safety_bonus(piso, VIP_CONFIG)
            > ranking._safety_bonus(meio, VIP_CONFIG)
            > ranking._safety_bonus(teto, VIP_CONFIG))


def test_a_seguranca_nao_salta_ao_sair_da_faixa():
    """A funcao tem que ser continua nas duas bordas -- se ela pulasse pra
    cima logo acima do teto, a linha cara ganharia pontos justamente por
    estar fora."""
    piso = VIP_CONFIG.conservative_odd_low
    teto = VIP_CONFIG.conservative_odd_high

    assert ranking._safety_bonus(teto + 0.01, VIP_CONFIG) < ranking._safety_bonus(teto, VIP_CONFIG)
    assert ranking._safety_bonus(piso - 0.01, VIP_CONFIG) < ranking._safety_bonus(piso, VIP_CONFIG)


def test_pedido_do_usuario_desce_a_linha_quando_a_estatistica_empata():
    """'compensa dar uma baixa pra ser seguro e pegar linha 8.5 por 1.60'.

    Over 8.5 @1.60 com taxa 78% contra Over 9.5 @1.88 com taxa 68% -- antes o
    edge maior da linha 9.5 competia de igual pra igual; agora a mais segura
    vence com folga."""
    linha_85 = _linha(1.60, taxa=0.786, edge=0.16, ev=0.26)
    linha_95 = _linha(1.88, taxa=0.680, edge=0.15, ev=0.28)
    escolhida = ranking.select_smart_safe_line([linha_95, linha_85], VIP_CONFIG)
    assert escolhida["odd"] == 1.60


def test_linha_alta_ainda_vence_se_for_muito_melhor_estatisticamente():
    """A inclinacao e' preferencia, nao proibicao: dentro da faixa, uma taxa
    claramente superior continua ganhando."""
    fraca_barata = _linha(1.55, taxa=0.61, edge=0.05, ev=0.02)
    forte_cara = _linha(1.88, taxa=0.92, edge=0.28, ev=0.40)
    escolhida = ranking.select_smart_safe_line([fraca_barata, forte_cara], VIP_CONFIG)
    assert escolhida["odd"] == 1.88


def test_alavancagem_prefere_a_perna_barata_da_propria_faixa():
    """Com a faixa herdada de 1.50-1.90 (toda acima do teto de 1.55 do
    produto), o termo empurrava a alavancagem pro lado CARO do range."""
    assert (ranking._safety_bonus(1.15, ALAVANCAGEM_CONFIG)
            > ranking._safety_bonus(1.50, ALAVANCAGEM_CONFIG))


def test_alavancagem_alcanca_o_que_o_vip_nao_alcanca():
    """02/09: o piso da alavancagem saiu porque VIP e Dica subiram pra 1.45.
    O ponto nao e' que as faixas nao se toquem (1.45-1.55 e' comum as duas, e
    tudo bem: la' e' perna de combo, aqui e' pick sozinha) -- e' que a
    alavancagem CHEGUE onde as outras duas nao chegam mais."""
    assert ALAVANCAGEM_CONFIG.min_odd < VIP_CONFIG.conservative_odd_low
    assert ALAVANCAGEM_CONFIG.min_odd < DICA_CONFIG.min_odd


def test_pesos_do_line_score_somam_um():
    c = VIP_CONFIG
    total = (c.line_weight_taxa + c.line_weight_edge + c.line_weight_safety
             + c.line_weight_bookmakers + c.line_weight_stability)
    assert total == pytest.approx(1.0, abs=1e-9)
