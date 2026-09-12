"""Auditoria do motor de faltas (2026-09-11): calibracao da confianca,
qualidade de dados, motivo nomeado de NO_PICK e contrato com a revisao de IA.

CADA TESTE AQUI TRAVA UM DEFEITO QUE ESTAVA EM PRODUCAO, nao uma preferencia:

  contrato    `build_review_payload` le `value_label`/`taxa_real`/`confidence`,
              e o candidato de faltas nao tinha nenhuma delas -- a IA recebia
              `selection: null` e vetava sem saber o que estava vetando.
  calibracao  `confidence` era a taxa CRUA da tabela empirica; um pick com 10
              jogos de historico saia com a mesma confianca de um com 25.
  coerencia   `edge`/`ev` tem que sair da mesma probabilidade que o pick
              publica, senao o bilhete diz um numero e a margem usou outro.
  motivo      os seis descartes diferentes de `_avaliar_fixture` viravam o
              mesmo "nenhum candidato" no log.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from engine_pipelines import faltas_pipeline as fp
from services.pick_engine import fouls_calibration as fc
from services.pick_engine.ai_review import build_review_payload
from services.pick_engine.fouls_model import (
    data_quality_score, media_ponderada, probabilidade_calibrada,
    qualidade_da_amostra, taxa_base,
)


# --------------------------------------------------------------------------
# RECENCIA
# --------------------------------------------------------------------------

def test_media_ponderada_puxa_para_os_jogos_recentes():
    # 5 jogos fracos e depois 5 fortes: a media simples da 15, a ponderada
    # tem que ficar acima disso porque cada recente pesa 3 contra 2.
    valores = [10] * 5 + [20] * 5
    assert sum(valores) / len(valores) == 15
    assert media_ponderada(valores) > 15


def test_media_ponderada_com_historico_curto_e_a_media_simples():
    # 3 jogos: todos caem no primeiro tier, entao todos pesam igual.
    assert media_ponderada([10, 12, 14]) == pytest.approx(12.0)


def test_o_jogo_mais_antigo_nunca_pesa_mais_que_um_recente():
    # O bug da primeira versao: com peso de BLOCO, 11 jogos davam 25% ao unico
    # jogo mais antigo e a "recencia" puxava pra tras. Numa serie crescente a
    # ponderada TEM que ficar acima da simples.
    serie = [float(10 + i) for i in range(11)]
    assert media_ponderada(serie) > sum(serie) / len(serie)


def test_recencia_e_monotona_conforme_a_serie_cresce():
    crescente = [float(10 + i) for i in range(20)]
    assert media_ponderada(crescente) > sum(crescente) / len(crescente)
    decrescente = list(reversed(crescente))
    assert media_ponderada(decrescente) < sum(decrescente) / len(decrescente)


def test_media_ponderada_de_valores_iguais_e_o_proprio_valor():
    assert media_ponderada([11.0] * 30) == pytest.approx(11.0)


def test_sem_historico_nao_vira_zero():
    assert media_ponderada([]) is None


def test_recencia_atravessa_a_calibragem_junto_com_o_pipeline():
    # A tabela empirica so' vale se tiver sido calibrada pelo MESMO metodo que
    # monta a previsao. O acoplamento e' o que impede o descasamento silencioso
    # -- mesmo argumento do usar_mando.
    jogos = [
        {"fixture_id": i, "match_date": i, "home_team_id": 1, "away_team_id": 2,
         "home_fouls": 10.0 + i, "away_fouls": 10.0}
        for i in range(12)
    ]
    simples = fc.previsoes(jogos, usar_mando=False, usar_recencia=False)
    recente = fc.previsoes(jogos, usar_mando=False, usar_recencia=True)
    assert len(simples) == len(recente)
    # O mandante cresce a cada jogo, entao ponderar por recencia tem que prever
    # MAIS que a media simples no ultimo jogo da serie.
    assert recente[-1]["previsto"] > simples[-1]["previsto"]


def test_o_interruptor_de_recencia_nasce_desligado():
    # Ligar sem a Parte D de medir_faltas_mando_e_pressao.py seria inventar
    # peso, que e' o que a docstring do fouls_model proibe.
    assert fp.USAR_RECENCIA is False


def test_a_recalibragem_recebe_o_mesmo_interruptor_do_pipeline():
    import inspect
    fonte = inspect.getsource(fp.run_faltas_engine)
    assert "usar_recencia=USAR_RECENCIA" in fonte
    assert "usar_mando=USAR_MANDO" in fonte


# --------------------------------------------------------------------------
# CALIBRACAO DA CONFIANCA
# --------------------------------------------------------------------------

def test_amostra_curta_encolhe_a_confianca_em_direcao_a_taxa_base():
    base = taxa_base(24.5)
    curta, _ = probabilidade_calibrada(0.79, 24.5, n_time=10, n_faixa=159,
                                       margem=1.3, exigido=1.22)
    longa, _ = probabilidade_calibrada(0.79, 24.5, n_time=25, n_faixa=159,
                                       margem=3.0, exigido=0.69)
    assert base < curta < longa == 0.79


def test_projecao_colada_no_minimo_vale_menos_que_projecao_folgada():
    colada, _ = probabilidade_calibrada(0.79, 24.5, 25, 159, margem=0.70, exigido=0.69)
    folgada, _ = probabilidade_calibrada(0.79, 24.5, 25, 159, margem=2.00, exigido=0.69)
    assert colada < folgada


def test_faixa_medida_em_poucos_jogos_nao_vale_o_mesmo_que_a_de_159():
    fraca, _ = probabilidade_calibrada(0.79, 24.5, 25, n_faixa=50, margem=3.0, exigido=0.69)
    forte, _ = probabilidade_calibrada(0.79, 24.5, 25, n_faixa=159, margem=3.0, exigido=0.69)
    assert fraca < forte


def test_encolhimento_nunca_passa_da_taxa_base():
    # Encolher em direcao a zero seria dizer que a linha nao tem frequencia
    # historica nenhuma, o que e' falso -- ela tem, so' nao e' a da faixa.
    base = taxa_base(24.5)
    pior, _ = probabilidade_calibrada(0.79, 24.5, n_time=10, n_faixa=1,
                                      margem=0.7, exigido=0.69)
    assert pior >= base - 1e-9


def test_linha_desconhecida_nao_encolhe_nem_quebra():
    prob, detalhe = probabilidade_calibrada(0.70, 99.5, 20, 159, 2.0, 1.0)
    assert prob == 0.70 and detalhe["base"] is None


# --------------------------------------------------------------------------
# QUALIDADE DOS DADOS E DA AMOSTRA
# --------------------------------------------------------------------------

def test_qualidade_da_amostra_cresce_com_o_numero_de_jogos():
    assert qualidade_da_amostra(3) == "insuficiente"
    assert qualidade_da_amostra(6) == "baixa"
    assert qualidade_da_amostra(10) == "moderada"
    assert qualidade_da_amostra(15) == "boa"
    assert qualidade_da_amostra(30) == "forte"


def test_data_quality_cresce_com_amostra_e_com_arbitro():
    sem = data_quality_score(10, 10, 159, False, None)
    com = data_quality_score(10, 10, 159, True, 12)
    assert 0 <= sem < com <= 100


def test_data_quality_manda_o_lado_mais_curto():
    # O pick e' sobre o total do jogo: um time com 25 jogos nao compensa o
    # outro com 10.
    assert data_quality_score(25, 10, 159, False, None) == \
        data_quality_score(10, 25, 159, False, None)


def test_piso_de_qualidade_nao_binda_sozinho_mas_pega_a_combinacao():
    # DATA_QUALITY_MIN existe pra pegar varios sinais fracos JUNTOS, nao pra
    # repetir o MIN_JOGOS_PICK. No piso de amostra com a faixa mais forte tem
    # que passar; no piso de amostra com a faixa mais fraca, nao.
    piso = fp.MIN_JOGOS_PICK
    assert data_quality_score(piso, piso, 159, False, None) >= fp.DATA_QUALITY_MIN
    assert data_quality_score(piso, piso, 50, False, None) < fp.DATA_QUALITY_MIN


# --------------------------------------------------------------------------
# CONTRATO COM A REVISAO DE IA
# --------------------------------------------------------------------------

def _candidato():
    """O candidato como `_avaliar_fixture` monta hoje, so' com as chaves que o
    payload le. Montado na mao de proposito: o teste tem que quebrar quando
    alguem renomear uma chave no pipeline, nao acompanhar a renomeacao."""
    return {
        "line": 24.5, "odd": 1.75, "probability": 0.68, "probability_raw": 0.79,
        "edge": 0.109, "ev": 0.19, "expected_fouls": 26.9,
        "faixa_amostra": 159, "data_quality": 72,
        "market_name": "Faltas Mais/Menos",
        "value_label": "Over 24.5", "market_type": "Over 24.5",
        "taxa_real": 0.79, "confidence": 0.68, "data_quality_score": 72,
        "market_sample": 159,
        "referee_signal": {"media_faltas": 24.1, "jogos": 9},
        "match_context": {"agregado": "aberto"},
        "context_gate": None,
    }


def test_a_ia_nunca_recebe_selection_nula_quando_existe_selecao():
    payload = build_review_payload([_candidato()], "faltas",
                                   {"fixture_id": 1, "home_team": "A",
                                    "away_team": "B", "league_id": 71})
    pick = payload["picks"][0]
    assert pick["selection"] == "Over 24.5"
    assert pick["market"] == "Faltas Mais/Menos"


def test_a_ia_recebe_o_que_o_motor_usou_pra_decidir():
    payload = build_review_payload([_candidato()], "faltas", {})
    pick = payload["picks"][0]
    # Nenhum destes pode ser None: sao os campos que a auditoria pediu no
    # contrato entre motor e IA.
    for campo in ("selection", "market", "odd", "probability", "confidence",
                  "edge", "ev", "data_quality", "market_sample",
                  "referee_signal", "match_context"):
        assert pick[campo] is not None, campo


def test_o_pipeline_monta_de_fato_os_aliases_do_contrato():
    import inspect
    fonte = inspect.getsource(fp._avaliar_fixture)
    for chave in ('"value_label"', '"taxa_real"', '"confidence"',
                  '"data_quality_score"', '"market_sample"',
                  '"referee_signal"', '"match_context"'):
        assert chave in fonte, chave


# --------------------------------------------------------------------------
# NO_PICK COM MOTIVO NOMEADO
# --------------------------------------------------------------------------

class _OddsVazio:
    def load_odds_by_fixture(self, _):
        return []


class _OddsSemFaltas:
    def load_odds_by_fixture(self, _):
        return [{"market_name": "Goals Over/Under", "value_name": "Over 2.5",
                 "odd": 1.9}]


def _fixture():
    return {"fixture_id": 1, "league_id": 71, "season": 2026,
            "home_team_id": 10, "away_team_id": 20,
            "home_team": "A", "away_team": "B", "referee": None}


def test_sem_odds_diz_sem_odds():
    c, motivo = fp._avaliar_fixture(_fixture(), None, _OddsVazio(), None)
    assert c is None and motivo == fp.SEM_ODDS


def test_odds_sem_linha_de_faltas_suportada_tem_motivo_proprio():
    c, motivo = fp._avaliar_fixture(_fixture(), None, _OddsSemFaltas(), None)
    assert c is None and motivo == fp.SEM_LINHA


def test_os_motivos_sao_distintos_entre_si():
    motivos = {fp.SEM_ODDS, fp.SEM_LINHA, fp.PROB_BAIXA, fp.EDGE_BAIXO,
               fp.PROJECAO_CURTA, fp.QUALIDADE_BAIXA,
               fp.AMOSTRA_INSUFICIENTE.format(n=10)}
    assert len(motivos) == 7


def test_o_log_grava_o_motivo_em_vez_do_generico():
    import inspect
    fonte = inspect.getsource(fp.run_faltas_engine)
    assert "log_skip(\"FALTAS_ENGINE\", fixture, motivo or MOTIVO_SEM_CANDIDATO)" in fonte


# --------------------------------------------------------------------------
# COERENCIA: edge e ev saem da probabilidade PUBLICADA
# --------------------------------------------------------------------------

def test_edge_e_ev_sao_recalculados_com_a_probabilidade_calibrada():
    import inspect
    fonte = inspect.getsource(fp._avaliar_fixture)
    # A ordem importa: recalcular DEPOIS de encolher, e reaplicar o EDGE_MIN.
    i_calibra = fonte.index('analise["probability"] = calibrada')
    i_edge = fonte.index('analise["edge"] = round(calibrada')
    i_recorte = fonte.index('if analise["edge"] < EDGE_MIN')
    assert i_calibra < i_edge < i_recorte


def test_prob_real_guarda_a_taxa_medida_e_confidence_a_calibrada():
    import inspect
    fonte = inspect.getsource(fp._salvar)
    assert 'c.get("probability_raw") or c["probability"]' in fonte
