"""Fase de Homologacao (ver plano de validacao antes de promover o motor
pra producao): monta os relatorios estruturados de decisao a partir da
saida em modo debug do motor (orchestrator.analyze_fixture_markets(debug=True)
+ ranking.rank_all_candidates_debug + ranking.select_final_picks_debug).

Schema UNICO (build_homologation_record) gravado pelos 4 scripts de
homologacao (VIP/Free/Multipla/Alavancagem, em ai/*_homologation.py e
ai/vip_engine_shadow.py) -- secao 7 (agregacao entre os 4 tipos de pick)
depende de todos os JSONLs terem a mesma forma. Nada aqui recalcula
numero nenhum do motor -- so expoe/organiza o que ja foi calculado."""
from datetime import datetime
from services.pick_engine import explanation


def _line_identity(line: dict) -> tuple:
    return (line.get("market_id"), line.get("value"), line.get("line"))


def build_line_selection_section(all_lines: list, winner: dict | None = None) -> list:
    """Secao 3: todas as linhas avaliadas dentro de um mercado, ordenadas
    por line_score, cada uma com odd/score/motivo de rejeicao -- mostra
    por que a vencedora (se houver) bateu as outras. `winner` e o
    candidato aprovado (se existir) pra marcar qual das linhas listadas
    foi a escolhida; None quando o mercado inteiro foi eliminado (nenhuma
    linha venceu)."""
    winner_id = _line_identity(winner) if winner else None
    return [
        {
            "value_label": line.get("value_label"),
            "odd": line.get("odd"),
            "line_score": line.get("line_score"),
            "aprovada": line.get("reject_reason") is None,
            "motivo_rejeicao": line.get("reject_reason"),
            "vencedora": _line_identity(line) == winner_id,
        }
        for line in sorted(all_lines, key=lambda c: c["line_score"], reverse=True)
    ]


def build_discard_section(discarded: list, excluded: list, eliminated_markets: list, entries_dropped: list) -> list:
    """Secao 2: motivo de descarte, com a CAMADA em que aconteceu --
    "entrada" (odd invalida/poucos bookmakers/sem taxa, antes de virar
    candidato a linha), "linha" (mercado inteiro sem nenhuma linha
    aprovada, nem via fallback), "gate-final" (taxa/amostra/confidence/EV
    abaixo do minimo, ranking.rank_all_candidates_debug), "correlacao_ou_top_n"
    (perdeu pra um mercado do mesmo grupo de correlacao ou ficou fora do
    top-N, ranking.select_final_picks_debug). Sao 4 mecanismos DIFERENTES
    no motor -- misturar as camadas no relatorio atribuiria o motivo errado."""
    items = []
    for m in entries_dropped:
        items.append({
            "camada": "entrada", "market_name": m.get("market_name"),
            "market_type": m.get("family"), "scope": m.get("scope"), "motivo": [m.get("reason")],
        })
    for m in eliminated_markets:
        items.append({
            "camada": "linha", "market_type": m.get("market_type") or m.get("family"),
            "scope": m.get("scope"), "motivo": [m.get("reason")],
            "linhas_avaliadas": build_line_selection_section(m.get("all_lines") or []),
        })
    for c in discarded:
        items.append({
            "camada": "gate-final", "market_type": c.get("market_type"), "value_label": c.get("value_label"),
            "motivo": c.get("discard_reasons") or [], "final_score": c.get("final_score"),
        })
    for c in excluded:
        items.append({
            "camada": "correlacao_ou_top_n", "market_type": c.get("market_type"), "value_label": c.get("value_label"),
            "motivo": [c.get("exclude_reason")], "final_score": c.get("final_score"),
        })
    return items


def build_score_breakdown_section(candidate: dict, data_quality_score: float | None = None) -> dict:
    """Secao 4: composicao completa do score, campos verbatim do candidato
    -- nunca recalcula nada aqui, so expoe o que o motor ja calculou
    (probabilidade/edge/EV/variancia/Data Quality/Competition Profile/
    Bayesian/Score Final)."""
    ctx_raw = candidate.get("context_raw") or {}
    var_stats = candidate.get("variance") or {}
    taxa_real = candidate.get("taxa_real")
    taxa_bruta = candidate.get("taxa_bruta_pre_bayes")
    return {
        "market_type": candidate.get("market_type"),
        "value_label": candidate.get("value_label"),
        "probabilidade": {
            "taxa_real_ajustada": taxa_real,
            "taxa_bruta_pre_bayes": taxa_bruta,
        },
        "edge": candidate.get("edge"),
        "ev": candidate.get("ev"),
        "odd": candidate.get("odd"),
        "variancia": {
            "coeficiente_variacao": var_stats.get("coefficient_of_variation"),
            "penalidade_aplicada": candidate.get("variance_penalty"),
        },
        "data_quality_score": data_quality_score,
        "effective_min_edge": candidate.get("effective_min_edge"),
        "competition_profile": {
            "round_phase": ctx_raw.get("round_phase"),
            "venue": ctx_raw.get("venue"),
            "context_score": candidate.get("context_score"),
        },
        "ajuste_bayesiano": {
            "prior_aplicado": taxa_real is not None and taxa_bruta is not None and taxa_real != taxa_bruta,
            "delta": round(taxa_real - taxa_bruta, 4) if taxa_real is not None and taxa_bruta is not None else None,
        },
        "calibracao_delta": candidate.get("calibration_delta"),
        "model_fit": {
            "poisson_probability": candidate.get("poisson_probability"),
            "diff": candidate.get("model_fit_diff"),
            "adjustment": candidate.get("model_fit_adjustment"),
        },
        "confidence": candidate.get("confidence"),
        "risco": candidate.get("risco"),
        "chosen_via_fallback": candidate.get("chosen_via_fallback", False),
        "score_final": candidate.get("final_score"),
        "is_best_pick": candidate.get("is_best_pick", False),
    }


