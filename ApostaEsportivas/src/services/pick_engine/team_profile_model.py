"""Modelo 3 (Perfil das equipes): funcoes puras de perfil tatico/forma/
ofensivo/defensivo/disciplina/bolas-paradas, portadas dos metodos genericos
de national_team_profile_service.py (que ja eram estruturalmente
independentes de qualquer logica especifica de Copa do Mundo). Aqui viram
funcoes puras (matches, team_id) -> dict, reutilizaveis tanto para selecoes
quanto para clubes -- national_team_profile_service.py nao e alterado."""


def tactical_patterns(matches: list, team_id: int) -> dict:
    if not matches:
        return _default_tactical_profile()

    total_possession = total_shots = total_shots_on = 0
    total_passes = total_pass_accuracy = total_corners = total_fouls = 0
    count = 0

    for m in matches:
        is_home = m["home_team_id"] == team_id
        if is_home:
            total_possession += m.get("home_possession") or 0
            total_shots += m.get("home_total_shots") or 0
            total_shots_on += m.get("home_shots_on") or 0
            total_passes += m.get("home_passes") or 0
            total_pass_accuracy += m.get("home_passes_accuracy") or 0
            total_corners += m.get("home_corners") or 0
            total_fouls += m.get("home_fouls") or 0
        else:
            total_possession += m.get("away_possession") or 0
            total_shots += m.get("away_total_shots") or 0
            total_shots_on += m.get("away_shots_on") or 0
            total_passes += m.get("away_passes") or 0
            total_pass_accuracy += m.get("away_passes_accuracy") or 0
            total_corners += m.get("away_corners") or 0
            total_fouls += m.get("away_fouls") or 0
        count += 1

    if count == 0:
        return _default_tactical_profile()

    avg_possession = total_possession / count
    avg_shots = total_shots / count
    avg_shots_on = total_shots_on / count
    avg_passes = total_passes / count
    avg_pass_accuracy = total_pass_accuracy / count
    avg_corners = total_corners / count
    avg_fouls = total_fouls / count

    return {
        "style": _determine_playing_style(avg_possession, avg_shots, avg_passes),
        "avg_possession": round(avg_possession, 1),
        "avg_shots": round(avg_shots, 1),
        "avg_shots_on_target": round(avg_shots_on, 1),
        "shot_accuracy_pct": round((avg_shots_on / avg_shots * 100) if avg_shots > 0 else 0, 1),
        "avg_passes": round(avg_passes, 0),
        "avg_pass_accuracy": round(avg_pass_accuracy, 1),
        "avg_corners": round(avg_corners, 1),
        "avg_fouls": round(avg_fouls, 1),
        "pressing_intensity": _determine_pressing_intensity(avg_fouls, avg_possession),
    }


def _default_tactical_profile() -> dict:
    return {
        "style": "Dados insuficientes", "avg_possession": 0, "avg_shots": 0,
        "avg_shots_on_target": 0, "shot_accuracy_pct": 0, "avg_passes": 0,
        "avg_pass_accuracy": 0, "avg_corners": 0, "avg_fouls": 0,
        "pressing_intensity": "Desconhecida",
    }


def _determine_playing_style(possession: float, shots: float, passes: float) -> str:
    if possession >= 55 and passes >= 450:
        return "Posse de bola dominante"
    if possession >= 55:
        return "Posse de bola + Contra-ataque"
    if shots >= 14:
        return "Ataque direto e intenso"
    if possession <= 45:
        return "Contra-ataque rápido"
    return "Jogo equilibrado"


def _determine_pressing_intensity(fouls: float, possession: float) -> str:
    if fouls >= 13 and possession >= 52:
        return "Alta"
    if fouls >= 11:
        return "Média-Alta"
    if fouls >= 9:
        return "Média"
    return "Baixa"


def form_metrics(matches: list, team_id: int) -> dict:
    if not matches:
        return _default_form_metrics()

    results, wins, draws, losses = [], 0, 0, 0
    for m in matches:
        is_home = m["home_team_id"] == team_id
        home_goals = m.get("home_goals") or 0
        away_goals = m.get("away_goals") or 0
        scored, conceded = (home_goals, away_goals) if is_home else (away_goals, home_goals)
        if scored > conceded:
            results.append("W"); wins += 1
        elif scored == conceded:
            results.append("D"); draws += 1
        else:
            results.append("L"); losses += 1

    total = len(results)
    return {
        "sequence": "-".join(results),
        "last_5": "-".join(results[:5]),
        "games_played": total,
        "wins": wins, "draws": draws, "losses": losses,
        "win_rate": round(wins / total, 2) if total > 0 else 0,
        "draw_rate": round(draws / total, 2) if total > 0 else 0,
        "loss_rate": round(losses / total, 2) if total > 0 else 0,
    }


