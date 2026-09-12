"""A camada V2 do motor ao vivo: historico por mando, qualidade de dado,
regime, contradicao e as cinco portas novas.

CADA TESTE PRENDE UM DEFEITO NOMEADO DA AUDITORIA DE 2026-09-11
---------------------------------------------------------------
1. baseline por camadas que se SOBRESCREVEM, sem combinacao e sem recencia
2. `tendencia = INDEFINIDA` saindo do denominador da convergencia, ou seja,
   "nao ha evidencia" aumentando a convergencia relativa do que sobrou
3. renormalizacao de peso (pressao e convergencia) sem custo nenhum
4. nada distinguindo BAIXA PRODUCAO de BAIXA CONVERSAO
5. contradicao medida so' entre sinais ao vivo, nunca entre historico e campo
6. projecao colada na linha descontando confianca mas nunca reprovando
7. EV decidindo sozinho, sem desconto por qualidade da leitura
"""
import pytest

from services.pick_engine_live import (
    contradiction_model, data_quality, history_model, orchestrator as orq,
    regime_model, signal_score,
)
from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG, LiveEngineConfig
from dataclasses import replace


# ─────────────────────────────────────────────────────────────────────────
# 1 · HISTORICO: janelas, recencia e combinacao ponderada
# ─────────────────────────────────────────────────────────────────────────
def test_recencia_inclina_a_media_sem_sequestrar():
    """Jogo recente pesa mais -- mas a meia-vida e' longa de proposito, pra um
    unico jogo estranho nao virar o baseline (o overfitting que o pedido pedia
    pra evitar)."""
    serie = [14, 6, 6, 6, 6]          # o mais recente e' o fora da curva
    media = history_model.media_com_recencia(serie, 5)

    assert media["media_simples"] == 7.6
    assert media["valor"] > media["media_simples"]      # inclinou pro recente
    assert media["valor"] < 9.0                          # e nao sequestrou


def test_ausencia_nao_vira_zero_nem_desloca_a_posicao():
    """Jogo sem aquela estatistica sai da media daquela familia. Nao entra como
    zero (inflaria todo Under) e nao encurta a fila (faria jogo antigo se
    passar por recente)."""
    com_buraco = history_model.media_com_recencia([10, None, 10, 10], 4)
    sem_buraco = history_model.media_com_recencia([10, 10, 10], 3)

    assert com_buraco["n"] == 3
    assert com_buraco["valor"] == pytest.approx(10.0)
    assert com_buraco["valor"] == pytest.approx(sem_buraco["valor"])


def test_amostra_curta_nao_vira_componente():
    """Dois jogos no mando nao produzem um `last5`. O componente some e a
    cobertura registra que sumiu -- ele nao e' preenchido com a liga."""
    comps = history_model.componentes_do_lado(
        serie_contexto=[9, 11], serie_geral=[9, 11], baseline_liga=10.2)

    assert "last5_contexto" not in comps
    assert "temporada_contexto" not in comps
    assert comps["liga"]["valor"] == 10.2

    combinado = history_model.combinar(comps)
    assert combinado["cobertura"] == pytest.approx(0.10)   # so' a liga
    assert "last5_contexto" in combinado["ausentes"]


def test_o_baseline_combina_as_camadas_em_vez_de_substituir():
    """O DEFEITO 1. Antes, a camada de mando SOBRESCREVIA a media geral: 5
    jogos apagavam 20. Agora as duas entram na mesma conta, com peso."""
    contexto = [7.0] * 12      # o mando diz 7
    geral = [12.0] * 20        # a media geral do time diz 12
    comps = history_model.componentes_do_lado(contexto, geral, baseline_liga=10.2)
    combinado = history_model.combinar(comps)

    assert combinado["cobertura"] == pytest.approx(1.0)
    # 80% do peso e' o mando (7), 10% o geral (12), 10% a liga (10.2)
    assert combinado["valor"] == pytest.approx(0.8 * 7 + 0.1 * 12 + 0.1 * 10.2, abs=0.01)
    assert combinado["valor"] < 8.0        # o mando manda
    assert combinado["valor"] > 7.0        # e o resto nao sumiu


def test_um_lado_so_vale_com_metade_da_cobertura():
    casa = history_model.componentes_do_lado([9] * 12, [9] * 12, 10.2)
    combinado = history_model.baseline_do_confronto(casa, {}, None)

    assert combinado["lados_disponiveis"] == 1
    assert combinado["cobertura"] == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────
