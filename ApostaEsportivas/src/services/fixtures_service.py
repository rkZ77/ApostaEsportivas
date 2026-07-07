import datetime
from utils.db_utils import get_connection
import psycopg2.extras

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    _TZ_BRT = ZoneInfo("America/Sao_Paulo")
except Exception:
    _TZ_BRT = datetime.timezone(datetime.timedelta(hours=-3))


class FixturesService:

    ##########################################################################
    # Função interna para executar SELECT com conexão segura (dict)
    ##########################################################################
    def _query(self, sql, params=None, fetchone=False):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(sql, params or [])

        if fetchone:
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

    ##########################################################################
    # 1. Fixtures de HOJE
    ##########################################################################
    def get_fixtures_today(self):
        today = datetime.datetime.now(_TZ_BRT).date()
        tomorrow = today + datetime.timedelta(days=1)

        # Inclui jogos de hoje BRT + jogos de 00:00-02:59 BRT do próximo dia
        rows = self._query("""
            SELECT
                f.fixture_id,
                f.league_id,
                COALESCE(l.name, 'Unknown') AS league_name,
                f.season AS season,
                f.home_team_id,
                f.away_team_id,
                f.home_team,
                f.away_team,
                f.match_datetime,
                f.status
            FROM fixtures f
            LEFT JOIN leagues l ON f.league_id = l.league_id
            WHERE (
                DATE(f.match_datetime) = %s
                OR (DATE(f.match_datetime) = %s AND EXTRACT(HOUR FROM f.match_datetime) < 3)
            )
              AND f.status IN ('NS','TBD','LIVE')
            ORDER BY f.match_datetime ASC;
        """, (today, tomorrow))

        return self._format_fixtures(rows)

    ##########################################################################
    # 2. Buscar fixture por ID
    ##########################################################################
    def get_fixture_by_id(self, fixture_id):
        row = self._query("""
            SELECT
                f.fixture_id,
                f.league_id,
                COALESCE(l.name, 'Unknown') AS league_name,
                f.season AS season,
                f.home_team_id,
                f.away_team_id,
                f.home_team,
                f.away_team,
                f.match_datetime,
                f.status
            FROM fixtures f
            LEFT JOIN leagues l ON f.league_id = l.league_id
            WHERE f.fixture_id = %s;
        """, (fixture_id,), fetchone=True)

        if not row:
            return None

        return self._format_fixture_row(row)

    ##########################################################################
    # 3. Fixtures por intervalo de datas
    ##########################################################################
    def get_fixtures_by_range(self, start_date, end_date):
        rows = self._query("""
            SELECT
                f.fixture_id,
                f.league_id,
                COALESCE(l.name, 'Unknown') AS league_name,
                f.season AS season,
                f.home_team_id,
                f.away_team_id,
                f.home_team,
                f.away_team,
                f.match_datetime,
                f.status
            FROM fixtures f
            LEFT JOIN leagues l ON f.league_id = l.league_id
            WHERE DATE(f.match_datetime) BETWEEN %s AND %s
            ORDER BY f.match_datetime ASC;
        """, (start_date, end_date))

        return self._format_fixtures(rows)

    ##########################################################################
    # 4. Buscar TODOS os fixtures
    ##########################################################################
    def get_all_fixtures(self):
        rows = self._query("""
            SELECT
                f.fixture_id,
                f.league_id,
                COALESCE(l.name, 'Unknown') AS league_name,
                f.season AS season,
                f.home_team_id,
                f.away_team_id,
                f.home_team,
                f.away_team,
                f.match_datetime,
                f.status
            FROM fixtures f
            LEFT JOIN leagues l ON f.league_id = l.league_id
            ORDER BY f.match_datetime ASC;
        """)

        return self._format_fixtures(rows)

    ##########################################################################
    # 5. Helpers — Formatação padronizada (agora com dict)
    ##########################################################################
    def _format_fixtures(self, rows):
        fixtures = []
        for r in rows:
            fixtures.append(self._format_fixture_row(r))
        return fixtures

    def _format_fixture_row(self, r):
        return {
            "fixture_id": r["fixture_id"],
            "league_id": r["league_id"],
            "league_name": r.get("league_name"),
            "season": r.get("season"),
            "home_team_id": r["home_team_id"],
            "away_team_id": r["away_team_id"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "match_datetime": r["match_datetime"],
            "status": r["status"],
            "referee": r.get("referee"),
            "round": r.get("round"),
        }

    ##########################################################################
    # 6. Fixtures NS (usado quando quiser filtrar por league e season)
    ##########################################################################
    def load_fixtures_ns(self, league, season):
        rows = self._query("""
            SELECT
                f.fixture_id,
                f.league_id,
                COALESCE(l.name, 'Unknown') AS league_name,
                f.season AS season,
                f.home_team_id,
                f.away_team_id,
                f.home_team,
                f.away_team,
                f.match_datetime,
                f.status
            FROM fixtures f
            LEFT JOIN leagues l ON f.league_id = l.league_id
            WHERE f.league_id = %s
              AND f.season = %s
              AND f.status = 'NS'
            ORDER BY f.match_datetime ASC;
        """, (league, season))

        return self._format_fixtures(rows)

    ##########################################################################
    # 7. NOVO — Buscar TODOS os fixtures NS que ainda NÃO têm sugestão
    ##########################################################################
    def get_ns_without_suggestions(self):
        rows = self._query("""
            SELECT f.*
            FROM fixtures f
            LEFT JOIN picks_vip s ON s.fixture_id = f.fixture_id
            WHERE f.status = 'NS'
              AND s.fixture_id IS NULL
            ORDER BY f.match_datetime ASC;
        """)

        return self._format_fixtures(rows)
