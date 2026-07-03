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


def _line_score(candidate: dict, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """Pontuacao de linha (dentro de um mercado ja escolhido por
    estatistica): taxa real + edge (normalizado) + bonus da faixa
    conservadora de odd. E aqui, e so aqui, que a odd participa da
    decisao -- final_score() (escolha do MERCADO) nao usa EV/odd."""
    edge_norm = min(max(candidate.get("edge", 0.0), 0.0), 0.5) / 0.5
    bonus = _conservative_bonus(candidate["odd"], config)
    return round(
        candidate["taxa_real"] * config.line_weight_taxa
        + edge_norm * config.line_weight_edge
        + bonus * config.line_weight_conservative,
        4,
    )


def select_smart_safe_line(line_candidates: list, config: PickEngineConfig = DEFAULT_CONFIG) -> dict | None:
    """Descarta odd<min_odd, edge<min_edge, EV<=0; entre as que sobram
    escolhe a de maior line_score (taxa+edge+faixa conservadora de odd).
    Sem candidato aprovado, cai pra qualquer linha com odd>=1.01 (fallback
    conservador, nunca forca uma linha ruim silenciosamente)."""
    if not line_candidates:
        return None

    passed = [
        c for c in line_candidates
        if c["odd"] >= config.min_odd and c["edge"] >= config.min_edge and c["ev"] > 0
    ]
    pool = passed or [c for c in line_candidates if c["odd"] >= 1.01]
    if not pool:
        return None

    best = max(pool, key=lambda c: _line_score(c, config))
    best["line_score"] = _line_score(best, config)
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