def _default_form_metrics() -> dict:
    return {
        "sequence": "", "last_5": "", "games_played": 0, "wins": 0, "draws": 0,
        "losses": 0, "win_rate": 0, "draw_rate": 0, "loss_rate": 0,
    }


def offensive_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_goals = total_shots = total_shots_on = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        if is_home:
            total_goals += m.get("home_goals") or 0
            total_shots += m.get("home_total_shots") or 0
            total_shots_on += m.get("home_shots_on") or 0
        else:
            total_goals += m.get("away_goals") or 0
            total_shots += m.get("away_total_shots") or 0
            total_shots_on += m.get("away_shots_on") or 0

    return {
        "goals_per_game": round(total_goals / count, 2),
        "shots_per_game": round(total_shots / count, 1),
        "shots_on_target_per_game": round(total_shots_on / count, 1),
        "shot_conversion_pct": round((total_goals / total_shots * 100) if total_shots > 0 else 0, 1),
    }


def defensive_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_goals_against = clean_sheets = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        goals_against = (m.get("away_goals") or 0) if is_home else (m.get("home_goals") or 0)
        total_goals_against += goals_against
        if goals_against == 0:
            clean_sheets += 1

    return {
        "goals_against_per_game": round(total_goals_against / count, 2),
        "clean_sheets": clean_sheets,
        "clean_sheets_pct": round(clean_sheets / count, 2),
    }


def discipline_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_fouls = total_yellow = total_red = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        if is_home:
            total_fouls += m.get("home_fouls") or 0
            total_yellow += m.get("home_yellow_cards") or 0
            total_red += m.get("home_red_cards") or 0
        else:
            total_fouls += m.get("away_fouls") or 0
            total_yellow += m.get("away_yellow_cards") or 0
            total_red += m.get("away_red_cards") or 0

    return {
        "fouls_per_game": round(total_fouls / count, 1),
        "yellow_cards_per_game": round(total_yellow / count, 1),
        "red_cards_per_game": round(total_red / count, 2),
    }


def set_pieces_stats(matches: list, team_id: int) -> dict:
    if not matches:
        return {}
    total_corners = 0
    count = len(matches)
    for m in matches:
        is_home = m["home_team_id"] == team_id
        total_corners += (m.get("home_corners") or 0) if is_home else (m.get("away_corners") or 0)

    return {"corners_per_game": round(total_corners / count, 1)}


def strengths_weaknesses(stats: dict) -> tuple:
    strengths, weaknesses = [], []
    offensive = stats.get("offensive", {})
    defensive = stats.get("defensive", {})
    tactical = stats.get("tactical", {})
    form = stats.get("form", {})

    goals_pg = offensive.get("goals_per_game", 0)
    if goals_pg >= 2.0:
        strengths.append(f"Ataque eficiente ({goals_pg} gols/jogo)")
    elif goals_pg < 1.0:
        weaknesses.append(f"Dificuldade para marcar gols ({goals_pg} gols/jogo)")

    goals_against = defensive.get("goals_against_per_game", 0)
    clean_sheets_pct = defensive.get("clean_sheets_pct", 0)
    if clean_sheets_pct >= 0.40:
        strengths.append(f"Defesa sólida ({int(clean_sheets_pct * 100)}% clean sheets)")
    elif goals_against >= 1.5:
        weaknesses.append(f"Defesa vulnerável ({goals_against} gols sofridos/jogo)")

    possession = tactical.get("avg_possession", 0)
    if possession >= 55:
        strengths.append(f"Domínio de posse de bola ({possession}%)")
    elif possession <= 45:
        weaknesses.append(f"Baixa posse de bola ({possession}%)")

    shot_accuracy = tactical.get("shot_accuracy_pct", 0)
    if shot_accuracy >= 40:
        strengths.append(f"Alta precisão nos chutes ({shot_accuracy}%)")

    win_rate = form.get("win_rate", 0)
    if win_rate >= 0.65:
        strengths.append(f"Excelente forma recente ({int(win_rate * 100)}% vitórias)")
    elif win_rate <= 0.35:
        weaknesses.append(f"Forma irregular ({int(win_rate * 100)}% vitórias)")

    if len(strengths) < 2:
        strengths.append("Análise baseada em dados limitados")
    if len(weaknesses) < 2:
        weaknesses.append("Análise baseada em dados limitados")

    return strengths[:4], weaknesses[:3]


