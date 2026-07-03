"""Modelo 1 (Dados Estatisticos): taxa de ocorrencia ponderada por
recencia e forca do adversario, feitos x cedidos, classificacao de
mercado, eficiencia ofensiva. Migrado de pick_math_service.py
(feature/pick-math-deterministico), reorganizado em pacote modular."""
from datetime import datetime, date

from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


def temporal_decay_weight(match_date, reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    if isinstance(match_date, str):
        match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
    if isinstance(match_date, datetime):
        match_date = match_date.date()
    reference_date = reference_date or date.today()
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    days_old = (reference_date - match_date).days
    for max_days, weight in config.temporal_tiers:
        if days_old <= max_days:
            return weight
    return config.temporal_default


def opponent_weight(rank, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    if rank is None:
        return config.opponent_unknown_weight
    if rank <= config.opponent_top_rank:
        return config.opponent_top_weight
    if rank <= config.opponent_mid_rank:
        return config.opponent_mid_weight
    return config.opponent_weak_weight


def sample_quality(n: int, config: PickEngineConfig = DEFAULT_CONFIG) -> dict:
    if n >= config.sample_rich_n:
        return {"label": "RICO", "Q": config.sample_rich_q}
    if n >= config.sample_moderate_n:
        return {"label": "MODERADO", "Q": config.sample_moderate_q}
    if n >= config.sample_scarce_n:
        return {"label": "ESCASSO", "Q": config.sample_scarce_q}
    return {"label": "VAZIO", "Q": config.sample_empty_q}


def weighted_rate(matches: list, hit_fn, reference_date=None, config: PickEngineConfig = DEFAULT_CONFIG) -> dict:
    """Taxa de ocorrencia (0-1) de um evento no historico, ponderada por
    forca do adversario (opponent_weight) e recencia (temporal_decay_weight).

    hit_fn(match) -> valor numerico (0/1 para taxa de ocorrencia, ou um
    float para medias) ja lido no contexto correto (casa/fora) pelo
    chamador.
    """
    n = len(matches)
    quality = sample_quality(n, config)
    if n == 0:
        return {
            "taxa_bruta": None, "taxa_ponderada": None,
            "amostra": 0, "amostra_label": quality["label"], "Q": quality["Q"],
        }

    values = [hit_fn(m) for m in matches]
    taxa_bruta = sum(values) / n

    weights = [
        opponent_weight(m.get("opponent_rank"), config)
        * temporal_decay_weight(m["match_date"], reference_date, config)
        for m in matches
    ]
    total_weight = sum(weights)
    taxa_ponderada = (
        sum(v * w for v, w in zip(values, weights)) / total_weight
        if total_weight > 0 else taxa_bruta
    )

    return {
        "taxa_bruta": round(taxa_bruta, 4),
        "taxa_ponderada": round(taxa_ponderada, 4),
        "amostra": n,
        "amostra_label": quality["label"],
        "Q": quality["Q"],
    }


_FAMILY_STAT_FIELDS = {
    "goals":   {"total": "total_goals",        "home": "home_goals",        "away": "away_goals"},
    "corners": {"total": "total_corners",      "home": "home_corners",      "away": "away_corners"},
    "cards":   {"total": "total_yellow_cards", "home": "home_yellow_cards", "away": "away_yellow_cards"},
}

_EXCLUDED_MARKET_KEYWORDS = (
    "handicap", "winner", "chance", "1x2", "half", "first half", "second half",
    "shot", "shots", "possession", "offside", "foul", "save",
)


def classify_market(market_name: str):
    """Deriva (familia, escopo) do nome (ingles, de odds_service) para os
    mercados cobertos pelo Modelo 1: goals|corners|cards|btts, escopo
    total|home|away. Mercados de resultado (1X2/Dupla Chance/Handicap) e
    de meio-tempo ficam fora do escopo (retorna None) -- nao ha dado
    historico de meio-tempo em last10_home/last10_away hoje."""
    name = market_name.lower()
    if any(kw in name for kw in _EXCLUDED_MARKET_KEYWORDS):
        return None
    if "both teams" in name and "score" in name:
        return ("btts", "total")
    if "corner" in name:
        if "home" in name:
            return ("corners", "home")
        if "away" in name:
            return ("corners", "away")
        return ("corners", "total")
    if "card" in name:
        if "home" in name:
            return ("cards", "home")
        if "away" in name:
            return ("cards", "away")
        return ("cards", "total")
    if "goal" in name:
        if "home" in name:
            return ("goals", "home")
        if "away" in name:
            return ("goals", "away")
        return ("goals", "total")
    return None


def pool_and_field(family: str, scope: str, last10_home: list, last10_away: list):
    if family == "btts":
        return last10_home + last10_away, None
    field = _FAMILY_STAT_FIELDS[family][scope]
    if scope == "home":
        return last10_home, field
    if scope == "away":
        return last10_away, field
    return last10_home + last10_away, field


def market_taxa(family: str, scope: str, value: str, line_str: str,
                last10_home: list, last10_away: list, reference_date=None,
                config: PickEngineConfig = DEFAULT_CONFIG):
    pool, field = pool_and_field(family, scope, last10_home, last10_away)
    if not pool:
        return None

    direction = (value or "").strip().lower()

    if family == "btts":
        # Mercados compostos existem na API (ex: "Results/Both Teams Score"
        # com value "Home/Yes", "Away/No") e batem no classify_market por
        # conterem "both teams"+"score" no nome -- mas nao sao BTTS puro.
        # Value precisa ser EXATAMENTE "yes"/"no", senao e um mercado
        # composto/desconhecido, fora do escopo (retorna None).
        if direction not in ("yes", "sim", "no", "não", "nao"):
            return None
        want_btts = direction in ("yes", "sim")

        def hit_fn(m):
            occurred = (m.get("home_goals") or 0) > 0 and (m.get("away_goals") or 0) > 0
            return 1 if occurred == want_btts else 0
    else:
        # Mesma logica: "Total Goals/Both Teams To Score" tem value tipo
        # "o/yes 2.5" que nao e nem "over" nem "under" puro -- rejeita.
        if direction not in ("over", "under"):
            return None
        try:
            line_val = float(line_str)
        except (TypeError, ValueError):
            return None
        is_over = direction == "over"

        def hit_fn(m):
            stat = m.get(field) or 0
            over = 1 if stat > line_val else 0
            return over if is_over else 1 - over

    return weighted_rate(pool, hit_fn, reference_date=reference_date, config=config)


_SCORED_CONCEDED_FIELDS = {
    "goals":   ("home_goals", "away_goals"),
    "corners": ("home_corners", "away_corners"),
    "cards":   ("home_yellow_cards", "away_yellow_cards"),
}


def scored_conceded_avg(matches: list, is_home_ctx: bool, family: str):
    """Media do que o time FAZ (feitos) e do que CEDE (cedidos) no
    historico, no contexto correto (casa/fora). Base da validacao
    feitos-vs-cedidos: toda estimativa de total precisa ser validada
    cruzando feitos de um lado com cedidos do outro, nao so olhar se
    jogos passados bateram a linha."""
    if not matches or family not in _SCORED_CONCEDED_FIELDS:
        return None, None
    home_f, away_f = _SCORED_CONCEDED_FIELDS[family]
    scored_k, conceded_k = (home_f, away_f) if is_home_ctx else (away_f, home_f)
    n = len(matches)
    scored = sum((m.get(scored_k) or 0) for m in matches) / n
    conceded = sum((m.get(conceded_k) or 0) for m in matches) / n
    return round(scored, 3), round(conceded, 3)


def expected_value_convergence(last10_home: list, last10_away: list, family: str, scope: str):
    """Duas estimativas independentes do valor esperado para a partida,
    uma pelo que cada time costuma FAZER, outra pelo que costuma CEDER --
    se convergem (<=15% de diferenca), e sinal forte; se divergem, e
    motivo pra desconfiar do mercado, nao so olhar taxa historica isolada.

    scope='total' (ex. Gols Mais/Menos): feitos_casa+feitos_fora vs
      cedidos_casa+cedidos_fora.
    scope='home' (ex. Total de Gols Casa): feitos do mandante vs cedidos
      do visitante fora (o adversario especifico deste jogo).
    scope='away': feitos do visitante fora vs cedidos do mandante em casa.
    """
    if family not in _SCORED_CONCEDED_FIELDS:
        return None

    h_scored, h_conceded = scored_conceded_avg(last10_home, True, family)
    a_scored, a_conceded = scored_conceded_avg(last10_away, False, family)
    if None in (h_scored, h_conceded, a_scored, a_conceded):
        return None

    if scope == "home":
        estimate_feitos, estimate_cedidos = h_scored, a_conceded
    elif scope == "away":
        estimate_feitos, estimate_cedidos = a_scored, h_conceded
    else:
        estimate_feitos, estimate_cedidos = h_scored + a_scored, h_conceded + a_conceded

    base = max(abs(estimate_feitos), abs(estimate_cedidos), 0.01)
    diff_pct = abs(estimate_feitos - estimate_cedidos) / base

    return {
        "estimate_feitos":   round(estimate_feitos, 2),
        "estimate_cedidos":  round(estimate_cedidos, 2),
        "expected_value":    round((estimate_feitos + estimate_cedidos) / 2, 2),
        "converged":         diff_pct <= 0.15,
        "diff_pct":          round(diff_pct, 3),
    }


def offensive_efficiency(matches: list, is_home_ctx: bool) -> dict | None:
    """NOVO na Fase 1: eficiencia ofensiva usando chutes no alvo e posse
    (dados que ja existem no banco -- match_statistics.home_shots_on/
    home_possession -- mas nunca chegavam ao calculo de picks ate agora,
    so eram usados no perfil tatico de selecoes). Sinal secundario para
    mercados de gols/BTTS -- nao substitui a taxa historica, complementa."""
    if not matches:
        return None
    shots_on_k = "home_shots_on" if is_home_ctx else "away_shots_on"
    goals_k = "home_goals" if is_home_ctx else "away_goals"
    possession_k = "home_possession" if is_home_ctx else "away_possession"

    with_shots = [m for m in matches if m.get(shots_on_k) is not None]
    if not with_shots:
        return None

    n = len(with_shots)
    total_shots_on = sum((m.get(shots_on_k) or 0) for m in with_shots)
    total_goals = sum((m.get(goals_k) or 0) for m in with_shots)
    avg_shots_on = round(total_shots_on / n, 2)
    conversion = round(total_goals / total_shots_on, 3) if total_shots_on > 0 else None

    with_possession = [m for m in with_shots if m.get(possession_k) is not None]
    avg_possession = (
        round(sum((m.get(possession_k) or 0) for m in with_possession) / len(with_possession), 1)
        if with_possession else None
    )

    return {
        "amostra": n,
        "avg_shots_on_target": avg_shots_on,
        "conversion_rate": conversion,
        "avg_possession": avg_possession,
    }
