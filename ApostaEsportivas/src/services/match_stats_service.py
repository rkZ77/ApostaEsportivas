from utils.db_utils import get_connection
import psycopg2.extras
from datetime import datetime, date
from decimal import Decimal

# Competições de seleções nacionais (API-Football IDs).
# Para esses torneios, o histórico deve cruzar TODAS as competições
# (Copa + Eliminatórias + Amistosos) — não só a liga atual.
NATIONAL_TEAM_LEAGUE_IDS: frozenset = frozenset({
    1,    # Copa do Mundo FIFA
    9,    # Copa América
    10,   # Amistosos Internacionais
    4,    # Eurocopa (UEFA)
    14,   # Copa Africana de Nações (AFCON)
    23,   # Copa Asiática (AFC)
    11,   # Eliminatórias Copa América (CONMEBOL)
    31, 32, 33, 34, 35, 36, 37, 38, 39,  # Eliminatórias Copa do Mundo
    882, 780,                              # Outros qualificatórios
})


###############################################################################
# Sanitização universal (garante compatibilidade com JSON)
###############################################################################
def clean_row(row):
    if not row:
        return None

    clean = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            clean[k] = v.isoformat()
        elif isinstance(v, Decimal):
            clean[k] = float(v)
        else:
            clean[k] = v

    return clean


def clean_list(rows):
    return [clean_row(r) for r in rows]


