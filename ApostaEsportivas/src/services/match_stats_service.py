from utils.db_utils import get_connection
import psycopg2.extras
from datetime import datetime, date
from decimal import Decimal
from services.pick_engine.competition_profile import national_team_league_ids

# Competições de seleções nacionais (API-Football IDs).
# Para esses torneios, o histórico deve cruzar TODAS as competições
# (Copa + Eliminatórias + Amistosos) · não só a liga atual.
# Fonte única: services/pick_engine/competition_profile.py (Prioridade 1 do
# plano de refatoração · antes essa lista era mantida em paralelo aqui).
NATIONAL_TEAM_LEAGUE_IDS: frozenset = national_team_league_ids()

# Jogo encerrado, em SQL. AET/PEN entram desde 2026-08-13 · são exatamente os
# jogos de mata-mata, que é onde a amostra é curta. Quem decide se o jogo serve
# para a família de mercado em questão é stats_model.pool_and_field, porque a
# folha de um AET cobre 120 minutos e só gols têm placar de 90 separado.
FIM_DE_JOGO = "('FT', 'AET', 'PEN')"

# Quantos jogos ler no histórico multi-competição.
#
# 30 e não 15: pool_and_field fica só com os jogos do mando que o mercado
# descreve, cortando o pool a aproximadamente metade. Com 15, o time chegava a
# ~7 e não alcançava sample_rich_n=8 quase nunca. É leitura de banco, não de
# API · não custa requisição.
DEFAULT_LIMIT_MULTI = 30