# 2 · HISTORICAL ALIGNMENT
# ─────────────────────────────────────────────────────────────────────────
def test_alinhamento_e_o_exemplo_do_pedido():
    """Under 9 escanteios com historico de 7.5: fortemente favoravel.
    O mesmo Under com historico de 11.2: contra."""
    favoravel = history_model.historical_alignment(7.5, 9.0, "under", "corners")
    contra = history_model.historical_alignment(11.2, 9.0, "under", "corners")

    assert favoravel["alinhamento"] > 0.60
    assert contra["alinhamento"] < 0.40
    assert favoravel["rotulo"] in ("FAVORAVEL", "FORTEMENTE_FAVORAVEL")


def test_alinhamento_e_normalizado_pela_dispersao_da_familia():
    """A mesma distancia ABSOLUTA da linha significa coisas diferentes em gols
    e em escanteios -- sem normalizar, escanteio pareceria sempre mais alinhado
    so' por ter numero maior."""
    gols = history_model.historical_alignment(3.2, 2.5, "over", "goals")
    escanteios = history_model.historical_alignment(10.9, 10.2, "over", "corners")

    assert gols["alinhamento"] > escanteios["alinhamento"]


def test_historico_na_linha_e_exatamente_neutro():
    neutro = history_model.historical_alignment(9.5, 9.5, "over", "corners")
    assert neutro["alinhamento"] == pytest.approx(0.5)
    assert neutro["rotulo"] == "NEUTRO"


def test_sem_historico_o_alinhamento_nao_inventa_numero():
    vazio = history_model.historical_alignment(None, 9.5, "over", "corners")
    assert vazio["disponivel"] is False
    assert vazio["alinhamento"] is None


# ─────────────────────────────────────────────────────────────────────────
# 3 · INDEFINIDA NAO E' NEUTRO  (o defeito 2)
# ─────────────────────────────────────────────────────────────────────────
def _conv(tendencia, janelas, **kw):
    return signal_score.convergencia(
        direcao="over", familia="corners",
        estado={"minuto": 60, "diferenca_gols": 0},
        pressao={"total": 0.70, "nivel_total": "ALTA",
                 "home": {"peso_coberto": 0.9}, "away": {"peso_coberto": 0.9}},
        ritmo={"score": 1.30}, tendencia=tendencia, janelas=janelas,
        taxa_estimada_min=0.12, **kw)


def test_tendencia_indefinida_puxa_a_convergencia_pro_neutro():
    """O DEFEITO 2. Antes, INDEFINIDA saia do denominador e os sinais que
    sobravam definiam 100% do score -- entao NAO TER leitura anterior AUMENTAVA
    a convergencia relativa. Agora ela mantem o peso e contribui zero."""
    definida = _conv({"rotulo": "ACELERANDO", "variacao": 0.4},
                     {"principal": {"por_minuto": 0.18}})
    indefinida = _conv({"rotulo": "INDEFINIDA"},
                       {"principal": {"por_minuto": 0.18}})

    assert indefinida["score"] < definida["score"]
    assert "tendencia" in indefinida["criticos_ausentes"]
    assert indefinida["cobertura_real"] < 1.0


def test_sem_evidencia_nao_e_evidencia_contraria():
    """A correcao para no lugar certo: INDEFINIDA puxa pro neutro (0.5), nao
    pro lado oposto. Um sinal ausente nao pode CONTRADIZER o pick."""
    indefinida = _conv({"rotulo": "INDEFINIDA"}, {"principal": {"por_minuto": 0.18}})

    posicoes = {s["sinal"]: s["posicao"] for s in indefinida["sinais"]}
    assert posicoes["tendencia"] == "sem_evidencia"
    assert indefinida["contra"] == 0          # nao conta como sinal contrario
    assert indefinida["score"] > 0.5          # os sinais reais ainda mandam


def test_ausencia_do_provedor_continua_renormalizando():
    """A correcao NAO foi generalizada: xG nao publicado (ausencia do provedor,
    nao do motor) continua saindo do denominador. Sao coisas diferentes."""
    conv = _conv({"rotulo": "ESTAVEL"}, {"principal": {"por_minuto": 0.12}})
    fora = [s for s in conv["sinais"] if not s["disponivel"]]

    assert any(s["sinal"] == "qualidade_da_chance" and not s["penaliza"] for s in fora)


