import psycopg2.extras
from utils.arbitro import (chave_do_arbitro, chaves_equivalentes, parametros_candidatas,
                           sql_candidatas, sql_chave)
from utils.db_utils import get_connection


FINALIZADOS = ("FT", "AET", "PEN")


def chaves_da_pessoa(cur, chave: str) -> list:
    """A chave do arbitro mais as outras grafias da MESMA pessoa no banco
    (18/10/2026: "Ramon Abatti" e "Ramon Abatti Abel") · regra e motivo em
    utils/arbitro.chaves_equivalentes. Funciona com cursor de tupla ou dict."""
    conhecidas = set()
    for tabela in ("match_statistics", "arbitro_partidas"):
        try:
            cur.execute("SAVEPOINT grafias")
            cur.execute(f"SELECT DISTINCT {sql_chave('referee')} AS k FROM {tabela} "
                        f"WHERE {sql_candidatas('referee')}", parametros_candidatas(chave))
            for r in cur.fetchall():
                k = r["k"] if isinstance(r, dict) else r[0]
                if k:
                    conhecidas.add(k)
            cur.execute("RELEASE SAVEPOINT grafias")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT grafias")
    return chaves_equivalentes(chave, conhecidas)


# AS DUAS FONTES DO ARBITRO (18/10/2026, pedido do usuario: "melhorar os dados
# pro motor"). `match_statistics` so' tem as ligas ativas; `arbitro_partidas`
# (collectors/arbitro_temporada_service) tem os jogos dele nas outras ligas do
# pais e os buracos de folha das ativas. A media ja' era "temporada, todas as
# competicoes" -- so' faltava o resto das competicoes. O mesmo jogo nas duas
# vale UMA vez: o de match_statistics, a menos que la' ele nao tenha a folha.
_BASE = f"""
    SELECT ms.fixture_id, ms.total_yellow_cards AS y, ms.total_red_cards AS r,
           ms.home_fouls + ms.away_fouls AS f, ms.total_corners AS c, ms.total_goals AS g
      FROM match_statistics ms
     WHERE {sql_chave('ms.referee')} = ANY(%s)
       AND ms.season = %s
       -- Status entra desde 2026-08-27: jogo adiado ou interrompido com placar
       -- parcial nao entra na media do arbitro.
       AND ms.status IN ('FT', 'AET', 'PEN')"""

_EXTRA = f"""
    SELECT ap.fixture_id, ap.home_yellow_cards + ap.away_yellow_cards AS y,
           ap.home_red_cards + ap.away_red_cards AS r,
           ap.home_fouls + ap.away_fouls AS f, NULL::int AS c,
           ap.home_goals + ap.away_goals AS g
      FROM arbitro_partidas ap
     WHERE {sql_chave('ap.referee')} = ANY(%s)
       AND ap.season = %s AND ap.status IN ('FT', 'AET', 'PEN')
       AND ap.folha_checked_at IS NOT NULL
       AND ap.home_yellow_cards IS NOT NULL"""

# `games` e' lido como AMOSTRA: cards_referee_min_games (config.py) usa esse
# numero pra liberar ou bloquear o mercado de cartoes, entao conta so' jogo com
# folha de cartao -- o mesmo conjunto de que sai a media (AVG ignora NULL).
_AGREGADO = """
    SELECT %s AS referee, %s AS season,
           COUNT(*) FILTER (WHERE y IS NOT NULL)  AS games,
           COUNT(*)                               AS games_total,
           ROUND(AVG(y)::numeric, 2)              AS avg_yellow,
           ROUND(AVG(r)::numeric, 2)              AS avg_red,
           ROUND(AVG(f)::numeric, 2)              AS avg_fouls,
           ROUND(AVG(c)::numeric, 2)              AS avg_corners,
           ROUND(AVG(g)::numeric, 2)              AS avg_goals,
           MAX(y)                                 AS max_yellow,
           MIN(y)                                 AS min_yellow
      FROM todos"""

SQL_COM_EXTRAS = f"""
    WITH base AS ({_BASE}), extra AS ({_EXTRA}),
    todos AS (
        SELECT * FROM base b
         WHERE NOT (b.y IS NULL AND EXISTS (SELECT 1 FROM extra e WHERE e.fixture_id = b.fixture_id))
        UNION ALL
        SELECT * FROM extra e
         WHERE NOT EXISTS (SELECT 1 FROM base b WHERE b.fixture_id = e.fixture_id AND b.y IS NOT NULL)
    )
    {_AGREGADO}"""

SQL_SO_BASE = f"""
    WITH todos AS ({_BASE})
    {_AGREGADO}"""


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

        Desde 18/10/2026 junta as grafias da mesma pessoa ("Ramon Abatti" e
        "Ramon Abatti Abel") e soma os jogos dele nas outras ligas do país
        (`arbitro_partidas`) · ver as notas no topo deste arquivo.
        """
        chave = chave_do_arbitro(referee)
        if not chave:
            return None

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            chaves = chaves_da_pessoa(cur, chave)
            try:
                # Ordem dos %s: base, extra, agregado.
                cur.execute(SQL_COM_EXTRAS, (chaves, season, chaves, season, referee, season))
            except Exception:
                # Ambiente sem `arbitro_partidas` (o coletor nunca rodou): so'
                # match_statistics, como era.
                conn.rollback()
                cur.execute(SQL_SO_BASE, (chaves, season, referee, season))
            row = cur.fetchone()
        finally:
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
                AVG(home_red_cards + away_red_cards) AS avg_red,
                -- Faltas da liga (18/10/2026): referencia do perfil de faltas
                -- do arbitro no dossie (arbitro_no_contexto).
                AVG(home_fouls + away_fouls) AS avg_fouls
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
