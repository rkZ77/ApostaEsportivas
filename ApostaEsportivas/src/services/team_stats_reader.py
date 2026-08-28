from psycopg2.extras import Json

from utils.db_utils import get_connection


#: O RECORTE DE QUEM MERECE MEDIA (2026-08-28).
#:
#: Ate' aqui as duas varreduras (`get_all_teams` e
#: `get_teams_with_stale_statistics`) partiam da tabela `teams`, e isso errava
#: nas DUAS pontas ao mesmo tempo:
#:
#:   SOBRAVA  `teams` guarda toda liga que ja' passou pelo coletor, inclusive a
#:            inativa e a de temporada encerrada. Em PROD (28/08) eram 141 das
#:            1.490 linhas de `team_statistics` -- 9,5% da tabela -- calculadas
#:            e regravadas todo dia pra uma liga que o motor nunca consulta.
#:
#:   FALTAVA  o INNER JOIN em `teams` exclui o time que JOGOU na liga mas nao
#:            foi cadastrado nela (a sincronizacao de times traz o elenco da
#:            liga, e um time que entrou por mata-mata, repescagem ou
#:            renomeacao fica de fora). Em PROD eram 457 combinacoes
#:            (time, liga, temporada) com 1.398 partidas gravadas e nenhuma
#:            media possivel. Elas apareciam no /admin como "sem media" e o
#:            botao de recalculo nunca as alcancava, porque ele fazia o mesmo
#:            INNER JOIN -- backlog que nao tinha como zerar.
#:
#: A pergunta certa nao e' "este time esta' cadastrado?", e' "esta partida esta'
#: numa competicao que o motor le?". Quem responde isso e' `leagues`: cadastrada,
#: `ativa`, e na temporada corrente dela.
#:
#: Custa zero requisicao de API -- e' recorte de tabela.
_SQL_ALVOS_DA_MEDIA = """
    SELECT DISTINCT lado.team_id, ms.league_id, ms.season
      FROM match_statistics ms
      JOIN leagues l ON l.league_id = ms.league_id
                    AND l.season = ms.season
                    AND COALESCE(l.ativa, TRUE)
      CROSS JOIN LATERAL (VALUES (ms.home_team_id), (ms.away_team_id))
           AS lado(team_id)
     WHERE lado.team_id IS NOT NULL
       AND ms.status = 'FT'
"""