class MatchStatsService:

    def _query(self, sql, params=None):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(sql, params or [])
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return clean_list(rows)

    ##########################################################################
    # Últimos 10 jogos EM CASA da liga + temporada
    # Inclui opponent_name e opponent_rank via join com league_standings
    ##########################################################################
    def get_home_matches(self, team_id, season, league_id):
        return self._query("""
            SELECT
                ms.match_date,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_offsides, ms.away_offsides,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = ms.away_team_id
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE ms.home_team_id = %s
              AND ms.season = %s
              AND ms.league_id = %s
            ORDER BY ms.match_date DESC
            LIMIT 15;
        """, (team_id, season, league_id))

    ##########################################################################
    # Últimos 10 jogos FORA da liga + temporada
    # Inclui opponent_name e opponent_rank via join com league_standings
    ##########################################################################
    def get_away_matches(self, team_id, season, league_id):
        return self._query("""
            SELECT
                ms.match_date,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_offsides, ms.away_offsides,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = ms.home_team_id
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE ms.away_team_id = %s
              AND ms.season = %s
              AND ms.league_id = %s
            ORDER BY ms.match_date DESC
            LIMIT 15;
        """, (team_id, season, league_id))

    ##########################################################################
    # Últimos 10 jogos (CASA + FORA) da liga + temporada
    # Inclui opponent_name e opponent_rank via join com league_standings
    ##########################################################################
    def get_all_matches_full(self, team_id, season, league_id):
        return self._query("""
            SELECT
                ms.match_date,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_offsides, ms.away_offsides,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = CASE
                    WHEN ms.home_team_id = %s THEN ms.away_team_id
                    ELSE ms.home_team_id
                END
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.season = %s
              AND ms.league_id = %s
            ORDER BY ms.match_date DESC
            LIMIT 15;
        """, (team_id, team_id, team_id, season, league_id))

    ##########################################################################
    # Interface unificada padrão (já existente)
    # HOME → jogos em casa
    # AWAY → jogos fora
    ##########################################################################
    def get_all_matches(self, team_id, season, league_id, is_home):
        if is_home:
            return self.get_home_matches(team_id, season, league_id)
        return self.get_away_matches(team_id, season, league_id)

    ##########################################################################
    # NOVO: Interface unificada TOTAL (casa + fora)
    ##########################################################################
    def get_total_matches(self, team_id, season, league_id):
        return self.get_all_matches_full(team_id, season, league_id)

    ##########################################################################
    # SELEÇÕES — Últimos N jogos em QUALQUER competição (sem filtro de liga)
    # Usado para Copa América, Copa do Mundo, Eliminatórias e Amistosos:
    # a seleção pode ter só 3-4 jogos na Copa mas 15 contando eliminatórias.
    ##########################################################################
    def get_last_n_all_competitions(self, team_id, limit=15):
        return self._query("""
            SELECT
                ms.match_date,
                ms.league_id,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_offsides, ms.away_offsides,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                NULL::text    AS opponent_name,
                NULL::integer AS opponent_rank
            FROM match_statistics ms
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.status = 'FT'
            ORDER BY ms.match_date DESC
            LIMIT %s;
        """, (team_id, team_id, limit))

    ##########################################################################
    # Ponderação por qualidade do adversário
    # Tiers: top-6 (rank 1-6) → peso 2.0 | mid (7-12) → 1.0 | weak (13+) → 0.5
    # opponent_rank NULL → peso 1.0
    ##########################################################################
    @staticmethod
    def _opponent_weight(opponent_rank):
        if opponent_rank is None:
            return 1.0
        if opponent_rank <= 6:
            return 2.0
        if opponent_rank <= 12:
            return 1.0
        return 0.5

    def get_quality_weighted_summary(self, matches: list, team_id: int) -> dict:
        """
        Agrupa partidas por tier de qualidade do adversário e retorna stats
        por tier e uma média ponderada.

        Tiers: top-6 (rank 1-6), mid (rank 7-12), weak (rank 13+), unknown (NULL)
        Pesos: top-6=2.0, mid=1.0, weak=0.5, unknown=1.0
        """
        TIERS = {
            "top-6":   {"ranks": lambda r: r is not None and r <= 6,   "weight": 2.0},
            "mid":     {"ranks": lambda r: r is not None and 7 <= r <= 12, "weight": 1.0},
            "weak":    {"ranks": lambda r: r is not None and r >= 13,  "weight": 0.5},
            "unknown": {"ranks": lambda r: r is None,                   "weight": 1.0},
        }

        groups = {tier: [] for tier in TIERS}

        for m in matches:
            rank = m.get("opponent_rank")
            is_home = m.get("home_team_id") == team_id

            goals_scored  = m.get("home_goals", 0) if is_home else m.get("away_goals", 0)
            goals_against = m.get("away_goals", 0) if is_home else m.get("home_goals", 0)
            yellows       = m.get("home_yellow_cards", 0) if is_home else m.get("away_yellow_cards", 0)
            clean_sheet   = 1 if goals_against == 0 else 0

            entry = {
                "goals_scored":  goals_scored  or 0,
                "goals_against": goals_against or 0,
                "yellows":       yellows        or 0,
                "clean_sheet":   clean_sheet,
            }

            for tier, cfg in TIERS.items():
                if cfg["ranks"](rank):
                    groups[tier].append(entry)
                    break

        def tier_stats(entries):
            n = len(entries)
            if n == 0:
                return None
            return {
                "games":              n,
                "goals_per_game":     round(sum(e["goals_scored"]  for e in entries) / n, 2),
                "goals_against_per_game": round(sum(e["goals_against"] for e in entries) / n, 2),
                "clean_sheet_pct":    round(sum(e["clean_sheet"] for e in entries) / n * 100, 1),
                "yellow_cards_per_game": round(sum(e["yellows"] for e in entries) / n, 2),
            }

        result = {}
        for tier in TIERS:
            stats = tier_stats(groups[tier])
            if stats:
                result[tier] = stats

        # Weighted average (goals_against as main metric)
        total_weight = 0.0
        weighted_ga  = 0.0
        for tier, cfg in TIERS.items():
            entries = groups[tier]
            if not entries:
                continue
            w = cfg["weight"]
            avg_ga = sum(e["goals_against"] for e in entries) / len(entries)
            weighted_ga  += avg_ga * w * len(entries)
            total_weight += w * len(entries)

        if total_weight > 0:
            result["weighted_goals_against"] = round(weighted_ga / total_weight, 2)
        else:
            result["weighted_goals_against"] = None

        return result
