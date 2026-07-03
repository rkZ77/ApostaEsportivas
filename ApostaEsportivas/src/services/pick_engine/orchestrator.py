"""Ponto de entrada unico do motor de picks. Fases 2/3 adicionam chamadas
a context_model.py / team_profile_model.py / news_model.py / consensus.py
aqui dentro, sem tocar nos modulos de Fase 1 (stats_model, market_model,
confidence, calibration, ranking, explanation)."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG
from services.pick_engine import stats_model, market_model, confidence, calibration, ranking, explanation


def analyze_fixture_markets(
    structured_odds: list,
    last10_home: list,
    last10_away: list,
    reference_date=None,
    config: PickEngineConfig = DEFAULT_CONFIG,
    calibration_data: dict | None = None,
) -> list:
    """Calcula taxa/confidence/edge/EV para cada mercado goals/corners/
    cards/btts disponivel nas odds ja estruturadas (services.odds_service.
    OddsService.load_odds_structured), a partir do historico ja carregado.
    Nao cobre 1X2/Dupla Chance/Handicap.

    Retorna candidatos prontos para ranking.rank_market_candidates().
    """
    if calibration_data is None:
        calibration_data = calibration.get_market_calibration()

    groups: dict[tuple, list] = {}
    for m in structured_odds:
        classified = stats_model.classify_market(m.get("market_name", ""))
        if not classified:
            continue
        groups.setdefault(classified, []).append(m)

    candidates = []
    for (family, scope), entries in groups.items():
        convergence = stats_model.expected_value_convergence(last10_home, last10_away, family, scope)

        line_candidates = []
        for m in entries:
            best_odd = float(m.get("best_odd") or 0)
            if best_odd <= 1.0:
                continue
            taxa = stats_model.market_taxa(
                family, scope, m.get("value", ""), m.get("line", ""),
                last10_home, last10_away, reference_date, config,
            )
            if not taxa or taxa["taxa_ponderada"] is None:
                continue
            ev_edge = market_model.edge_and_ev(
                taxa["taxa_ponderada"], best_odd, market_model.implied_prob(best_odd)
            )
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

        best_line = ranking.select_smart_safe_line(line_candidates, config)
        if not best_line:
            continue

        market_type = "goals" if family == "btts" else family

        K = confidence.confirmation_k(best_line["amostra"], best_line["bookmakers_count"])
        K += confidence.convergence_adjustment(best_line["_direction"], best_line["_line_val"], convergence)
        K = round(min(max(K, 0.10), 1.00), 4)
        conf = confidence.confidence_score(C=best_line["taxa_real"], Q=best_line["Q"], K=K, config=config)

        cal_delta = calibration.calibration_adjustment(market_type, calibration_data)
        if cal_delta:
            conf = round(
                min(max(conf + cal_delta, config.confidence_min_clamp), config.confidence_max_clamp), 4
            )

        candidates.append({
            **best_line,
            "market_type": market_type,
            "confidence": conf,
            "risco": confidence.risco_from_confidence(conf, config),
            "convergence": convergence,
            "calibration_delta": cal_delta,
        })

    return candidates


def explain(candidate: dict) -> str:
    """Atalho: gera a explicacao estruturada e ja serializa pro campo
    reasoning (texto) do banco."""
    return explanation.explanation_to_text(explanation.build_explanation(candidate))