def test_o_historico_entra_na_convergencia():
    alinhado = _conv({"rotulo": "ESTAVEL"}, {"principal": {"por_minuto": 0.12}},
                     alinhamento_historico={"disponivel": True, "alinhamento": 0.95})
    contra = _conv({"rotulo": "ESTAVEL"}, {"principal": {"por_minuto": 0.12}},
                   alinhamento_historico={"disponivel": True, "alinhamento": 0.05})

    assert alinhado["score"] > contra["score"]
    assert alinhado["a_favor"] > contra["a_favor"]


# ─────────────────────────────────────────────────────────────────────────
# 4 · DATA COVERAGE  (o defeito 3)
# ─────────────────────────────────────────────────────────────────────────
def _info(disponivel=True, tendencia="ACELERANDO", janela=True):
    return {
        "disponivel": disponivel,
        "motivo": None if disponivel else "estatistica nao publicada pelo provedor",
        "tendencia": {"rotulo": tendencia},
        "janelas": {"principal": {"por_minuto": 0.15}} if janela else {},
    }


_PRESSAO_CHEIA = {"total": 0.6, "home": {"peso_coberto": 1.0},
                  "away": {"peso_coberto": 1.0}}


def test_folha_completa_e_excelente():
    q = data_quality.cobertura(
        _info(), _PRESSAO_CHEIA, {"nivel": "FRESH"},
        historico={"cobertura": 1.0}, prob_mercado=0.55)

    assert q["coverage"] == pytest.approx(1.0)
    assert q["classe"] == "EXCELENTE"
    assert q["missing"] == []


def test_pressao_pela_metade_entra_pela_metade():
    """O DEFEITO 3. Pressao feita de 2 dos 7 componentes saia com a mesma cara
    de uma feita de 7. Agora ela entra com a fracao que tem."""
    cheia = data_quality.cobertura(_info(), _PRESSAO_CHEIA, {"nivel": "FRESH"},
                                   {"cobertura": 1.0}, 0.55)
    parcial = data_quality.cobertura(
        _info(), {"total": 0.6, "home": {"peso_coberto": 0.3},
                  "away": {"peso_coberto": 0.3}},
        {"nivel": "FRESH"}, {"cobertura": 1.0}, 0.55)

    assert parcial["coverage"] < cheia["coverage"]
    assert any("pressao parcial" in m for m in parcial["missing"])


def test_tendencia_indefinida_custa_cobertura():
    q = data_quality.cobertura(_info(tendencia="INDEFINIDA"), _PRESSAO_CHEIA,
                               {"nivel": "FRESH"}, {"cobertura": 1.0}, 0.55)

    assert q["parciais"]["tendencia"] == 0.0
    assert any("INDEFINIDA" in m for m in q["missing"])


def test_cobertura_cheia_nao_premia():
    """Dado completo e' o esperado, nao um bonus: o fator maximo e' 1.0."""
    assert data_quality.fator_de_confianca(1.0) == 1.0
    assert data_quality.fator_de_confianca(0.0) == data_quality.FATOR_MINIMO
    assert data_quality.fator_de_confianca(0.7) < 1.0


# ─────────────────────────────────────────────────────────────────────────
# 5 · REGIME: producao x conversao  (o defeito 4)
# ─────────────────────────────────────────────────────────────────────────
def test_baixa_producao_e_baixa_conversao_sao_estados_diferentes():
    """O DEFEITO 4. As duas partidas tem POUCO GOL aos 60 minutos, e o motor
    residual lia as duas como Under. Sao jogos opostos."""
    travado = regime_model.regime(
        {"minuto": 60, "goals_total": 0, "xg_home": 0.2, "xg_away": 0.1,
         "diferenca_gols": 0},
        pressao={"total": 0.30, "home": {"peso_coberto": 1.0},
                 "away": {"peso_coberto": 1.0}},
        ritmo={"score": 0.60}, eventos={}, familia="goals")

    criando = regime_model.regime(
        {"minuto": 60, "goals_total": 0, "xg_home": 1.3, "xg_away": 0.9,
         "diferenca_gols": 0},
        pressao={"total": 0.75, "home": {"peso_coberto": 1.0},
                 "away": {"peso_coberto": 1.0}},
        ritmo={"score": 0.70}, eventos={}, familia="goals")

    assert travado["estado"] == regime_model.LOW_ACTIVITY
    assert criando["estado"] == regime_model.CONVERSION_LOW


def test_regime_sem_insumo_nao_inventa_rotulo():
    vazio = regime_model.regime({"minuto": 40}, None, None, None, "fouls")
    assert vazio["estado"] == regime_model.INDEFINIDO
    assert vazio["confianca"] == 0.0


