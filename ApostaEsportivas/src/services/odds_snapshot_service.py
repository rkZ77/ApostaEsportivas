"""Odds de um jogo PASSADO, reconstruidas do arquivo append-only.

POR QUE ISTO PRECISOU EXISTIR
-----------------------------
`odds_values` e' upsert: cada coleta sobrescreve a anterior, entao ela guarda a
cotacao de AGORA, nunca a de ontem. Medido em producao em 2026-08-13: a tabela
inteira tinha 1 fixture distinto, e nenhum jogo encerrado. Consequencia pratica,
descoberta tentando rodar o backtest: ele cruza `match_statistics` (1274 jogos
encerrados) com `odds_values` e achava ZERO partida -- em DEV e em PROD. Nao era
banco desatualizado, era a tabela nao guardar passado.

`odds_snapshots` foi criada exatamente pra isso e ja acumulava 311 mil linhas de
39 fixtures (33 encerrados) sem NINGUEM ler: OddsService consulta so'
`odds_values`. Este servico e' o leitor que faltava.

O QUE ELE DEVOLVE
-----------------
A mesma estrutura de OddsService.load_odds_by_fixture, porque herda dele e
sobrescreve SO' a consulta -- toda a camada de cima (deteccao de par corrompido,
melhor odd entre casas, regra de minimo 2 bookmakers em over/under) e' a mesma
que roda em producao. Backtest que reimplementasse aquilo estaria medindo outro
motor.

O QUE O SNAPSHOT NAO GUARDA, E DE ONDE VEM
------------------------------------------
A tabela grava so' o `market_id`. Nome, traducao e tipo de mercado sao
reconstruidos:

    market_en / market_pt  <- bet_markets_map (329 mercados cadastrados)
    market_type            <- stats_model.classify_market(market_en), a MESMA
                              funcao que classifica em producao
    bookmaker_name         <- bookmakers

`team_id`/`team_name` nao existem no arquivo e saem None. Confirmado que nada em
services/pick_engine le esse campo.

QUAL FOTO E' ESCOLHIDA
----------------------
A ULTIMA antes do apito: `minutes_to_kickoff >= corte`, ordenado crescente, um
registro por (casa, mercado, selecao, linha). E' o preco que o apostador teria
pego. `corte` maior simula "quanto o motor veria se rodasse N minutos antes",
que e' como comparar geracao cedo x tarde sem inventar dado.
"""
import psycopg2.extras

from utils.db_utils import get_connection
from services.odds_service import OddsService
from services.pick_engine.stats_model import classify_market


class SnapshotOddsService(OddsService):

    def __init__(self, minutos_antes: int = 0):
        self.minutos_antes = minutos_antes

    def load_odds_by_fixture(self, fixture_id):
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # DISTINCT ON + ORDER BY crescente = o registro mais PROXIMO do apito
        # entre os que ainda sao pre-jogo. minutes_to_kickoff positivo e' antes
        # do jogo (negativo e' ao vivo, e a coluna guarda os dois).
        cur.execute("""
            SELECT DISTINCT ON (s.bookmaker_id, s.market_id, s.value_name, s.line_value)
                   s.bookmaker_id,
                   s.market_id,
                   s.value_name,
                   s.line_value,
                   s.odd_value,
                   s.minutes_to_kickoff,
                   b.bookmaker_name,
                   m.market_en,
                   m.market_pt
              FROM odds_snapshots s
              LEFT JOIN bookmakers b      ON b.bookmaker_id = s.bookmaker_id
              LEFT JOIN bet_markets_map m ON m.bet_id       = s.market_id
             WHERE s.fixture_id = %s
               AND s.minutes_to_kickoff >= %s
             ORDER BY s.bookmaker_id, s.market_id, s.value_name, s.line_value,
                      s.minutes_to_kickoff ASC
        """, (fixture_id, self.minutos_antes))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        estruturado = []
        for r in rows:
            market_en = r["market_en"]
            if not market_en:
                # Mercado fora do catalogo: sem o nome em ingles nao ha como
                # classificar familia/escopo, e chutar produziria pick de um
                # mercado que o motor nao entende. Pular e' o correto.
                continue
            familia_escopo = classify_market(market_en)
            odd = float(r["odd_value"] or 0)
            if odd <= 1.0:
                continue
            estruturado.append({
                "market_id":      r["market_id"],
                "market_type":    familia_escopo[0] if familia_escopo else None,
                "market_name":    market_en,
                "market_pt":      r["market_pt"],
                "line":           r["line_value"],
                "line_value":     r["line_value"],
                "value_name":     r["value_name"],
                "odd":            odd,
                "odd_value":      odd,
                "bookmaker_id":   r["bookmaker_id"],
                "bookmaker":      r["bookmaker_name"] or f"casa {r['bookmaker_id']}",
                "bookmaker_name": r["bookmaker_name"] or f"casa {r['bookmaker_id']}",
                # Nao existe no arquivo. Confirmado que pick_engine nao le.
                "team":           None,
                "_minutos_ate_o_apito": r["minutes_to_kickoff"],
            })
        return estruturado

    def fixtures_com_snapshot(self, limit=None) -> list:
        """Fixtures ENCERRADOS que tem cotacao pre-jogo arquivada.

        Substitui a consulta que o backtest fazia contra `odds_values` e que
        sempre devolvia vazio. Exige pelo menos uma foto pre-jogo: fixture que
        so' tem registro ao vivo nao serve pra backtest de pre-jogo.
        """
        conn = get_connection()
        cur = conn.cursor()
        sql = """
            SELECT ms.fixture_id, ms.league_id, ms.season,
                   ms.home_team_id, ms.away_team_id, ms.match_date,
                   COUNT(*) AS fotos
              FROM match_statistics ms
              JOIN odds_snapshots s ON s.fixture_id = ms.fixture_id
             WHERE ms.status = 'FT'
               AND s.minutes_to_kickoff >= %s
             GROUP BY ms.fixture_id, ms.league_id, ms.season,
                      ms.home_team_id, ms.away_team_id, ms.match_date
             ORDER BY ms.match_date ASC
        """
        params = [self.minutos_antes]
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        cur.execute(sql, params)
        cols = ["fixture_id", "league_id", "season",
                "home_team_id", "away_team_id", "match_date", "fotos"]
        linhas = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return linhas
