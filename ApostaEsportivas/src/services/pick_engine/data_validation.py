"""Data Validation Engine: camada que valida os dados ANTES de qualquer
analise de mercado -- historico suficiente, cobertura das fontes,
integridade dos valores e outliers. Gera um Data Quality Score (0-100)
que acompanha a analise, em vez de deixar dado ruim silenciosamente
degradar taxa/confidence sem ninguem perceber a causa.

Nao recalcula o que ja existe: reaproveita stats_model.sample_quality()
(amostra -> Q) e variance_model.variance_stats() (media/desvio) em vez de
duplicar essa matematica."""
from services.pick_engine import stats_model, variance_model


# ============================================================
# 1. HISTORICO
# ============================================================
#: Quanto da qualidade da amostra depende de saber CONTRA QUEM o time jogou.
#: Com 0.15, historico inteiro sem classificacao do adversario vale 85% do Q --
#: penalidade real e pequena. Nao pode ser grande: adversario desconhecido nao
#: torna o jogo invalido, so' cega o unico ajuste que corrigiria a forca dele
#: (stats_model.opponent_weight, que sem rank cai no peso neutro).
PESO_ADVERSARIO_CONHECIDO = 0.15


def validate_history(matches: list, min_games: int = 5) -> dict:
    """Amostra minima pra uma analise ter algum valor -- reaproveita
    stats_model.sample_quality() (mesmos tiers RICO/MODERADO/ESCASSO/VAZIO
    ja usados no resto do motor, nao um limite novo e desalinhado).

    QUANTIDADE NAO E' QUALIDADE (2026-08-13). Ate' aqui este validador so'
    CONTAVA jogos: 15 partidas de quatro competicoes diferentes, contra
    adversario que o banco nem sabe quem e', pontuavam igual a 15 partidas de
    Brasileirao com classificacao conhecida. Como o Data Quality Score escala o
    `min_edge` exigido (config.dqs_baseline / dqs_min_edge_scale), a lacuna
    fazia o motor cobrar a MESMA margem de seguranca nos dois casos.

    O sinal medido e' a fracao do historico com `opponent_rank` conhecido,
    porque e' ele que diz se a ponderacao por forca do adversario esta
    funcionando ou rodando cega. Amostra de copa costuma trazer adversario de
    campeonato estrangeiro nao coletado, e e' exatamente onde a cautela extra
    faz falta.

    `competicoes` vai junto no retorno como informacao de rastro (aparece no
    decision_log), NAO como penalidade: historico multi-competicao e' o
    comportamento desejado em copa, nao um defeito a punir.
    """
    n = len(matches)
    quality = stats_model.sample_quality(n)
    reasons = []
    if n == 0:
        reasons.append("Nenhum jogo no historico")
    elif n < min_games:
        reasons.append(f"Amostra abaixo do minimo ({n} de {min_games} jogos)")

    com_rank = sum(1 for m in matches if m.get("opponent_rank") is not None)
    fracao_conhecida = (com_rank / n) if n else 0.0
    competicoes = len({m.get("league_id") for m in matches if m.get("league_id") is not None})
    if n and com_rank < n:
        reasons.append(
            f"{n - com_rank} de {n} jogos sem classificacao do adversario "
            f"(ponderacao por forca fica neutra neles)"
        )

    fator = (1 - PESO_ADVERSARIO_CONHECIDO) + PESO_ADVERSARIO_CONHECIDO * fracao_conhecida
    return {
        "passed": n >= min_games,
        "amostra": n,
        "label": quality["label"],
        "Q": round(quality["Q"] * fator, 4),
        "Q_bruto": quality["Q"],
        "adversario_conhecido": round(fracao_conhecida, 3),
        "competicoes": competicoes,
        "reasons": reasons,
    }


def validate_market_sample(family: str, scope: str, last10_home: list, last10_away: list,
                            min_games: int = 5, team_id: int | None = None) -> dict:
    """Amostra minima ESPECIFICA da familia de mercado, nao do time em
    geral -- um time pode ter historico geral rico (validate_history
    passa) mas o campo bruto desta familia (ex.: home_corners) ausente em
    parte dos jogos. stats_model._extract_stat() trata campo ausente como
    0 no calculo de taxa hoje (`m.get(field) or 0`) em vez de excluir o
    jogo da amostra -- isso e' uma decisao de calculo separada (mudaria
    taxa_real/confidence, fora de escopo desta validacao) -- aqui so
    reporta quantos jogos do pool realmente TEM o dado, pra essa lacuna
    nao ficar invisivel."""
    pool, _ = stats_model.pool_and_field(family, scope, last10_home, last10_away, team_id)
    if not pool:
        return {"passed": False, "amostra_total": 0, "amostra_com_dado": 0, "reasons": ["Sem jogos no pool desta familia"]}

    fields = stats_model._FAMILY_STAT_FIELDS.get(family)
    if not fields:
        # Familia sem campo bruto dedicado (ex.: btts usa home_goals/
        # away_goals, sempre presentes p/ jogos com status FT) -- sem gap
        # conhecido de cobertura pra checar aqui.
        return {"passed": len(pool) >= min_games, "amostra_total": len(pool), "amostra_com_dado": len(pool), "reasons": []}

    def _has_data(m):
        side = stats_model.resolve_side(m, scope, team_id)
        if side in ("home", "away"):
            return m.get(fields[side]) is not None
        total_field = fields.get("total")
        if total_field:
            return m.get(total_field) is not None
        return m.get(fields["home"]) is not None or m.get(fields["away"]) is not None

    com_dado = sum(1 for m in pool if _has_data(m))
    reasons = []
    if com_dado < len(pool):
        reasons.append(
            f"{len(pool) - com_dado} de {len(pool)} jogos sem o campo desta familia preenchido "
            f"(tratados como 0 no calculo de taxa hoje)"
        )
    if com_dado < min_games:
        reasons.append(f"Amostra real com dado ({com_dado}) abaixo do minimo ({min_games})")

    return {
        "passed": com_dado >= min_games,
        "amostra_total": len(pool),
        "amostra_com_dado": com_dado,
        "reasons": reasons,
    }