def test_conversao_nao_e_definida_para_cartao():
    """Cartao nao e' convertido de nada. Devolver um indice aqui seria inventar."""
    conv = regime_model.conversao({"minuto": 50}, "cards")
    assert conv["disponivel"] is False


def test_regime_cedo_vale_menos():
    cedo = regime_model.regime(
        {"minuto": 18, "goals_total": 0, "xg_home": 1.4, "xg_away": 1.0},
        {"total": 0.7, "home": {"peso_coberto": 1.0}, "away": {"peso_coberto": 1.0}},
        {"score": 0.7}, {}, "goals")
    tarde = regime_model.regime(
        {"minuto": 70, "goals_total": 0, "xg_home": 1.4, "xg_away": 1.0},
        {"total": 0.7, "home": {"peso_coberto": 1.0}, "away": {"peso_coberto": 1.0}},
        {"score": 0.7}, {}, "goals")

    assert cedo["confianca"] < tarde["confianca"]


# ─────────────────────────────────────────────────────────────────────────
# 6 · CONTRADICAO  (o defeito 5)
# ─────────────────────────────────────────────────────────────────────────
def test_historico_e_ao_vivo_em_lados_opostos_da_linha():
    """O DEFEITO 5. A contagem de sinais so' via briga ENTRE SINAIS AO VIVO --
    historico contra campo nunca aparecia em lugar nenhum."""
    alinhamento = history_model.historical_alignment(12.5, 9.5, "under", "corners")
    c = contradiction_model.contradicao(
        alinhamento=alinhamento, projecao=8.0, linha=9.5, direcao="under",
        regime=None, conv={"a_favor": 4, "contra": 0})

    assert c["score"] > 0.3
    assert any("lados opostos" in r for r in c["reasons"])


def test_lados_do_confronto_discordando_e_contradicao():
    """Mandante 7.2 em casa e visitante 12.9 fora produzem uma media de 10 que
    nao descreve nenhum dos dois."""
    alinhamento = history_model.historical_alignment(
        10.05, 9.5, "over", "corners", lado_casa=7.2, lado_fora=12.9)
    c = contradiction_model.contradicao(
        alinhamento=alinhamento, projecao=10.4, linha=9.5, direcao="over",
        regime=None, conv={"a_favor": 4, "contra": 0})

    assert any("discordam" in r for r in c["reasons"])


def test_under_num_jogo_que_criou_e_nao_converteu():
    c = contradiction_model.contradicao(
        alinhamento=None, projecao=1.4, linha=2.5, direcao="under",
        regime={"estado": regime_model.CONVERSION_LOW, "confianca": 0.9},
        conv={"a_favor": 3, "contra": 0})

    assert c["score"] >= 0.85
    assert any("converteu pouco" in r for r in c["reasons"])


def test_regime_incerto_nao_derruba_pick_como_se_fosse_leitura_completa():
    forte = contradiction_model.contradicao(
        None, 1.4, 2.5, "under",
        {"estado": regime_model.CONVERSION_LOW, "confianca": 1.0}, None)
    fraco = contradiction_model.contradicao(
        None, 1.4, 2.5, "under",
        {"estado": regime_model.CONVERSION_LOW, "confianca": 0.2}, None)

    assert fraco["score"] < forte["score"]


def test_tudo_alinhado_nao_produz_contradicao():
    alinhamento = history_model.historical_alignment(11.5, 9.5, "over", "corners",
                                                     lado_casa=11.2, lado_fora=11.8)
    c = contradiction_model.contradicao(
        alinhamento=alinhamento, projecao=11.0, linha=9.5, direcao="over",
        regime={"estado": regime_model.NORMAL, "confianca": 0.8},
        conv={"a_favor": 5, "contra": 0}, divergencia_modelo=0.06)

    assert c["score"] == 0.0
    assert c["reasons"] == []


# ─────────────────────────────────────────────────────────────────────────
# 7 · EV AJUSTADO  (o defeito 7)
# ─────────────────────────────────────────────────────────────────────────
def _ajuste(cobertura, contradicao, alinhamento, ev=0.20):
    return orq.ev_ajustado(
        ev, {"coverage": cobertura}, {"score": contradicao},
        {"alinhamento": alinhamento})


def test_ev_ajustado_nunca_infla():
    """Confirmacao perfeita devolve fator 1.0, nao 1.3. Inflar EV por
    confirmacao e' como se produz o pick que parece otimo no log."""
    perfeito = _ajuste(1.0, 0.0, 1.0)
    assert perfeito["fator"] == pytest.approx(1.0)
    assert perfeito["adjusted_ev"] == pytest.approx(0.20)


