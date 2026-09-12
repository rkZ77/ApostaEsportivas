"""Motor Jogadores V2 -- as camadas que nasceram em 2026-09-11.

Cada teste cobre uma decisao que o motor NAO tomava antes: minutos esperados,
mando do jogador, adversario como ajuste, separacao entre probabilidade do
modelo e calibrada, contradicao, auditoria final e -- o que ja' tinha sido
corrigido duas vezes nos outros motores -- preco fora da ordenacao.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.player_stats_engine import (contradiction, count_model, decision,
                                          minutes_model, quality, selection)
from services.player_stats_engine import config as cfg
from services.player_stats_engine import methods as cat


# --------------------------------------------------------------- MINUTOS

def _perfil(minutos, titular=True):
    folhas = [{"minutes": m, "is_substitute": not titular, "position": "M"}
              for m in minutos]
    return {
        "amostra": len(folhas),
        "minutos_medios": sum(minutos) / len(minutos),
        "minutos_ultimo": minutos[0],
        "minutos_serie": minutos,
        "jogos_completos": sum(1 for m in minutos if m >= 85),
        "titularidades": len(folhas) if titular else 0,
        "minutos_como_titular": (sum(minutos) / len(minutos)) if titular else None,
        "curtas": sum(1 for m in minutos if 0 < m < 60),
        "ausencias": sum(1 for m in minutos if m == 0),
        "posicoes": ["M"],
    }


def test_o_fator_e_neutro_quando_hoje_e_o_regime_da_amostra():
    """A camada nova nao pode deixar o motor conservador de graca.

    O caso comum e' o jogador que joga o mesmo tanto de sempre. Se o fator
    saisse abaixo de 1 nesse caso, TODO pick perderia projecao por uma
    correcao que nao corrige nada.
    """
    assert minutes_model.fator_de_minutos(88.0, 88.0) == 1.0


def test_quem_volta_de_lesao_perde_projecao():
    perfil = _perfil([55, 62, 0, 0, 90, 88])
    esperados = minutes_model.minutos_esperados(perfil)
    fator = minutes_model.fator_de_minutos(esperados, 87.0)
    assert fator < 1.0
    # E nao despenca: a perda de minuto custa menos que o proporcional, porque
    # contagem nao se distribui uniformemente no relogio.
    assert fator > (esperados / 87.0)


def test_o_fator_tem_piso_e_teto_declarados():
    assert minutes_model.fator_de_minutos(10, 90) == minutes_model.FATOR_MIN
    assert minutes_model.fator_de_minutos(200, 90) == minutes_model.FATOR_MAX


def test_rodizio_e_risco_alto_de_minutos():
    perfil = _perfil([90, 22, 0, 90, 18, 0])
    assert minutes_model.risco_de_minutos(perfil, {"taxa_titularidade": 0.5}) == "HIGH"


def test_titular_fixo_e_risco_baixo():
    perfil = _perfil([90, 90, 88, 90, 90, 86])
    assert minutes_model.risco_de_minutos(perfil, {"taxa_titularidade": 0.95}) == "LOW"


def test_sem_folha_a_titularidade_e_desconhecida_e_nao_neutra():
    """§33 · ausencia de dado critico nao vira 'segue o jogo'.

    O pick de jogador NASCE afirmando titularidade. Quando o motor nao sabe,
    quem pagaria a conta e' o apostador -- entao o estado tem nome proprio e a
    auditoria final o reprova.
    """
    assert minutes_model.status_de_titularidade(
        {"partidas_do_time": 0}, _perfil([90])) == minutes_model.DESCONHECIDO
    assert minutes_model.status_de_titularidade(
        {"partidas_do_time": 15, "taxa_titularidade": 0.2},
        _perfil([90])) == minutes_model.RESERVA


def test_funcao_instavel_e_medida_e_nao_inferida_do_nome():
    perfil = {"posicoes": ["D", "M", "F"], "amostra": 6}
    risco, _ = minutes_model.risco_de_funcao(perfil, [], cat.SHOTS)
    assert risco == "HIGH"


# ------------------------------------------------------------------ MANDO

def test_o_mando_puxa_a_media_sem_dominar_ela():
    """§7 · os dois erros opostos, resolvidos pelo mesmo encolhimento."""
    geral = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    com_duas = count_model.media_com_mando(geral, [4, 4])
    com_dez = count_model.media_com_mando(geral, [4] * 10)
    assert com_duas["media"] < com_dez["media"]
    # Duas atuacoes em casa nao podem valer mais que a serie inteira.
    assert com_duas["peso_mando"] < 0.5 < com_dez["peso_mando"]


def test_sem_amostra_de_mando_a_media_e_a_geral():
    valores = [2, 3, 1, 2]
    assert (count_model.media_com_mando(valores, [])["media"]
            == count_model.media_ponderada(valores))


# ----------------------------------------------- PROBABILIDADE CALIBRADA

def test_modelo_e_calibrada_sao_campos_diferentes():
    """§18 · nunca transformar confidence em probabilidade."""
    a = count_model.analisar(valores=[3, 2, 3, 2, 3, 2, 3, 2], linha=1.5,
                             phi=1.4, odd=1.80, penalidade_variancia=0.05)
    assert a["probability_modelo"] > a["probability_calibrada"]
    assert a["probability"] == a["probability_calibrada"]


def test_edge_e_ev_saem_da_calibrada_e_nao_da_bruta():
    """§25 e §26 · 'nao usar probabilidade bruta inflada'."""
    a = count_model.analisar(valores=[3, 3, 3, 3, 3, 3], linha=1.5, phi=1.2,
                             odd=1.70, desconto_contradicao=0.08)
    p = a["probability_calibrada"]
    assert abs(a["edge"] - (p - 1 / 1.70)) < 1e-4
    assert abs(a["ev"] - (p * 0.70 - (1 - p))) < 1e-4
    assert abs(a["fair_odd"] - 1 / p) < 1e-3


def test_o_abatimento_tem_teto():
    a = count_model.analisar(valores=[4, 4, 4, 4], linha=0.5, phi=1.0, odd=1.50,
                             penalidade_variancia=0.5, desconto_contradicao=0.5)
    assert a["abatimento"] == count_model.ABATIMENTO_MAX


def test_a_mesma_conta_vale_pro_caminho_de_saves():
    """`saves` nao passa por `analisar`, e por isso o abatimento e' funcao
    propria: duas implementacoes da mesma calibragem divergiriam em silencio,
    que e' o que aconteceu com o contexto de competicao em 27/08."""
    bruta = {"probability_modelo": 0.80, "odd": 1.60}
    saida = count_model.aplicar_abatimento(bruta, penalidade_variancia=0.06)
    assert saida["probability_calibrada"] == 0.74
    assert abs(saida["edge"] - (0.74 - 1 / 1.60)) < 1e-4