def attribute_soft_factors(candidate: dict, data_quality_score: float | None = None) -> list:
    """Fatores que INFLUENCIAM o score sem serem gates de aprovacao/descarte
    -- variancia, Data Quality Score, calibracao historica descontam
    confidence ou sobem o min_edge exigido, mas nunca reprovam um mercado
    sozinhos na arquitetura atual. Reportados aqui como contexto, nao como
    motivo de descarte binario (mesmo que o usuario tenha citado "variancia
    alta"/"Data Quality baixa" como exemplo de motivo -- nao existe esse
    gate hoje, e nao vou inventar um so pro relatorio bater com o exemplo)."""
    notes = []
    v_penalty = candidate.get("variance_penalty") or 0
    if v_penalty:
        notes.append(f"Variancia alta descontou {v_penalty*100:.1f}% do confidence (nao descartou o mercado)")
    if data_quality_score is not None and data_quality_score < 80:
        notes.append(
            f"Data Quality Score baixo ({data_quality_score:.0f}/100) elevou o edge minimo exigido "
            f"pra {candidate.get('effective_min_edge')}"
        )
    cal_delta = candidate.get("calibration_delta") or 0
    if cal_delta:
        notes.append(f"Calibracao historica ajustou confidence em {cal_delta*100:+.1f}%")
    return notes


def _leg_summary(leg: dict) -> dict:
    return {
        "market_type": leg.get("market_type"), "market": leg.get("market"),
        "line": leg.get("line"), "odd": leg.get("odd"), "confidence": leg.get("confidence"),
        "probability": leg.get("probability"), "ev": leg.get("ev"), "reasoning": leg.get("reasoning"),
        "result": leg.get("result"), "profit": leg.get("profit"),
    }


def build_comparison_section(engine_pick: dict | None, old_leg: dict | None) -> dict:
    """Secao 6 (pick unico -- VIP/Free): compara o pick do motor com o pick
    real que a IA salvou pro MESMO fixture. None em qualquer lado vira
    status explicito, nunca erro. confidence/probabilidade dos dois
    sistemas sao mostrados lado a lado com ressalva -- nao verificado se
    sao metodologicamente comparaveis (autoreportado pela IA vs calibrado
    estatisticamente pelo motor)."""
    if old_leg is None:
        return {"status": "sem_comparacao_disponivel", "motivo": "IA nao tem pick salvo pra este fixture"}
    if engine_pick is None:
        return {
            "status": "motor_sem_pick", "ia": _leg_summary(old_leg),
            "motivo": "motor nao aprovou nenhum mercado pra este fixture",
        }
    return {
        "status": "comparado",
        "mesmo_mercado": engine_pick.get("market_type") == old_leg.get("market_type"),
        "motor": {
            "market_type": engine_pick.get("market_type"), "value_label": engine_pick.get("value_label"),
            "odd": engine_pick.get("odd"), "confidence": engine_pick.get("confidence"),
            "ev": engine_pick.get("ev"), "taxa_real": engine_pick.get("taxa_real"),
        },
        "ia": _leg_summary(old_leg),
        "ressalva": (
            "confidence/probabilidade dos dois sistemas nao sao necessariamente comparaveis "
            "numero a numero (autoreportado pela IA vs calibrado estatisticamente pelo motor)"
        ),
    }