def test_ev_alto_com_leitura_ruim_deixa_de_ser_suficiente():
    """A regra do pedido: EV +20% com cobertura baixa, historico contra e
    contradicao alta nao e' a mesma oportunidade que EV +20% limpo."""
    ruim = _ajuste(0.72, 0.55, 0.20)
    # Os tres descontos juntos cortam quase metade do EV declarado.
    assert ruim["fator"] < 0.55
    assert ruim["adjusted_ev"] < 0.55 * _ajuste(1.0, 0.0, 1.0)["adjusted_ev"]


def test_ev_negativo_passa_intacto():
    """Descontar EV negativo o deixaria MENOS negativo -- um desconto
    premiando um candidato ruim."""
    assert _ajuste(0.5, 0.9, 0.1, ev=-0.10)["adjusted_ev"] == pytest.approx(-0.10)


def test_sem_historico_o_ev_nao_e_punido_duas_vezes():
    """A ausencia ja' custou na cobertura; cobrar de novo no alinhamento seria
    o mesmo buraco pago duas vezes."""
    assert _ajuste(0.85, 0.0, None)["fator_alinhamento"] == 1.0


# ─────────────────────────────────────────────────────────────────────────
# 8 · AS CINCO PORTAS, E O MODO SOMBRA
# ─────────────────────────────────────────────────────────────────────────
def _portas(config=DEFAULT_LIVE_CONFIG, **kw):
    base = dict(familia="corners", direcao="over",
                qualidade={"coverage": 0.95, "missing": []},
                contradicao={"score": 0.0, "reasons": []},
                alinhamento={"alinhamento": 0.75, "rotulo": "FAVORAVEL",
                             "baseline_historico": 11.0, "linha": 9.5},
                distancia=1.4, ev_ajustado_valor=0.12)
    base.update(kw)
    return orq._gates_v2(config, **base)


def test_sem_defeito_nenhuma_porta_reprova():
    assert _portas() == []


@pytest.mark.parametrize("mudanca,trecho", [
    ({"qualidade": {"coverage": 0.55, "missing": ["tendencia INDEFINIDA"]}},
     "cobertura de dados"),
    ({"contradicao": {"score": 0.80, "reasons": ["historico contra"]}},
     "contradicao"),
    ({"alinhamento": {"alinhamento": 0.12, "rotulo": "FORTEMENTE_CONTRA",
                      "baseline_historico": 6.0, "linha": 9.5}},
     "historico FORTEMENTE_CONTRA"),
    ({"distancia": 0.10}, "margem minima"),
    ({"ev_ajustado_valor": 0.01}, "EV ajustado"),
])
def test_cada_porta_reprova_pelo_seu_motivo(mudanca, trecho):
    motivos = _portas(**mudanca)
    assert any(trecho in m for m in motivos), motivos


def test_modo_sombra_calcula_tudo_e_nao_reprova_nada():
    """A valvula de seguranca. Este projeto ja' desligou o motor ao vivo sem
    querer trocando uma formula por uma mais correta (ver
    config.confianca_minima) -- com `v2_enforce=False` as portas medem e nao
    cortam, e o rastro continua completo."""
    sombra = replace(DEFAULT_LIVE_CONFIG, v2_enforce=False)
    tudo_errado = dict(
        qualidade={"coverage": 0.10, "missing": ["tudo"]},
        contradicao={"score": 1.0, "reasons": ["tudo contra"]},
        alinhamento={"alinhamento": 0.01, "rotulo": "FORTEMENTE_CONTRA",
                     "baseline_historico": 3.0, "linha": 9.5},
        distancia=0.01, ev_ajustado_valor=-0.50)

    assert _portas(config=sombra, **tudo_errado) == []
    assert len(_portas(config=DEFAULT_LIVE_CONFIG, **tudo_errado)) == 5


def test_alinhamento_minimo_nao_exige_confirmacao_do_historico():
    """O motor ao vivo existe pra achar o jogo que esta' se comportando
    diferente do que os dois times costumam fazer. A porta corta o historico
    FORTEMENTE contra, nao o historico neutro."""
    neutro = {"alinhamento": 0.50, "rotulo": "NEUTRO",
              "baseline_historico": 9.5, "linha": 9.5}
    assert _portas(alinhamento=neutro) == []


def test_familia_sem_margem_configurada_nao_reprova_por_margem():
    """Familia nova sem entrada em `margem_minima_por_familia` nao pode ser
    cortada por um limiar que ninguem escolheu pra ela."""
    assert _portas(familia="btts", distancia=0.01) == []