# Quantos jogos ler no histórico DE LIGA (pontos corridos).
#
# Aqui o recorte já é a própria liga e a própria temporada · o campeonato tem
# começo e fim, e o time joga entre 38 e 46 partidas nele. O teto existe só pra
# a consulta não virar varredura se aparecer temporada com dado sujo; na
# prática ele quer dizer "a temporada inteira".
#
# ERA 15, E ESSE 15 FICOU PARA TRÁS.
#
# O limite do caminho multi-competição subiu de 15 para 30 em 2026-08-13, com a
# razão escrita na constante acima: `stats_model.pool_and_field` fica só com os
# jogos do MANDO que o mercado descreve, e isso corta o pool a aproximadamente
# metade · com 15 o time chegava a ~7 e não alcançava `sample_rich_n=8` quase
# nunca. A razão vale igual aqui, e ninguém subiu este lado.
#
# O efeito era o motor enxergar bem o que é raro (copa, mata-mata, seleção, que
# passam pelo caminho multi) e enxergar pouco justamente o que é comum: liga de
# pontos corridos, que é a origem da maioria esmagadora dos jogos analisados.
# Depois do filtro de mando e do descarte por família, sobrava algo em torno de
# cinco jogos por mercado.
#
# Ampliar não afrouxa a análise: `temporal_decay_weight` já pesa jogo velho
# menos (0,50 acima de 60 dias, contra 1,0 nos últimos 14). O LIMIT era um
# corte duro, de tudo ou nada, em cima de um sistema que já tinha amortecimento
# suave · e o corte duro estava chegando antes do amortecimento.
#
# É leitura de banco, não de API: não custa requisição.
DEFAULT_LIMIT_LEAGUE = 60


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

    ##########################################################################
    # Jogos EM CASA da liga + temporada (a temporada inteira)
    # Inclui opponent_name e opponent_rank via join com league_standings
    ##########################################################################
    def get_home_matches(self, team_id, season, league_id):
        """Jogos EM CASA daquele time na liga e temporada · a temporada toda.

        Mesmo corte de DEFAULT_LIMIT_LEAGUE do histórico completo, e pelo mesmo
        motivo: aqui o pool já nasce de um mando só, então cortar em 15 é
        cortar quase metade de um returno inteiro.
        """
        return self._query(f"""
            SELECT
                ms.match_date,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_goalkeeper_saves, ms.away_goalkeeper_saves,
                ms.home_offsides, ms.away_offsides,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = ms.away_team_id
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE ms.home_team_id = %s
              AND ms.season = %s
              AND ms.league_id = %s
              AND ms.status IN {FIM_DE_JOGO}
            ORDER BY ms.match_date DESC
            LIMIT {DEFAULT_LIMIT_LEAGUE};
        """, (team_id, season, league_id))

    ##########################################################################
    # Jogos FORA da liga + temporada (a temporada inteira)
    # Inclui opponent_name e opponent_rank via join com league_standings
    ##########################################################################
    def get_away_matches(self, team_id, season, league_id):
        """Jogos FORA daquele time na liga e temporada · ver get_home_matches."""
        return self._query(f"""
            SELECT
                ms.match_date,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_goalkeeper_saves, ms.away_goalkeeper_saves,
                ms.home_offsides, ms.away_offsides,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = ms.home_team_id
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE ms.away_team_id = %s
              AND ms.season = %s
              AND ms.league_id = %s
              AND ms.status IN {FIM_DE_JOGO}
            ORDER BY ms.match_date DESC
            LIMIT {DEFAULT_LIMIT_LEAGUE};
        """, (team_id, season, league_id))

    ##########################################################################
    # Jogos (CASA + FORA) da liga + temporada (a temporada inteira)
    # Inclui opponent_name e opponent_rank via join com league_standings
    ##########################################################################
    def get_all_matches_full(self, team_id, season, league_id, before_date=None, since_date=None):
        """before_date (opcional): só jogos com match_date < before_date --
        usado por backtests pra evitar vazar resultado futuro no histórico
        de um fixture já encerrado. since_date (opcional, Fase 1.6 do plano
        de implementação 2026-07-25): só jogos com match_date >= since_date
        -- usado quando o time tem uma mudança estrutural marcada (troca de
        técnico/elenco relevante, ver teams.structural_change_date) pra não
        deixar jogos de ANTES da mudança contaminar a taxa histórica. Os
        dois filtros são independentes e podem coexistir. None (padrão)
        lê a temporada inteira daquela liga · ver DEFAULT_LIMIT_LEAGUE, e o
        porquê de não serem mais os 15 de antes."""
        date_filter = "AND ms.match_date < %s" if before_date else ""
        since_filter = "AND ms.match_date >= %s" if since_date else ""
        params = (
            (team_id, team_id, team_id, season, league_id)
            + ((before_date,) if before_date else ())
            + ((since_date,) if since_date else ())
        )
        return self._query(f"""
            SELECT
                ms.match_date,
                ms.league_id,
                ms.status,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_goals_90, ms.away_goals_90,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_goalkeeper_saves, ms.away_goalkeeper_saves,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_offsides, ms.away_offsides,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = CASE
                    WHEN ms.home_team_id = %s THEN ms.away_team_id
                    ELSE ms.home_team_id
                END
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.season = %s
              AND ms.league_id = %s
              -- Status entra em 2026-08-27. O caminho multi-competição sempre
              -- filtrou (FIM_DE_JOGO); este não, e jogo adiado ou interrompido
              -- com linha gravada entrava no histórico com o que estivesse na
              -- folha. Quem decide se um AET serve pra família de mercado em
              -- questão continua sendo stats_model.pool_and_field.
              AND ms.status IN {FIM_DE_JOGO}
              {date_filter}
              {since_filter}
            ORDER BY ms.match_date DESC
            LIMIT {DEFAULT_LIMIT_LEAGUE};
        """, params)

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

    ##########################################################################
    # SELEÇÕES · Últimos N jogos em QUALQUER competição (sem filtro de liga)
    # Usado para Copa América, Copa do Mundo, Eliminatórias e Amistosos:
    # a seleção pode ter só 3-4 jogos na Copa mas 15 contando eliminatórias.
    ##########################################################################
    def get_last_n_all_competitions(self, team_id, limit=DEFAULT_LIMIT_MULTI, before_date=None, since_date=None):
        """before_date (opcional): só jogos com match_date < before_date --
        usado por backtests pra evitar vazar resultado futuro no histórico
        de um fixture já encerrado. since_date (opcional, Fase 1.6): só
        jogos com match_date >= since_date, ver get_all_matches_full().
        None (padrão) preserva o comportamento atual.

        FORÇA DO ADVERSÁRIO (2026-08-13). Até esta data as duas colunas de
        oponente saíam `NULL` cravado, e stats_model.weighted_rate pondera cada
        jogo por `opponent_weight(m["opponent_rank"])` · sem rank todo jogo caía
        em `opponent_unknown_weight`. Ou seja: justamente na copa, onde o
        histórico mistura adversário de Brasileirão com mata-mata continental, o
        ajuste por qualidade do adversário ficava DESLIGADO. O JOIN é o mesmo de
        get_all_matches_full, só que casado com `ms.league_id` de cada jogo (que
        varia aqui) em vez da liga da fixture.

        Liga sem classificação coletada (campeonato estrangeiro não cadastrado)
        continua devolvendo NULL, e isso é correto: peso desconhecido é melhor
        que peso inventado.

        LIMITE 30, não 15. O pool passa por stats_model.pool_and_field, que fica
        só com os jogos do mando que o mercado descreve · o corte é de
        aproximadamente metade. Com 15 o time chegava a ~7 no pool e não
        alcançava `sample_rich_n=8` quase nunca. O 15 antigo foi calibrado antes
        do filtro de mando existir (2026-08-08) e ninguém subiu depois.

        PRORROGAÇÃO ENTRA, mas só onde é comparável · ver
        stats_model.pool_and_field. A folha de estatística de um AET descreve
        120 minutos, então escanteios/cartões/faltas vêm inflados; só gols têm
        coluna de 90 minutos separada. Por isso a coluna `status` vai junto: a
        decisão de usar ou não o jogo é POR FAMÍLIA, e quem sabe a família é o
        modelo, não esta consulta.
        """
        date_filter = "AND ms.match_date < %s" if before_date else ""
        since_filter = "AND ms.match_date >= %s" if since_date else ""
        params = (
            (team_id, team_id, team_id)
            + ((before_date,) if before_date else ())
            + ((since_date,) if since_date else ())
            + (limit,)
        )
        return self._query(f"""
            SELECT
                ms.match_date,
                ms.league_id,
                ms.status,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_goals_90, ms.away_goals_90,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                ms.home_goalkeeper_saves, ms.away_goalkeeper_saves,
                ms.home_shots_on, ms.away_shots_on,
                ms.home_total_shots, ms.away_total_shots,
                ms.home_offsides, ms.away_offsides,
                ms.home_possession, ms.away_possession,
                ms.home_passes, ms.away_passes,
                ms.home_passes_accuracy, ms.away_passes_accuracy,
                ls.team_name AS opponent_name,
                ls.rank      AS opponent_rank
            FROM match_statistics ms
            LEFT JOIN league_standings ls
                ON ls.team_id = CASE
                    WHEN ms.home_team_id = %s THEN ms.away_team_id
                    ELSE ms.home_team_id
                END
               AND ls.league_id = ms.league_id
               AND ls.season = ms.season
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.status IN {FIM_DE_JOGO}
              {date_filter}
              {since_filter}
            ORDER BY ms.match_date DESC
            LIMIT %s;
        """, params)

    def get_h2h_matches(self, team_a, team_b, limit=10, before_date=None):
        """Confrontos diretos entre dois times, de TODAS as competicoes.

        A auditoria registrou "H2H nao tem coletor" (data_validation.
        validate_coverage marca a fonte como sempre ausente). Isso estava
        errado no diagnostico: o dado sempre esteve em `match_statistics`, que
        guarda os dois times de cada partida -- faltava a CONSULTA, nao a
        coleta. Nenhuma chamada de API nova, nenhuma tabela nova.

        Cruza todas as competicoes de proposito: a carga emocional de um
        classico nao respeita fronteira de campeonato, e restringir a liga
        atual derrubaria a amostra pra 2 jogos por temporada, que nao sustenta
        estimativa nenhuma.

        `before_date` evita vazamento em backtest, mesmo contrato dos demais
        metodos deste servico.
        """
        date_filter = "AND ms.match_date < %s" if before_date else ""
        params = (
            (team_a, team_b, team_b, team_a)
            + ((before_date,) if before_date else ())
            + (limit,)
        )
        return self._query(f"""
            SELECT
                ms.match_date, ms.league_id,
                ms.home_team_id, ms.away_team_id,
                ms.home_goals, ms.away_goals, ms.total_goals,
                ms.home_corners, ms.away_corners, ms.total_corners,
                ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                ms.home_fouls, ms.away_fouls,
                NULL::text    AS opponent_name,
                NULL::integer AS opponent_rank
            FROM match_statistics ms
            WHERE ((ms.home_team_id = %s AND ms.away_team_id = %s)
                OR (ms.home_team_id = %s AND ms.away_team_id = %s))
              AND ms.status = 'FT'
              {date_filter}
            ORDER BY ms.match_date DESC
            LIMIT %s;
        """, params)

    ##########################################################################
    # Mudanca estrutural (Fase 1.6 do plano de implementacao, 2026-07-25):
    # flag manual pra "zerar" jogos anteriores a troca de tecnico/elenco
    # relevante -- ver teams.structural_change_date. Marcacao e' processo
    # manual (quem decide que o time mudou o suficiente pra justificar),
    # nao deteccao automatica (isso seria Fase 3, changepoint formal).
    ##########################################################################
    def get_structural_change_date(self, team_id):
        row = self._query(
            "SELECT structural_change_date FROM teams WHERE team_id = %s",
            (team_id,),
        )
        if not row or not row[0].get("structural_change_date"):
            return None
        return row[0]["structural_change_date"]

    ##########################################################################
    # Ponderação por qualidade do adversário
    # Tiers: top-6 (rank 1-6) → peso 2.0 | mid (7-12) → 1.0 | weak (13+) → 0.5
    # opponent_rank NULL → peso 1.0
    ##########################################################################
    @staticmethod
    def _opponent_weight(opponent_rank):
        if opponent_rank is None:
            return 1.0
        if opponent_rank <= 6:
            return 2.0
        if opponent_rank <= 12:
            return 1.0
        return 0.5

    def get_quality_weighted_summary(self, matches: list, team_id: int) -> dict:
        """
        Agrupa partidas por tier de qualidade do adversário e retorna stats
        por tier e uma média ponderada.

        Tiers: top-6 (rank 1-6), mid (rank 7-12), weak (rank 13+), unknown (NULL)
        Pesos: top-6=2.0, mid=1.0, weak=0.5, unknown=1.0
        """
        TIERS = {
            "top-6":   {"ranks": lambda r: r is not None and r <= 6,   "weight": 2.0},
            "mid":     {"ranks": lambda r: r is not None and 7 <= r <= 12, "weight": 1.0},
            "weak":    {"ranks": lambda r: r is not None and r >= 13,  "weight": 0.5},
            "unknown": {"ranks": lambda r: r is None,                   "weight": 1.0},
        }

        groups = {tier: [] for tier in TIERS}

        for m in matches:
            rank = m.get("opponent_rank")
            is_home = m.get("home_team_id") == team_id

            goals_scored  = m.get("home_goals", 0) if is_home else m.get("away_goals", 0)
            goals_against = m.get("away_goals", 0) if is_home else m.get("home_goals", 0)
            yellows       = m.get("home_yellow_cards", 0) if is_home else m.get("away_yellow_cards", 0)
            clean_sheet   = 1 if goals_against == 0 else 0

            entry = {
                "goals_scored":  goals_scored  or 0,
                "goals_against": goals_against or 0,
                "yellows":       yellows        or 0,
                "clean_sheet":   clean_sheet,
            }

            for tier, cfg in TIERS.items():
                if cfg["ranks"](rank):
                    groups[tier].append(entry)
                    break

        def tier_stats(entries):
            n = len(entries)
            if n == 0:
                return None
            return {
                "games":              n,
                "goals_per_game":     round(sum(e["goals_scored"]  for e in entries) / n, 2),
                "goals_against_per_game": round(sum(e["goals_against"] for e in entries) / n, 2),
                "clean_sheet_pct":    round(sum(e["clean_sheet"] for e in entries) / n * 100, 1),
                "yellow_cards_per_game": round(sum(e["yellows"] for e in entries) / n, 2),
            }

        result = {}
        for tier in TIERS:
            stats = tier_stats(groups[tier])
            if stats:
                result[tier] = stats

        # Weighted average (goals_against as main metric)
        total_weight = 0.0
        weighted_ga  = 0.0
        for tier, cfg in TIERS.items():
            entries = groups[tier]
            if not entries:
                continue
            w = cfg["weight"]
            avg_ga = sum(e["goals_against"] for e in entries) / len(entries)
            weighted_ga  += avg_ga * w * len(entries)
            total_weight += w * len(entries)

        if total_weight > 0:
            result["weighted_goals_against"] = round(weighted_ga / total_weight, 2)
        else:
            result["weighted_goals_against"] = None

        return result
