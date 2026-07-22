"""Modelo de arbitro/intensidade de jogo: valida se ha dado confiavel do
arbitro e se o jogo tem contexto de tensao suficiente pra caber cartoes.
Espelha a regra que ja existia no prompt de IA legado (dica_do_dia_pipeline.py:
"cartoes so' com arbitro >=3 jogos"), agora reimplementada no motor
deterministico e usada por TODOS os pipelines (VIP/Free/Multipla/Alavancagem/
Bingo, ja que sao todos orquestrados por analyze_fixture_markets), reforcada
com o contexto de jogo (pressao de tabela + intensidade tatica dos times),
nao so o historico do arbitro isolado."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG

# Media tipica de cartoes amarelos por jogo de um arbitro -- ponto neutro do
# delta abaixo, mesmo espirito de referencia que _CONVERSION_BASELINE usa em
# team_profile_model.py (nao um "ajuste" arbitrario, so' o ponto zero).
_REFEREE_YELLOW_BASELINE = 3.8


def referee_signal(referee_stats: dict | None, config: PickEngineConfig = DEFAULT_CONFIG) -> dict:
    """Confiabilidade do dado de arbitro pra este fixture -- reliable=True
    so' com amostra minima (cards_referee_min_games) de jogos apitados na
    temporada; sem isso, os demais campos ficam None (nunca usa media com
    amostra insuficiente, mesmo se referee_stats existir)."""
    games = referee_stats.get("games", 0) if referee_stats else 0
    reliable = referee_stats is not None and games >= config.cards_referee_min_games

    def _f(key):
        # referee_stats vem direto do psycopg2 (RealDictCursor) -- colunas
        # NUMERIC do Postgres chegam como Decimal, nao float. Normaliza aqui
        # (unico ponto de entrada do dado bruto no motor) pra nunca misturar
        # Decimal com float mais adiante (bug real de producao: game_intensity
        # fazia Decimal - float e estourava TypeError).
        val = referee_stats.get(key) if reliable else None
        return float(val) if val is not None else None

    return {
        "reliable": reliable,
        "games": games,
        "avg_yellow": _f("avg_yellow"),
        "avg_red": _f("avg_red"),
        "avg_fouls": _f("avg_fouls"),
    }


def game_intensity(context_data: dict | None, matchup_data: dict | None, referee: dict) -> dict:
    """Combina 3 sinais independentes ja calculados em outros modelos (nenhum
    dado novo alem do arbitro) num score 0-1 (0.5=neutro) de "quao quente" o
    jogo tende a ser pra cartoes:
    1. pressing_score de compare_matchup (-2 a +4, faltas/posse dos 2 times).
    2. pressao de tabela dos dois lados (context_model.table_pressure).
    3. media de amarelos do arbitro vs baseline (arbitro rigoroso reforca o
       sinal, permissivo atenua).
    Sempre devolve os componentes brutos junto do rotulo -- nunca so' o
    rotulo (mesma convencao de context_model.py/team_profile_model.py)."""
    score = 0.5
    components: dict = {}

    pressing_score = None
    if matchup_data:
        pressing_score = matchup_data.get("cards", {}).get("components", {}).get("pressing_score")
    if pressing_score is not None:
        score += max(min(pressing_score / 4 * 0.20, 0.20), -0.10)
        components["pressing_score"] = pressing_score

    table_labels = {}
    if context_data:
        for side in ("table_pressure_home", "table_pressure_away"):
            label = context_data.get(side, {}).get("label")
            table_labels[side] = label
            if label in ("pressao_alta", "briga_topo"):
                score += 0.08
            elif label == "pressao_moderada":
                score += 0.04
    if table_labels:
        components["table_pressure"] = table_labels

    if referee.get("reliable") and referee.get("avg_yellow") is not None:
        diff = referee["avg_yellow"] - _REFEREE_YELLOW_BASELINE
        score += max(min(diff * 0.05, 0.15), -0.15)
        components["referee_avg_yellow"] = referee["avg_yellow"]
        components["referee_baseline"] = _REFEREE_YELLOW_BASELINE

    score = round(max(min(score, 1.0), 0.0), 4)
    if score >= 0.65:
        label = "quente"
    elif score <= 0.40:
        label = "frio"
    else:
        label = "morno"

    return {"score": score, "label": label, "components": components}


def cards_market_eligible(
    referee: dict, intensity: dict, config: PickEngineConfig = DEFAULT_CONFIG,
) -> tuple:
    """Gate duro pro mercado de cartoes (family='cards'/'handicap_cards'):
    precisa de arbitro confiavel (>=cards_referee_min_games jogos) E o jogo
    nao pode estar classificado 'frio' (score abaixo de
    cards_intensity_cold_threshold) -- so' o extremo frio bloqueia, pra nao
    zerar a frequencia de picks de cartoes. Devolve (elegivel, motivo) --
    motivo sempre preenchido quando reprovado, pra log/homologacao."""
    if not referee.get("reliable"):
        return False, f"arbitro sem dado confiavel (jogos={referee.get('games', 0)} < {config.cards_referee_min_games})"
    if intensity["score"] < config.cards_intensity_cold_threshold:
        return False, f"jogo sem contexto de tensao suficiente pra cartoes (intensidade={intensity['label']}, score={intensity['score']})"
    return True, None