# ============================================================
# 2. COBERTURA
# ============================================================
def validate_coverage(
    structured_odds: list | None,
    last10_home: list | None,
    last10_away: list | None,
    standings_home: dict | None = None,
    standings_away: dict | None = None,
    referee_stats: dict | None = None,
    context_data: dict | None = None,
    h2h: list | None = None,
) -> dict:
    """Verifica existencia de cada fonte de dado pra esta partida. H2H nao
    tem coletor hoje (ver plano de coleta nova) -- sempre marcado ausente,
    nao conta como falha (e um gap conhecido, nao um erro desta partida
    especifica) mas fica visivel no relatorio pra nao mascarar a lacuna."""
    sources = {
        "odds":            bool(structured_odds),
        "history_home":    bool(last10_home),
        "history_away":    bool(last10_away),
        "standings_home":  bool(standings_home),
        "standings_away":  bool(standings_away),
        "referee":         bool(referee_stats),
        "context":         bool(context_data),
        "h2h":             bool(h2h),
    }
    # H2H fora do calculo de score por enquanto -- gap de coleta conhecido,
    # nao penaliza partida por partida (ver Paralelo no plano de refatoracao).
    scored_sources = {k: v for k, v in sources.items() if k != "h2h"}
    present = sum(1 for v in scored_sources.values() if v)
    total = len(scored_sources)
    missing = [k for k, v in sources.items() if not v]

    return {
        "score": round(present / total * 100, 1) if total else 0.0,
        "sources": sources,
        "missing": missing,
    }


# ============================================================
# 3. INTEGRIDADE
# ============================================================
_NON_NEGATIVE_FIELDS = (
    "home_goals", "away_goals", "home_corners", "away_corners",
    "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards",
    "home_fouls", "away_fouls", "home_shots_on", "away_shots_on",
    "home_total_shots", "away_total_shots", "home_offsides", "away_offsides",
)
_TOTAL_PAIRS = (
    ("total_goals", "home_goals", "away_goals"),
    ("total_corners", "home_corners", "away_corners"),
    ("total_yellow_cards", "home_yellow_cards", "away_yellow_cards"),
)


def validate_statistics_integrity(matches: list) -> dict:
    """Verifica campos negativos e inconsistencia entre total_X e
    home_X+away_X (quando os dois existem no mesmo jogo -- alguns
    historicos so tem um dos dois, o que e normal, nao um erro)."""
    issues = []
    for i, m in enumerate(matches):
        for field in _NON_NEGATIVE_FIELDS:
            val = m.get(field)
            if val is not None and val < 0:
                issues.append(f"jogo {i} ({m.get('match_date')}): {field}={val} (negativo)")

        for total_field, home_field, away_field in _TOTAL_PAIRS:
            total = m.get(total_field)
            home = m.get(home_field)
            away = m.get(away_field)
            if total is not None and home is not None and away is not None and total != home + away:
                issues.append(
                    f"jogo {i} ({m.get('match_date')}): {total_field}={total} "
                    f"mas {home_field}+{away_field}={home + away}"
                )

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "issue_count": len(issues),
        "matches_checked": len(matches),
    }


# ============================================================
# 4. OUTLIERS
# ============================================================
# Modified z-score via mediana + MAD (Iglewicz & Hoaglin) em vez de
# media+desvio-padrao: media/desvio sao PUXADOS pelo proprio outlier que
# se quer detectar (efeito "masking" -- um unico jogo bizarro numa amostra
# pequena de ~15 jogos infla o desvio o bastante pra se esconder do
# proprio z-score). Mediana e MAD sao resistentes a isso -- e o metodo
# padrao recomendado pra deteccao de outlier em amostras pequenas.
_MODIFIED_Z_THRESHOLD_DEFAULT = 3.5
_MAD_CONSTANT = 0.6745


