from utils.db_utils import get_connection
import psycopg2.extras
from datetime import datetime, date
from decimal import Decimal

from services.pick_engine.competition_profile import uses_all_competitions_history


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

        COPA NAO USA ESTA TABELA (2026-08-13), e o motivo e' coerencia dentro da
        MESMA fixture. `team_statistics` e' agregada por (time, liga, temporada):
        numa Libertadores ela descreve os 3 a 6 jogos daquele time NA
        Libertadores. Enquanto isso a taxa empirica do mesmo pick le 30 jogos
        multi-competicao (competition_profile.uses_all_competitions_history).
        Metade do motor lia uma amostra e a outra metade lia outra, e o
        `model_disagreement_threshold` -- que manda usar a MENOR das duas
        estimativas quando elas discordam -- disparava por causa dessa diferenca
        de fonte, nao por desacordo real sobre a partida.

        Devolvendo (None, None) aqui, o cruzamento feitos-x-cedidos cai no mesmo
        historico que a taxa usa. E o caminho de historico cru deixou de pular o
        encolhimento (ver stats_model.expected_value_convergence), entao trocar
        de fonte nao custa mais o ajuste que foi medido como ganho.

        Esta tabela ficou orfa entre 2026-07-17 (corte da IA em producao, que
        levou junto os unicos leitores dela) e 2026-08-03, sendo alimentada
        todo dia sem ninguem consumir."""
        if uses_all_competitions_history(league_id):
            return (None, None)
        return (
            self.get_stats(home_team_id, league_id, season, "HOME"),
            self.get_stats(away_team_id, league_id, season, "AWAY"),
        )

    ##########################################################################
    # Media da LIGA por contexto -- alvo do encolhimento
    ##########################################################################
    # Minimo de linhas de team_statistics pra a media de uma competicao servir
    # de alvo de encolhimento. Abaixo disso o "baseline" descreve um punhado de
    # times e carrega mais ruido do que a estimativa que ele deveria estabilizar.
    #
    # 12 linhas = 6 times com HOME e AWAY. Uma fase de grupos de Libertadores
    # tem 32 times, mas so' os que ja jogaram entram com games_count > 0, e no
    # comeco da competicao isso e' um pugilo.
    MIN_LINHAS_BASELINE = 12

    def get_league_baseline(self, league_id, season):
        """Media da liga, por contexto, de tudo que o time FAZ. E' o alvo pra
        onde a estimativa de um time e' puxada quando ele tem poucos jogos
        (stats_model.shrink_to_baseline).

        Sem isso o encolhimento nao existe, e foi exatamente o que faltava:
        medido contra 506 jogos reais, cruzar feitos-x-cedidos SEM encolher
        perde da media dos 15 jogos crus em escanteios (-1.1%) e faltas
        (-2.9%); encolhendo, passa a ganhar nas tres familias medidas
        (+2.0% / +3.5% / +2.3%).

        COMPETICAO DE COPA CAI NO BASELINE GLOBAL (2026-08-13). O alvo do
        encolhimento existe pra ESTABILIZAR uma estimativa curta; tirado de uma
        competicao que tambem tem poucos jogos, ele proprio e' instavel e passa
        a espalhar ruido em vez de conter. A media de todas as competicoes
        coletadas na temporada nao descreve a Libertadores especificamente, mas
        descreve "uma partida de futebol tipica" com amostra grande -- que e'
        exatamente o papel de um prior. Ver MIN_LINHAS_BASELINE.
        """
        proprio = self._baseline_query(
            "WHERE league_id = %s AND season = %s AND games_count > 0",
            (league_id, season))
        if proprio and (proprio.get("linhas") or 0) >= self.MIN_LINHAS_BASELINE:
            return proprio
        global_ = self._baseline_query(
            "WHERE season = %s AND games_count > 0", (season,))
        if global_ and (global_.get("linhas") or 0) > 0:
            global_["escopo"] = "global"
            return global_
        # Nem a temporada inteira tem linha: sem alvo, shrink_to_baseline
        # devolve o valor cru -- que e' melhor que encolher pra um numero
        # inventado.
        return proprio

    def _baseline_query(self, where: str, params: tuple):
        return self._query(f"""
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
            {where};
        """, params)
