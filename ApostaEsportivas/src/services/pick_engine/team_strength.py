"""Team Strength Score: agrega os componentes ja calculados separadamente
por team_profile_model.build_profile() (ataque/defesa/forma/disciplina/
bolas-paradas) num unico score 0-100 -- nao recalcula nada, so normaliza e
combina o que ja existe. Util pra comparar duas equipes de forma direta
(ex.: "Portugal 84 x Espanha 79") em mercados de resultado/handicap/dupla
chance, onde o delta bruto do compare_matchup (por familia goals/corners/
cards) nao da uma leitura unica de "quem e mais forte no geral"."""

# Pesos dos componentes (somam 1.0) -- ataque e defesa pesam mais porque
# sao os fundamentos mais diretamente ligados a resultado de partida; forma
# recente entra com peso proprio por capturar momento (nao so qualidade
# estrutural); disciplina e bolas-paradas sao sinais secundarios.
_W_ATTACK = 0.30
_W_DEFENSE = 0.30
_W_FORM = 0.25
_W_DISCIPLINE = 0.05
_W_SET_PIECES = 0.10

# Escalas de referencia pra normalizar cada metrica bruta em 0-100 --
# valores tipicos de futebol profissional usados como teto/piso (nao sao
# "ajuste" arbitrario por time, sao a mesma escala pra todos).
_GOALS_PG_CEILING = 3.0
_SHOT_CONVERSION_CEILING = 40.0
_GOALS_AGAINST_CEILING = 3.0
_YELLOW_PG_CEILING = 5.0
_CORNERS_PG_CEILING = 8.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _attack_score(offensive_stats: dict) -> float:
    goals_pg = offensive_stats.get("goals_per_game", 0) or 0
    conversion = offensive_stats.get("shot_conversion_pct", 0) or 0
    goals_component = _clamp01(goals_pg / _GOALS_PG_CEILING)
    conversion_component = _clamp01(conversion / _SHOT_CONVERSION_CEILING)
    return (goals_component * 0.65 + conversion_component * 0.35) * 100


def _defense_score(defensive_stats: dict) -> float:
    goals_against = defensive_stats.get("goals_against_per_game", 0) or 0
    clean_sheets_pct = defensive_stats.get("clean_sheets_pct", 0) or 0
    solidity_component = _clamp01(1 - goals_against / _GOALS_AGAINST_CEILING)
    clean_sheet_component = _clamp01(clean_sheets_pct)
    return (solidity_component * 0.6 + clean_sheet_component * 0.4) * 100


def _form_score(form: dict) -> float:
    win_rate = form.get("win_rate", 0) or 0
    draw_rate = form.get("draw_rate", 0) or 0
    # Empate vale meio ponto de "forma" (nem derrota nem vitoria) --
    # mesma logica de pontos corridos (V=1, E=0.5, D=0).
    return _clamp01(win_rate + draw_rate * 0.5) * 100


def _discipline_score(discipline_stats: dict) -> float:
    yellow_pg = discipline_stats.get("yellow_cards_per_game", 0) or 0
    return _clamp01(1 - yellow_pg / _YELLOW_PG_CEILING) * 100


def _set_pieces_score(set_pieces_stats: dict) -> float:
    corners_pg = set_pieces_stats.get("corners_per_game", 0) or 0
    return _clamp01(corners_pg / _CORNERS_PG_CEILING) * 100


def team_strength_score(profile: dict) -> dict:
    """Recebe um profile ja montado por team_profile_model.build_profile()
    e devolve o score 0-100 + o detalhamento por componente (sempre exposto,
    nunca um numero opaco)."""
    attack = _attack_score(profile.get("offensive_stats", {}))
    defense = _defense_score(profile.get("defensive_stats", {}))
    form = _form_score(profile.get("form", {}))
    discipline = _discipline_score(profile.get("discipline_stats", {}))
    set_pieces = _set_pieces_score(profile.get("set_pieces_stats", {}))

    total = (
        attack * _W_ATTACK + defense * _W_DEFENSE + form * _W_FORM
        + discipline * _W_DISCIPLINE + set_pieces * _W_SET_PIECES
    )

    return {
        "score": round(total, 1),
        "components": {
            "attack": round(attack, 1),
            "defense": round(defense, 1),
            "form": round(form, 1),
            "discipline": round(discipline, 1),
            "set_pieces": round(set_pieces, 1),
        },
    }


def compare_team_strength(profile_home: dict, profile_away: dict) -> dict:
    """Score dos dois times + diferenca (positivo = casa mais forte)."""
    home = team_strength_score(profile_home)
    away = team_strength_score(profile_away)
    return {
        "home": home,
        "away": away,
        "diff": round(home["score"] - away["score"], 1),
    }
