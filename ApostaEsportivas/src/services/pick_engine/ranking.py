"""Selecao de linha (Smart Safe Line), filtro de elegibilidade e Score
Final. Fase 5: mercado (qual familia vence) e escolhido 100% por
estatistica (final_score, sem EV); odd so entra depois, na escolha da
LINHA dentro do mercado ja vencedor (select_smart_safe_line/line_score),
preferindo uma faixa conservadora de odd sem travar nela."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


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


def _line_score(candidate: dict, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """Pontuacao de linha (dentro de um mercado ja escolhido por
    estatistica): taxa real + edge + faixa conservadora de odd + consenso
    de bookmakers + estabilidade historica da linha. E aqui, e so aqui,
    que a odd participa da decisao -- final_score() (escolha do MERCADO)
    nao usa EV/odd.

    Variancia e Data Quality Score deliberadamente NAO entram aqui --
    sao constantes pra todos os candidatos do mesmo mercado/fixture
    (nao ajudam a escolher ENTRE linhas), ver config.py."""
    edge_norm = min(max(candidate.get("edge", 0.0), 0.0), 0.5) / 0.5
    conservative = _conservative_bonus(candidate["odd"], config)
    bookmakers = _bookmakers_bonus(candidate.get("bookmakers_count", 1), config)
    stability = _stability_bonus(candidate)
    return round(
        candidate["taxa_real"] * config.line_weight_taxa
        + edge_norm * config.line_weight_edge
        + conservative * config.line_weight_conservative
        + bookmakers * config.line_weight_bookmakers
        + stability * config.line_weight_stability,
        4,
    )


def select_smart_safe_line(
    line_candidates: list, config: PickEngineConfig = DEFAULT_CONFIG, data_quality_score: float | None = None,
) -> dict | None:
    """Descarta odd<min_odd, odd>max_odd (mercado iliquido/raramente
    cotado, nao valor real), edge<min_edge_efetivo, EV<=0; entre as que
    sobram escolhe a de maior line_score (taxa+edge+odd conservadora+
    bookmakers+estabilidade). Sem candidato aprovado, cai pra qualquer
    linha com odd entre 1.01 e max_odd (fallback conservador, nunca forca
    uma linha ruim ou um outlier de mercado ilíquido silenciosamente).

    data_quality_score (0-100, de data_validation.data_quality_score)
    ajusta o min_edge exigido pra cima quando o dado da fixture e' ruim --
    fixture com cobertura/integridade fraca precisa de uma margem de
    seguranca maior pra aprovar uma linha, em vez do mesmo limiar fixo
    de sempre. None (caller nao calculou DQS ainda) -> sem ajuste."""
    if not line_candidates:
        return None

    effective_min_edge = config.min_edge
    if data_quality_score is not None and data_quality_score < config.dqs_baseline:
        deficit = (config.dqs_baseline - data_quality_score) / 100
        effective_min_edge = config.min_edge * (1 + deficit * config.dqs_min_edge_scale)

    passed = [
        c for c in line_candidates
        if config.min_odd <= c["odd"] <= config.max_odd and c["edge"] >= effective_min_edge and c["ev"] > 0
    ]
    pool = passed or [c for c in line_candidates if 1.01 <= c["odd"] <= config.max_odd]
    if not pool:
        return None

    best = max(pool, key=lambda c: _line_score(c, config))
    best["line_score"] = _line_score(best, config)
    best["effective_min_edge"] = round(effective_min_edge, 4)
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
    return eligible[:top_n]


def select_final_picks(ranked_candidates: list, max_picks: int = 3) -> list:
    """Recebe um pool ja ranqueado (saida de rank_all_candidates) e aplica
    o corte final: no maximo 1 pick por categoria, ate max_picks no total,
    define is_best_pick (nunca RISCO ALTO a menos que todos os escolhidos
    sejam ALTO). Assume que ranked_candidates ja vem ordenado por
    final_score (rank_all_candidates garante isso)."""
    picked, used_categories = [], set()
    for c in ranked_candidates:
        cat = c["market_type"]
        if cat in used_categories:
            continue
        picked.append(c)
        used_categories.add(cat)
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


def rank_market_candidates(candidates: list, config: PickEngineConfig = DEFAULT_CONFIG) -> list:
    """Compatibilidade com os chamadores atuais (shadow/engine_pipelines):
    equivalente a select_final_picks(rank_all_candidates(...)) com os
    limites padrao (top_n=10, max_picks=3). Codigo novo que quer ver o pool
    mais rico antes do corte final (ex.: a interpretacao da IA na Fase 4)
    deve chamar rank_all_candidates() diretamente."""
    return select_final_picks(rank_all_candidates(candidates, config))