# --------------------------------------------------------------- VARIANCIA

def test_a_referencia_de_dispersao_e_do_metodo():
    """CV 1.4 e' regular em chute no alvo e extremo em defesa de goleiro.

    Um limiar unico penalizaria os dois do mesmo jeito -- que e' o erro que o
    piso de amostra cometeu ate' 10/09, pelo outro lado.
    """
    assert quality.penalidade_de_variancia(1.4, cat.SHOTS_ON.cv_referencia) == 0.0
    assert quality.penalidade_de_variancia(1.4, cat.SAVES.cv_referencia) > 0.0


def test_a_penalidade_satura():
    assert (quality.penalidade_de_variancia(99, 0.65)
            == quality.PENALIDADE_MAX)


# ------------------------------------------------------------------ MARGEM

def test_a_margem_e_relativa_a_linha():
    """0.4 de folga e' 80% sobre 'meio chute' e 1.6% sobre 24.5 passes."""
    curta = quality.margem_de_projecao(0.9, 0.5)
    longa = quality.margem_de_projecao(24.9, 24.5)
    assert curta["relativa"] > cfg.MARGEM_RELATIVA_MINIMA
    assert longa["relativa"] < cfg.MARGEM_RELATIVA_MINIMA


def test_projecao_abaixo_da_linha_tem_margem_negativa():
    assert quality.margem_de_projecao(1.2, 1.5)["direcao"] == "under"