class TeamStatsReader:

    def __init__(self, conn=None):
        """Conexao COMPARTILHADA por lote (2026-08-28).

        `conn=None` mantem o comportamento de sempre -- uma conexao por
        chamada, que e' o que todo chamador antigo espera. Passando uma
        conexao, a classe usa aquela e NAO fecha nada: quem abriu, fecha.

        Ver a docstring de MatchStatsServiceMedia.__init__ pro numero medido e
        pro efeito disso no site.
        """
        self._conn = conn

    def _abrir(self):
        """(conexao, fecha_no_fim)."""
        if self._conn is not None:
            return self._conn, False
        return get_connection(), True

    ##########################################################################
    # Busca todos os times que merecem media
    ##########################################################################
    def get_all_teams(self):
        """Todo time que o motor pode ler · ver _SQL_ALVOS_DA_MEDIA."""

        conn, fechar = self._abrir()
        cur = conn.cursor()

        cur.execute(_SQL_ALVOS_DA_MEDIA)

        rows = cur.fetchall()

        cur.close()
        if fechar:
            conn.close()

        return [
            {"team_id": r[0], "league_id": r[1], "season": r[2]}
            for r in rows
        ]

    ##########################################################################
    # Retorna times distintos que tiveram fixture atualizada recentemente
    ##########################################################################
    def get_teams_with_recent_fixtures(self, days=3):
        from datetime import datetime, timedelta, timezone
        conn, fechar = self._abrir()
        cur = conn.cursor()
        limit_date = datetime.now(timezone.utc) - timedelta(days=days)
        # Mesmo recorte de `get_teams_with_stale_statistics` (ver
        # _SQL_ALVOS_DA_MEDIA): antes isto fazia INNER JOIN em `teams` e
        # herdava os dois erros descritos la'.
        cur.execute(f"""
            WITH alvos AS (
                {_SQL_ALVOS_DA_MEDIA}
            )
            SELECT DISTINCT lado.team_id, ms.league_id, ms.season
              FROM match_statistics ms
              CROSS JOIN LATERAL (VALUES (ms.home_team_id), (ms.away_team_id))
                   AS lado(team_id)
              JOIN alvos a ON a.team_id = lado.team_id
                          AND a.league_id = ms.league_id
                          AND a.season = ms.season
             WHERE ms.last_updated >= %s
        """, (limit_date,))
        rows = cur.fetchall()
        cur.close()
        if fechar:
            conn.close()
        return [{"team_id": r[0], "league_id": r[1], "season": r[2]} for r in rows]

    ##########################################################################
    # DELETA TODAS AS ESTATÍSTICAS
    ##########################################################################
    def delete_all_team_statistics(self):

        conn, fechar = self._abrir()
        cur = conn.cursor()

        print("[TeamStatsReader] Deletando todas as estatísticas...")

        cur.execute("DELETE FROM team_statistics;")

        conn.commit()
        cur.close()
        if fechar:
            conn.close()

        print("ok team_statistics limpa.\n")

    ##########################################################################
    # UPSERT na team_statistics COM CONTEXT_TYPE
    ##########################################################################
    def get_teams_with_stale_statistics(self, limite: int = 0):
        """Times cuja MEDIA esta' mais velha que a ultima partida deles.

        POR QUE ISTO EXISTE (2026-08-27)

        As duas formas que havia eram grossas demais nas duas pontas:

          update_full_season_statistics()      APAGA `team_statistics` inteira
                                               e reprocessa todo time do banco;
          update_recent_teams_statistics(3)    reprocessa todo time que teve
                                               jogo nos ultimos 3 dias.

        A segunda e' a que a varredura automatica usava, e ela refaz a conta de
        um time mesmo quando NADA daquele time mudou na passada -- basta ele ter
        jogado. Numa janela de tres dias cheia sao dezenas de times, cada um
        custando duas leituras da temporada inteira e dois upserts com conexao
        propria. O trabalho e' quase todo desperdicio, e ele acontece no
        caminho de uma VISITA ao site.

        Aqui a pergunta e' a exata: existe partida daquele time gravada DEPOIS
        da ultima vez que a media dele foi escrita? Se nao existe, refazer a
        conta produz o mesmo numero.

        Custa zero requisicao de API -- e' comparacao de `last_updated` entre
        duas tabelas que ja' tem a coluna.

        Time SEM linha em `team_statistics` entra: media que nunca foi
        calculada e' o caso mais desatualizado que existe, e o LEFT JOIN
        devolveria NULL, que nao e' "menor que" nada em SQL.
        """
        conn, fechar = self._abrir()
        cur = conn.cursor()
        # `team_statistics` tem uma linha por contexto (HOME/AWAY); a media do
        # time so' esta' em dia quando A MAIS VELHA delas for mais nova que a
        # ultima partida. MIN, portanto, e nao MAX.
        cur.execute(f"""
            WITH alvos AS (
                {_SQL_ALVOS_DA_MEDIA}
            ),
            ultima_partida AS (
                SELECT lado.team_id, ms.league_id, ms.season,
                       MAX(ms.last_updated) AS gravada_em
                  FROM match_statistics ms
                  CROSS JOIN LATERAL (VALUES (ms.home_team_id), (ms.away_team_id))
                       AS lado(team_id)
                 WHERE lado.team_id IS NOT NULL
                 GROUP BY lado.team_id, ms.league_id, ms.season
            ),
            media AS (
                SELECT team_id, league_id, season, MIN(last_updated) AS calculada_em
                  FROM team_statistics
                 GROUP BY team_id, league_id, season
            )
            SELECT u.team_id, u.league_id, u.season
              FROM ultima_partida u
              -- O recorte agora vem de `leagues`, e nao de `teams`: ver
              -- _SQL_ALVOS_DA_MEDIA pro que sobrava e o que faltava no
              -- INNER JOIN antigo.
              JOIN alvos a ON a.team_id = u.team_id
                          AND a.league_id = u.league_id
                          AND a.season = u.season
              LEFT JOIN media m ON m.team_id = u.team_id
                               AND m.league_id = u.league_id
                               AND m.season = u.season
             WHERE m.calculada_em IS NULL OR m.calculada_em < u.gravada_em
             ORDER BY u.gravada_em DESC
             {"LIMIT %s" if limite else ""}
        """, (limite,) if limite else ())
        rows = cur.fetchall()
        cur.close()
        if fechar:
            conn.close()
        return [{"team_id": r[0], "league_id": r[1], "season": r[2]} for r in rows]

    def upsert_team_statistics(self, team_id, league_id, season, stats):

        conn, fechar = self._abrir()
        cur = conn.cursor()

        context_type = stats["context_type"]

        # Remove context_type do dicionário de colunas dinâmicas. `dict` vira
        # JSONB (`games_by_stat`): psycopg2 não adapta dict sozinho.
        data_columns = {k: (Json(v) if isinstance(v, dict) else v)
                        for k, v in stats.items() if k != "context_type"}

        columns = ", ".join(data_columns.keys())
        values_placeholders = ", ".join(["%s"] * len(data_columns))
        update_set = ", ".join(
            [f"{k} = EXCLUDED.{k}" for k in data_columns.keys()]
        )

        sql = f"""
            INSERT INTO team_statistics (
                team_id,
                league_id,
                season,
                context_type,
                {columns},
                last_updated
            )
            VALUES (%s, %s, %s, %s, {values_placeholders}, NOW())
            ON CONFLICT (team_id, league_id, season, context_type)
            DO UPDATE SET
                {update_set},
                last_updated = NOW();
        """

        cur.execute(
            sql,
            [team_id, league_id, season, context_type] +
            list(data_columns.values())
        )

        conn.commit()
        cur.close()
        if fechar:
            conn.close()
