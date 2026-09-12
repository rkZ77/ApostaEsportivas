"""Pick Boost V2 -- o que a V1 aprovava e a V2 recusa.

Cada teste aqui nasce de um defeito concreto da V1, e nao de uma propriedade
bonita do codigo novo. A ordem e' a do diagnostico:

  1. EV negativo virava pick;
  2. a probabilidade do par era o produto de duas pernas que se contradizem;
  3. 4/4 valia 100%;
  4. o primeiro tempo era lido pelo nivel (media) e nunca pelo formato;
  5. amostra rala e cobertura de HT ruim nao custavam nada;
  6. preco nao reprovava -- e nao pode passar a ordenar.

Nenhum deles toca banco: os perfis sao montados a mao.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pick_engine_boost import (  # noqa: E402
    calibration, config as cfg, contradiction, decision, ht_risk, joint,
    quality, score as scoring, shrinkage, stats_model,
)


# ---------------------------------------------------------------------------
# Fabrica de historico
# ---------------------------------------------------------------------------
def jogo(team_id, *, gols_time, gols_adv, ht_time, ht_adv, em_casa=True,
         data="2026-09-01"):
    from datetime import date
    ano, mes, dia = (int(x) for x in data.split("-"))
    if em_casa:
        return {"fixture_id": 1, "match_date": date(ano, mes, dia),
                "home_team_id": team_id, "away_team_id": 99,
                "home_goals": gols_time, "away_goals": gols_adv,
                "home_goals_ht": ht_time, "away_goals_ht": ht_adv}
    return {"fixture_id": 1, "match_date": date(ano, mes, dia),
            "home_team_id": 99, "away_team_id": team_id,
            "home_goals": gols_adv, "away_goals": gols_time,
            "home_goals_ht": ht_adv, "away_goals_ht": ht_time}


def historico(team_id, placares, *, mando_alternado=True):
    """placares: lista de (gols_time, gols_adv, ht_time, ht_adv)."""
    saida = []
    for i, (gt, ga, ht, ha) in enumerate(placares):
        saida.append(jogo(team_id, gols_time=gt, gols_adv=ga, ht_time=ht,
                          ht_adv=ha, em_casa=(i % 2 == 0) if mando_alternado else True,
                          data=f"2026-09-{(i % 28) + 1:02d}"))
    return saida


# ---------------------------------------------------------------------------
# 1. Encolhimento
# ---------------------------------------------------------------------------
class TestEncolhimento:
    def test_quatro_de_quatro_nao_vale_cem_por_cento(self):
        """O caso que originou a regra: piso de amostra 4, e 4/4 entrando na
        probabilidade final como certeza."""
        assert shrinkage.encolher(4, 4, 0.75, cfg.PSEUDO_JOGOS_FT) < 0.90

    def test_amostra_grande_quase_nao_encolhe(self):
        crua, encolhida = 0.90, shrinkage.encolher(27, 30, 0.75, cfg.PSEUDO_JOGOS_FT)
        assert abs(encolhida - crua) < 0.03

    def test_encolhe_pros_dois_lados(self):
        """Nao e' um redutor pessimista: 2/10 SOBE em direcao ao baseline."""
        assert shrinkage.encolher(2, 10, 0.75, cfg.PSEUDO_JOGOS_FT) > 0.20

    def test_sem_baseline_devolve_a_frequencia_crua(self):
        assert shrinkage.encolher(4, 4, None, 6) == 1.0

    def test_classes_de_amostra(self):
        assert shrinkage.classe_de_amostra(3) == "INSUFICIENTE"
        assert shrinkage.classe_de_amostra(5) == "MUITO_FRACA"
        assert shrinkage.classe_de_amostra(12) == "RAZOAVEL"
        assert shrinkage.classe_de_amostra(31) == "FORTE"