# ------------------------------------------------------------ CONTRADICAO

def _candidato(**kw):
    base = {
        "metodo": cat.SHOTS,
        "jogador": {"player_id": 1, "player_name": "Fulano", "team_name": "Time",
                    "taxa_titularidade": 0.9},
        "analise": {"linha": 1.5, "esperado": 2.4, "amostra": 12,
                    "probability": 0.70, "probability_calibrada": 0.70,
                    "probability_modelo": 0.70, "abatimento": 0.0,
                    "odd": 1.60, "implied_probability": 0.625,
                    "edge": 0.075, "ev": 0.12, "fair_odd": 1.429,
                    "amostra_no_mando": 5, "penalidade_variancia": 0.0},
        "minutos": {"status": minutes_model.PROVAVEL, "esperados": 88.0,
                    "fator": 1.0, "risco": "LOW", "risco_funcao": "LOW",
                    "posicao": "F", "perfil": {"amostra": 8}},
        "dispersao": {"amostra": 12, "media": 2.4, "cv": 0.9, "desvio": 2.1},
        "margem": quality.margem_de_projecao(2.4, 1.5),
        "classe_amostra": "limitada",
        "data_quality": {"score": 92.0, "componentes": {}},
        "adversario_ajuste": {"disponivel": True, "ajuste": 1.02},
        "matchup": {"disponivel": False, "motivo": "sem dado"},
        "contradicoes": [],
        "outliers": [],
        "serie": [2] * 12,
    }
    base.update(kw)
    return base


def _detectar(c):
    return contradiction.detectar(
        analise=c["analise"], disp=c["dispersao"], margem=c["margem"],
        frequencia=c.get("frequencia"), amostra=c["analise"]["amostra"],
        classe_amostra=c["classe_amostra"], minutos=c["minutos"],
        risco_minutos=c["minutos"]["risco"],
        risco_funcao=c["minutos"]["risco_funcao"],
        status_titular=c["minutos"]["status"],
        adversario=c["adversario_ajuste"], outliers_serie=c["outliers"])


def test_candidato_coerente_nao_tem_contradicao():
    assert _detectar(_candidato()) == []


def test_media_alta_com_minutos_baixos_e_critica():
    c = _candidato(minutos={**_candidato()["minutos"], "fator": 0.78,
                            "esperados": 62.0})
    criticas = contradiction.criticas(_detectar(c))
    assert any(x["codigo"] == "MINUTOS_CONTRA_MEDIA" for x in criticas)


def test_frequencia_alta_contra_projecao_abaixo_da_linha_e_critica():
    c = _candidato(frequencia=0.8, margem=quality.margem_de_projecao(1.4, 1.5))
    assert any(x["codigo"] == "FREQUENCIA_CONTRA_PROJECAO"
               for x in contradiction.criticas(_detectar(c)))


def test_probabilidade_alta_com_amostra_minuscula_e_critica():
    c = _candidato(classe_amostra="muito limitada")
    c["analise"]["probability"] = 0.82
    assert any(x["codigo"] == "CONFIANCA_SEM_AMOSTRA"
               for x in contradiction.criticas(_detectar(c)))


def test_outlier_que_sustenta_a_projecao_e_critico():
    """§16 · o outlier NAO e' removido da media. Ele e' sinalizado, e o pick
    que so' existe por causa dele nao sai."""
    serie = [1, 1, 1, 1, 1, 9, 1, 1]
    disp = quality.dispersao(serie)
    c = _candidato(serie=serie, dispersao=disp, outliers=quality.outliers(serie, disp),
                   margem=quality.margem_de_projecao(2.0, 1.5))
    assert any(x["codigo"] == "PROJECAO_SUSTENTADA_POR_OUTLIER"
               for x in contradiction.criticas(_detectar(c)))


def test_contradicao_grave_desconta_e_nao_reprova():
    graves = [{"codigo": "X", "severidade": contradiction.GRAVE, "texto": ""}]
    assert contradiction.desconto(graves) == contradiction.DESCONTO_GRAVE
    assert contradiction.criticas(graves) == []


