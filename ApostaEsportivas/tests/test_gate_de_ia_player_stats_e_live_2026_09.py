"""O gate de IA nos dois motores que nao tinham: Player Stats e ao vivo.

O modo de falha que estes testes guardam nao e' "o gate nao roda" -- e' o
gate rodando com o payload EM BRANCO. `build_review_payload` nasceu dos
motores de mercado de time e le nomes (`market_name`, `taxa_real`) que nem o
Player Stats nem o ao vivo usam: sem tradutor, a chamada acontece, custa
dinheiro, grava evento no painel e a IA opina sobre um pick vazio.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine_pipelines.player_stats_pipeline import _pick_para_ia as ps_para_ia
from engine_pipelines.live_pipeline import _pick_para_ia as live_para_ia
from services.pick_engine.ai_review import build_review_payload, DEFAULT_PROVIDERS


class _Metodo:
    label, slug = "Chutes no alvo", "shots_on"


def test_player_stats_chega_na_ia_com_o_pick_preenchido():
    c = {
        "analise": {"odd": 1.80, "probability": 0.71, "edge": 0.09,
                    "ev": 0.12, "amostra": 8},
        "jogador": {"player_name": "Fulano", "team_name": "Time A"},
        "metodo": _Metodo(), "rotulo_linha": "2 ou mais chutes no alvo",
        "composicao": {"atuacoes": 8},
    }
    pick = build_review_payload([ps_para_ia(c)], "player_stats")["picks"][0]
    assert pick["odd"] == 1.80
    assert pick["probability"] == 0.71
    assert pick["market"] == "Chutes no alvo"
    # QUEM e' o jogador precisa atravessar: e' o que distingue prop de jogador
    # de mercado de time, e sem isso a IA nao tem sobre o que opinar.
    assert "Fulano" in pick["selection"]


def test_live_chega_na_ia_com_o_minuto_e_o_ja_observado():
    candidato = {"familia": "corners", "market": "Escanteios Mais/Menos",
                 "line": "Over 9.5", "linha": 9.5, "odd": 1.95,
                 "probability": 0.68, "confidence": 0.7, "edge": 0.06, "ev": 0.10}
    estado = {"minuto": 80, "home_goals": 1, "away_goals": 0, "corners_total": 4}
    pick = build_review_payload([live_para_ia(candidato, estado)], "live")["picks"][0]
    assert pick["odd"] == 1.95
    # Sem minuto e contador, "Over 9.5 aos 80 com 4" e "aos 20 com 4" viram o
    # mesmo pick pra quem le' o payload.
    assert pick["match_context"]["minuto"] == 80
    assert pick["match_context"]["ja_observado"] == 4


def test_os_dois_motores_usam_openai():
    assert DEFAULT_PROVIDERS["player_stats"] == "openai"
    assert DEFAULT_PROVIDERS["live"] == "openai"
