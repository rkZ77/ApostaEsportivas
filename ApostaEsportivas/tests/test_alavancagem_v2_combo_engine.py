"""Alavancagem V2: o motor de COMBINACAO, separado do motor simples.

O que estes testes protegem nao e' um numero, e' uma pergunta que o motor
antigo nao fazia: "estas pernas continuam boas JUNTAS?". Ate' a V2 a resposta
era sempre sim por construcao -- duas pernas aprovadas individualmente viravam
um bilhete aprovado, com a probabilidade sendo o produto cru e o risco do
bilhete nao existindo como conceito.

Os dois REDs de combinacao do historico estao aqui como caso de teste, cada um
no teste que teria impedido a aposta.
"""
import pytest

from services.pick_engine import combo_engine as ce


def perna(fixture_id, market_type, odd, *, taxa_real=None, confidence=0.80,
          amostra=25, data_quality_score=85.0, risco="BAIXO", direcao="over",
          linha=1.5, scope="total", **extra):
    taxa = taxa_real if taxa_real is not None else min(0.97, round(1.15 / odd, 4))
    return {
        "_fixture": {"fixture_id": fixture_id},
        "market_type": market_type, "market_name": market_type,
        "value_label": f"{direcao.title()} {linha}", "scope": scope,
        "odd": odd, "confidence": confidence, "taxa_real": taxa,
        "edge": round(taxa - (1.0 / odd) + 0.09, 4),
        "ev": round(taxa * odd - 1.0, 4),
        "amostra": amostra, "data_quality_score": data_quality_score,
        "risco": risco, "_direction": direcao, "_line_val": linha,
        **extra,
    }


# ---------------------------------------------------------------------------
# §8  AMOSTRA
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n,classe", [
    (0, "muito_fraca"), (4, "muito_fraca"), (5, "limitada"), (9, "limitada"),
    (10, "razoavel"), (19, "razoavel"), (20, "boa"), (29, "boa"), (30, "forte"),
])
def test_classificacao_de_amostra(n, classe):
    assert ce.classificar_amostra(n)["classe"] == classe


def test_amostra_ausente_nao_e_favoravel():
    """Dado ausente nunca vira credito -- a regra vale no motor inteiro."""
    assert ce.classificar_amostra(None)["classe"] == "muito_fraca"
    assert ce.classificar_amostra(None)["score"] == 0.0


def test_quatro_de_quatro_nao_e_evidencia_forte():
    """§8: 4/4, 5/5 e 6/6 sao amostra muito fraca, por mais redonda que a
    fracao pareca."""
    assert ce.classificar_amostra(4)["score"] == 0.0
    assert ce.classificar_amostra(6)["score"] == 35.0


# ---------------------------------------------------------------------------
# §15 / §16 / §27  CORRELACAO
# ---------------------------------------------------------------------------
def test_mesma_familia_no_mesmo_jogo_e_correlacao_alta():
    par = ce.classificar_correlacao(perna(1, "goals", 1.2), perna(1, "goals", 1.3))
    assert par["nivel"] == ce.ALTA


def test_gols_e_resultado_no_mesmo_jogo_e_correlacao_alta():
    """O buraco que o veto por familia deixava aberto: familias diferentes,
    mesmo jogo, mesma causa. "Over 2.5 gols" + "Casa vence" passava."""
    par = ce.classificar_correlacao(perna(1, "goals", 1.2), perna(1, "result", 1.3))
    assert par["nivel"] == ce.ALTA
    assert "placar" in par["motivo"]


def test_familias_sem_mecanismo_mapeado_no_mesmo_jogo_sao_desconhecidas():
    """§16: sem mecanismo nomeado nao se assume independencia."""
    par = ce.classificar_correlacao(perna(1, "mercado_novo", 1.2),
                                    perna(1, "outro_novo", 1.3))
    assert par["nivel"] == ce.DESCONHECIDA


def test_mesma_familia_em_jogos_diferentes_e_correlacao_media():
    """A ESTRUTURA DOS DOIS REDs DO HISTORICO -- 21/06 (Over 1.5 + Over 0.5 do
    2o tempo) e 23/08 (Under 3.5 + Under 4.5), as quatro pernas `goals`, em
    jogos diferentes. Independentes no gramado, nao no modelo: e' a mesma
    estimativa de gols aplicada duas vezes, e o motor antigo tratava o par como
    totalmente independente.

    MEDIA e nao ALTA de proposito: a terceira combinacao dessa estrutura
    (24/06) foi GREEN, e 1G/2R nao sustenta um veto (§57). O preco e' um
    desconto declarado, nao uma porta fechada."""
    par = ce.classificar_correlacao(perna(1, "goals", 1.2), perna(2, "goals", 1.3))
    assert par["nivel"] == ce.MEDIA