def build_profile(matches: list, team_id: int) -> dict:
    """Monta o perfil completo (tatico/forma/ofensivo/defensivo/disciplina/
    bolas-paradas/pontos-fortes-fracos) a partir de jogos ja buscados --
    funciona tanto com match_stats_service.py (clubes) quanto com o
    _fetch_recent_matches de national_team_profile_service.py (selecoes),
    pois ambos devolvem o mesmo formato de linha."""
    tactical = tactical_patterns(matches, team_id)
    form = form_metrics(matches, team_id)
    offensive = offensive_stats(matches, team_id)
    defensive = defensive_stats(matches, team_id)
    discipline = discipline_stats(matches, team_id)
    set_pieces = set_pieces_stats(matches, team_id)
    strengths, weaknesses = strengths_weaknesses({
        "offensive": offensive, "defensive": defensive,
        "tactical": tactical, "form": form,
    })

    return {
        "team_id": team_id,
        "matches_analyzed": len(matches),
        "tactical_profile": tactical,
        "form": form,
        "offensive_stats": offensive,
        "defensive_stats": defensive,
        "discipline_stats": discipline,
        "set_pieces_stats": set_pieces,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


_PRESSING_SCORE = {"Alta": 2, "Média-Alta": 1, "Média": 0, "Baixa": -1, "Desconhecida": 0}

# Baselines de referencia (media tipica de futebol profissional) usados so
# como ponto zero do delta -- nao sao "ajuste" arbitrario, so o centro da
# escala pra decidir se o delta pende pra Over ou Under.
_CORNERS_BASELINE = 9.5
_CARDS_BASELINE = 20.0


def compare_matchup(profile_home: dict, profile_away: dict) -> dict:
    """Compara os perfis de casa e fora e devolve deltas numericos por
    familia de mercado (goals/corners/cards). Cada delta e soma de
    componentes explicitos (sempre expostos em 'components'), nunca um
    numero ajustado sem conta rastreavel."""
    off_h, off_a = profile_home.get("offensive_stats", {}), profile_away.get("offensive_stats", {})
    def_h, def_a = profile_home.get("defensive_stats", {}), profile_away.get("defensive_stats", {})
    tac_h, tac_a = profile_home.get("tactical_profile", {}), profile_away.get("tactical_profile", {})
    disc_h, disc_a = profile_home.get("discipline_stats", {}), profile_away.get("discipline_stats", {})
    sp_h, sp_a = profile_home.get("set_pieces_stats", {}), profile_away.get("set_pieces_stats", {})

    combined_goals_avg = round((off_h.get("goals_per_game", 0) + off_a.get("goals_per_game", 0)), 2)
    combined_defense_solidity = round(
        (def_h.get("clean_sheets_pct", 0) + def_a.get("clean_sheets_pct", 0)) / 2, 2
    )
    goals_delta = round(combined_goals_avg - combined_defense_solidity * 2.5, 2)

    combined_corners_avg = round(sp_h.get("corners_per_game", 0) + sp_a.get("corners_per_game", 0), 2)
    possession_styles = {tac_h.get("style"), tac_a.get("style")}
    possession_bonus = 1.0 if "Posse de bola dominante" in possession_styles else 0.0
    corners_delta = round(combined_corners_avg + possession_bonus - _CORNERS_BASELINE, 2)

    combined_fouls_avg = round(disc_h.get("fouls_per_game", 0) + disc_a.get("fouls_per_game", 0), 2)
    pressing_score = (
        _PRESSING_SCORE.get(tac_h.get("pressing_intensity"), 0)
        + _PRESSING_SCORE.get(tac_a.get("pressing_intensity"), 0)
    )
    cards_delta = round((combined_fouls_avg - _CARDS_BASELINE) / 10 + pressing_score * 0.15, 2)

    def label(delta):
        if delta > 0.15:
            return "Over"
        if delta < -0.15:
            return "Under"
        return "neutro"

    return {
        "goals": {
            "delta": goals_delta, "label": label(goals_delta),
            "components": {
                "combined_goals_per_game": combined_goals_avg,
                "combined_defense_solidity_pct": combined_defense_solidity,
            },
        },
        "corners": {
            "delta": corners_delta, "label": label(corners_delta),
            "components": {
                "combined_corners_per_game": combined_corners_avg,
                "possession_dominant_bonus": possession_bonus,
                "baseline": _CORNERS_BASELINE,
            },
        },
        "cards": {
            "delta": cards_delta, "label": label(cards_delta),
            "components": {
                "combined_fouls_per_game": combined_fouls_avg,
                "pressing_score": pressing_score,
                "baseline": _CARDS_BASELINE,
            },
        },
    }


def profile_score_for_market(matchup: dict | None, market_type: str) -> float | None:
    """Reduz o delta de compare_matchup (para a familia de mercado do
    candidato) a um score 0-1 (0.5=neutro) para uso no Score Final
    (ranking.py::final_score). Delta tipico fica entre -2 e +2; escala
    suave para nao dominar o score."""
    if not matchup:
        return None
    entry = matchup.get(market_type)
    if not entry:
        return 0.5
    delta = entry.get("delta", 0.0)
    return round(max(min(0.5 + delta * 0.15, 1.0), 0.0), 4)
