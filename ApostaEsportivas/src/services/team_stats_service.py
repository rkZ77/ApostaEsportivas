from utils.db_utils import get_connection
import psycopg2.extras
from datetime import datetime, date
from decimal import Decimal


###############################################################################
# Sanitização universal
###############################################################################
def clean_stats(row):
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


class TeamStatsService:

    def _query(self, sql, params=None):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(sql, params or [])
        row = cur.fetchone()

        cur.close()
        conn.close()

        return clean_stats(row)

    ##########################################################################
    # Estatísticas filtrando por LIGA + TEMPORADA + CONTEXTO
    ##########################################################################
    def get_stats(self, team_id, league_id, season, context_type):

        return self._query("""
            SELECT *
            FROM team_statistics
            WHERE team_id = %s
              AND league_id = %s
              AND season = %s
              AND context_type = %s
            LIMIT 1;
        """, (team_id, league_id, season, context_type))

    ##########################################################################
    # Par (mandante em HOME, visitante em AWAY) de um confronto
    ##########################################################################
    def get_for_fixture(self, home_team_id, away_team_id, league_id, season):
        """(stats_mandante_em_casa, stats_visitante_fora) -- o recorte certo
        pra cruzar "o que o mandante FAZ em casa" com "o que o visitante CEDE
        fora", que e' o sinal usado por
        stats_model.expected_value_convergence().

        Devolve (None, None) por lado que nao tiver linha: time recem-promovido,
        liga sem coleta na temporada, etc. O motor cai no historico cru nesse
        caso, entao ausencia aqui nunca derruba a analise.

        Esta tabela ficou orfa entre 2026-07-17 (corte da IA em producao, que
        levou junto os unicos leitores dela) e 2026-08-03, sendo alimentada
        todo dia sem ninguem consumir."""
        return (
            self.get_stats(home_team_id, league_id, season, "HOME"),
            self.get_stats(away_team_id, league_id, season, "AWAY"),
        )

    ##########################################################################
    # Media da LIGA por contexto -- alvo do encolhimento
    ##########################################################################
    def get_league_baseline(self, league_id, season):
        """Media da liga, por contexto, de tudo que o time FAZ. E' o alvo pra
        onde a estimativa de um time e' puxada quando ele tem poucos jogos
        (stats_model.shrink_to_baseline).

        Sem isso o encolhimento nao existe, e foi exatamente o que faltava:
        medido contra 506 jogos reais, cruzar feitos-x-cedidos SEM encolher
        perde da media dos 15 jogos crus em escanteios (-1.1%) e faltas
        (-2.9%); encolhendo, passa a ganhar nas tres familias medidas
        (+2.0% / +3.5% / +2.3%)."""
        return self._query("""
            SELECT
                AVG(avg_goals_for)   FILTER (WHERE context_type = 'HOME') AS home_goals,
                AVG(avg_goals_for)   FILTER (WHERE context_type = 'AWAY') AS away_goals,
                AVG(avg_corners_for) FILTER (WHERE context_type = 'HOME') AS home_corners,
                AVG(avg_corners_for) FILTER (WHERE context_type = 'AWAY') AS away_corners,
                AVG(avg_fouls_for)   FILTER (WHERE context_type = 'HOME') AS home_fouls,
                AVG(avg_fouls_for)   FILTER (WHERE context_type = 'AWAY') AS away_fouls,
                AVG(avg_saves_for)   FILTER (WHERE context_type = 'HOME') AS home_saves,
                AVG(avg_saves_for)   FILTER (WHERE context_type = 'AWAY') AS away_saves,
                AVG(avg_yellow_for + 2 * avg_red_for)
                    FILTER (WHERE context_type = 'HOME') AS home_cards,
                AVG(avg_yellow_for + 2 * avg_red_for)
                    FILTER (WHERE context_type = 'AWAY') AS away_cards,
                COUNT(*) AS linhas
            FROM team_statistics
            WHERE league_id = %s AND season = %s AND games_count > 0;
        """, (league_id, season))
