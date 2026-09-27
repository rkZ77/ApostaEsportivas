# -*- coding: utf-8 -*-
"""Dossie da partida e falha do provedor de IA (2026-09-27).

O dossie e' o que a IA le' antes do parecer; a falha do provedor passou a ser
classificada, gravada e, em enforce, a bloquear o pick. Nada toca banco.
"""
import pytest

from collectors.lineups_collector_service import ler_escalacao
from services.pick_engine import ai_review, dossie_da_partida as d
from services.pick_engine.ai_review import AIReviewGate, AIReviewSettings, classificar_falha

CASA, FORA = 10, 20


def jogo(mandante, gols_m, gols_v, esc_m=5, esc_v=4, ht_m=None, ht_v=None):
    return {"home_team_id": mandante, "away_team_id": 99 if mandante != 99 else 98,
            "home_goals": gols_m, "away_goals": gols_v,
            "home_goals_ht": ht_m, "away_goals_ht": ht_v,
            "home_corners": esc_m, "away_corners": esc_v,
            "home_yellow_cards": 1, "away_yellow_cards": 2,
            "home_red_cards": 0, "away_red_cards": 0}


def test_medias_feitas_e_cedidas_no_mando_do_jogo():
    hist = [jogo(CASA, 2, 0), jogo(CASA, 1, 1), jogo(CASA, 3, 2),
            {**jogo(99, 0, 4), "away_team_id": CASA}]   # jogo fora, fica de fora
    m = d.medias_do_time(hist, CASA, "home")
    assert m["gols"]["feitos"]["media"] == 2.0
    assert m["gols"]["cedidos"]["media"] == 1.0
    assert m["gols"]["feitos"]["n"] == 3
    assert m["cartoes"]["feitos"]["media"] == 1.0


def test_metrica_sem_amostra_minima_nao_entra():
    """Dois jogos com 1o tempo nao descrevem ninguem -- a chave some."""
    hist = [jogo(CASA, 1, 0, ht_m=1, ht_v=0), jogo(CASA, 1, 0, ht_m=0, ht_v=0), jogo(CASA, 1, 0)]
    assert "gols_1t" not in d.medias_do_time(hist, CASA, "home")


def test_forma_recente():
    hist = [jogo(CASA, 2, 0), jogo(CASA, 1, 1), jogo(CASA, 0, 1)]
    f = d.forma(hist, CASA)
    assert f["sequencia"] == "VED"


def test_rodizio_e_troca_de_tecnico():
    base = list(range(1, 12))
    escal = [("d3", base[:6] + [20, 21, 22, 23, 24]), ("d2", base), ("d1", base)]
    r = d.rodizio(escal, [("4-3-3", "Novo"), ("4-4-2", "Antigo"), ("4-4-2", "Antigo")])
    assert r["trocas_por_jogo"] == [5, 0]
    assert r["titulares_em_todos"] == 6
    assert r["tecnico_mudou"] == {"atual": "Novo", "anterior": "Antigo"}


def test_escalacao_da_api():
    item = {"team": {"id": 7}, "formation": "4-3-3", "coach": {"id": 1, "name": "X"},
            "startXI": [{"player": {"id": i}} for i in range(1, 12)],
            "substitutes": [{"player": {"id": 50}}, {"player": {}}]}
    linha = ler_escalacao(item)
    assert linha["titulares"] == list(range(1, 12))
    assert linha["reservas"] == [50]


@pytest.mark.parametrize("erro, tipo", [
    ("Error code: 400 - {'error': {'message': 'Your credit balance is too low'}}", "sem_credito"),
    ("Error code: 429 - insufficient_quota: You exceeded your current quota", "sem_credito"),
    ("Error code: 401 - invalid x-api-key", "chave_invalida"),
    ("Error code: 429 - rate_limit_error", "limite_de_taxa"),
    ("Error code: 529 - overloaded_error", "provedor_fora"),
    ("model_not_found: gpt-9", "modelo_invalido"),
    ("algo estranho", "erro"),
])
def test_classificacao_da_falha(erro, tipo):
    assert classificar_falha(erro) == tipo


