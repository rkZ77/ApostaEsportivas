from utils.db_utils import get_connection


class MatchStatsServiceMedia:

    def __init__(self, conn=None):
        """Conexao COMPARTILHADA por lote (2026-08-28).

`conn=None` mantem o comportamento de sempre -- uma conexao por chamada, que
e' o que todo chamador antigo espera. Passando uma conexao, a classe inteira
passa a usar aquela e NAO fecha nada: quem abriu, fecha.

POR QUE ISTO IMPORTA MAIS DO QUE PARECE

Abrir conexao com o Supabase custa ~1000ms medidos (a consulta mediana custa
~150ms, e o plano dela roda em menos de 1ms -- o custo e' handshake, nao
banco). O agregador abria uma conexao POR CONSULTA: ler os jogos do time, e
mais uma por upsert de contexto. Sao ~3 por time.

E ele nao roda so' na mao. `website/backend/stats_sweep` dispara
`update_stale_teams_statistics()` numa VISITA ao site, em thread de fundo. Com
dezenas de times na fila isso e' centena de conexoes abertas em rajada -- e
elas saem das MESMAS ~57 conexoes que o projeto Supabase tem pro site inteiro
(`website/backend/database` explica o teto). O sintoma no navegador e' o que
o usuario relatou: tela que carrega na hora e tela que fica pendurada,
dependendo de estar ou nao no meio de uma varredura.
"""
        self.db = get_connection
        self._conn = conn

    def _abrir(self):
        """(conexao, fecha_no_fim). Ver a docstring de __init__."""
        if self._conn is not None:
            return self._conn, False
        return self.db(), True

    ##########################################################################
    # BUSCA TODOS OS JOGOS FINALIZADOS (FT) DO TIME NA TEMPORADA
    ##########################################################################
    def get_team_games_stats_in_season(self, team_id, league_id, season):

        conn, fechar = self._abrir()
        cur = conn.cursor()

        query = """
            SELECT *
            FROM match_statistics
            WHERE league_id = %s
              AND season = %s
              AND status = 'FT'
              AND (home_team_id = %s OR away_team_id = %s)
        """

        cur.execute(query, (league_id, season, team_id, team_id))

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        cur.close()
        if fechar:
            conn.close()

        return [dict(zip(columns, row)) for row in rows]

    ##########################################################################
    # BUSCA ÚLTIMOS N JOGOS DA SELEÇÃO (QUALQUER COMPETIÇÃO)
    ##########################################################################
    def get_national_team_last_n_games(self, team_id, last_n=10):
        """Últimos N jogos finalizados de uma seleção, independente de liga/temporada."""
        conn, fechar = self._abrir()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM match_statistics
            WHERE status = 'FT'
              AND (home_team_id = %s OR away_team_id = %s)
            ORDER BY match_date DESC
            LIMIT %s
        """, (team_id, team_id, last_n))

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        cur.close()
        if fechar:
            conn.close()

        return [dict(zip(columns, row)) for row in rows]

    ##########################################################################
    # LÓGICA DE AGREGAÇÃO COMPARTILHADA
    ##########################################################################

    #: Métrica -> (sufixo da coluna do lado FEITO, sufixo do lado CEDIDO).
    #: A chave é o nome que vira `avg_<chave>_for` / `avg_<chave>_against` em
    #: `team_statistics`, e o valor é como a coluna se chama em
    #: `match_statistics` depois do prefixo home_/away_.
    _METRICAS = [
        ("goals",           "goals",           "goals"),
        ("corners",         "corners",         "corners"),
        ("yellow",          "yellow_cards",    "yellow_cards"),
        ("red",             "red_cards",       "red_cards"),
        ("shots_on",        "shots_on",        "shots_on"),
        ("shots_off",       "shots_off",       "shots_off"),
        ("total_shots",     "total_shots",     "total_shots"),
        ("blocked",         "blocked_shots",   "blocked_shots"),
        ("saves",           "goalkeeper_saves", "goalkeeper_saves"),
        ("fouls",           "fouls",           "fouls"),
        ("offsides",        "offsides",        "offsides"),
        ("possession",      "possession",      "possession"),
        ("passes",          "passes",          "passes"),
        ("passes_accuracy", "passes_accuracy", "passes_accuracy"),
    ]

    #: Métricas cujo TOTAL da partida (feitos + cedidos) tem coluna própria em
    #: `team_statistics`. Só existem para as quatro que viram mercado de total.
    _COM_TOTAL = ("goals", "corners", "yellow", "red")

    def _aggregate_games(self, games, team_id):
        """Agrega lista de jogos em médias HOME/AWAY. Usado por ambos os métodos.

        CADA MÉTRICA DIVIDE PELOS JOGOS EM QUE ELA EXISTE (2026-08-28).

        Até aqui isto somava `g.get(coluna) or 0` e dividia tudo pelo mesmo
        `count`. Ou seja: partida sem folha entrava na média como partida com
        zero escanteio, zero falta e zero posse de bola.

        É o mesmo `or 0` que já foi corrigido em duas outras camadas -- o
        coletor (utils/stat_sheet, que grava NULL em vez de zero) e o histórico
        cru do motor (stats_model._tem_folha_da_familia, que derruba do pool o
        jogo de folha parcial). As duas correções passaram longe DESTA função,
        que é justamente a que alimenta `team_statistics`: desde 2026-08-03 ela
        é a fonte PREFERIDA do cruzamento feitos-x-cedidos, e o histórico cru é
        só o fallback. A correção foi toda pro caminho de reserva.

        Medido em PROD em 2026-08-28: 145 das 1.490 fatias (time, liga,
        temporada, mando) tinham pelo menos um jogo assim, e nelas a média saía
        1,23 escanteio e 4,06 faltas ABAIXO da real. O erro tem direção fixa,
        sempre pra baixo, ou seja sempre inflando Under.

        `games_by_stat` guarda quantos jogos sustentaram cada métrica. Sem isso
        o encolhimento de stats_model acreditaria numa amostra maior do que a
        que ele de fato tem (ele lê `games_count`, que é a contagem de jogos do
        time no mando, não a da métrica).
        """

        def base_totals():
            t = {"count": 0}
            for chave, _f, _a in self._METRICAS:
                t[f"{chave}_for"] = 0.0
                t[f"{chave}_against"] = 0.0
                t[f"n_{chave}"] = 0
                # O total da partida só conta quando os DOIS lados vieram: com
                # um lado só, "total de escanteios do jogo" seria metade dele.
                t[f"n_{chave}_total"] = 0
                t[f"{chave}_total"] = 0.0
            return t

        home = base_totals()
        away = base_totals()

        for g in games:

            if g["home_team_id"] == team_id:
                target, prefix_for, prefix_against = home, "home", "away"
            else:
                target, prefix_for, prefix_against = away, "away", "home"

            for chave, col_for, col_against in self._METRICAS:
                feito = g.get(f"{prefix_for}_{col_for}")
                cedido = g.get(f"{prefix_against}_{col_against}")

                # Ausência não é zero. O jogo continua contando pra `count`
                # (ele aconteceu) mas não entra na média desta métrica.
                if feito is not None:
                    target[f"{chave}_for"] += float(feito)
                    target[f"n_{chave}"] += 1
                if feito is not None and cedido is not None:
                    target[f"{chave}_total"] += float(feito) + float(cedido)
                    target[f"n_{chave}_total"] += 1
                if cedido is not None:
                    target[f"{chave}_against"] += float(cedido)

            target["count"] += 1

        def build_avg(totals, context_type):
            count = totals["count"]
            if count == 0:
                return None

            result = {}
            amostra = {}
            for chave, _f, _a in self._METRICAS:
                n = totals[f"n_{chave}"]
                amostra[chave] = n
                # Métrica que NENHUM jogo publicou fica NULL, e não zero: a
                # coluna vazia é lida como ausência pelo motor (que cai no
                # histórico cru), enquanto um zero seria número inventado.
                result[f"avg_{chave}_for"] = round(totals[f"{chave}_for"] / n, 2) if n else None
                result[f"avg_{chave}_against"] = (
                    round(totals[f"{chave}_against"] / n, 2) if n else None)

                if chave in self._COM_TOTAL:
                    n_tot = totals[f"n_{chave}_total"]
                    result[f"avg_total_{chave}"] = (
                        round(totals[f"{chave}_total"] / n_tot, 2) if n_tot else None)

            result["games_count"] = count
            result["games_by_stat"] = amostra
            result["context_type"] = context_type
            return result

        results = []
        for totals, contexto in ((home, "HOME"), (away, "AWAY")):
            media = build_avg(totals, contexto)
            if media:
                results.append(media)

        return results

    ##########################################################################
    # CALCULA MÉDIAS COMPLETAS SEPARADAS POR HOME / AWAY
    ##########################################################################
    def calculate_team_season_averages(self, team_id, league_id, season):

        games = self.get_team_games_stats_in_season(team_id, league_id, season)

        if not games:
            return []

        return self._aggregate_games(games, team_id)

    ##########################################################################
    # CALCULA MÉDIAS DAS SELEÇÕES · ÚLTIMOS N JOGOS (AMISTOSOS + COPA)
    ##########################################################################
    def calculate_national_team_averages(self, team_id, last_n=10):
        """Médias dos últimos N jogos da seleção, misturando amistosos e Copa do Mundo."""
        games = self.get_national_team_last_n_games(team_id, last_n)

        if not games:
            return []

        return self._aggregate_games(games, team_id)
