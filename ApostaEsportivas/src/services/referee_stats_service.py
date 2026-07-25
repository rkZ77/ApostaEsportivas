import psycopg2.extras
from utils.db_utils import get_connection


class RefereeStatsService:

    def get_stats(self, referee: str, season: int) -> dict | None:
        """Retorna médias pré-calculadas do árbitro na temporada, ou None se não houver dados."""
        if not referee:
            return None

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                r.referee_id,
                r.name        AS referee,
                rs.season,
                rs.games,
                rs.avg_yellow,
                rs.avg_red,
                rs.avg_fouls,
                rs.avg_corners,
                rs.avg_goals,
                rs.max_yellow,
                rs.min_yellow
            FROM referee_stats rs
            JOIN referees r ON r.referee_id = rs.referee_id
            WHERE r.name = %s
              AND rs.season = %s
        """, (referee, season))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        return dict(row)

    def get_league_stats(self, league_id: int, season: int) -> dict | None:
        """Fallback quando o arbitro especifico do jogo nao tem amostra
        confiavel (< cards_referee_min_games) -- media de cartoes da LIGA
        inteira nesta temporada, pra nao bloquear o mercado de cartoes so'
        porque um arbitro novo/pouco visto ainda nao acumulou jogos.
        referee_stats nao rastreia liga (so' temporada) -- agrega direto de
        match_statistics, que ja tem league_id proprio (registro permanente;
        `fixtures` e' so' fila operacional que roda vazia/curta entre
        coletas, join por ali perderia jogos antigos -- achado real testando
        isso: fixtures com so' 3 linhas no momento do teste, match_statistics
        com 922). Achado real 2026-07-25: gate de arbitro bloqueou cartoes em
        2 de 3 jogos VIP do dia so' por falta de dado do arbitro especifico."""
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                COUNT(*) AS games,
                AVG(home_yellow_cards + away_yellow_cards) AS avg_yellow,
                AVG(home_red_cards + away_red_cards) AS avg_red
            FROM match_statistics
            WHERE league_id = %s AND season = %s
              AND home_yellow_cards IS NOT NULL
        """, (league_id, season))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or not row["games"]:
            return None

        return dict(row)
