from datetime import datetime, date

from services.match_stats_service import MatchStatsService

opponent_weight = MatchStatsService._opponent_weight


def temporal_decay_weight(match_date, reference_date=None) -> float:
    if isinstance(match_date, str):
        match_date = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
    if isinstance(match_date, datetime):
        match_date = match_date.date()
    reference_date = reference_date or date.today()
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    days_old = (reference_date - match_date).days
    if days_old <= 14:
        return 1.0
    if days_old <= 30:
        return 0.85
    if days_old <= 60:
        return 0.70
    return 0.50


def sample_quality(n: int) -> dict:
    if n >= 8:
        return {"label": "RICO", "Q": 1.00}
    if n >= 4:
        return {"label": "MODERADO", "Q": 0.75}
    if n >= 1:
        return {"label": "ESCASSO", "Q": 0.45}
    return {"label": "VAZIO", "Q": 0.20}


def weighted_rate(matches: list, hit_fn, reference_date=None) -> dict:
    """Taxa de ocorrência (0-1) de um evento no histórico, ponderada por
    força do adversário (opponent_weight) e recência (temporal_decay_weight).

    hit_fn(match) -> valor numérico (0/1 para taxa de ocorrência, ou um float
    para médias como gols/escanteios por jogo) já lido no contexto correto
    (casa/fora) pelo chamador.
    """
    n = len(matches)
    quality = sample_quality(n)
    if n == 0:
        return {
            "taxa_bruta": None, "taxa_ponderada": None,
            "amostra": 0, "amostra_label": quality["label"], "Q": quality["Q"],
        }

    values = [hit_fn(m) for m in matches]
    taxa_bruta = sum(values) / n

    weights = [
        opponent_weight(m.get("opponent_rank")) * temporal_decay_weight(m["match_date"], reference_date)
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


def confidence_score(C: float, Q: float, K: float) -> float:
    raw = (C * 0.45) + (Q * 0.25) + (K * 0.30)
    return round(min(max(raw, 0.20), 0.92), 4)


def implied_prob(odd: float) -> float:
    return round(1 / odd, 4) if odd and odd > 0 else 0.0


def no_vig_pair_prob(odd_a: float, odd_b: float):
    if not odd_a or not odd_b or odd_a <= 1.0 or odd_b <= 1.0:
        return None, None
    ia, ib = 1 / odd_a, 1 / odd_b
    total = ia + ib
    return round(ia / total, 4), round(ib / total, 4)


def resolve_prob_baseline(entry: dict, sibling_entry: dict = None) -> dict:
    """Probabilidade implícita de mercado para usar como baseline do edge.
    Usa no-vig quando o par complementar (Over/Under, Yes/No) tem cobertura
    de >=2 bookmakers dos dois lados; caso contrário cai para 1/best_odd.
    """
    if (
        sibling_entry
        and entry.get("bookmakers_count", 0) >= 2
        and sibling_entry.get("bookmakers_count", 0) >= 2
    ):
        prob_a, prob_b = no_vig_pair_prob(entry["best_odd"], sibling_entry["best_odd"])
        if prob_a is not None:
            return {"prob": prob_a, "source": "no_vig"}

    return {"prob": implied_prob(entry["best_odd"]), "source": "implied"}


def edge_and_ev(taxa_real: float, odd: float, prob_baseline: float) -> dict:
    edge = round(taxa_real - prob_baseline, 4)
    ev = round(taxa_real * odd - 1, 4)
    return {"edge": edge, "ev": ev}


def select_smart_safe_line(line_candidates: list) -> dict | None:
    """line_candidates: lista de dicts com pelo menos
    {line, odd, taxa_real, edge, ev}. Aplica o processo obrigatório da
    seção SMART SAFE LINE do prompt: descarta odd<1.60, edge<5%, EV<=0;
    entre as que sobram escolhe maior taxa_real (empate: maior edge).
    """
    if not line_candidates:
        return None

    passed = [
        c for c in line_candidates
        if c["odd"] >= 1.60 and c["edge"] >= 0.05 and c["ev"] > 0
    ]
    pool = passed or [c for c in line_candidates if c["odd"] >= 1.01]
    if not pool:
        return None

    return max(pool, key=lambda c: (c["taxa_real"], c["edge"]))


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
    mercados cobertos pelo calculo deterministico: goals|corners|cards|btts,
    escopo total|home|away. Mercados de resultado (1X2/Dupla Chance/Handicap)
    e mercados de meio-tempo ficam fora do escopo (retorna None) -- nao ha
    dado historico de meio-tempo em last10_home/last10_away hoje."""
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


def _pool_and_field(family: str, scope: str, last10_home: list, last10_away: list):
    if family == "btts":
        return last10_home + last10_away, None
    field = _FAMILY_STAT_FIELDS[family][scope]
    if scope == "home":
        return last10_home, field
    if scope == "away":
        return last10_away, field
    return last10_home + last10_away, field


def _market_taxa(family: str, scope: str, value: str, line_str: str,
                  last10_home: list, last10_away: list, reference_date=None):
    pool, field = _pool_and_field(family, scope, last10_home, last10_away)
    if not pool:
        return None

    direction = (value or "").strip().lower()

    if family == "btts":
        want_btts = direction in ("yes", "sim")

        def hit_fn(m):
            occurred = (m.get("home_goals") or 0) > 0 and (m.get("away_goals") or 0) > 0
            return 1 if occurred == want_btts else 0
    else:
        try:
            line_val = float(line_str)
        except (TypeError, ValueError):
            return None
        is_over = direction == "over"

        def hit_fn(m):
            stat = m.get(field) or 0
            over = 1 if stat > line_val else 0
            return over if is_over else 1 - over

    return weighted_rate(pool, hit_fn, reference_date=reference_date)


_SCORED_CONCEDED_FIELDS = {
    "goals":   ("home_goals", "away_goals"),
    "corners": ("home_corners", "away_corners"),
    "cards":   ("home_yellow_cards", "away_yellow_cards"),
}


def scored_conceded_avg(matches: list, is_home_ctx: bool, family: str):
    """Média do que o time FAZ (feitos) e do que CEDE (cedidos) no histórico,
    no contexto correto (casa/fora). Base da seção 3.1: toda estimativa de
    total precisa ser validada cruzando feitos de um lado com cedidos do
    outro, não só olhar se jogos passados bateram a linha."""
    if not matches or family not in _SCORED_CONCEDED_FIELDS:
        return None, None
    home_f, away_f = _SCORED_CONCEDED_FIELDS[family]
    scored_k, conceded_k = (home_f, away_f) if is_home_ctx else (away_f, home_f)
    n = len(matches)
    scored = sum((m.get(scored_k) or 0) for m in matches) / n
    conceded = sum((m.get(conceded_k) or 0) for m in matches) / n
    return round(scored, 3), round(conceded, 3)


def expected_value_convergence(last10_home: list, last10_away: list, family: str, scope: str):
    """Réplica da seção 3.1 (FEITOS vs CEDIDOS): duas estimativas
    independentes do valor esperado para a partida, uma pelo que cada time
    costuma FAZER, outra pelo que costuma CEDER — se convergem (≤15% de
    diferença), é sinal forte; se divergem, é motivo pra desconfiar do
    mercado, não só olhar taxa histórica isolada.

    scope='total' (ex. Gols Mais/Menos): feitos_casa+feitos_fora vs
      cedidos_casa+cedidos_fora.
    scope='home' (ex. Total de Gols Casa): feitos do mandante vs cedidos do
      visitante fora (o adversário específico deste jogo).
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


def _convergence_adjustment(direction: str, line_val: float | None, convergence: dict | None) -> float:
    """Delta pra somar no K bruto: a convergência feitos/cedidos concorda com
    a direção (Over/Under) do pick escolhido -> +0.10 (confirmador extra);
    diverge da direção OU as duas estimativas nem convergem entre si ->
    -0.10 (reduz confirmação, igual à regra "declare incerteza, reduza K 1
    nível" da seção 3.1). Sem dado suficiente -> 0 (neutro)."""
    if not convergence or line_val is None:
        return 0.0
    if not convergence["converged"]:
        return -0.10
    implied_direction = "over" if convergence["expected_value"] > line_val else "under"
    return 0.10 if implied_direction == direction else -0.10


def _confirmation_k(amostra: int, bookmakers_count: int) -> float:
    """Aproximacao de K (confirmadores independentes) usando os sinais
    disponiveis nesta camada: tamanho de amostra e consenso entre bookmakers.
    Nao inclui arbitro/standings (nao chegam ate aqui) -- fica mais
    conservador que o K descrito no prompt original."""
    score = 0.0
    if amostra >= 8:
        score += 1.0
    elif amostra >= 5:
        score += 0.6
    if bookmakers_count >= 3:
        score += 1.0
    elif bookmakers_count >= 2:
        score += 0.6

    if score >= 1.8:
        return 1.00
    if score >= 1.0:
        return 0.70
    if score >= 0.5:
        return 0.40
    return 0.10


def risco_from_confidence(conf: float) -> str:
    if conf >= 0.80:
        return "BAIXO"
    if conf >= 0.65:
        return "MEDIO"
    return "ALTO"


def analyze_fixture_markets(structured_odds: list, last10_home: list, last10_away: list,
                             reference_date=None) -> list:
    """Ponto de entrada da Fase 2: calcula taxa/confidence/edge/EV para cada
    mercado goals/corners/cards/btts disponivel nas odds ja estruturadas
    (services.odds_service.OddsService.load_odds_structured), a partir do
    historico ja carregado. Nao cobre 1X2/Dupla Chance/Handicap.

    Retorna candidatos prontos para rank_market_candidates().
    """
    groups: dict[tuple, list] = {}
    for m in structured_odds:
        classified = classify_market(m.get("market_name", ""))
        if not classified:
            continue
        groups.setdefault(classified, []).append(m)

    candidates = []
    for (family, scope), entries in groups.items():
        convergence = expected_value_convergence(last10_home, last10_away, family, scope)

        line_candidates = []
        for m in entries:
            best_odd = float(m.get("best_odd") or 0)
            if best_odd <= 1.0:
                continue
            taxa = _market_taxa(family, scope, m.get("value", ""), m.get("line", ""),
                                 last10_home, last10_away, reference_date)
            if not taxa or taxa["taxa_ponderada"] is None:
                continue
            ev_edge = edge_and_ev(taxa["taxa_ponderada"], best_odd, implied_prob(best_odd))
            try:
                line_val = float(m.get("line")) if family != "btts" else None
            except (TypeError, ValueError):
                line_val = None
            line_candidates.append({
                "market_id":        m.get("market_id"),
                "market_name":      m.get("market_pt") or m.get("market_name"),
                "value":            m.get("value"),
                "line":             m.get("line"),
                "value_label":      m.get("value_label"),
                "odd":              best_odd,
                "best_bookmaker":   m.get("best_bookmaker"),
                "bookmakers_count": m.get("bookmakers_count", 1),
                "taxa_real":        taxa["taxa_ponderada"],
                "amostra":          taxa["amostra"],
                "amostra_label":    taxa["amostra_label"],
                "Q":                taxa["Q"],
                "_direction":       (m.get("value") or "").strip().lower(),
                "_line_val":        line_val,
                **ev_edge,
            })

        best_line = select_smart_safe_line(line_candidates)
        if not best_line:
            continue

        K = _confirmation_k(best_line["amostra"], best_line["bookmakers_count"])
        K += _convergence_adjustment(best_line["_direction"], best_line["_line_val"], convergence)
        K = round(min(max(K, 0.10), 1.00), 4)
        conf = confidence_score(C=best_line["taxa_real"], Q=best_line["Q"], K=K)

        candidates.append({
            **best_line,
            "market_type": "goals" if family == "btts" else family,
            "confidence": conf,
            "risco": risco_from_confidence(conf),
            "convergence": convergence,
        })

    return candidates


def build_reasoning(candidate: dict) -> str:
    """Reasoning gerado por template a partir dos numeros ja calculados —
    sem chamada de IA. Decisao do usuario (2026-07-02): eliminar a IA do
    calculo/selecao das picks VIP para remover a variancia dia-a-dia."""
    prob_implicita = implied_prob(candidate["odd"])
    conv = candidate.get("convergence")
    if conv:
        status = "CONVERGE" if conv["converged"] else "DIVERGE"
        conv_txt = (
            f" VALIDAÇÃO FEITOS×CEDIDOS: feitos={conv['estimate_feitos']} | "
            f"cedidos={conv['estimate_cedidos']} | esperado={conv['expected_value']} "
            f"({status}, diff={conv['diff_pct']*100:.1f}%)."
        )
    else:
        conv_txt = " VALIDAÇÃO FEITOS×CEDIDOS: sem dado suficiente."
    return (
        f"[CÁLCULO DETERMINÍSTICO] {candidate['market_name']} {candidate['value_label']} — "
        f"taxa real ponderada (peso por recência + força do adversário) = "
        f"{candidate['taxa_real']*100:.1f}% em {candidate['amostra']} jogos analisados "
        f"(amostra {candidate.get('amostra_label', '?')})."
        f"{conv_txt} "
        f"Probabilidade implícita da odd ({candidate['odd']}) = {prob_implicita*100:.1f}% → "
        f"edge = {candidate['edge']*100:+.1f}% | EV = {candidate['ev']*100:+.1f}%. "
        f"Confidence = {candidate['confidence']*100:.0f}% | RISCO {candidate['risco']}. "
        f"Consenso de {candidate['bookmakers_count']} casa(s) de aposta, melhor odd em "
        f"{candidate['best_bookmaker']}. "
        f"Calculado por pick_math_service (Python), sem intervenção de IA nesta etapa."
    )


_CATEGORY_MAX = 1


def rank_market_candidates(candidates: list) -> list:
    """candidates: dicts com {market_type, confidence, taxa_real, amostra, odd, risco}.
    Replica seção 5 do prompt: descarta taxa<65%/amostra<5/confidence<0.55,
    ordena por confidence->taxa->amostra, no máx 1 por categoria (goals/
    corners/cards/result), define is_best_pick (nunca RISCO ALTO a menos
    que todos sejam ALTO).
    """
    eligible = [
        c for c in candidates
        if c["taxa_real"] >= 0.65 and c["amostra"] >= 5 and c["confidence"] >= 0.55
    ]
    eligible.sort(key=lambda c: (c["confidence"], c["taxa_real"], c["amostra"]), reverse=True)

    picked, used_categories = [], set()
    for c in eligible:
        cat = c["market_type"]
        if cat in used_categories:
            continue
        picked.append(c)
        used_categories.add(cat)
        if len(picked) == 3:
            break

    if not picked:
        return []

    non_high_risk = [c for c in picked if c.get("risco") != "ALTO"]
    best_pool = non_high_risk or picked
    best = max(best_pool, key=lambda c: c["confidence"])
    for c in picked:
        c["is_best_pick"] = c is best

    return picked