def build_combo_comparison_section(engine_combo: list, old_legs: list, engine_leg_debug_by_fixture: dict) -> dict:
    """Secao 6 (combo -- Multipla/Alavancagem): comparacao por ATRIBUICAO
    DE PERNA, nao por dois blobs opacos -- pra cada perna que a IA
    escolheu e o motor nao, explica se o motor nem avaliou aquele
    (fixture_id, market_type), avaliou e rejeitou (com motivo, olhando o
    debug completo daquele fixture em engine_leg_debug_by_fixture), ou
    avaliou/aprovou mas ficou fora do combo so pela combinatoria de odd
    (motor concordou que o mercado e' bom, so nao coube na faixa exigida)."""
    def _fid(p):
        return (p.get("_fixture") or {}).get("fixture_id") or p.get("fixture_id")

    engine_keys = {(_fid(p), p.get("market_type")) for p in engine_combo}
    old_keys = {(leg.get("fixture_id"), leg.get("market_type")) for leg in old_legs}

    legs_only_ai = []
    for leg in old_legs:
        key = (leg.get("fixture_id"), leg.get("market_type"))
        if key in engine_keys:
            continue
        debug = engine_leg_debug_by_fixture.get(leg.get("fixture_id"))
        motivo = "motor nao tem dado pra este fixture"
        if debug:
            match = next((c for c in debug.get("candidates", []) if c.get("market_type") == leg.get("market_type")), None)
            if match:
                motivo = "motor avaliou e aprovou o mercado, mas a perna nao entrou no combo (combinatoria de odd)"
            else:
                dropped = [d for d in debug.get("entries_dropped", []) if d.get("market_type") == leg.get("market_type")]
                elim = [e for e in debug.get("eliminated_markets", [])
                        if (e.get("market_type") or e.get("family")) == leg.get("market_type")]
                if dropped:
                    motivo = f"motor descartou na entrada: {dropped[0]['reason']}"
                elif elim:
                    motivo = f"motor eliminou o mercado: {elim[0]['reason']}"
                else:
                    motivo = "motor nao avaliou este mercado pra este fixture"
        legs_only_ai.append({**_leg_summary(leg), "fixture_id": leg.get("fixture_id"), "motor_nao_escolheu_porque": motivo})

    legs_only_engine = [
        {"fixture_id": _fid(p), "market_type": p.get("market_type"), "value_label": p.get("value_label")}
        for p in engine_combo if (_fid(p), p.get("market_type")) not in old_keys
    ]
    return {
        "pernas_em_comum": len(engine_keys & old_keys),
        "so_na_ia": legs_only_ai,
        "so_no_motor": legs_only_engine,
        "ressalva": "confidence/score_combo/confidence_media dos dois sistemas nao sao necessariamente comparaveis numero a numero",
    }


def build_market_report(picked: list, excluded: list, discarded: list,
                         eliminated_markets: list, entries_dropped: list,
                         data_quality_score: float | None = None) -> dict:
    """Secoes 1-5, uma fixture. Recebe a saida completa do modo debug:
    (picked, excluded) de ranking.select_final_picks_debug() e
    (eligible->picked/excluded, discarded) de ranking.rank_all_candidates_debug(),
    mais eliminated_markets/entries_dropped de
    orchestrator.analyze_fixture_markets(debug=True)."""
    mercados_avaliados = sorted(
        {c.get("market_type") for c in picked + excluded + discarded if c.get("market_type")}
        | {m.get("market_type") or m.get("family") for m in eliminated_markets}
    )
    return {
        "mercados_avaliados": mercados_avaliados,
        "mercados_descartados": build_discard_section(discarded, excluded, eliminated_markets, entries_dropped),
        "linhas_por_mercado": {
            c["market_type"]: build_line_selection_section(c.get("_all_lines") or [], winner=c)
            for c in picked
        },
        "picks_aprovados": [build_score_breakdown_section(c, data_quality_score) for c in picked],
        "explicacoes": {
            c["market_type"]: explanation.explanation_to_text(explanation.build_explanation(c))
            for c in picked
        },
        "fatores_contribuintes": {
            c["market_type"]: attribute_soft_factors(c, data_quality_score)
            for c in picked
        },
    }


def build_homologation_record(pick_type: str, fixture: dict, market_report: dict, comparison: dict,
                               data_quality_score: float | None = None) -> dict:
    """Schema UNICO gravado pelos 4 scripts de homologacao -- secao 7
    (agregacao entre VIP/Free/Multipla/Alavancagem) depende de todos os
    JSONLs terem exatamente esta forma. record_type="fixture" (uma fixture
    avaliada) -- Multipla/Alavancagem tambem gravam record_type="combo"
    (resumo do combo escolhido, construido a parte por nao caber no
    formato de 1 fixture -- ver build_combo_comparison_section)."""
    return {
        "record_type": "fixture",
        "pick_type": pick_type,
        "logged_at": datetime.now().isoformat(),
        "fixture_id": fixture.get("fixture_id"),
        "home_team": fixture.get("home_team"),
        "away_team": fixture.get("away_team"),
        "league_id": fixture.get("league_id"),
        "data_quality_score": data_quality_score,
        "mercados_avaliados": market_report["mercados_avaliados"],
        "mercados_descartados": market_report["mercados_descartados"],
        "linhas_por_mercado": market_report["linhas_por_mercado"],
        "picks_aprovados": market_report["picks_aprovados"],
        "explicacoes": market_report["explicacoes"],
        "fatores_contribuintes": market_report["fatores_contribuintes"],
        "comparacao_ia": comparison,
    }