def test_jogos_e_familias_diferentes_e_correlacao_baixa():
    par = ce.classificar_correlacao(perna(1, "goals", 1.2), perna(2, "cards", 1.3))
    assert par["nivel"] == ce.BAIXA


def test_correlacao_do_combo_e_a_do_pior_par():
    """A media esconderia um par ALTO atras de dois pares BAIXOS."""
    legs = [perna(1, "goals", 1.1), perna(1, "result", 1.1), perna(3, "cards", 1.1)]
    assert ce.correlacao_do_combo(legs)["nivel"] == ce.ALTA


def test_sinal_da_dependencia_separa_over_de_under_no_mesmo_jogo():
    positivo = ce.classificar_correlacao(
        perna(1, "goals", 1.2, direcao="over"),
        perna(1, "corners", 1.2, direcao="over"))
    negativo = ce.classificar_correlacao(
        perna(1, "goals", 1.2, direcao="over"),
        perna(1, "corners", 1.2, direcao="under"))
    assert positivo["sinal"] == "positivo"
    assert negativo["sinal"] == "negativo"


# ---------------------------------------------------------------------------
# §30  REDUNDANCIA
# ---------------------------------------------------------------------------
def test_over_1_5_contem_over_0_5():
    """Redundancia: Over 1.5 implica Over 0.5, entao o bilhete e' o Over 1.5
    sozinho, cotado pior.

    Este caso NAO esta' no historico -- o veto por (fixture, familia) ja' o
    impedia. Ele esta' aqui porque o veto antigo so' o pegava por acidente, ao
    comparar familias: bastava a segunda perna cair num `correlation_group`
    diferente (o que aconteceu com "btts" ate' 2026-08-10) pra o par passar e o
    bilhete ser publicado como se fossem dois eventos."""
    motivo = ce.detectar_redundancia(
        perna(1, "goals", 1.28, direcao="over", linha=1.5),
        perna(1, "goals", 1.16, direcao="over", linha=0.5))
    assert motivo is not None
    assert "implica" in motivo


def test_under_mais_baixo_contem_under_mais_alto():
    motivo = ce.detectar_redundancia(
        perna(1, "goals", 1.25, direcao="under", linha=3.5),
        perna(1, "goals", 1.13, direcao="under", linha=4.5))
    assert motivo is not None


def test_linhas_encaixadas_em_jogos_diferentes_nao_sao_redundantes():
    """Redundancia e' sobre o MESMO evento. Over 1.5 no jogo A e Over 0.5 no
    jogo B sao dois eventos -- correlacionados pelo modelo, e' outra coisa."""
    assert ce.detectar_redundancia(
        perna(1, "goals", 1.28, direcao="over", linha=1.5),
        perna(2, "goals", 1.16, direcao="over", linha=0.5)) is None


# ---------------------------------------------------------------------------
# §17 / §18  PROBABILIDADE COMBINADA
# ---------------------------------------------------------------------------
def test_perna_unica_nao_leva_desconto():
    """§3: o motor simples esta' medido e nao se mexe nele. Cobrar da simples
    um desconto que nasceu da multiplicacao mudaria o que ja' funciona."""
    perfis = [ce.validar_individual(perna(1, "goals", 1.45))]
    corr = ce.correlacao_do_combo([perna(1, "goals", 1.45)])
    p = ce.probabilidade_combinada(perfis, corr)
    assert p["raw"] == p["adjusted"]
    assert p["desconto_por_perna"] == 0.0


def test_desconto_e_aplicado_perna_a_perna_nao_no_produto():
    """Onde o desconto entra importa: o vies mora na PERNA. Se cada perna esta'
    otimista em d, o produto de duas esta' otimista em ~2d -- descontar no
    produto trataria o vies como se ele nascesse da multiplicacao."""
    legs = [perna(1, "goals", 1.25, taxa_real=0.90),
            perna(2, "cards", 1.20, taxa_real=0.90)]
    perfis = [ce.validar_individual(l) for l in legs]
    corr = ce.correlacao_do_combo(legs)
    p = ce.probabilidade_combinada(perfis, corr)

    d = p["desconto_por_perna"]
    assert p["raw"] == pytest.approx(0.81, abs=1e-4)
    assert p["adjusted"] == pytest.approx((0.90 - d) ** 2, abs=1e-4)
    # E o resultado e' MENOR que descontar d uma vez do produto -- que e'
    # exatamente a diferenca que o teste existe pra travar.
    assert p["adjusted"] < 0.81 - d


