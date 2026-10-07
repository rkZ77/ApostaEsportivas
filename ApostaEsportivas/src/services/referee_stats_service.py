import psycopg2.extras
from utils.arbitro import chave_do_arbitro, sql_chave
from utils.db_utils import get_connection


class RefereeStatsService:

    def get_stats(self, referee: str, season: int) -> dict | None:
        """Médias do árbitro na temporada, ou None se não houver jogo dele.

        AGREGA DIRETO DE match_statistics PELA CHAVE DO NOME (2026-10-07).
        Antes lia `referee_stats` casando `referees.name` com o texto exato do
        jogo de hoje. A API escreve o mesmo árbitro de mais de um jeito
        ("Raphael Claus" / "Raphael Claus, Brazil"), cada grafia tinha a sua
        linha em `referees`, e a amostra dele ficava partida: o motor achava só
        o pedaço com a grafia de hoje e caía no fallback da liga. Ver
        utils/arbitro.py.

        Mesmas colunas e mesmo recorte do coletor
        (`_recalculate_referee_stats`): temporada, jogo encerrado, e `games`
        contando só jogo com folha de cartão, que é a amostra do gate.
        """
        chave = chave_do_arbitro(referee)
        if not chave:
            return None

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(f"""
            SELECT
                %s                                                   AS referee,
                %s                                                   AS season,
                COUNT(*) FILTER (WHERE ms.total_yellow_cards IS NOT NULL) AS games,
                COUNT(*)                                             AS games_total,
                ROUND(AVG(ms.total_yellow_cards)::numeric, 2)        AS avg_yellow,
                ROUND(AVG(ms.total_red_cards)::numeric, 2)           AS avg_red,
                ROUND(AVG(ms.home_fouls + ms.away_fouls)::numeric, 2) AS avg_fouls,
                ROUND(AVG(ms.total_corners)::numeric, 2)             AS avg_corners,
                ROUND(AVG(ms.total_goals)::numeric, 2)               AS avg_goals,
                MAX(ms.total_yellow_cards)                           AS max_yellow,
                MIN(ms.total_yellow_cards)                           AS min_yellow
            FROM match_statistics ms
            WHERE {sql_chave('ms.referee')} = %s
              AND ms.season = %s
              AND ms.status IN ('FT', 'AET', 'PEN')
        """, (referee, season, chave, season))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or not row["games_total"]:
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
              -- Mesmo recorte da media do arbitro (2026-10-07): jogo adiado
              -- ou interrompido com placar parcial nao entra.
              AND status IN ('FT', 'AET', 'PEN')
        """, (league_id, season))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or not row["games"]:
            return None

        return dict(row)