# ---------------------------------------------------------------------------
# 2. A probabilidade do par
# ---------------------------------------------------------------------------
class TestProbabilidadeDoPar:
    def test_o_produto_superestima(self):
        """A afirmacao que a V1 tinha ao contrario na propria docstring."""
        from services.pick_engine import probability_model as pm
        lam_ft, lam_ht = 2.60, 1.10
        produto = pm.prob_over(1.5, lam_ft, cfg.PHI_GOLS_TOTAL) * pm.prob_under(2.5, lam_ht, 1.0)
        par = joint.probabilidade_do_par(lam_ft, lam_ht)
        assert par < produto

    def test_o_par_nunca_passa_da_perna_mais_fraca(self):
        from services.pick_engine import probability_model as pm
        for lam_ft, lam_ht in ((2.2, 0.8), (3.1, 1.4), (2.6, 1.1)):
            par = joint.probabilidade_do_par(lam_ft, lam_ht)
            assert par <= pm.prob_over(1.5, lam_ft, 1.0) + 1e-9
            assert par <= pm.prob_under(2.5, lam_ht, 1.0) + 1e-9

    def test_primeiro_tempo_mais_quente_derruba_o_par(self):
        assert (joint.probabilidade_do_par(2.6, 1.6)
                < joint.probabilidade_do_par(2.6, 0.9))

    def test_a_frequencia_do_par_e_contada_e_nao_reconstruida(self):
        # 3 jogos: um com as duas coisas, um so' com Over, um so' com Under.
        jogos = [
            jogo(1, gols_time=2, gols_adv=1, ht_time=1, ht_adv=0),   # par OK
            jogo(1, gols_time=2, gols_adv=2, ht_time=2, ht_adv=1),   # HT estourou
            jogo(1, gols_time=1, gols_adv=0, ht_time=0, ht_adv=0),   # FT nao bateu
        ]
        assert joint.frequencia_do_par(jogos) == (1, 3)

    def test_lambda_do_segundo_tempo_nunca_e_negativo(self):
        assert joint.lambda_segundo_tempo(1.0, 1.6) > 0


# ---------------------------------------------------------------------------
# 3. Risco do primeiro tempo
# ---------------------------------------------------------------------------
class TestRiscoHT:
    def test_mesma_frequencia_formatos_diferentes(self):
        """Os dois tem 10/10 de Under 2.5 HT. Um deles nao deveria passar.

        Perfil A: dois jogos de 2 gols e oito de 0 -- media 0,4.
        Perfil B: dez jogos de 1 gol -- media 1,0.

        A V1 preferia o A, porque olhava so' a media. O A e' o que tem dois
        jogos encostados na linha.
        """
        # phi = variancia/media: A e' 0,64/0,4 = 1,6 (cauda); B e' 0/1,0 = 0.
        a = {"under25_ht_total": 10, "under25_ht_acertos": 10, "ht_2mais": 2,
             "ht_3mais": 0, "ht_exatos_2": 2, "ht_max": 2, "desvio": 0.8,
             "dispersao_relativa": 1.6}
        b = {"under25_ht_total": 10, "under25_ht_acertos": 10, "ht_2mais": 0,
             "ht_3mais": 0, "ht_exatos_2": 0, "ht_max": 1, "desvio": 0.0,
             "dispersao_relativa": 0.0}
        risco_a = ht_risk.calcular(0.4, {**a, "freq_2mais": 0.2, "freq_3mais": 0.0,
                                         "freq_exatos_2": 0.2, "jogos": 10})
        risco_b = ht_risk.calcular(1.0, {**b, "freq_2mais": 0.0, "freq_3mais": 0.0,
                                         "freq_exatos_2": 0.0, "jogos": 10})
        assert risco_a["score"] > risco_b["score"]

    def test_tres_gols_no_intervalo_pesa(self):
        base = {"freq_2mais": 0.3, "freq_exatos_2": 0.3, "dispersao_relativa": 1.0,
                "under25_ht_total": 10, "acertos_under25": 7, "jogos_exatos_2": 3}
        sem = ht_risk.calcular(1.0, {**base, "freq_3mais": 0.0})
        com = ht_risk.calcular(1.0, {**base, "freq_3mais": 0.20})
        assert com["score"] > sem["score"] + 10

    def test_o_teto_bloqueia(self):
        pessimo = ht_risk.calcular(1.9, {"freq_2mais": 0.7, "freq_3mais": 0.3,
                                         "freq_exatos_2": 0.5,
                                         "dispersao_relativa": 2.2})
        assert pessimo["score"] >= cfg.HT_RISK_BLOQUEIA
        assert pessimo["bloqueia"] is True
        assert pessimo["classe"] == "CRITICO"

    def test_tail_risk_le_a_concentracao_dentro_do_acerto(self):
        """Dez acertos de Under 2.5 HT, sete deles parando exatamente em 2."""
        tail = ht_risk.tail_risk({"acertos_under25": 10, "jogos_exatos_2": 7,
                                  "freq_3mais": 0.05, "max_ht": 3})
        assert tail["concentracao_em_2"] == 0.7
        assert tail["score"] > 40

    def test_sem_acerto_a_concentracao_nao_vira_zero(self):
        tail = ht_risk.tail_risk({"acertos_under25": 0, "jogos_exatos_2": 0,
                                  "freq_3mais": 0.0, "max_ht": None})
        assert tail["concentracao_em_2"] is None