def test_correlacao_media_custa_mais_desconto_que_correlacao_baixa():
    def ajustada(fixture_b, familia_b):
        legs = [perna(1, "goals", 1.25, taxa_real=0.90),
                perna(fixture_b, familia_b, 1.20, taxa_real=0.90)]
        perfis = [ce.validar_individual(l) for l in legs]
        return ce.probabilidade_combinada(perfis, ce.correlacao_do_combo(legs))

    baixa = ajustada(2, "cards")
    media = ajustada(2, "goals")
    assert media["desconto_por_perna"] > baixa["desconto_por_perna"]
    assert media["adjusted"] < baixa["adjusted"]


# ---------------------------------------------------------------------------
# §14  RISCO DO BILHETE
# ---------------------------------------------------------------------------
def test_risco_do_bilhete_nunca_e_melhor_que_o_da_pior_perna():
    legs = [perna(1, "goals", 1.25, risco="BAIXO"),
            perna(2, "cards", 1.20, risco="MEDIO")]
    perfis = [ce.validar_individual(l) for l in legs]
    risco = ce.risco_combinado(perfis, ce.correlacao_do_combo(legs))
    assert risco["nivel"] in ("MEDIO", "ALTO")


def test_correlacao_alta_leva_o_bilhete_a_risco_alto():
    legs = [perna(1, "goals", 1.25), perna(1, "result", 1.20)]
    perfis = [ce.validar_individual(l) for l in legs]
    risco = ce.risco_combinado(perfis, ce.correlacao_do_combo(legs))
    assert risco["nivel"] == "ALTO"


# ---------------------------------------------------------------------------
# §13 / §25  GATES DA COMBINACAO
# ---------------------------------------------------------------------------
def test_duas_pernas_de_risco_alto_nao_viram_uma_dupla():
    """§13: a combinacao amplifica o risco. Duas incertezas multiplicadas nao
    viram uma certeza, por mais que o EV combinado pareca alto."""
    legs = [perna(1, "goals", 1.25, risco="ALTO"), perna(2, "cards", 1.20, risco="ALTO")]
    resultado = ce.avaliar(legs, 1.50)
    assert resultado["decision"] == "NO_PICK"
    assert resultado["gates"]["individual_quality"] is False


def test_perna_de_risco_alto_ainda_pode_ser_uma_simples():
    """§35: uma pick excelente como simples pode ser uma peca de bilhete ruim,
    e o contrario tambem vale. As duas respostas sao independentes."""
    perfil = ce.validar_individual(perna(1, "goals", 1.45, risco="ALTO"))
    assert perfil["simples_ok"] is True
    assert perfil["combo_ok"] is False


def test_amostra_curta_barra_a_perna_do_combo_mas_nao_da_simples():
    perfil = ce.validar_individual(perna(1, "goals", 1.45, amostra=6))
    assert perfil["simples_ok"] is True
    assert perfil["combo_ok"] is False
    assert any("amostra" in m for m in perfil["motivos_combo"])


def test_ev_negativo_reprova_nos_dois_destinos():
    """§6: confidence alta e score alto nao compensam EV negativo."""
    ruim = perna(1, "goals", 1.45, taxa_real=0.60, confidence=0.95)
    perfil = ce.validar_individual(ruim)
    assert perfil["simples_ok"] is False
    assert ce.avaliar([ruim], 1.45)["decision"] == "NO_PICK"


def test_gate_de_correlacao_desconhecida_reprova_por_padrao():
    """§16: correlacao desconhecida e' penalizada, nunca assumida
    independente."""
    legs = [perna(1, "mercado_novo", 1.25), perna(1, "outro_novo", 1.20)]
    resultado = ce.avaliar(legs, 1.50)
    assert resultado["decision"] == "NO_PICK"
    assert resultado["gates"]["correlation"] is False


def test_mesmo_jogo_com_sinal_negativo_nao_sai():
    """§27: no mesmo jogo, direcoes opostas fazem o produto SUPERESTIMAR -- o
    erro que quebra bilhete."""
    legs = [perna(1, "goals", 1.25, direcao="over"),
            perna(1, "corners", 1.20, direcao="under")]
    resultado = ce.avaliar(legs, 1.50)
    assert resultado["decision"] == "NO_PICK"
    assert resultado["gates"]["same_fixture"] is False


