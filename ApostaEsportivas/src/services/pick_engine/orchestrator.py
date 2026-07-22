"""Ponto de entrada unico do motor de picks. `consensus.py` fica fora deste
fluxo por decisao explicita (modo sombra, roda separado em
shadow_consensus.py, sem influenciar o calculo de picks aqui)."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG
from services.pick_engine import (
    stats_model, market_model, confidence, calibration, ranking, explanation,
    context_model, team_profile_model, news_model, probability_model, variance_model,
    data_validation, bayesian_model, referee_model,
)

_CARDS_FAMILIES = ("cards", "handicap_cards")

_OPPOSITE_VALUE = {
    "over": "under", "under": "over",
    "yes": "no", "no": "yes", "sim": "não", "não": "sim", "nao": "sim",
}


def _find_sibling(entry: dict, entries: list) -> dict | None:
    """Acha a entrada complementar (Over/Under ou Yes/No do MESMO
    market_id+line) pra calculo de probabilidade no-vig -- None se nao
    houver par (mercado sem contraparte, ex.: handicap/outcome de 3 vias)."""
    opposite = _OPPOSITE_VALUE.get((entry.get("value") or "").strip().lower())
    if not opposite:
        return None
    for other in entries:
        if other is entry:
            continue
        if (
            other.get("market_id") == entry.get("market_id")
            and other.get("line") == entry.get("line")
            and (other.get("value") or "").strip().lower() == opposite
        ):
            return other
    return None


def analyze_fixture_markets(
    structured_odds: list,
    last10_home: list,
    last10_away: list,
    reference_date=None,
    config: PickEngineConfig = DEFAULT_CONFIG,
    calibration_data: dict | None = None,
    context_data: dict | None = None,
    matchup_data: dict | None = None,
    news_data: dict | None = None,
    team_strength_data: dict | None = None,
    referee_stats: dict | None = None,
    league_id: int | None = None,
    data_quality_score: float | None = None,
    debug: bool = False,
) -> list | dict:
    """Calcula taxa/confidence/edge/EV para cada mercado suportado
    (classify_market()) disponivel nas odds ja estruturadas
    (services.odds_service.OddsService.load_odds_structured), a partir do
    historico ja carregado. Cobre gols/escanteios/cartoes/ambas marcam/
    chutes/impedimentos (over-under), 1X2, dupla chance, empate anula
    aposta, handicap (gols/escanteios/cartoes), par/impar, clean sheet e
    vitoria sem sofrer gol -- ver stats_model.classify_market() pra lista
    completa e o que fica de fora (jogador individual, placar exato,
    1o/2o tempo).

    `context_data` (saida de context_model.build_context), `matchup_data`
    (saida de team_profile_model.compare_matchup), `news_data` (saida de
    news_model.injury_signal) e `team_strength_data` (saida de
    team_strength.compare_team_strength) sao opcionais -- Fase 1 continua
    funcionando identica sem eles (ranking.final_score() so aplica os pesos
    de Contexto/Perfil/Noticias quando os campos existem no candidato;
    team_strength_data e so informativo por enquanto, anexado a cada
    candidato mas ainda nao pesado no confidence -- ver Fase 2b).

    `data_quality_score` (0-100, saida de
    data_validation.data_quality_score) e opcional -- quando presente,
    ranking.select_smart_safe_line() exige mais edge pra aprovar uma
    linha em fixtures com dado ruim (Prioridade 2 do plano de refatoracao).

    Fase 2b (Statistical Engine): pra familias com decomposicao feitos/
    cedidos (goals/corners/cards, ver stats_model._SCORED_CONCEDED_FIELDS),
    alem da taxa empirica bruta agora tambem calcula P(linha) via Poisson
    (probability_model, lambda = expected_value_convergence) e usa a
    concordancia entre as duas estimativas como termo M no confidence
    (confidence.model_fit_adjustment); e a variancia/coeficiente de
    variacao do historico bruto como termo V (variance_model.variance_penalty)
    -- mercados com dispersao alta (mesma media, resultados muito
    irregulares) perdem confidence mesmo com taxa boa.

    Retorna candidatos prontos para ranking.rank_market_candidates().

    `referee_stats` (saida de services.referee_stats_service.RefereeStatsService.
    get_stats) e opcional -- quando ausente, mercados de cartoes (cards/
    handicap_cards) ficam bloqueados por falta de dado confiavel de arbitro
    (ver referee_model.cards_market_eligible, gate duro pra TODOS os
    pipelines: sem arbitro com amostra minima OU jogo classificado "frio"
    pelo contexto, cartoes nem vira candidato).

    `league_id` e opcional -- quando presente, calibration.get_prior/
    calibration_adjustment tentam a calibracao segmentada por
    (market_type, league_id) antes de cair pro agregado so por market_type
    (ver services/pick_engine/calibration.py, fallback gracioso quando a
    liga especifica nao tem amostra suficiente).

    `debug=True` (fase de homologacao, ver services/pick_engine/homologation.py
    e o plano de validacao antes de promover o motor pra producao): retorno
    muda de list pra dict {"candidates": [...], "eliminated_markets": [...],
    "entries_dropped": [...]} -- captura tambem os `continue` silenciosos
    (odd invalida, poucos bookmakers, taxa sem dado) que hoje descartam uma
    entrada ANTES dela virar line_candidate, e familias inteiras eliminadas
    (sem best_line). `debug=False` (default, usado por toda a producao/
    pipelines atuais) mantem o retorno IDENTICO ao de sempre -- nao muda
    nenhuma decisao, so nao expoe o rastro extra.
    """
    entries_dropped = []
    eliminated_markets = []
    if calibration_data is None:
        calibration_data = calibration.get_market_calibration()
    ctx_score = context_model.context_score(context_data) if context_data else None
    news_score = news_model.news_score(news_data) if news_data else None
    referee_sig = referee_model.referee_signal(referee_stats, config)
    game_intensity = referee_model.game_intensity(context_data, matchup_data, referee_sig)

    groups: dict[tuple, list] = {}
    for m in structured_odds:
        classified = stats_model.classify_market(m.get("market_name", ""))
        if not classified:
            continue
        groups.setdefault(classified, []).append(m)

    candidates = []
    for (family, scope), entries in groups.items():
        if family in _CARDS_FAMILIES:
            eligible, reason = referee_model.cards_market_eligible(referee_sig, game_intensity, config)
            if not eligible:
                if debug:
                    eliminated_markets.append({
                        "family": family, "scope": scope, "market_type": family,
                        "reason": reason,
                    })
                continue

        convergence = stats_model.expected_value_convergence(last10_home, last10_away, family, scope)
        market_type = "goals" if family == "btts" else family
        # Prioridade 6: prior Bayesiano pra encolher taxa em amostra pequena
        # -- MESMA fonte que calibration_adjustment ja usa (hit-rate real
        # historico do market_type), nao um numero novo/inventado.
        bayes_prior = calibration.get_prior(market_type, calibration_data, league_id=league_id)

        line_candidates = []
        for m in entries:
            best_odd = float(m.get("best_odd") or 0)
            if best_odd <= 1.0:
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope, "reason": "odd invalida ou ausente",
                    })
                continue
            if m.get("bookmakers_count", 1) < config.min_bookmakers_count:
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope,
                        "reason": f"poucos bookmakers ({m.get('bookmakers_count', 1)} < {config.min_bookmakers_count})",
                    })
                continue
            taxa = stats_model.compute_taxa(
                family, scope, m.get("value", ""), m.get("line", ""),
                last10_home, last10_away, reference_date, config,
            )
            if not taxa or taxa["taxa_ponderada"] is None:
                if debug:
                    entries_dropped.append({
                        "market_name": m.get("market_pt") or m.get("market_name"),
                        "family": family, "scope": scope, "reason": "sem taxa calculavel (amostra insuficiente)",
                    })
                continue
            # Encolhimento Bayesiano: puxa a taxa em direcao ao prior
            # proporcional a quao pequena e' a amostra (n<<10 -> quase todo
            # peso vai pro prior; n>>10 -> quase nao muda). taxa_bruta_raw
            # preserva o valor original pra transparencia/debug -- taxa_real
            # (usado daqui pra frente em edge/EV/confidence) e' o ajustado.
            taxa_bruta_raw = taxa["taxa_ponderada"]
            taxa_ajustada = bayesian_model.shrink_taxa(taxa_bruta_raw, taxa["amostra"], bayes_prior)
            # No-vig quando o par complementar (Over/Under, Yes/No) tiver
            # 2+ bookmakers dos dois lados -- probabilidade real de mercado
            # sem a margem da casa embutida, mais precisa que 1/odd puro
            # (que ja tinha essa peca pronta em market_model desde a Fase 1
            # e nunca era chamada). Cai pra implied_prob automaticamente
            # via resolve_prob_baseline quando nao ha par ou nao ha consenso.
            sibling = _find_sibling(m, entries)
            prob_baseline = market_model.resolve_prob_baseline(m, sibling)
            ev_edge = market_model.edge_and_ev(
                taxa_ajustada, best_odd, prob_baseline["prob"]
            )
            try:
                line_val = float(m.get("line")) if family != "btts" else None
            except (TypeError, ValueError):
                line_val = None
            # Estabilidade da linha especifica ao longo do tempo (nao so a
            # media agregada) -- entra no line_score via ranking._stability_bonus.
            # So cobre mercados classicos (over/under/btts); None pros
            # demais (handicap/outcome/etc), tratado como neutro no score.
            stability = stats_model.line_stability(
                family, scope, m.get("value", ""), m.get("line", ""), last10_home, last10_away,
            )
            line_candidates.append({
                "market_id":        m.get("market_id"),
                "market_name":      m.get("market_pt") or m.get("market_name"),
                "value":            m.get("value"),
                "line":             m.get("line"),
                "value_label":      m.get("value_label"),
                "odd":              best_odd,
                "best_bookmaker":   m.get("best_bookmaker"),
                "bookmakers_count": m.get("bookmakers_count", 1),
                "taxa_real":        taxa_ajustada,
                "taxa_bruta_pre_bayes": taxa_bruta_raw,
                "amostra":          taxa["amostra"],
                "amostra_label":    taxa["amostra_label"],
                "Q":                taxa["Q"],
                "prob_baseline_source": prob_baseline["source"],
                "stability":        stability,
                "_direction":       (m.get("value") or "").strip().lower(),
                "_line_val":        line_val,
                **ev_edge,
            })

        best_line = ranking.select_smart_safe_line(line_candidates, config, data_quality_score=data_quality_score)
        if not best_line:
            if debug and line_candidates:
                eliminated_markets.append({
                    "family": family, "scope": scope, "market_type": market_type,
                    "reason": "nenhuma linha aprovada (nem via fallback conservador)",
                    "all_lines": ranking.evaluate_all_lines(line_candidates, config, data_quality_score),
                })
            continue

        is_poisson_fam = probability_model.is_poisson_family(family)
        # BTTS tem Poisson proprio (Prioridade 5): P(ambas marcam) =
        # P(casa marca)xP(fora marca), com um lambda por LADO (nao um
        # lambda combinado do jogo inteiro como goals/corners/cards usam)
        # -- por isso fica fora de is_poisson_family, tratado a parte
        # abaixo, mas conta igual pra decidir se K cede lugar a M.
        has_poisson_signal = is_poisson_fam or family == "btts"

        # K: para familias SEM Poisson (shots/outcome/handicap/etc),
        # convergence_adjustment continua sendo o unico sinal de "o
        # feitos/cedidos concorda com a direcao do pick". Para familias COM
        # Poisson (goals/corners/cards/btts), esse bonus/penalidade sai
        # daqui -- M abaixo usa a MESMA base estatistica pra fazer a mesma
        # pergunta de forma mais precisa (probabilidade completa, nao so
        # direcao); manter os dois seria confirmar a mesma evidencia duas
        # vezes (Prioridade 1.3 do plano de refatoracao).
        K = confidence.confirmation_k(best_line["amostra"], best_line["bookmakers_count"])
        if not has_poisson_signal:
            K += confidence.convergence_adjustment(best_line["_direction"], best_line["_line_val"], convergence)
        K = round(min(max(K, 0.10), 1.00), 4)
        conf = confidence.confidence_score(C=best_line["taxa_real"], Q=best_line["Q"], K=K, config=config)

        cal_delta = calibration.calibration_adjustment(market_type, calibration_data, league_id=league_id)

        # V (variancia): mesma media, dispersao real -> menos previsivel,
        # perde confidence mesmo com taxa boa (nao aplica a familias sem
        # leitura de valor bruto, ex. btts/outcome -- variance_stats retorna
        # None e a penalidade fica 0).
        var_stats = variance_model.variance_stats(family, scope, last10_home, last10_away)
        v_penalty = variance_model.variance_penalty(
            var_stats["coefficient_of_variation"] if var_stats else None
        )

        # Amostra especifica desta familia (Prioridade 3) -- so exposto/
        # logado por enquanto, NAO usado como filtro/penalidade ainda: a
        # correcao completa exigiria mudar _extract_stat() pra excluir
        # jogos sem o campo em vez de tratar como 0, o que mudaria
        # taxa_real/confidence pra qualquer familia com gap de cobertura --
        # decisao separada, fora do escopo desta revisao.
        market_sample = data_validation.validate_market_sample(family, scope, last10_home, last10_away)

        # M (model-fit): concordancia entre a taxa empirica (contagem direta)
        # e a probabilidade do modelo Poisson pra MESMA linha -- substitui
        # convergence_adjustment (K) pra familias com sinal Poisson, ver
        # comentario acima.
        poisson_prob = None
        model_fit_diff = None
        if is_poisson_fam and convergence and best_line["_line_val"] is not None:
            poisson_prob = probability_model.poisson_prob_for_line(
                convergence["expected_value"], best_line["_line_val"], best_line["_direction"]
            )
            model_fit_diff = probability_model.model_fit(best_line["taxa_real"], poisson_prob)
        elif family == "btts":
            # Lambda por lado (nao o convergence combinado do loop, que e'
            # scope='total') -- feitos do time x cedido pelo adversario,
            # em cada lado separadamente.
            home_conv = stats_model.expected_value_convergence(last10_home, last10_away, "goals", "home")
            away_conv = stats_model.expected_value_convergence(last10_home, last10_away, "goals", "away")
            if home_conv and away_conv:
                btts_prob = probability_model.btts_probability(
                    home_conv["expected_value"], away_conv["expected_value"]
                )
                want_yes = best_line["_direction"] in ("yes", "sim")
                poisson_prob = btts_prob if want_yes else round(1 - btts_prob, 4) if btts_prob is not None else None
                model_fit_diff = probability_model.model_fit(best_line["taxa_real"], poisson_prob)
        m_adjustment = confidence.model_fit_adjustment(model_fit_diff) if has_poisson_signal else 0.0

        total_delta = (cal_delta or 0) - v_penalty + m_adjustment
        if total_delta:
            conf = round(
                min(max(conf + total_delta, config.confidence_min_clamp), config.confidence_max_clamp), 4
            )

        candidate = {
            **best_line,
            "market_type": market_type,
            "confidence": conf,
            "risco": confidence.risco_from_confidence(conf, config),
            "convergence": convergence,
            "calibration_delta": cal_delta,
            "variance": var_stats,
            "variance_penalty": v_penalty,
            "market_sample": market_sample,
            "poisson_probability": poisson_prob,
            "model_fit_diff": model_fit_diff,
            "model_fit_adjustment": m_adjustment,
            "context_score": ctx_score,
            "context_raw": context_data,
            "profile_score": team_profile_model.profile_score_for_market(matchup_data, market_type),
            "matchup_raw": matchup_data.get(market_type) if matchup_data else None,
            "news_score": news_score,
            "news_raw": news_data,
            "team_strength": team_strength_data,
            "referee_signal": referee_sig if family in _CARDS_FAMILIES else None,
            "game_intensity": game_intensity if family in _CARDS_FAMILIES else None,
        }
        if debug:
            candidate["_all_lines"] = ranking.evaluate_all_lines(line_candidates, config, data_quality_score)
        candidates.append(candidate)

    if debug:
        return {"candidates": candidates, "eliminated_markets": eliminated_markets, "entries_dropped": entries_dropped}
    return candidates


def explain(candidate: dict) -> str:
    """Atalho: gera a explicacao estruturada e ja serializa pro campo
    reasoning (texto) do banco."""
    return explanation.explanation_to_text(explanation.build_explanation(candidate))