# ---------------------------------------------------------------------------
# 4. Qualidade de dado e convergencia
# ---------------------------------------------------------------------------
class TestQualidadeDeDado:
    def _perfil(self, **kw):
        base = {"jogos": 10, "jogos_com_ht": 10, "jogos_no_mando": 5,
                "media_gols_total": 2.8, "media_gols_ht": 1.0, "freq_over15": 0.8,
                "freq_under25_ht": 0.9, "freq_over15_mando": 0.8, "desvio_gols_ht": 0.8}
        base.update(kw)
        return base

    def test_cobertura_de_ht_ruim_custa(self):
        hist = historico(1, [(2, 1, 1, 0)] * 10)
        cheia = quality.data_quality(self._perfil(), self._perfil(), hist, hist)
        rala = quality.data_quality(self._perfil(jogos_com_ht=4),
                                    self._perfil(jogos_com_ht=4), hist, hist)
        assert rala["score"] < cheia["score"]

    def test_amostra_de_quatro_jogos_nao_alcanca_o_minimo(self):
        """O piso de 4 continua valendo como piso -- mas quatro jogos nao
        produzem qualidade de dado suficiente, e agora isso tem nome."""
        hist = historico(1, [(2, 1, 1, 0)] * 4)
        q = quality.data_quality(self._perfil(jogos=4, jogos_com_ht=4, jogos_no_mando=2),
                                 self._perfil(jogos=4, jogos_com_ht=4, jogos_no_mando=2),
                                 hist, hist)
        assert q["suficiente"] is False
        assert q["classe"] == "INSUFICIENTE"

    def test_o_elo_mais_fraco_manda(self):
        hist = historico(1, [(2, 1, 1, 0)] * 14)
        misto = quality.data_quality(self._perfil(jogos=14, jogos_com_ht=14),
                                     self._perfil(jogos=4, jogos_com_ht=4), hist, hist)
        bom = quality.data_quality(self._perfil(jogos=14, jogos_com_ht=14),
                                   self._perfil(jogos=14, jogos_com_ht=14), hist, hist)
        assert misto["score"] < bom["score"]

    def test_sinal_ausente_nao_conta_como_discordancia(self):
        conv = quality.convergencia({"freq_over15": 0.8, "prob_modelo_ft": 0.8,
                                     "margem_ft": 0.9, "freq_under25_ht": 0.9})
        assert conv["disponiveis"] == 4
        assert conv["fracao"] == 1.0

    def test_poucos_sinais_a_favor_reprovam(self):
        conv = quality.convergencia({
            "freq_over15": 0.62, "freq_over15_mando": 0.55, "prob_modelo_ft": 0.68,
            "margem_ft": 0.30, "freq_under25_ht": 0.90, "prob_modelo_ht": 0.92,
            "margem_ht": 1.5, "tendencia_media": -0.1})
        assert conv["suficiente"] is False