# ---------------------------------------------------------------------------
# §32 / §46  CONTRADICOES
# ---------------------------------------------------------------------------
def test_confianca_de_90_com_amostra_curta_e_contradicao():
    """§46: nunca permitir confidence >= 90% so' porque a fracao saiu redonda.
    Foi o perfil exato das duas pernas do RED de 23/08 (0.92 e 0.9148)."""
    achados = ce.detectar_contradicoes(perna(1, "goals", 1.25, confidence=0.92, amostra=8))
    assert any(c["tipo"] == "confianca_alta_amostra_curta" for c in achados)


def test_confianca_de_90_com_amostra_cheia_nao_e_contradicao():
    achados = ce.detectar_contradicoes(perna(1, "goals", 1.25, confidence=0.92, amostra=34))
    assert not any(c["tipo"] == "confianca_alta_amostra_curta" for c in achados)


def test_projecao_contra_a_linha_e_contradicao():
    leg = perna(1, "goals", 1.25, projecao={"classe": "contra_a_linha",
                                            "valor": 1.2, "margem_em_sigmas": -0.4})
    achados = ce.detectar_contradicoes(leg)
    assert any(c["tipo"] == "projecao_contra_a_linha" for c in achados)


def test_duas_contradicoes_graves_bloqueiam_o_bilhete():
    ruim = perna(1, "goals", 1.25, confidence=0.95, amostra=8,
                 projecao={"classe": "contra_a_linha", "valor": 1.2,
                           "margem_em_sigmas": -0.4})
    resultado = ce.avaliar([ruim, perna(2, "cards", 1.20)], 1.50)
    assert resultado["decision"] == "NO_PICK"
    assert resultado["gates"]["contradiction"] is False


# ---------------------------------------------------------------------------
# §39 / §40  TRES SELECOES
# ---------------------------------------------------------------------------
def test_tripla_exige_correlacao_baixa_em_todos_os_pares():
    legs = [perna(1, "goals", 1.15), perna(2, "goals", 1.12), perna(3, "cards", 1.10)]
    resultado = ce.avaliar(legs, 1.4168)
    assert resultado["decision"] == "NO_PICK"
    assert resultado["gates"]["three_legs"] is False


def test_tripla_forte_de_familias_diferentes_passa():
    legs = [perna(1, "goals", 1.15), perna(2, "corners", 1.12), perna(3, "cards", 1.10)]
    resultado = ce.avaliar(legs, 1.4168)
    assert resultado["decision"] == "PICK"
    assert resultado["gates"]["three_legs"] is True


def test_tripla_com_amostra_de_dupla_nao_passa():
    """§39: o que basta pra uma dupla nao basta pra uma tripla."""
    legs = [perna(1, "goals", 1.15, amostra=12),
            perna(2, "corners", 1.12), perna(3, "cards", 1.10)]
    assert ce.avaliar(legs, 1.4168)["gates"]["three_legs"] is False


# ---------------------------------------------------------------------------
# §19 / §20  SCORE
# ---------------------------------------------------------------------------
def test_score_nao_pontua_preco():
    """Odd e EV eliminam nos gates e nunca ordenam -- a regra permanente do
    motor, e o §20 do proprio pedido ("nao selecionar pelo maior EV")."""
    assert ce.DEFAULT_COMBO_CONFIG.peso_ev == 0.0
    legs = [perna(1, "goals", 1.25), perna(2, "cards", 1.20)]
    avaliacao = ce.avaliar(legs, 1.50)
    assert avaliacao["combined"]["score_weights"]["ev"] == 0.0


def test_pesos_sao_renormalizados():
    legs = [perna(1, "goals", 1.25), perna(2, "cards", 1.20)]
    pesos = ce.avaliar(legs, 1.50)["combined"]["score_weights"]
    assert sum(pesos.values()) == pytest.approx(1.0, abs=1e-3)


def test_bilhete_desequilibrado_perde_para_o_equilibrado():
    """§60: duas pernas medianas nao viram "uma aposta forte" por soma. Metade
    do termo de qualidade e' a PIOR perna."""
    equilibrado = [perna(1, "goals", 1.25, confidence=0.82),
                   perna(2, "cards", 1.20, confidence=0.82)]
    desequilibrado = [perna(3, "goals", 1.25, confidence=0.95),
                      perna(4, "cards", 1.20, confidence=0.69)]
    a = ce.avaliar(equilibrado, 1.50)["combined"]["score"]
    b = ce.avaliar(desequilibrado, 1.50)["combined"]["score"]
    assert a > b


