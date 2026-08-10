"""Selecao de linha (Smart Safe Line), filtro de elegibilidade e Score
Final. Fase 5: mercado (qual familia vence) e escolhido 100% por
estatistica (final_score, sem EV); odd so entra depois, na escolha da
LINHA dentro do mercado ja vencedor (select_smart_safe_line/line_score),
preferindo uma faixa conservadora de odd sem travar nela."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG

# Grupo de correlacao (familia raiz) por market_type -- mercados do mesmo
# grupo compartilham a MESMA fonte de dado bruto (contagem de gols/
# escanteios/cartoes do jogo), mesmo sendo estruturas de aposta diferentes
# (over/under vs handicap vs par/impar vs clean sheet). Prioridade 3 do
# plano de refatoracao: select_final_picks() usava market_type puro pra
# "1 pick por categoria" -- "cards" e "handicap_cards" contavam como
# categorias DIFERENTES, entao o corte final podia aprovar os dois ao
# mesmo tempo como se fossem confirmadores independentes, quando na
# verdade vem do mesmo historico de cartoes do time.
_CORRELATION_GROUP_OVERRIDES = {
    "clean_sheet": "goals",     # depende do placar (gols sofridos = 0)
    "win_to_nil": "goals",      # depende do placar (vence e nao sofre gol)
    # BTTS tambem sai do placar, e ficar de fora deste mapa custava caro na
    # alavancagem (achado em 2026-08-10, a partir de uma pergunta do usuario).
    # O veto de correlacao la' e' por (fixture_id, correlation_group) e a
    # docstring de _find_combo cita "Over 1.5 gols + Ambas Marcam no mesmo
    # jogo" como o exemplo do que ele protege -- so' que "btts" caia em grupo
    # proprio, entao esse par exato PASSAVA e ia pro bilhete com as duas
    # probabilidades multiplicadas como se fossem independentes.
    #
    # Nao sao, e o erro nao e' simetrico. Com Over o produto subestima (as duas
    # pernas ganham juntas), o que e' conservador; com UNDER ele superestima, e
    # muito: "Under 2.5 + Ambas Marcam" so' paga em 1-1 (~12%), enquanto
    # 0.55 x 0.50 anunciava ~28%. Os dois sao mercado barato de probabilidade
    # alta, exatamente o perfil que o teto de odd 1.55 faz o motor escolher.
    # No limite havia bilhete IMPOSSIVEL: "Under 1.5 + Ambas Marcam" e' 0%.
    #
    # Efeito colateral aceito: em select_final_picks BTTS passa a disputar o
    # slot de "goals" na mesma fixture, em vez de ocupar um proprio. E' a mesma
    # decisao que clean_sheet/win_to_nil ja seguem, e pelo mesmo motivo -- dois
    # recortes do mesmo placar nao sao dois confirmadores independentes.
    "btts": "goals",
    "outcome": "result",
    "double_chance": "result",
    "draw_no_bet": "result",
    "shots_on_target": "shots",  # chutes no alvo e chutes totais sao o mesmo sinal de volume ofensivo
}


def correlation_group(market_type: str) -> str:
    """Familia raiz de um market_type, pra agrupar mercados correlacionados
    (mesma fonte de dado bruto) mesmo quando o market_type e' tecnicamente
    diferente."""
    for prefix in ("handicap_", "odd_even_"):
        if market_type.startswith(prefix):
            return market_type[len(prefix):]
    return _CORRELATION_GROUP_OVERRIDES.get(market_type, market_type)


def _conservative_bonus(odd: float, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """1.0 dentro de [conservative_odd_low, conservative_odd_high]; cai
    linearmente pra fora, nunca zera de vez -- uma linha fora da faixa
    ainda pode vencer se taxa/edge forem bem superiores (preferencia
    suave, nao filtro rigido -- decisao explicita do usuario)."""
    low, high = config.conservative_odd_low, config.conservative_odd_high
    if low <= odd <= high:
        return 1.0
    dist = (low - odd) if odd < low else (odd - high)
    return round(max(0.0, 1.0 - dist * 0.5), 4)


def _bookmakers_bonus(bookmakers_count: int, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """0-1, satura em bookmakers_bonus_saturation casas -- mais consenso de
    preco = mais confiavel que a odd reflete valor real, nao erro de 1
    casa isolada (min_bookmakers_count ja exige >=2 pra entrar como
    candidato; isso aqui recompensa GRADUALMENTE mais consenso ainda)."""
    return round(min(bookmakers_count / config.bookmakers_bonus_saturation, 1.0), 4)


def _stability_bonus(candidate: dict) -> float:
    """1.0 = taxa identica entre metade recente e metade antiga do
    historico (estavel); cai conforme diverge. 0.5 (neutro) quando nao ha
    dado de estabilidade (mercado fora do escopo de line_stability, ex.
    handicap/outcome, ou amostra pequena demais pra dividir ao meio) --
    nem premia nem pune por falta de informacao."""
    stability = candidate.get("stability")
    if not stability:
        return 0.5
    return round(max(0.0, 1.0 - stability["instability"]), 4)


def _round_line_penalty(candidate: dict, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """Linha redonda (sem .5, ex. 'Under 10') pode empatar exato com o
    resultado -- PUSH na graduacao real (nem GREEN nem RED, ver
    ai_result_checker_service.py::evaluate_asian). taxa_real ja vem
    corrigida pra nao contar esse empate como vitoria (stats_model.py,
    weighted_rate ignora push na amostra), mas duas linhas com taxa
    parecida ainda merecem desempate a favor da .5 -- ela nunca produz
    PUSH, e' sempre GREEN ou RED. Penalidade leve (nao elimina a linha
    redonda se ela for claramente melhor, so' desempata) -- pedido do
    usuario 2026-07-25: preferir 'Over 8.5' a 'Over 8'/'Under 9' quando
    estatisticamente equivalentes."""
    line_val = candidate.get("_line_val")
    if line_val is None or line_val % 1 != 0:
        return 0.0
    return config.round_line_push_penalty


def _line_score(candidate: dict, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """Pontuacao de linha (dentro de um mercado ja escolhido por
    estatistica): taxa real + edge + faixa conservadora de odd + consenso
    de bookmakers + estabilidade historica da linha, menos uma pequena
    penalidade se a linha for redonda (risco de PUSH -- ver
    _round_line_penalty). E aqui, e so aqui, que a odd participa da
    decisao -- final_score() (escolha do MERCADO) nao usa EV/odd.

    Variancia e Data Quality Score deliberadamente NAO entram aqui --
    sao constantes pra todos os candidatos do mesmo mercado/fixture
    (nao ajudam a escolher ENTRE linhas), ver config.py."""
    edge_norm = min(max(candidate.get("edge", 0.0), 0.0), 0.5) / 0.5
    conservative = _conservative_bonus(candidate["odd"], config)
    bookmakers = _bookmakers_bonus(candidate.get("bookmakers_count", 1), config)
    stability = _stability_bonus(candidate)
    score = (
        candidate["taxa_real"] * config.line_weight_taxa
        + edge_norm * config.line_weight_edge
        + conservative * config.line_weight_conservative
        + bookmakers * config.line_weight_bookmakers
        + stability * config.line_weight_stability
    )
    return round(max(score - _round_line_penalty(candidate, config), 0.0), 4)


def evaluate_all_lines(
    line_candidates: list, config: PickEngineConfig = DEFAULT_CONFIG, data_quality_score: float | None = None,
) -> list:
    """Avalia TODAS as linhas candidatas (nao so a vencedora) -- extraido de
    select_smart_safe_line() pra alimentar tanto a escolha real quanto o
    relatorio de homologacao (fase de validacao antes de promover o motor
    pra producao, ver plano). Cada linha recebe line_score + reject_reason
    (None = passou no filtro primario; senao um motivo especifico -- odd
    abaixo do minimo/acima do teto, edge insuficiente, EV<=0). Constroi
    dicts NOVOS (nunca muta line_candidates), pra o modo debug nao vazar
    campos extras no caminho normal.

    data_quality_score (0-100, de data_validation.data_quality_score)
    ajusta o min_edge exigido pra cima quando o dado da fixture e' ruim --
    fixture com cobertura/integridade fraca precisa de uma margem de
    seguranca maior pra aprovar uma linha, em vez do mesmo limiar fixo
    de sempre. None (caller nao calculou DQS ainda) -> sem ajuste."""
    effective_min_edge = config.min_edge
    if data_quality_score is not None and data_quality_score < config.dqs_baseline:
        deficit = (config.dqs_baseline - data_quality_score) / 100
        effective_min_edge = config.min_edge * (1 + deficit * config.dqs_min_edge_scale)
    effective_min_edge = round(effective_min_edge, 4)

    evaluated = []
    for c in line_candidates:
        if c["odd"] < config.min_odd:
            reason = "odd abaixo do minimo"
        elif c["odd"] > config.max_odd:
            reason = "odd acima do teto de sanidade"
        elif c["edge"] < effective_min_edge:
            reason = "edge abaixo do minimo efetivo"
        elif c["ev"] <= 0:
            reason = "EV nao positivo"
        else:
            reason = None
        evaluated.append({
            **c,
            "line_score": _line_score(c, config),
            "effective_min_edge": effective_min_edge,
            "reject_reason": reason,
        })
    return evaluated


def select_smart_safe_line(
    line_candidates: list, config: PickEngineConfig = DEFAULT_CONFIG, data_quality_score: float | None = None,
) -> dict | None:
    """Descarta odd<min_odd, odd>max_odd (mercado iliquido/raramente
    cotado, nao valor real), edge<min_edge_efetivo, EV<=0; entre as que
    sobram escolhe a de maior line_score (taxa+edge+odd conservadora+
    bookmakers+estabilidade). Sem candidato aprovado, cai pra qualquer
    linha com odd entre 1.01 e max_odd (fallback conservador, nunca forca
    uma linha ruim ou um outlier de mercado ilíquido silenciosamente) --
    nesse caso chosen_via_fallback=True, o vencedor pode ele mesmo carregar
    um reject_reason (nao passou no filtro primario, so nao havia nada
    melhor); ver services/pick_engine/homologation.py pra como isso e'
    reportado na fase de validacao."""
    if not line_candidates:
        return None

    evaluated = evaluate_all_lines(line_candidates, config, data_quality_score)
    passed = [c for c in evaluated if c["reject_reason"] is None]
    chosen_via_fallback = not passed
    pool = passed or [c for c in evaluated if 1.01 <= c["odd"] <= config.max_odd]
    if not pool:
        return None

    best = max(pool, key=lambda c: c["line_score"])
    best = {**best, "chosen_via_fallback": chosen_via_fallback}
    return best


# Pesos ativos por fase (renormalizados p/ somar 1.0 entre os modelos ja
# implementados -- Consenso fica de fora do score, e so log em modo sombra):
# Fase 1: Dados Estatisticos (35) -- embutido no "base" abaixo via
#   confidence/Q. Mercado/EV (10) NAO entra mais aqui (Fase 5) -- odd so
#   decide a linha dentro do mercado ja escolhido, nunca qual mercado vence.
# Fase 2: + Contexto (20) e Perfil das equipes (15) => total ativo 80.
# Fase 3: + Noticias (10) => total ativo 90.
_W_BASE = 0.45 / 0.90      # Dados Estatisticos (sem EV, Fase 5)
_W_CONTEXT = 0.20 / 0.90
_W_PROFILE = 0.15 / 0.90
_W_NEWS = 0.10 / 0.90


def final_score(candidate: dict) -> float:
    """Score Final = decide qual MERCADO vence (gols/escanteios/cartoes/
    1X2/handicap/etc) -- 100% estatistico (confidence + qualidade da
    amostra + contexto/perfil/noticias quando presentes), SEM EV/odd
    (Fase 5 -- antes o EV entrava aqui e uma odd mais alta podia fazer um
    mercado estatisticamente mais fraco vencer; a odd agora so decide a
    linha dentro do mercado ja escolhido, em select_smart_safe_line).

    Sem nenhum sinal de Contexto/Perfil/Noticias, o resultado e so
    confidence*0.8 + Q*0.2 (renormalizado sem o termo de EV que existia
    antes da Fase 5)."""
    base = round(candidate["confidence"] * 0.8 + candidate.get("Q", 0.0) * 0.2, 4)

    ctx_score = candidate.get("context_score")
    profile_score = candidate.get("profile_score")
    news_score = candidate.get("news_score")
    if ctx_score is None and profile_score is None and news_score is None:
        return base

    ctx_score = ctx_score if ctx_score is not None else 0.5
    profile_score = profile_score if profile_score is not None else 0.5
    news_score = news_score if news_score is not None else 0.5
    return round(
        base * _W_BASE + ctx_score * _W_CONTEXT + profile_score * _W_PROFILE + news_score * _W_NEWS,
        4,
    )


def rank_all_candidates(candidates: list, config: PickEngineConfig = DEFAULT_CONFIG, top_n: int = 10) -> list:
    """Descarta taxa<min_taxa / amostra<min_amostra / confidence<min_confidence
    / EV<=min_ev, ordena pelo Score Final e devolve os top_n melhores --
    SEM cortar por categoria (Fase 6: o corte "1 por categoria, max 3"
    acontecia aqui antes de qualquer interpretacao; agora fica em
    select_final_picks(), chamado DEPOIS que o pool mais rico foi visto
    -- pela IA em Fase 4, ou pelo caller em modo sombra/determinístico).
    `market_type` continua em cada candidato (metadado pra quem for
    escolher depois), so nao filtra mais aqui.

    EV positivo e criterio obrigatorio de aprovacao (nao so de escolha de
    linha) -- select_smart_safe_line tem um fallback conservador que pode
    devolver uma linha com EV negativo quando nenhuma passa no filtro
    primario; esse fallback e valido pra nao deixar a lista vazia sem
    motivo, mas NUNCA deve virar uma aposta aprovada.

    odd>=min_odd tambem e reforcado aqui pelo mesmo motivo: o fallback de
    select_smart_safe_line pode escolher a MELHOR linha disponivel de um
    mercado mesmo com odd abaixo de min_odd (ex.: Dupla Chance com odd 1.23
    quando nao ha outra linha do mercado pra competir) -- sem este gate,
    esse candidato ainda concorreria por final_score (que nao usa odd) e
    podia virar o pick final com odd baixa demais para VIP/Free (achado
    real rodando o motor contra jogos ao vivo)."""
    eligible = [
        c for c in candidates
        if c["taxa_real"] >= config.min_taxa
        and c["amostra"] >= config.min_amostra
        and c["confidence"] >= config.min_confidence
        and c["ev"] > config.min_ev
        and c["odd"] >= config.min_odd
    ]
    for c in eligible:
        c["final_score"] = final_score(c)
    eligible.sort(key=lambda c: c["final_score"], reverse=True)
    return eligible[:top_n]


def rank_all_candidates_debug(candidates: list, config: PickEngineConfig = DEFAULT_CONFIG, top_n: int = 10) -> tuple:
    """Mesmos 4 gates de rank_all_candidates(), mas SEM short-circuit --
    todo candidato reprovado carrega discard_reasons (pode ter mais de um
    motivo ao mesmo tempo) e ainda ganha final_score calculado (util pra
    homologacao: "esse mercado pontuou 0.61, teria entrado no top-3 se nao
    fosse a amostra"). Constroi dicts NOVOS, nunca muta `candidates` --
    caminho de debug, nunca usado pela producao. Retorna (eligible, discarded),
    eligible ja ordenado e cortado em top_n como rank_all_candidates()."""
    eligible, discarded = [], []
    for c in candidates:
        reasons = []
        if c["taxa_real"] < config.min_taxa:
            reasons.append(f"taxa abaixo do minimo ({c['taxa_real']*100:.1f}% < {config.min_taxa*100:.0f}%)")
        if c["amostra"] < config.min_amostra:
            reasons.append(f"amostra insuficiente ({c['amostra']} < {config.min_amostra})")
        if c["confidence"] < config.min_confidence:
            reasons.append(f"confidence abaixo do minimo ({c['confidence']*100:.1f}% < {config.min_confidence*100:.0f}%)")
        if c["ev"] <= config.min_ev:
            reasons.append(f"EV nao positivo ({c['ev']*100:+.1f}%)")
        if c["odd"] < config.min_odd:
            reasons.append(f"odd abaixo do minimo ({c['odd']} < {config.min_odd})")

        scored = {**c, "final_score": final_score(c)}
        if reasons:
            discarded.append({**scored, "discard_reasons": reasons})
        else:
            eligible.append(scored)

    eligible.sort(key=lambda c: c["final_score"], reverse=True)
    return eligible[:top_n], discarded


def select_final_picks(ranked_candidates: list, max_picks: int = 3) -> list:
    """Recebe um pool ja ranqueado (saida de rank_all_candidates) e aplica
    o corte final: no maximo 1 pick por GRUPO DE CORRELACAO (nao
    market_type puro -- ver correlation_group(), evita aprovar "cards" e
    "handicap_cards" juntos como se fossem confirmadores independentes),
    ate max_picks no total, define is_best_pick (nunca RISCO ALTO a menos
    que todos os escolhidos sejam ALTO). Assume que ranked_candidates ja
    vem ordenado por final_score (rank_all_candidates garante isso)."""
    picked, used_groups = [], set()
    for c in ranked_candidates:
        group = correlation_group(c["market_type"])
        if group in used_groups:
            continue
        picked.append(c)
        used_groups.add(group)
        if len(picked) == max_picks:
            break

    if not picked:
        return []

    non_high_risk = [c for c in picked if c.get("risco") != "ALTO"]
    best_pool = non_high_risk or picked
    best = max(best_pool, key=lambda c: c["final_score"])
    for c in picked:
        c["is_best_pick"] = c is best

    return picked


def select_final_picks_debug(ranked_eligible: list, max_picks: int = 3) -> tuple:
    """Mesma logica de select_final_picks(), mas sem o `break` antecipado --
    todo candidato depois do corte final continua sendo visitado, pra poder
    ser tagueado com o motivo exato de exclusao (homologacao). Recebe so o
    pool ELEGIVEL (saida de rank_all_candidates_debug()[0]) -- candidatos
    ja descartados pelos gates nao sao re-julgados aqui. Retorna
    (picked, excluded), mesmo `picked`/is_best_pick que select_final_picks()."""
    picked, excluded, used_groups = [], [], set()
    for c in ranked_eligible:
        group = correlation_group(c["market_type"])
        if len(picked) >= max_picks:
            excluded.append({**c, "exclude_reason": "fora_do_top_n"})
        elif group in used_groups:
            winner = next(p for p in picked if correlation_group(p["market_type"]) == group)
            excluded.append({**c, "exclude_reason": f"correlacionado_com:{winner['market_type']}"})
        else:
            picked.append(c)
            used_groups.add(group)

    if not picked:
        return [], excluded

    non_high_risk = [c for c in picked if c.get("risco") != "ALTO"]
    best_pool = non_high_risk or picked
    best = max(best_pool, key=lambda c: c["final_score"])
    for c in picked:
        c["is_best_pick"] = c is best

    return picked, excluded


def rank_market_candidates(candidates: list, config: PickEngineConfig = DEFAULT_CONFIG) -> list:
    """Compatibilidade com os chamadores atuais (shadow/engine_pipelines):
    equivalente a select_final_picks(rank_all_candidates(...)) com os
    limites padrao (top_n=10, max_picks=3). Codigo novo que quer ver o pool
    mais rico antes do corte final (ex.: a interpretacao da IA na Fase 4)
    deve chamar rank_all_candidates() diretamente."""
    return select_final_picks(rank_all_candidates(candidates, config))
