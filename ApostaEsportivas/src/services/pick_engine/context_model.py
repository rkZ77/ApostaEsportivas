"""Modelo 2 (Contexto): mando de campo, dias de descanso e uma aproximacao
de pressao de tabela. Descanso e mando sao exatos (dados ja existentes);
pressao de tabela e uma APROXIMACAO deliberada -- a tabela `fixtures` nao
tem round/stage/jogos-restantes, entao deteccao real de mata-mata/must-win
nao e possivel hoje (ver plano Fase 2). Nunca declarar "must_win" ou
"mata-mata" a partir daqui -- so um sinal de pressao, sempre com os
numeros brutos (rank/saldo/pontos) expostos junto."""
from datetime import datetime, date
from services.pick_engine.competition_profile import is_neutral_venue

_PRESSURE_LABELS = {
    "briga_topo": "Disputando posicoes de topo da tabela",
    "pressao_alta": "Zona de risco na tabela (saldo de gols muito negativo)",
    "pressao_moderada": "Alguma pressao na tabela (saldo de gols negativo)",
    "neutro": "Sem pressao de tabela aparente",
    "desconhecido": "Posicao na tabela desconhecida",
}


def rest_days(matches: list, team_id: int, reference_date=None):
    """Dias desde o ultimo jogo do time (o mais recente <= reference_date).
    Usa o match_date ja presente no historico -- sem nova query."""
    reference_date = reference_date or date.today()
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    played_dates = []
    for m in matches:
        d = m.get("match_date")
        if d is None:
            continue
        if isinstance(d, str):
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        if isinstance(d, datetime):
            d = d.date()
        if d <= reference_date:
            played_dates.append(d)

    if not played_dates:
        return None
    return (reference_date - max(played_dates)).days


def table_pressure(standings_row: dict | None) -> dict:
    """Aproximacao de pressao de tabela via rank/pontos/saldo de gols.
    NAO e deteccao de mata-mata/must-win real (falta jogos-restantes/round
    no schema) -- rotulo e sempre acompanhado dos numeros brutos."""
    if not standings_row:
        return {"label": "desconhecido", "is_approximation": True,
                "rank": None, "points": None, "goal_diff": None, "played": None}

    rank = standings_row.get("rank")
    goal_diff = standings_row.get("goal_diff")
    played = standings_row.get("played")

    if rank is None:
        label = "desconhecido"
    elif rank <= 4:
        label = "briga_topo"
    elif goal_diff is not None and goal_diff <= -5 and (played or 0) >= 5:
        label = "pressao_alta"
    elif goal_diff is not None and goal_diff <= -2:
        label = "pressao_moderada"
    else:
        label = "neutro"

    return {
        "label": label,
        "description": _PRESSURE_LABELS[label],
        "is_approximation": True,
        "rank": rank,
        "points": standings_row.get("points"),
        "goal_diff": goal_diff,
        "played": played,
    }


def home_advantage_context(league_id) -> dict:
    """Mando de campo normal, exceto competicoes de sede neutra (Copa do
    Mundo hoje -- ver services.pick_engine.competition_profile, fonte unica
    de verdade pra isso)."""
    is_neutral = is_neutral_venue(league_id)
    return {
        "is_neutral_venue": is_neutral,
        "note": (
            "Copa do Mundo: sede neutra, sem vantagem de mando para nenhuma selecao"
            if is_neutral else "Mando de campo normal"
        ),
    }


def build_context(home_matches: list, away_matches: list, home_team_id: int, away_team_id: int,
                   home_standing: dict | None, away_standing: dict | None,
                   league_id, reference_date=None) -> dict:
    reference_date = reference_date or date.today()
    return {
        "rest_days_home": rest_days(home_matches, home_team_id, reference_date),
        "rest_days_away": rest_days(away_matches, away_team_id, reference_date),
        "table_pressure_home": table_pressure(home_standing),
        "table_pressure_away": table_pressure(away_standing),
        "venue": home_advantage_context(league_id),
    }


def context_score(context: dict) -> float:
    """Reduz o contexto a um score numerico (0-1, neutro=0.5) para somar no
    Score Final -- ajustes pequenos e limitados, nunca uma certeza. Toda
    parcela e rastreavel a um campo do context dict."""
    score = 0.5

    rh, ra = context.get("rest_days_home"), context.get("rest_days_away")
    if rh is not None and ra is not None:
        diff = rh - ra
        score += max(min(diff / 3 * 0.05, 0.10), -0.10)

    for side in ("table_pressure_home", "table_pressure_away"):
        if context.get(side, {}).get("label") == "pressao_alta":
            score += 0.03

    return round(max(min(score, 1.0), 0.0), 4)
