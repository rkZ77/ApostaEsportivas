"""NOVO na Fase 1: explicacao estruturada da pick (fatores positivos,
fatores negativos, riscos, motivo da escolha) -- sem raciocinio interno.
O rastro de depuracao (linhas avaliadas/rejeitadas pelo Smart Safe Line
etc.) fica so no log/console, nunca no texto salvo. Todo numero aqui vem
direto do candidato ja calculado -- nenhum numero e inventado nesta
camada."""
from services.pick_engine.market_model import implied_prob


def build_explanation(candidate: dict) -> dict:
    """Retorna a explicacao estruturada como dict -- quem chama decide
    como serializar (texto pro campo reasoning hoje; JSON no futuro sem
    mudar esta funcao)."""
    prob_implicita = implied_prob(candidate["odd"])
    positive_factors = []
    negative_factors = []
    risks = []

    positive_factors.append(
        f"Taxa real ponderada de {candidate['taxa_real']*100:.1f}% "
        f"em {candidate['amostra']} jogos ({candidate.get('amostra_label', '?')})"
    )
    if candidate["edge"] > 0:
        positive_factors.append(f"Edge positivo de {candidate['edge']*100:+.1f}% sobre a odd de mercado")

    conv = candidate.get("convergence")
    if conv:
        if conv["converged"]:
            positive_factors.append(
                f"Convergência feitos×cedidos ({conv['estimate_feitos']} vs {conv['estimate_cedidos']}, "
                f"diferença de {conv['diff_pct']*100:.1f}%)"
            )
        else:
            negative_factors.append(
                f"Divergência feitos×cedidos ({conv['estimate_feitos']} vs {conv['estimate_cedidos']}, "
                f"diferença de {conv['diff_pct']*100:.1f}%)"
            )
    else:
        risks.append("Sem dado suficiente para validação feitos×cedidos")

    if candidate.get("amostra_label") in ("ESCASSO", "VAZIO"):
        risks.append(f"Amostra {candidate['amostra_label'].lower()} · confiança limitada")

    if candidate.get("bookmakers_count", 1) < 2:
        risks.append("Consenso de apenas 1 casa de apostas")

    cal_delta = candidate.get("calibration_delta") or 0
    if cal_delta:
        note = f"Histórico real do mercado indica ajuste de {cal_delta*100:+.1f}% no confidence"
        (negative_factors if cal_delta < 0 else positive_factors).append(note)

    var_stats = candidate.get("variance")
    v_penalty = candidate.get("variance_penalty") or 0
    if v_penalty:
        negative_factors.append(
            f"Dispersão alta no histórico (coeficiente de variação {var_stats['coefficient_of_variation']:.2f}) "
            f"· resultado menos previsível mesmo com a taxa observada"
        )

    poisson_prob = candidate.get("poisson_probability")
    if poisson_prob is not None:
        note = f"Modelo Poisson estima {poisson_prob*100:.1f}% de probabilidade para esta linha"
        m_adj = candidate.get("model_fit_adjustment") or 0
        if m_adj > 0:
            positive_factors.append(f"{note} · concorda com a taxa empírica")
        elif m_adj < 0:
            negative_factors.append(f"{note} · diverge da taxa empírica, desconfie")
        else:
            positive_factors.append(note)

    ctx = candidate.get("context_raw")
    if ctx:
        rh, ra = ctx.get("rest_days_home"), ctx.get("rest_days_away")
        if rh is not None and ra is not None and rh != ra:
            note = f"Descanso: mandante {rh}d vs visitante {ra}d"
            (positive_factors if rh > ra else negative_factors).append(note)
        for side_key, side_label in (("table_pressure_home", "Mandante"), ("table_pressure_away", "Visitante")):
            pressure = ctx.get(side_key) or {}
            if pressure.get("label") == "pressao_alta":
                risks.append(
                    f"{side_label} em zona de risco na tabela (saldo {pressure.get('goal_diff')}, "
                    f"aproximação por posição na tabela · não é confirmação de mata-mata)"
                )
        venue = ctx.get("venue") or {}
        if venue.get("is_neutral_venue"):
            risks.append("Sede neutra · sem vantagem de mando para nenhum dos times")

    matchup = candidate.get("matchup_raw")
    direction = candidate.get("_direction")
    if matchup and matchup.get("label") != "neutro" and direction in ("over", "under"):
        note = f"Matchup de perfis aponta para {matchup['label']} (delta {matchup['delta']:+.2f})"
        agrees = matchup["label"].lower() == direction
        (positive_factors if agrees else negative_factors).append(note)

    referee_sig = candidate.get("referee_signal")
    intensity = candidate.get("game_intensity")
    if referee_sig and intensity:
        avg_red = referee_sig.get("avg_red") or 0.0
        positive_factors.append(
            f"Árbitro com média de {referee_sig['avg_yellow']} cartões amarelos e "
            f"{avg_red} vermelhos/jogo em {referee_sig['games']} jogos na temporada · "
            f"contexto de jogo classificado como '{intensity['label']}' "
            f"(score {intensity['score']*100:.0f}%)"
        )

    news = candidate.get("news_raw")
    if news:
        for side_key, side_label in (("home", "Mandante"), ("away", "Visitante")):
            titulares = news.get(side_key, {}).get("titulares_desfalcados", [])
            if titulares:
                nomes = ", ".join(t["name"] for t in titulares[:3])
                risks.append(
                    f"{side_label} desfalcado de {len(titulares)} titular(es) recente(s) ({nomes}) "
                    f"· aproximação por cruzamento de nome entre lesões e escalações recentes"
                )

    return {
        "market": candidate["market_name"],
        "line": candidate["value_label"],
        "odd": candidate["odd"],
        "probability": candidate["taxa_real"],
        "implied_probability": prob_implicita,
        "ev": candidate["ev"],
        "confidence": candidate["confidence"],
        "risco": candidate["risco"],
        "positive_factors": positive_factors,
        "negative_factors": negative_factors,
        "risks": risks,
        "why_chosen": (
            f"{candidate['market_name']} {candidate['value_label']} tem o melhor Score Final "
            f"entre os candidatos elegíveis (confidence {candidate['confidence']*100:.0f}%, "
            f"EV {candidate['ev']*100:+.1f}%)."
            if candidate.get("is_best_pick") else
            f"Candidato elegível com confidence {candidate['confidence']*100:.0f}% e "
            f"EV {candidate['ev']*100:+.1f}%."
        ),
    }


def explanation_to_text(explanation: dict) -> str:
    """Serializa a explicacao estruturada pro campo reasoning (texto) do
    banco -- schema atual nao muda, so o CONTEUDO fica limpo (sem rastro
    de depuracao interna)."""
    parts = [
        f"[{explanation['market']} {explanation['line']} @ {explanation['odd']}] "
        f"Probabilidade real: {explanation['probability']*100:.1f}% "
        f"(implícita na odd: {explanation['implied_probability']*100:.1f}%) | "
        f"EV: {explanation['ev']*100:+.1f}% | Confiança: {explanation['confidence']*100:.0f}% "
        f"| Risco: {explanation['risco']}."
    ]
    if explanation["positive_factors"]:
        parts.append("A favor: " + "; ".join(explanation["positive_factors"]) + ".")
    if explanation["negative_factors"]:
        parts.append("Contra: " + "; ".join(explanation["negative_factors"]) + ".")
    if explanation["risks"]:
        parts.append("Riscos: " + "; ".join(explanation["risks"]) + ".")
    parts.append(explanation["why_chosen"])
    return " ".join(parts)
