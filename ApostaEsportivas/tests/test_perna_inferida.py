"""Ida ou volta, quando a API nao diz.

Medido em producao em 2026-08-10: os 8 jogos de oitavas da Libertadores no
banco vinham todos com round='Round of 16', sem "1st leg"/"2nd leg". Com isso
parse_leg devolvia None, is_jogo_de_volta ficava False sempre e
encontrar_jogo_de_ida nunca era consultado (estava atras de um `if leg != 2`).
Nas VOLTAS o motor trataria cada jogo como ida: sem agregado, sem saber quem
precisa do resultado, e sem os pontos de stakes da decisao.

A inferencia usa o que define ida e volta: o mando inverte. Quem visita hoje foi
o mandante da ida.
"""
import pytest

from services.pick_engine import context_gate
from services.pick_engine import match_context_model as mcm

CASA, FORA = 10, 20        # times do jogo de HOJE
LIGA, TEMPORADA = 13, 2026  # Libertadores


def _ida(match_date, mandante=FORA, visitante=CASA, gols_m=2, gols_v=1, liga=LIGA):
    """Jogo anterior entre os dois. Por padrao no mando invertido (o visitante
    de hoje recebendo), que e' a forma de uma ida."""
    return {"match_date": match_date, "league_id": liga, "season": TEMPORADA,
            "home_team_id": mandante, "away_team_id": visitante,
            "home_goals": gols_m, "away_goals": gols_v}


def _contexto(h2h, round_str="Round of 16", match_date="2026-08-18"):
    return context_gate.build_context(
        round_str=round_str, home_team_id=CASA, away_team_id=FORA,
        h2h_matches=h2h, league_id=LIGA, season=TEMPORADA,
        baseline_cartoes=4.0, match_date=match_date,
    )


# ─────────────────────────── o caso Libertadores ───────────────────────────


def test_volta_sem_rotulo_e_inferida_pelo_mando_invertido():
    tie = _contexto([_ida("2026-08-11")])["tie"]
    assert tie["fase"] == "OITAVAS"
    assert tie["leg"] == 2
    assert tie["leg_origem"] == "inferido"
    assert tie["is_jogo_de_volta"] is True
    # e o agregado da ida entra na conta: 2x1 pro time que hoje visita
    assert tie["placar_ida"]["gols_mandante_atual"] == 1     # CASA fez 1 fora
    assert tie["placar_ida"]["gols_visitante_atual"] == 2    # FORA fez 2 em casa
    assert tie["lider_agregado"] == "away"
    assert tie["precisa_de_resultado"] == "home"


def test_ida_continua_sendo_ida():
    """Sem encontro anterior no confronto, nada e' inferido."""
    tie = _contexto([])["tie"]
    assert tie["leg"] is None and tie["leg_origem"] is None
    assert tie["is_jogo_de_volta"] is False
    assert tie["placar_ida"] is None


def test_rotulo_explicito_vence_a_inferencia():
    """Quando a API diz, ela sabe -- inclusive pra dizer que e' IDA."""
    tie = _contexto([_ida("2026-08-11")], round_str="Round of 16 - 1st Leg")["tie"]
    assert tie["leg"] == 1
    assert tie["leg_origem"] == "rotulo"
    assert tie["is_jogo_de_volta"] is False


# ─────────────────────── o que a inferencia NAO pode confundir ───────────────


def test_jogo_do_mesmo_mando_nao_e_ida():
    """Se o time que visita hoje tambem visitou no encontro anterior, aquilo nao
    foi a ida de um mata-mata -- foi outra coisa (turno de grupo, campeonato)."""
    mesmo_mando = _ida("2026-08-11", mandante=CASA, visitante=FORA)
    tie = _contexto([mesmo_mando])["tie"]
    assert tie["leg"] is None
    assert tie["placar_ida"] is None


def test_jogo_de_grupo_meses_antes_nao_vira_ida():
    """Em Libertadores dois times do mesmo grupo podem se reencontrar no mata-
    mata. O encontro de marco nao e' a ida das oitavas de agosto."""
    tie = _contexto([_ida("2026-03-15")])["tie"]
    assert tie["leg"] is None
    assert tie["placar_ida"] is None


def test_outra_competicao_nao_vira_ida():
    tie = _contexto([_ida("2026-08-11", liga=71)])["tie"]
    assert tie["leg"] is None


def test_pontos_corridos_nunca_infere_perna():
    """Fase que nao e' mata-mata nao tem ida e volta pra inferir, mesmo com
    encontro recente no mando invertido (returno de campeonato)."""
    tie = context_gate.build_context(
        round_str="Regular Season - 21", home_team_id=CASA, away_team_id=FORA,
        h2h_matches=[_ida("2026-08-11", liga=72)], league_id=72, season=TEMPORADA,
        baseline_cartoes=4.0, match_date="2026-08-18",
    )["tie"]
    assert tie["fase"] is None
    assert tie["is_mata_mata"] is False
    assert tie["leg"] is None


def test_sem_data_da_partida_nao_infere():
    """Sem referencia nao da' pra aplicar a janela, e sem janela a inferencia
    confundiria grupo com mata-mata. Melhor voltar ao comportamento antigo."""
    tie = _contexto([_ida("2026-08-11")], match_date=None)["tie"]
    assert tie["leg"] is None


# ─────────────────────── o efeito no que o motor decide ───────────────────────


def test_volta_inferida_pesa_mais_que_ida():
    """stakes_score enxerga a decisao: volta soma +0.10, e agregado apertado
    soma mais. Era exatamente isso que se perdia sem o rotulo."""
    ida = mcm.stakes_score(_contexto([])["tie"])
    volta = mcm.stakes_score(_contexto([_ida("2026-08-11")])["tie"])
    assert volta > ida


def test_volta_com_agregado_empatado_e_o_cenario_mais_tenso():
    empatada = _contexto([_ida("2026-08-11", gols_m=1, gols_v=1)])["tie"]
    assert empatada["precisa_de_resultado"] == "ambos"
    decidida = _contexto([_ida("2026-08-11", gols_m=3, gols_v=0)])["tie"]
    assert mcm.stakes_score(empatada) > mcm.stakes_score(decidida)
