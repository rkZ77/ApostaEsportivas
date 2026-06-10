from utils.db_utils import get_connection
import psycopg2.extras
from datetime import datetime, date
from decimal import Decimal


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

    # Colunas relevantes para análise da IA (descarta shots/passes/posse/etc.)
    _COLS = """
        match_date,
        home_team_id, away_team_id,
        home_goals, away_goals, total_goals,
        home_corners, away_corners, total_corners,
        home_yellow_cards, away_yellow_cards, total_yellow_cards,
        home_red_cards, away_red_cards, total_red_cards,
        home_fouls, away_fouls
    """

    ##########################################################################
    # Últimos 10 jogos EM CASA da liga + temporada
    ##########################################################################
    def get_home_matches(self, team_id, season, league_id):
        return self._query(f"""
            SELECT {self._COLS}
            FROM match_statistics
            WHERE home_team_id = %s
              AND season = %s
              AND league_id = %s
            ORDER BY match_date DESC
            LIMIT 10;
        """, (team_id, season, league_id))

    ##########################################################################
    # Últimos 10 jogos FORA da liga + temporada
    ##########################################################################
    def get_away_matches(self, team_id, season, league_id):
        return self._query(f"""
            SELECT {self._COLS}
            FROM match_statistics
            WHERE away_team_id = %s
              AND season = %s
              AND league_id = %s
            ORDER BY match_date DESC
            LIMIT 10;
        """, (team_id, season, league_id))

    ##########################################################################
    # Últimos 10 jogos (CASA + FORA) da liga + temporada
    ##########################################################################
    def get_all_matches_full(self, team_id, season, league_id):
        return self._query(f"""
            SELECT {self._COLS}
            FROM match_statistics
            WHERE (home_team_id = %s OR away_team_id = %s)
              AND season = %s
              AND league_id = %s
            ORDER BY match_date DESC
            LIMIT 10;
        """, (team_id, team_id, season, league_id))

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
