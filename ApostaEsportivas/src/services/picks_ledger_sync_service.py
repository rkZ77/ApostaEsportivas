"""Sincroniza uma tabela unica (`picks_ledger`) com TODAS as pernas de
picks das 5 tabelas (picks_vip/picks_free/picks_multiplas/picks_alavancagem/
picks_bingo),
independente de serem geradas por IA (producao) ou pelo motor deterministico
(engine_pipelines/, hoje so em DEV) -- uma linha por PERNA individual, com
schema consistente.

Nunca escreve nas 4 tabelas de origem, so le delas (via
services/pick_legs_extractor.py) e escreve em picks_ledger. Cada perna tem
seu resultado (GREEN/RED/PUSH) resolvido de forma INDEPENDENTE via
AIResultCheckerService, direto de match_statistics -- para multiplas/
alavancagem isso da o resultado de CADA perna, nao o resultado combinado
da aposta inteira (uma multipla RED pode ter 1 perna GREEN e 1 RED).

Auto-provisiona a tabela (CREATE TABLE IF NOT EXISTS) onde quer que rode
-- mesmo padrao ja usado em engine_pipelines/*.py. Chamado a partir de
atualizar_resultados_sugestoes.py, entao roda continuamente junto do
fluxo de checagem de resultado que ja existe."""
import psycopg2.extras
from utils.db_utils import get_connection
from services.pick_legs_extractor import fetch_all_legs, fixture_context
from services.ai_result_checker_service import AIResultCheckerService

_PICK_TYPE_BY_TABLE = {
    "picks_vip": "vip",
    "picks_free": "free",
    "picks_multiplas": "multipla",
    "picks_alavancagem": "alavancagem",
    "picks_bingo": "bingo",
}


def _create_table_if_needed(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_ledger (
            id              SERIAL PRIMARY KEY,
            source_table    TEXT NOT NULL,
            source_id       INTEGER NOT NULL,
            leg_number      INTEGER,  -- 1/2/3; sempre 1 pra picks de perna unica (vip/free) --
                                      -- nunca NULL, pra o UNIQUE abaixo deduplicar direito
            pick_type       TEXT NOT NULL,
            source_system   TEXT,
            fixture_id      INTEGER,
            match_date      DATE,
            home_team_id    INTEGER,
            away_team_id    INTEGER,
            home_team       TEXT,
            away_team       TEXT,
            league_id       INTEGER,
            market          TEXT,
            market_type     TEXT,
            line            TEXT,
            odd             NUMERIC,
            bet_house       TEXT,
            confidence      NUMERIC,
            probability     NUMERIC,
            ev              NUMERIC,
            stake_pct       NUMERIC,
            stake_units     INTEGER,
            reasoning       TEXT,
            result          TEXT,
            profit          NUMERIC,
            created_at      TIMESTAMP,
            synced_at       TIMESTAMP DEFAULT NOW(),
            UNIQUE (source_table, source_id, leg_number)
        )
    """)


def _detect_source_system(reasoning: str | None) -> str:
    """O motor (explanation.py::explanation_to_text) sempre gera reasoning
    comecando com '[Mercado Linha @ Odd] Probabilidade real: ...' -- padrao
    fixo, barato de checar. Qualquer outra coisa (ou None) e tratado como
    'ai'. Heuristica, nao 100% garantida, mas correta na pratica."""
    if reasoning and reasoning.strip().startswith("[") and "Probabilidade real:" in reasoning:
        return "engine"
    return "ai"


def _resolve_leg_result(checker: AIResultCheckerService, cur, leg: dict):
    """Resultado INDEPENDENTE da perna, direto de match_statistics -- nunca
    usa o `result` combinado que multiplas/alavancagem guardam pra aposta
    inteira. Retorna (result, profit) ou (None, None) se o jogo ainda nao
    tem stats (pendente) ou o mercado nao e suportado pelo checker."""
    if not leg.get("fixture_id") or not leg.get("market"):
        return None, None
    stats = checker.get_fixture_result(leg["fixture_id"], cur)
    if not stats:
        return None, None
    result, factor = checker.evaluate_pick(leg["market"], leg["line"] or "", leg.get("odd") or 1.5, stats)
    if result is None:
        return None, None
    odd = leg.get("odd") or 0
    profit = checker.calculate_profit(factor, odd) if odd else None
    return result, (float(profit) if profit is not None else None)


def sync() -> dict:
    """Roda a sincronizacao completa. Retorna um resumo (contagens) --
    nunca levanta excecao pra fora (quem chama trata como best-effort)."""
    conn = get_connection()
    dict_cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    plain_cur = conn.cursor()
    checker = AIResultCheckerService()

    _create_table_if_needed(plain_cur)
    conn.commit()

    legs = fetch_all_legs(dict_cur)
    inserted = updated = skipped = 0

    for leg in legs:
        try:
            home_id, away_id = leg.get("home_team_id"), leg.get("away_team_id")
            league_id = None
            ctx = fixture_context(plain_cur, leg["fixture_id"]) if leg.get("fixture_id") else None
            if ctx:
                home_id = home_id or ctx["home_team_id"]
                away_id = away_id or ctx["away_team_id"]
                league_id = ctx["league_id"]

            result, profit = _resolve_leg_result(checker, plain_cur, leg)
            source_system = _detect_source_system(leg.get("reasoning"))
            pick_type = _PICK_TYPE_BY_TABLE[leg["source_table"]]

            plain_cur.execute("""
                INSERT INTO picks_ledger (
                    source_table, source_id, leg_number, pick_type, source_system,
                    fixture_id, match_date, home_team_id, away_team_id, home_team, away_team,
                    league_id, market, market_type, line, odd, bet_house,
                    confidence, probability, ev, stake_pct, stake_units, reasoning,
                    result, profit, created_at
                ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s)
                ON CONFLICT (source_table, source_id, leg_number) DO UPDATE SET
                    result = EXCLUDED.result,
                    profit = EXCLUDED.profit,
                    synced_at = NOW()
                RETURNING (xmax = 0) AS inserted
            """, (
                leg["source_table"], leg["source_id"], leg["leg_number"], pick_type, source_system,
                leg.get("fixture_id"), leg.get("match_date"), home_id, away_id,
                leg.get("home_team"), leg.get("away_team"),
                league_id, leg.get("market"), leg.get("market_type"), leg.get("line"), leg.get("odd"),
                leg.get("bet_house"), leg.get("confidence"), leg.get("probability"), leg.get("ev"),
                leg.get("stake_pct"), leg.get("stake_units"), leg.get("reasoning"),
                result, profit, leg.get("created_at"),
            ))
            was_inserted = plain_cur.fetchone()[0]
            if was_inserted:
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            skipped += 1
            print(f"[PICKS_LEDGER] Aviso: pulando perna {leg.get('source_table')}#{leg.get('source_id')}"
                  f"/{leg.get('leg_number')}: {e}")
            conn.rollback()
            continue

    conn.commit()
    dict_cur.close()
    plain_cur.close()
    conn.close()

    summary = {"total": len(legs), "inserted": inserted, "updated": updated, "skipped": skipped}
    print(f"[PICKS_LEDGER] {summary['total']} pernas processadas | "
          f"{inserted} novas | {updated} atualizadas | {skipped} puladas.")
    return summary


if __name__ == "__main__":
    sync()
