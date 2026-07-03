"""Selecao de linha (Smart Safe Line), filtro de elegibilidade e Score
Final combinando confidence + EV + qualidade da amostra."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


def select_smart_safe_line(line_candidates: list, config: PickEngineConfig = DEFAULT_CONFIG) -> dict | None:
    """Descarta odd<min_odd, edge<min_edge, EV<=0; entre as que sobram
    escolhe maior taxa_real (empate: maior edge). Sem candidato aprovado,
    cai pra qualquer linha com odd>=1.01 (fallback conservador, nunca
    forca uma linha ruim silenciosamente)."""
    if not line_candidates:
        return None

    passed = [
        c for c in line_candidates
        if c["odd"] >= config.min_odd and c["edge"] >= config.min_edge and c["ev"] > 0
    ]
    pool = passed or [c for c in line_candidates if c["odd"] >= 1.01]
    if not pool:
        return None

    return max(pool, key=lambda c: (c["taxa_real"], c["edge"]))


def final_score(candidate: dict) -> float:
    """Score Final = combinacao de confidence + EV normalizado + qualidade
    da amostra (Q). Fases 2/3 somam o termo de contexto/matchup/consenso
    aqui dentro, sem reescrever o resto do modulo de ranking."""
    ev_norm = min(max(candidate.get("ev", 0.0), -0.5), 1.0)
    return round(
        candidate["confidence"] * 0.6
        + ev_norm * 0.25
        + candidate.get("Q", 0.0) * 0.15,
        4,
    )


def rank_market_candidates(candidates: list, config: PickEngineConfig = DEFAULT_CONFIG) -> list:
    """Descarta taxa<min_taxa / amostra<min_amostra / confidence<min_confidence
    / EV<=min_ev, ordena pelo Score Final, no maximo 1 pick por categoria
    (ate 3 no total), define is_best_pick (nunca RISCO ALTO a menos que
    todos os escolhidos sejam ALTO).

    EV positivo e criterio obrigatorio de aprovacao (nao so de escolha de
    linha) -- select_smart_safe_line tem um fallback conservador que pode
    devolver uma linha com EV negativo quando nenhuma passa no filtro
    primario; esse fallback e valido pra nao deixar a lista vazia sem
    motivo, mas NUNCA deve virar uma aposta aprovada."""
    eligible = [
        c for c in candidates
        if c["taxa_real"] >= config.min_taxa
        and c["amostra"] >= config.min_amostra
        and c["confidence"] >= config.min_confidence
        and c["ev"] > config.min_ev
    ]
    for c in eligible:
        c["final_score"] = final_score(c)
    eligible.sort(key=lambda c: c["final_score"], reverse=True)

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
    best = max(best_pool, key=lambda c: c["final_score"])
    for c in picked:
        c["is_best_pick"] = c is best

    return picked