# ---------------------------------------------------------------------------
# 5. As portas
# ---------------------------------------------------------------------------
def _cenario_bom():
    return dict(
        ev=0.06, edge=0.04,
        qualidade={"score": 88.0, "classe": "BOA", "suficiente": True},
        convergencia={"fracao": 0.875, "a_favor": 7, "disponiveis": 8, "suficiente": True},
        risco_ht={"score": 30.0, "classe": "BAIXO", "bloqueia": False, "penaliza": False},
        tail={"score": 20.0, "bloqueia": False},
        confronto={"margem_ft": 0.95, "lambda_ht": 1.05, "lambda_ft": 2.45},
        contradicoes={"achados": [], "graves": [], "bloqueia": False},
        calibrada={"prob": 0.70, "fonte": "sem_medicao"},
        amostra_classe="RAZOAVEL",
        score_final_valor=78.0,
    )


class TestPortas:
    def test_o_cenario_bom_vira_pick(self):
        assert decision.avaliar(**_cenario_bom())["decision"] == "PICK"

    def test_ev_negativo_reprova_com_score_alto(self):
        """O defeito numero um da V1, no formato exato em que ele acontecia."""
        v = decision.avaliar(**{**_cenario_bom(), "ev": -0.086, "edge": -0.04,
                                "score_final_valor": 92.0})
        assert v["decision"] == "NO_PICK"
        assert v["codigo"] == decision.NO_PICK_NEGATIVE_EV

    def test_ev_zero_tambem_reprova(self):
        v = decision.avaliar(**{**_cenario_bom(), "ev": 0.0})
        assert v["codigo"] == decision.NO_PICK_NEGATIVE_EV

    def test_edge_negativo_reprova(self):
        v = decision.avaliar(**{**_cenario_bom(), "edge": -0.01})
        assert v["codigo"] == decision.NO_PICK_NEGATIVE_EDGE

    def test_risco_de_ht_critico_reprova(self):
        v = decision.avaliar(**{**_cenario_bom(),
                                "risco_ht": {"score": 84.0, "classe": "CRITICO",
                                             "bloqueia": True, "penaliza": True}})
        assert v["codigo"] == decision.NO_PICK_HIGH_HT_RISK

    def test_cauda_perigosa_tem_codigo_proprio(self):
        v = decision.avaliar(**{**_cenario_bom(), "tail": {"score": 90.0, "bloqueia": True}})
        assert v["codigo"] == decision.NO_PICK_HIGH_TAIL_RISK

    def test_projecao_encostada_na_linha_reprova(self):
        v = decision.avaliar(**{**_cenario_bom(),
                                "confronto": {"margem_ft": 0.20, "lambda_ht": 1.0}})
        assert v["codigo"] == decision.NO_PICK_LOW_PROJECTION_MARGIN

    def test_primeiro_tempo_projetado_alto_reprova(self):
        v = decision.avaliar(**{**_cenario_bom(),
                                "confronto": {"margem_ft": 0.95, "lambda_ht": 2.3}})
        assert v["codigo"] == decision.NO_PICK_LOW_PROJECTION_MARGIN

    def test_contradicao_grave_bloqueia(self):
        v = decision.avaliar(**{**_cenario_bom(),
                                "contradicoes": {"achados": [], "graves": [
                                    {"descricao": "x"}], "bloqueia": True}})
        assert v["codigo"] == decision.NO_PICK_MODEL_CONTRADICTION

    def test_convergencia_fraca_reprova(self):
        v = decision.avaliar(**{**_cenario_bom(),
                                "convergencia": {"fracao": 0.375, "a_favor": 3,
                                                 "disponiveis": 8, "suficiente": False}})
        assert v["codigo"] == decision.NO_PICK_INSUFFICIENT_CONVERGENCE

    def test_amostra_insuficiente_reprova_mas_muito_fraca_nao(self):
        """O piso de 4 jogos e' decisao do usuario e continua sendo o piso."""
        assert decision.avaliar(**{**_cenario_bom(),
                                   "amostra_classe": "INSUFICIENTE"})["codigo"] == \
            decision.NO_PICK_SMALL_SAMPLE
        assert decision.avaliar(**{**_cenario_bom(),
                                   "amostra_classe": "MUITO_FRACA"})["decision"] == "PICK"

    def test_todas_as_portas_sao_avaliadas_e_nao_so_a_primeira(self):
        v = decision.avaliar(**{**_cenario_bom(), "ev": -0.1, "edge": -0.1,
                                "score_final_valor": 10.0})
        assert len(v["gates_reprovados"]) >= 3

    def test_o_motivo_carrega_o_numero_que_reprovou(self):
        v = decision.avaliar(**{**_cenario_bom(), "ev": -0.086})
        assert "-8.6%" in v["motivo"]

    def test_todo_codigo_tem_frase(self):
        for nome, valor in vars(decision).items():
            if nome.startswith("NO_PICK_"):
                assert valor in decision.MOTIVOS