def test_falha_nao_entra_no_cache(monkeypatch):
    gravados = []
    gate = AIReviewGate(AIReviewSettings(mode="shadow"),
                        call_model=lambda *_: (_ for _ in ()).throw(RuntimeError("overloaded 529")))
    monkeypatch.setattr(gate, "_store_cache", lambda *a: gravados.append(a))
    monkeypatch.setattr(gate, "_load_cache", lambda key: None)
    monkeypatch.setattr(gate, "_daily_limit_reached", lambda: False)
    monkeypatch.setattr(gate, "_record_event", lambda *a: None)
    review = gate.review([{"market_name": "x"}], "vip")
    assert review["erro_tipo"] == "provedor_fora"
    assert review["decision"] == "approve"          # shadow nao bloqueia
    assert gravados == []


def test_dossie_entra_no_payload_so_quando_existe():
    sem = ai_review.build_review_payload([{}], "vip")
    com = ai_review.build_review_payload([{}], "vip", dossies={"1": {"rodada": "R1"}})
    assert "dossie" not in sem
    assert com["dossie"] == {"1": {"rodada": "R1"}}


# ---------------------------------------------------------------------------
# Desfalque e tecnico no Score Final; ritmo por tempo no ao vivo
# ---------------------------------------------------------------------------
from services.pick_engine import news_model
from services.pick_engine_live import residual_model as rm


def test_so_titular_recente_fora_do_jogo_pesa():
    desf = [
        {"jogador": "Titular", "tipo": "Missing Fixture", "titular_nos_ultimos_jogos": 4},
        {"jogador": "Emprestado", "tipo": "Missing Fixture", "titular_nos_ultimos_jogos": 0},
        {"jogador": "Duvida", "tipo": "Questionable", "titular_nos_ultimos_jogos": 3},
    ]
    lado = d._sinal_do_lado(desf, {"tecnico_mudou": {"atual": "A", "anterior": "B"}})
    assert lado == {"titulares_desfalcados": ["Titular"], "outros_desfalcados": ["Duvida"],
                    "tecnico_mudou": True}


def test_desfalque_e_tecnico_novo_so_derrubam_o_score():
    neutro = {"home": {"titulares_desfalcados": [], "outros_desfalcados": []},
              "away": {"titulares_desfalcados": [], "outros_desfalcados": []}}
    assert news_model.news_score(neutro) == 0.5
    com = {"home": {"titulares_desfalcados": ["X"], "outros_desfalcados": [], "tecnico_mudou": True},
           "away": {"titulares_desfalcados": [], "outros_desfalcados": ["Y"]}}
    assert news_model.news_score(com) == round(0.5 - (0.08 + 0.08 + 0.02), 4)


def test_motor_desfalques_desliga(monkeypatch):
    monkeypatch.setenv("MOTOR_DESFALQUES", "off")
    assert d.sinal_de_desfalques(123) is None


@pytest.mark.parametrize("minuto, status", [(20, "1H"), (45, "HT"), (70, "2H")])
def test_ritmo_por_tempo_com_meio_a_meio_e_a_conta_antiga(minuto, status):
    antigo = rm.lambda_residual("corners", 5, minuto, status, 10.0)
    novo = rm.lambda_residual("corners", 5, minuto, status, 10.0, fracao_1t=0.5)
    assert novo["lambda_residual"] == pytest.approx(antigo["lambda_residual"], abs=1e-3)


def test_segundo_tempo_mais_forte_aumenta_o_que_falta_no_intervalo():
    uniforme = rm.lambda_residual("corners", 5, 45, "HT", 10.0)["lambda_residual"]
    medido = rm.lambda_residual("corners", 5, 45, "HT", 10.0, fracao_1t=0.40)["lambda_residual"]
    assert medido > uniforme


def test_parcela_ate():
    assert rm.parcela_ate(45, 0.4) == pytest.approx(0.4)
    assert rm.parcela_ate(90, 0.4) == pytest.approx(1.0)
    assert rm.parcela_ate(0, 0.4) == 0