# ─────────────────────────────────────────────────────────────────────────
# 9 · COBERTURA DE FIACAO · o teste que a V2 precisa ter desde o dia 1
# ─────────────────────────────────────────────────────────────────────────
def test_toda_familia_configurada_tem_extrator_de_total_historico():
    """Mesmo espirito do teste de `CHAVE_DO_ESTADO`: familia ligada no config
    sem extrator historico nasce sem baseline V2, em silencio."""
    from engine_pipelines.live_pipeline import TOTAL_DA_FAMILIA

    faltando = [f for f in DEFAULT_LIVE_CONFIG.familias if f not in TOTAL_DA_FAMILIA]
    assert faltando == [], f"familia sem extrator historico: {faltando}"


def test_os_pesos_da_convergencia_somam_um():
    assert sum(signal_score.PESOS.values()) == pytest.approx(1.0)


def test_os_pesos_historicos_do_config_batem_com_os_componentes():
    assert len(LiveEngineConfig().pesos_historicos) == len(history_model.PESOS_PADRAO)
    assert sum(history_model.PESOS_PADRAO.values()) == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────
# 10 · O BACKTEST RECONSTROI A V2 A PARTIR DO RASTRO GRAVADO
# ─────────────────────────────────────────────────────────────────────────
def test_o_backtest_le_um_pick_gravado_sem_tocar_em_api():
    """O `engine_debug` tem que bastar pra reconstruir a decisao da V2 meses
    depois. Se este teste quebrar, o backtest esta' medindo outra coisa (ou
    estourando) contra o historico de PROD -- e ai o numero que ele imprime nao
    vale nada."""
    from scripts import live_backtest_v2 as bt

    debug = {
        "current_state": {"minuto": 62, "goals_total": 1, "corners_total": 7,
                          "blocked_shots_total": 3, "diferenca_gols": 1},
        "trend": {"rotulo": "ESTAVEL"},
        "recent_windows": {"principal": {"por_minuto": 0.12, "largura_real": 10}},
        "projection": {"projecao_total": 11.4},
        "pressure": {"total": 0.62, "nivel_total": "ALTA",
                     "home": {"peso_coberto": 0.9}, "away": {"peso_coberto": 0.9}},
        "freshness": {"nivel": "FRESH"},
        "rhythm": {"score": 1.1},
        "events": {},
        "convergence": {"a_favor": 4, "contra": 0},
        "confidence_breakdown": {"divergencia_modelo": 0.08},
        "market": {"prob_mercado": 0.61},
    }
    pick = {"market_type": "corners", "line": "Over 9.5", "line_value": 9.5,
            "ev": 0.11, "_historico": {"valor": 11.1, "cobertura": 0.9,
                                       "home": {"valor": 11.4},
                                       "away": {"valor": 10.8}}}

    saida = bt._v2_sobre_o_pick(debug, pick, DEFAULT_LIVE_CONFIG)

    assert saida["reprovado_por"] == []          # este pick a V2 tambem aprova
    assert saida["alignment"] > 0.5
    assert saida["coverage"] > 0.9
    assert saida["margem"] == pytest.approx(1.9)


def test_o_backtest_reconhece_o_pick_que_a_v2_recusa():
    from scripts import live_backtest_v2 as bt

    debug = {
        "current_state": {"minuto": 28, "goals_total": 0, "corners_total": 2},
        "trend": {"rotulo": "INDEFINIDA"},
        "recent_windows": {},
        "projection": {"projecao_total": 9.4},
        "pressure": {"total": 0.40, "home": {"peso_coberto": 0.3},
                     "away": {"peso_coberto": 0.3}},
        "freshness": {"nivel": "DELAYED"},
        "rhythm": {"score": 0.8},
        "events": {},
        "convergence": {"a_favor": 3, "contra": 1},
        "confidence_breakdown": {"divergencia_modelo": 0.31},
        "market": {"prob_mercado": 0.52},
    }
    pick = {"market_type": "corners", "line": "Over 9.5", "line_value": 9.5,
            "ev": 0.09, "_historico": {}}

    saida = bt._v2_sobre_o_pick(debug, pick, DEFAULT_LIVE_CONFIG)

    assert saida["reprovado_por"], "a V2 deveria recusar: dado pela metade, "
    assert any("cobertura" in m for m in saida["reprovado_por"])
    assert any("margem" in m for m in saida["reprovado_por"])