# ---------------------------------------------------------------------------
# 6. O preco elimina, mas nao ordena
# ---------------------------------------------------------------------------
class TestScoreFinal:
    def _dimensoes(self, valor):
        return {"estatistico": 80.0, "modelo": 75.0, "valor": valor, "mando": 70.0,
                "seguranca_ht": 80.0, "amostra": 60.0, "qualidade_dado": 85.0,
                "convergencia": 87.5}

    def test_ev_nao_muda_a_ordenacao(self):
        """Regra do projeto: preco elimina nas portas e nunca ordena. Nao basta
        pesar pouco -- tem que ser zero."""
        vazio = {"total": 0.0}
        assert (decision.score_final(self._dimensoes(0.0), vazio)
                == decision.score_final(self._dimensoes(100.0), vazio))

    def test_o_peso_do_valor_esta_declarado_em_zero(self):
        assert cfg.PESOS_SCORE_FINAL["valor"] == 0.0

    def test_penalidade_desconta(self):
        base = decision.score_final(self._dimensoes(0.0), {"total": 0.0})
        punido = decision.score_final(self._dimensoes(0.0), {"total": 12.0})
        assert round(base - punido, 1) == 12.0

    def test_zona_cinzenta_de_risco_ht_custa_ponto(self):
        p = decision.penalidades({"score": 72.0}, {"margem_ft": 1.4, "lambda_ht": 1.0},
                                 0.05)
        assert p["risco_ht"] > 0

    def test_risco_baixo_nao_penaliza(self):
        p = decision.penalidades({"score": 20.0}, {"margem_ft": 1.4, "lambda_ht": 1.0},
                                 0.05)
        assert "risco_ht" not in p


# ---------------------------------------------------------------------------
# 7. Contradicoes
# ---------------------------------------------------------------------------
class TestContradicoes:
    def test_historico_forte_com_modelo_fraco(self):
        r = contradiction.detectar({"freq_over15": 0.88, "prob_modelo_ft": 0.62},
                                   {}, 0.05, 80)
        assert r["bloqueia"] is True
        assert r["achados"][0]["codigo"] == "HISTORICO_FT_CONTRA_MODELO"

    def test_under_forte_com_primeiro_tempo_quente(self):
        r = contradiction.detectar({"freq_under25_ht": 0.90, "lambda_ht": 1.7},
                                   {}, 0.05, 80)
        assert any(a["codigo"] == "HISTORICO_HT_CONTRA_PROJECAO" for a in r["graves"])

    def test_score_alto_com_ev_negativo_e_contradicao_critica(self):
        r = contradiction.detectar({}, {}, -0.05, 85)
        assert any(a["codigo"] == "SCORE_ALTO_COM_EV_NEGATIVO" for a in r["graves"])

    def test_sem_ev_a_contradicao_de_valor_nao_e_testada(self):
        r = contradiction.detectar({}, {}, None, 85)
        assert not any(a["codigo"] == "SCORE_ALTO_COM_EV_NEGATIVO" for a in r["achados"])

    def test_tendencia_contraria_e_leve_e_nao_bloqueia(self):
        r = contradiction.detectar(
            {"tendencia": {"over15": -0.30, "under25_ht": -0.25}}, {}, 0.05, 80)
        assert r["bloqueia"] is False
        assert r["achados"]