# ---------------------------------------------------------------------------
# §50 / §51  O DOCUMENTO DA DECISAO
# ---------------------------------------------------------------------------
def test_engine_debug_tem_a_forma_do_paragrafo_50():
    legs = [perna(1, "goals", 1.25), perna(2, "cards", 1.20)]
    doc = ce.avaliar(legs, 1.50)

    assert doc["type"] == "dupla"
    assert len(doc["legs"]) == 2
    for leg in doc["legs"]:
        for campo in ("market", "odd", "probability", "confidence", "EV",
                      "risk", "data_quality", "sample_quality",
                      "probability_raw", "probability_model",
                      "probability_calibrated", "fair_odd", "edge",
                      "projection_margin", "convergence"):
            assert campo in leg, campo
    for campo in ("odd", "probability_raw", "probability_adjusted", "fair_odd",
                  "edge", "EV", "risk", "correlation", "diversification",
                  "score", "implied_probability"):
        assert campo in doc["combined"], campo
    for gate in ("individual_quality", "EV", "edge", "probability", "risk",
                 "correlation", "redundancy", "same_fixture", "contradiction"):
        assert gate in doc["gates"], gate
    assert doc["decision"] in ("PICK", "NO_PICK")


def test_no_pick_sempre_carrega_o_motivo():
    """§51: o motivo E' o produto. Um dia sem alavancagem sem motivo gravado e'
    um silencio, e silencio nao se audita."""
    legs = [perna(1, "goals", 1.25), perna(1, "result", 1.20)]
    doc = ce.avaliar(legs, 1.50)
    assert doc["decision"] == "NO_PICK"
    assert doc["reasons"]


def test_ev_combinado_sai_da_probabilidade_ajustada():
    """§24: EV sobre a AJUSTADA, nunca sobre a bruta. A media dos EVs das
    pernas (o que se fazia antes da correcao de 08/08) nao tem significado
    nenhum num bilhete que so' paga se tudo bater."""
    legs = [perna(1, "goals", 1.25), perna(2, "cards", 1.20)]
    doc = ce.avaliar(legs, 1.50)
    comb = doc["combined"]
    assert comb["EV"] == pytest.approx(comb["probability_adjusted"] * 1.50 - 1.0, abs=1e-4)
    assert comb["probability_adjusted"] < comb["probability_raw"]


def test_edge_combinado_compara_com_a_implicita_da_odd_do_bilhete():
    """§23. A implicita ignora a margem da casa de proposito: sem tirar o vig
    ela sai alta, o edge sai baixo, e o erro cai pro lado conservador."""
    legs = [perna(1, "goals", 1.25), perna(2, "cards", 1.20)]
    comb = ce.avaliar(legs, 1.50)["combined"]
    assert comb["implied_probability"] == pytest.approx(1 / 1.50, abs=1e-4)
    assert comb["edge"] == pytest.approx(
        comb["probability_adjusted"] - comb["implied_probability"], abs=1e-4)


# ---------------------------------------------------------------------------
# §52 / §53  A ESCOLHA
# ---------------------------------------------------------------------------
def test_combo_so_vence_a_simples_com_probabilidade_maior():
    """A faixa e' do TOTAL, entao dupla e simples pagam o mesmo. Trocar uma
    pela outra so' se justifica com probabilidade maior -- e por uma margem,
    porque a estimativa do combo e' a menos confiavel das duas."""
    simples = ce.avaliar([perna(1, "goals", 1.45, taxa_real=0.88)], 1.45)
    dupla = ce.avaliar([perna(2, "goals", 1.25), perna(3, "cards", 1.20)], 1.50)
    assert simples["decision"] == dupla["decision"] == "PICK"

    escolhida = ce.escolher([simples, dupla])
    assert len(escolhida["legs"]) == 1

    simples_fraca = ce.avaliar([perna(1, "goals", 1.45, taxa_real=0.75)], 1.45)
    escolhida = ce.escolher([simples_fraca, dupla])
    assert len(escolhida["legs"]) == 2


def test_sem_simples_na_faixa_o_combo_sai_sozinho():
    """A razao original do formato existir: em 30/07 a melhor perna do dia
    estava a 1.39 contra um piso de 1.40, e o dia ficou sem produto por um
    centavo."""
    dupla = ce.avaliar([perna(1, "goals", 1.25), perna(2, "cards", 1.20)], 1.50)
    escolhida = ce.escolher([dupla])
    assert len(escolhida["legs"]) == 2
    assert "nenhuma simples" in escolhida["escolha"]


def test_nada_aprovado_devolve_none():
    """§51/§52: NO_PICK e' resultado normal. O motor nao precisa entregar
    alavancagem todo dia."""
    ruim = ce.avaliar([perna(1, "goals", 1.45, taxa_real=0.55)], 1.45)
    assert ce.escolher([ruim]) is None