# --------------------------------------------------------- AUDITORIA FINAL

def test_o_candidato_coerente_vira_pick():
    decisao, motivo, itens = decision.avaliar(_candidato())
    assert decisao == "PICK", motivo
    assert len(itens) == 20


def test_as_vinte_perguntas_sao_respondidas_mesmo_quando_a_primeira_falha():
    """Uma checklist que para no primeiro erro faz o painel culpar a camada
    errada -- o pick morreria de amostra e de minutos, e so' a amostra
    apareceria."""
    c = _candidato(classe_amostra="insuficiente")
    c["analise"]["amostra"] = 2
    c["minutos"] = {**c["minutos"], "risco": "HIGH", "esperados": 40.0}
    decisao, _, itens = decision.avaliar(c)
    assert decisao == "NO_PICK"
    assert len(itens) == 20
    assert len([i for i in itens if not i["ok"]]) >= 2


def test_qualidade_de_dado_insuficiente_reprova():
    c = _candidato(data_quality={"score": 55.0, "componentes": {}})
    decisao, motivo, _ = decision.avaliar(c)
    assert decisao == "NO_PICK"
    assert "qualidade" in motivo


def test_margem_curta_reprova():
    c = _candidato()
    c["analise"]["esperado"] = 1.55
    c["margem"] = quality.margem_de_projecao(1.55, 1.5)
    decisao, motivo, _ = decision.avaliar(c)
    assert decisao == "NO_PICK"
    assert "margem" in motivo


def test_a_aritmetica_do_pick_e_conferida_antes_de_publicar():
    """§26 · 'se houver inconsistencia matematica, RECALCULAR'. Aqui ela
    reprova, que e' o passo anterior: um pick cujo edge nao bate com a
    probabilidade gravada nao pode sair enquanto ninguem souber qual dos dois
    esta' errado."""
    c = _candidato()
    c["analise"]["edge"] = 0.42
    decisao, motivo, _ = decision.avaliar(c)
    assert decisao == "NO_PICK"
    assert "edge" in motivo


# --------------------------------------------------------------- SELECAO

def test_o_preco_nao_ordena():
    """A regra ja' foi aplicada no pre-jogo generico e no ao vivo. Este
    pipeline usava Score proprio e ficou de fora das duas passagens: 0.28 de
    seguranca da odd + 0.10 de edge = 38% da escolha era preco."""
    comum = dict(amostra=12, amostra_saturacao=cfg.AMOSTRA_SATURACAO,
                 data_quality=90, margem_relativa=0.3, penalidade_variancia=0.0,
                 risco_minutos="LOW", risco_funcao="LOW")
    assert (selection.score_de_selecao(probabilidade=0.70, **comum)["score"]
            == selection.score_de_selecao(probabilidade=0.70, **comum)["score"])
    assert selection.score_de_selecao(probabilidade=0.70, **comum)["preco"] == 0.0


def test_ev_maior_com_risco_maior_perde():
    """§38, literalmente: 'Jogador A EV +20% risco alto, Jogador B EV +13%
    risco baixo -- B pode ser superior'."""
    a = selection.score_de_selecao(
        probabilidade=0.72, amostra=8, amostra_saturacao=cfg.AMOSTRA_SATURACAO,
        data_quality=72, margem_relativa=0.15, penalidade_variancia=0.06,
        risco_minutos="HIGH", risco_funcao="MEDIUM")
    b = selection.score_de_selecao(
        probabilidade=0.68, amostra=15, amostra_saturacao=cfg.AMOSTRA_SATURACAO,
        data_quality=95, margem_relativa=0.35, penalidade_variancia=0.0,
        risco_minutos="LOW", risco_funcao="LOW")
    assert b["score"] > a["score"]