# ---------------------------------------------------------------------------
# 8. Calibracao e confianca
# ---------------------------------------------------------------------------
class TestCalibracao:
    def test_sem_medicao_a_probabilidade_nao_e_mexida(self):
        r = calibration.calibrar(0.72)
        assert r["prob"] == 0.72
        assert r["fonte"] == "sem_medicao"

    def test_a_tabela_vem_vazia_de_proposito(self):
        assert cfg.CALIBRACAO_MEDIDA == ()

    def test_com_medicao_a_correcao_e_pela_metade(self, monkeypatch):
        monkeypatch.setattr(cfg, "CALIBRACAO_MEDIDA", ((0.70, 0.75, 0.60, 40),))
        r = calibration.calibrar(0.72)
        assert r["fonte"] == "medida"
        assert r["prob"] == pytest.approx(0.66, abs=1e-3)

    def test_faixa_sem_amostra_nao_calibra(self, monkeypatch):
        monkeypatch.setattr(cfg, "CALIBRACAO_MEDIDA", ((0.70, 0.75, 0.60, 3),))
        assert calibration.calibrar(0.72)["fonte"] == "sem_medicao"

    def test_confianca_e_menor_que_a_probabilidade(self):
        c = calibration.confianca(
            0.72, {"score": 80.0}, {"fracao": 0.75}, "LIMITADA", 0.05)
        assert c < 0.72

    def test_evidencia_pior_derruba_a_confianca(self):
        forte = calibration.confianca(0.72, {"score": 95.0}, {"fracao": 1.0}, "FORTE", 0.0)
        fraca = calibration.confianca(0.72, {"score": 72.0}, {"fracao": 0.6},
                                      "MUITO_FRACA", 0.15)
        assert fraca < forte <= 0.72


# ---------------------------------------------------------------------------
# 9. Fim a fim, sem banco
# ---------------------------------------------------------------------------
class TestFluxoCompleto:
    def _confronto(self, placares_home, placares_away):
        ph = stats_model.perfil_do_time(historico(1, placares_home), 1, "home")
        pa = stats_model.perfil_do_time(historico(2, placares_away), 2, "away")
        return ph, pa, stats_model.analisar_confronto(ph, pa)

    def test_o_confronto_devolve_os_campos_da_v2(self):
        _, _, c = self._confronto([(2, 1, 1, 0)] * 10, [(1, 2, 0, 1)] * 10)
        for chave in ("prob_modelo_par", "freq_par", "prob_combinada",
                      "prob_combinada_produto_v1", "divergencia_modelo_historico",
                      "margem_ft", "margem_ht", "distribuicao_ht", "baseline"):
            assert chave in c

    def test_a_combinada_deixou_de_ser_o_produto(self):
        _, _, c = self._confronto([(2, 1, 1, 0)] * 10, [(1, 2, 0, 1)] * 10)
        assert c["prob_combinada"] != c["prob_combinada_produto_v1"]

    def test_o_recorte_de_mando_usa_os_catorze_jogos(self):
        """A V1 cortava os dez primeiros e so' depois separava por mando,
        deixando ~5 jogos onde ha' 7."""
        p = stats_model.perfil_do_time(historico(1, [(2, 1, 1, 0)] * 14), 1, "home")
        assert p["jogos_no_mando"] == 7

    def test_a_dispersao_relativa_entra_na_distribuicao(self):
        _, _, c = self._confronto([(2, 1, 1, 0)] * 10, [(1, 2, 0, 1)] * 10)
        assert "dispersao_relativa" in c["distribuicao_ht"]

    def test_a_distribuicao_ht_soma_os_dois_times(self):
        ph, pa, c = self._confronto([(3, 0, 2, 0)] * 10, [(0, 0, 0, 0)] * 10)
        d = c["distribuicao_ht"]
        assert d["jogos"] == 20
        assert d["jogos_exatos_2"] == 10
        assert d["freq_2mais"] == 0.5

    def test_quatro_jogos_perfeitos_nao_produzem_probabilidade_de_certeza(self):
        _, _, c = self._confronto([(2, 0, 1, 0)] * 4, [(2, 0, 0, 1)] * 4)
        assert c["freq_over15"] < 0.95
        assert c["prob_combinada"] < 0.90

    def test_o_score_estatistico_continua_existindo(self):
        ph, pa, c = self._confronto([(2, 1, 1, 0)] * 10, [(1, 2, 0, 1)] * 10)
        calculo = scoring.calcular(c, ph, pa)
        assert 0 <= calculo["score"] <= 100
        assert calculo["parcelas"]