def _median(values: list) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def detect_outliers(family: str, scope: str, last10_home: list, last10_away: list,
                     z_threshold: float = _MODIFIED_Z_THRESHOLD_DEFAULT,
                     team_id: int | None = None) -> dict:
    """Marca jogos cujo valor bruto foge muito da mediana do proprio pool
    (modified z-score via MAD > z_threshold). Amostra pequena (<2) ou
    familia sem leitura de valor bruto -> sem deteccao possivel, retorna
    vazio (nao e erro).

    `team_id` resolve o mando por partida (ver stats_model.resolve_side) --
    sem ele o pool alterna entre o valor do time e o do adversario, o que
    embaralha mediana e MAD e faz a deteccao apontar o alvo errado."""
    if family not in variance_model._VALUE_FAMILIES:
        return {"outliers": [], "outlier_count": 0, "checked": 0}

    pool, _ = stats_model.pool_and_field(family, scope, last10_home, last10_away, team_id)
    if not pool or len(pool) < 2:
        return {"outliers": [], "outlier_count": 0, "checked": len(pool)}

    values = [stats_model._extract_stat(m, family, scope, team_id) for m in pool]
    median = _median(values)
    mad = _median([abs(v - median) for v in values])

    outliers = []
    if mad > 0:
        for m, value in zip(pool, values):
            modified_z = _MAD_CONSTANT * (value - median) / mad
            if abs(modified_z) > z_threshold:
                outliers.append({
                    "match_date": m.get("match_date"),
                    "value": value,
                    "median": median,
                    "modified_z_score": round(modified_z, 2),
                })

    return {
        "outliers": outliers,
        "outlier_count": len(outliers),
        "checked": len(pool),
    }


# ============================================================
# 4b. AGREGACAO POR FIXTURE (P1.2 -- liga integrity/outlier no DQS)
# ============================================================
# Familias com leitura de valor bruto (mesmo escopo de variance_model.
# _VALUE_FAMILIES) -- outlier e' por familia, mas o Data Quality Score e'
# computado 1x por fixture (nao por mercado) nos pipelines hoje; agregar
# aqui evita reestruturar o call site pra virar por-familia.
_OUTLIER_CHECK_FAMILIES = ("goals", "corners", "cards")


def aggregate_fixture_quality_checks(last10_home: list, last10_away: list,
                                      home_team_id: int | None = None,
                                      away_team_id: int | None = None) -> tuple[dict, dict]:
    """Roda validate_statistics_integrity() (nivel fixture, cobre todas as
    familias de uma vez) e detect_outliers() (por familia, agregado aqui)
    pros dois times, devolve (integrity_validation, outlier_info) prontos
    pra passar em data_quality_score(). Bug real corrigido 2026-07-25: as
    duas funcoes existiam e nunca eram chamadas por nenhum pipeline --
    data_quality_score() rodava sempre com os dois componentes travados em
    100.0 (25% do peso do score cego a outlier/inconsistencia real)."""
    integrity = validate_statistics_integrity(last10_home + last10_away)

    outliers, checked = [], 0
    for family in _OUTLIER_CHECK_FAMILIES:
        for scope in ("home", "away"):
            info = detect_outliers(
                family, scope, last10_home, last10_away,
                team_id=stats_model.scope_team_id(scope, home_team_id, away_team_id),
            )
            outliers.extend(info["outliers"])
            checked += info["checked"]
    outlier_info = {"outliers": outliers, "outlier_count": len(outliers), "checked": checked}

    return integrity, outlier_info


# ============================================================
# 5. DATA QUALITY SCORE (0-100)
# ============================================================
_W_HISTORY = 0.40
_W_COVERAGE = 0.35
_W_INTEGRITY = 0.15
_W_OUTLIER = 0.10


def data_quality_score(history_validation: dict, coverage_validation: dict,
                        integrity_validation: dict | None = None,
                        outlier_info: dict | None = None) -> dict:
    """Combina os 4 validadores num score 0-100 -- cada componente exposto
    separadamente (nunca um numero opaco). Integridade/outlier sao
    opcionais (nem todo caller roda os 4 -- ex.: outlier so faz sentido
    por familia de mercado, nao por fixture inteiro de uma vez)."""
    history_component = history_validation["Q"] * 100
    coverage_component = coverage_validation["score"]

    if integrity_validation is not None:
        checked = integrity_validation["matches_checked"] or 1
        integrity_component = max(0.0, 100 - (integrity_validation["issue_count"] / checked * 100))
    else:
        integrity_component = 100.0

    if outlier_info is not None and outlier_info["checked"] > 0:
        outlier_ratio = outlier_info["outlier_count"] / outlier_info["checked"]
        outlier_component = max(0.0, 100 - outlier_ratio * 200)
    else:
        outlier_component = 100.0

    total = (
        history_component * _W_HISTORY + coverage_component * _W_COVERAGE
        + integrity_component * _W_INTEGRITY + outlier_component * _W_OUTLIER
    )

    return {
        "score": round(total, 1),
        "components": {
            "history": round(history_component, 1),
            "coverage": round(coverage_component, 1),
            "integrity": round(integrity_component, 1),
            "outlier": round(outlier_component, 1),
        },
    }