def test_stake_so_desce():
    cheio = selection.fator_de_stake(data_quality=95, classe_amostra="forte",
                                     risco_minutos="LOW", penalidade_variancia=0.0)
    curto = selection.fator_de_stake(data_quality=72, classe_amostra="muito limitada",
                                     risco_minutos="MEDIUM", penalidade_variancia=0.08)
    assert cheio["fator"] == 1.0
    assert curto["fator"] < 1.0


# ----------------------------------------------------------- QUALIDADE

def test_qualidade_do_dado_abre_a_conta():
    q = quality.data_quality_score(
        amostra=16, min_atuacoes=8, perfil_minutos={"amostra": 10},
        status_titular=minutes_model.PROVAVEL, risco_minutos="LOW",
        dias_desde_ultima=5, adversario={"disponivel": True})
    assert q["score"] == 100.0
    assert set(q["componentes"]) == {"amostra", "minutos", "titularidade",
                                     "recencia", "adversario"}


def test_titularidade_desconhecida_custa_qualidade_mas_quem_reprova_e_a_checklist():
    """Duas camadas, dois papeis -- e o corte de qualidade sozinho NAO basta.

    Sem titularidade medida o pick perde os 20 pontos dela e ainda assim fica
    em 80, acima do piso: um jogador com amostra longa, minutos regulares e
    adversario conhecido nao tem dado RUIM, tem um dado FALTANDO. Quem reprova
    e' a auditoria final, onde a pergunta "o jogador está disponível?" e'
    critica -- e e' por isso que ela existe separada do score.
    """
    q = quality.data_quality_score(
        amostra=16, min_atuacoes=8, perfil_minutos={"amostra": 10},
        status_titular=minutes_model.DESCONHECIDO, risco_minutos="LOW",
        dias_desde_ultima=5, adversario={"disponivel": True})
    assert q["componentes"]["titularidade"] == 0.0
    assert q["score"] >= cfg.DATA_QUALITY_MINIMO

    c = _candidato(data_quality=q)
    c["minutos"] = {**c["minutos"], "status": minutes_model.DESCONHECIDO}
    decisao, motivo, _ = decision.avaliar(c)
    assert decisao == "NO_PICK"
    assert "disponível" in motivo


# ------------------------------------------------------------------ RASTRO

def test_o_rastro_sai_serializavel_e_com_o_41_inteiro():
    """O `engine_debug` e' gravado como texto no banco e lido pela aba Motor.
    Um campo que so' existe em memoria (um dataclass, um Decimal solto) quebra
    a gravacao do pick DEPOIS de todo o calculo ter sido feito."""
    import json
    from engine_pipelines import player_stats_pipeline as pipe

    c = _candidato(oferta={"n": 2, "odd": 1.60, "bookmaker": "Casa",
                           "market_id": 240, "market_name": "Player Shots"},
                   rotulo_linha="2 ou mais chutes", serie_no_mando=[2, 3],
                   dias_desde_ultima=6, composicao={"atuacoes": 12},
                   acertos=9, frequencia=0.75, calibragem={"phi": 1.3},
                   selecao={"score": 0.6}, stake_fator={"fator": 1.0})
    rastro = json.loads(pipe._engine_debug(c))
    for campo in ("jogador", "disponibilidade", "funcao", "historico", "amostra",
                  "matchup", "projecao", "probabilidade", "mercado",
                  "penalidade_de_variancia", "qualidade_do_dado", "contradicoes",
                  "auditoria_final", "decisao"):
        assert campo in rastro, campo
    assert len(rastro["auditoria_final"]) == 20


def test_o_rastro_de_saves_mostra_o_adversario_que_decide():
    """Em `saves` o adversario e' o SINAL, nos outros e' ajuste. Um campo so'
    faria o pick de defesas exibir 'método sem ajuste de adversário' justamente
    no metodo em que o adversario decide tudo."""
    c = _candidato(metodo=cat.SAVES,
                   adversario={"media": 4.8, "amostra": 10, "mando": "away",
                               "contador": "chutes no alvo"},
                   adversario_ajuste={"disponivel": False,
                                      "motivo": "método sem ajuste de adversário"})
    rastro = decision.engine_debug(c, "PICK", None, decision.checklist(c))
    assert rastro["adversario"]["media"] == 4.8
