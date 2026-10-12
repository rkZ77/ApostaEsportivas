"""O "Final" das pernas antigas sai da folha gravada (12/10/2026). Sem banco."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import finais_antigos as fa  # noqa: E402

FOLHA = {
    "status": "FT", "home_goals": 2, "away_goals": 1, "home_goals_ht": 0, "away_goals_ht": 1,
    "home_corners": 7, "away_corners": 4, "home_corners_1h": 3, "away_corners_1h": 1,
    "home_yellow_cards": 3, "away_yellow_cards": 2, "home_red_cards": 1, "away_red_cards": 0,
    "valid_yellow_home": 2, "valid_yellow_away": 2, "valid_red_home": 1, "valid_red_away": 0,
}


def test_escanteios_do_jogo_e_do_1o_tempo():
    assert fa.valor_final("Escanteios Mais/Menos", "corners", "Under 10.5", FOLHA) == 11
    assert fa.valor_final("Total de Escanteios (1º Tempo)", "corners_1h", "Under 4.5", FOLHA) == 4


def test_escanteios_de_um_lado():
    assert fa.valor_final("Escanteios Visitante Mais/Menos", "corners", "Under 5.5", FOLHA) == 4


def test_gols_do_jogo_e_do_1o_tempo():
    assert fa.valor_final("Gols Mais/Menos", "goals", "Over 2.5", FOLHA) == 3
    assert fa.valor_final("Gols Mais/Menos - 1º Tempo", "goals_1h", "Under 1.5", FOLHA) == 1


def test_cartao_usa_so_a_contagem_validada():
    """Crua daria 3+2+2*1 = 7; validada (banco fora) e' 2+2+2*1 = 6."""
    assert fa.valor_final("Cartões Mais/Menos", "cards", "Under 6.5", FOLHA) == 6
    sem_validacao = {**FOLHA, "valid_yellow_home": None}
    assert fa.valor_final("Cartões Mais/Menos", "cards", "Under 6.5", sem_validacao) is None


def test_prorrogacao_so_gol_pelos_90():
    aet = {**FOLHA, "status": "AET", "home_goals_90": 1, "away_goals_90": 1}
    assert fa.valor_final("Gols Mais/Menos", "goals", "Over 2.5", aet) == 2
    assert fa.valor_final("Escanteios Mais/Menos", "corners", "Under 10.5", aet) is None


def test_sem_folha_ou_jogo_aberto_ou_2o_tempo_nao_inventa():
    assert fa.valor_final("Gols Mais/Menos", "goals", "Over 2.5", None) is None
    assert fa.valor_final("Gols Mais/Menos", "goals", "Over 2.5", {**FOLHA, "status": "2H"}) is None
    assert fa.valor_final("Gols Mais/Menos - 2º Tempo", None, "Over 1.5", FOLHA) is None
    sem_escanteio = {k: v for k, v in FOLHA.items() if "corners" not in k}
    assert fa.valor_final("Escanteios Mais/Menos", "corners", "Under 10.5", sem_escanteio) is None
