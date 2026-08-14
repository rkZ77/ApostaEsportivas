from utils.db_utils import get_connection


class StandingsService:

    def get_team_standing(self, team_id, league_id, season):

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""

        SELECT
            rank,
            points,
            goals_diff,
            form,
            played,
            win,
            draw,
            lose
        FROM league_standings
        WHERE team_id = %s
        AND league_id = %s
        AND season = %s

        """, (team_id, league_id, season))

        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return None

        return {
            "rank": row[0],
            "points": row[1],
            "goal_diff": row[2],
            "form": row[3],
            "played": row[4],
            "wins": row[5],
            "draws": row[6],
            "losses": row[7]
        }

    def get_league_table(self, league_id, season):
        """A tabela INTEIRA da competicao, ordenada por posicao.

        get_team_standing devolve a linha de um time so', e com uma linha so'
        nao da' pra responder o que a camada de pressao competitiva precisa:
        "quantos pontos faltam pra sair do rebaixamento" exige saber quem esta'
        na primeira posicao FORA dele. Por isso esta consulta existe separada,
        em vez de virar dois get_team_standing.

        `description` e' a marcacao da propria API-Football pra cada faixa
        ("Relegation", "Promotion - Copa Libertadores (Group Stage)",
        "Champions League league stage"). E' de la' que as zonas saem -- cada
        liga tem um desenho diferente (o Brasileirao rebaixa 4, o Portugues
        rebaixa 2 e ainda tem um playoff), e adivinhar isso por numero fixo de
        posicoes daria errado em metade das ligas cobertas.

        Lista vazia quando a liga nao tem classificacao coletada (copa/
        mata-mata) ou a consulta falha -- nunca levanta, pelo mesmo motivo de
        get_for_fixture: classificacao e' sinal auxiliar.
        """
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT team_id, team_name, rank, points, goals_diff, form,
                       played, win, draw, lose, description
                FROM league_standings
                WHERE league_id = %s AND season = %s
                ORDER BY rank
            """, (league_id, season))
            linhas = [
                {"team_id": r[0], "team_name": r[1], "rank": r[2], "points": r[3],
                 "goal_diff": r[4], "form": r[5], "played": r[6], "wins": r[7],
                 "draws": r[8], "losses": r[9], "description": r[10]}
                for r in cur.fetchall()
            ]
            cur.close()
            conn.close()
            return linhas
        except Exception as e:
            print(f"[STANDINGS] Tabela indisponivel "
                  f"(liga {league_id}, temporada {season}): {e}")
            return []

    def get_for_fixture(self, home_team_id, away_team_id, league_id, season):
        """(mandante, visitante) na tabela da competicao -- mesmo formato de
        acesso que TeamStatsService.get_for_fixture ja' usa nos pipelines.

        (None, None) quando a liga nao tem classificacao coletada (copa/
        mata-mata) ou a consulta falha: sem tabela o motor volta ao
        comportamento anterior, so' sem o sinal de pressao. Nunca levanta --
        classificacao e' sinal auxiliar, nao pode derrubar a geracao de pick.

        Ate' 2026-08-05 nenhum pipeline chamava StandingsService: todos
        passavam None pros dois lados de context_model.build_context(), o que
        deixava table_pressure() preso em 'desconhecido' e desligava na
        pratica o termo de pressao no context_score, o componente de pressao
        no game_intensity (gate de cartoes) e o efeito da fase de mata-mata.
        """
        try:
            return (
                self.get_team_standing(home_team_id, league_id, season),
                self.get_team_standing(away_team_id, league_id, season),
            )
        except Exception as e:
            print(f"[STANDINGS] Classificacao indisponivel "
                  f"(liga {league_id}, temporada {season}): {e}")
            return None, None