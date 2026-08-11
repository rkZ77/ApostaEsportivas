"""Sincroniza uma tabela unica (`picks_ledger`) com TODAS as pernas de
picks das 4 tabelas (picks_vip/picks_free/picks_multiplas/picks_alavancagem),
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
import json

import psycopg2.extras
from utils.db_utils import get_connection
from services.pick_legs_extractor import fetch_all_legs, fixture_context
from services.ai_result_checker_service import AIResultCheckerService
from services.pick_engine import attribution, competition_profile

_PICK_TYPE_BY_TABLE = {
    "picks_vip": "vip",
    "picks_free": "free",
    "picks_multiplas": "multipla",
    "picks_alavancagem": "alavancagem",
    "picks_faltas": "faltas",
    "picks_goleiros": "goleiros",
    # Ao vivo (2026-08-11). E' o rotulo que permite separar PRE_MATCH de LIVE
    # em qualquer analise do ledger: `WHERE pick_type = 'live'` de um lado,
    # `WHERE pick_type <> 'live'` do outro. Sem coluna nova.
    "picks_live": "live",
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
    # ------------------------------------------------------------------
    # Dimensoes de atribuicao (2026-08-05). A tabela ja' existia com o
    # essencial; o que faltava era justamente o recorte -- sem estas colunas
    # nao da' pra responder "onde o motor ganha e onde perde", que e' o
    # proposito do ledger. ADD COLUMN IF NOT EXISTS porque a tabela ja' esta'
    # criada em PROD: CREATE TABLE IF NOT EXISTS acima nao adiciona coluna
    # nenhuma numa tabela que ja' existe (gap de migracao ja' conhecido).
    #
    # Nenhuma coluna e' NOT NULL: linha antiga fica NULL e o dashboard trata
    # NULL como "nao atribuido" em vez de sumir com a linha.
    # ------------------------------------------------------------------
    for coluna, tipo in (
        ("season",           "INTEGER"),   # temporada
        ("competition_type", "TEXT"),      # LEAGUE | CLUB_CUP | QUALIFIERS | FRIENDLY | INTERNATIONAL_TOURNAMENT
        ("round_phase",      "TEXT"),      # GROUP_STAGE | KNOCKOUT_SINGLE | KNOCKOUT_TWO_LEGS
        ("round_label",      "TEXT"),      # texto cru da API ("Regular Season - 12")
        ("referee",          "TEXT"),
        ("kickoff_at",       "TIMESTAMP"), # horario exato, pra recorte por faixa do dia
        ("kickoff_hour",     "INTEGER"),   # 0-23, desnormalizado pra agrupar barato
        ("pick_side",        "TEXT"),      # home | away | neutral -- de que lado a aposta esta'
        ("is_favorite",      "BOOLEAN"),   # a selecao apostada era a favorita do mercado
        ("odd_band",         "TEXT"),      # faixa de odd, pra calibracao por faixa
        ("closing_odd",      "NUMERIC"),
        ("clv",              "NUMERIC"),   # (odd_entrada / odd_fechamento) - 1
        ("ev_realizado",     "NUMERIC"),   # profit efetivo da perna, alinhado ao ev esperado
        ("engine_version",   "TEXT"),      # commit_sha que gerou a pick
        # ── Quem revisou o pick (2026-08-08) ──────────────────────────────
        # O gate de IA (services/pick_engine/ai_review.py) usa provider
        # diferente por pipeline. Sem estas colunas nao da' pra responder
        # "qual modelo aprova o que da' green" -- so' da' pra contar chamada,
        # que e' contabilidade de custo, nao de qualidade.
        # ai_decision fica separado do parecer inteiro de proposito: e' o
        # unico campo que entra em GROUP BY, e JSONB nao indexa de graca.
        ("ai_provider",      "TEXT"),      # anthropic | openai | NULL (sem revisao)
        ("ai_model",         "TEXT"),
        ("ai_decision",      "TEXT"),      # approve | reject
        ("ai_status",        "TEXT"),      # ok | unavailable | invalid_response | disabled | ...
        ("ai_risk",          "TEXT"),      # low | medium | high
    ):
        cur.execute(f"ALTER TABLE picks_ledger ADD COLUMN IF NOT EXISTS {coluna} {tipo};")

    # Indices dos recortes mais consultados pelo dashboard. Sem eles, cada
    # corte varre a tabela inteira -- barato agora, caro depois de uma
    # temporada de picks.
    for nome, colunas in (
        ("idx_picks_ledger_market",  "market_type"),
        ("idx_picks_ledger_league",  "league_id, season"),
        ("idx_picks_ledger_house",   "bet_house"),
        ("idx_picks_ledger_referee", "referee"),
        ("idx_picks_ledger_result",  "result"),
        ("idx_picks_ledger_ai",      "ai_model, ai_decision"),
    ):
        cur.execute(f"CREATE INDEX IF NOT EXISTS {nome} ON picks_ledger ({colunas});")


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


def _fixture_dimensions(cur, fixture_id: int | None) -> dict:
    """Arbitro, horario e rodada da partida. Vem de `fixtures`, que e' efemera
    (so' guarda jogos NS por alguns dias) -- por isso o fallback pra
    match_statistics, que e' permanente mas nao tem arbitro nem round.

    Perna antiga fica com esses campos NULL e o painel a mostra como
    '(nao atribuido)'. Isso e' deliberado: cobertura ruim de dimensao e'
    informacao sobre a coleta, nao motivo pra esconder a linha."""
    vazio = {"referee": None, "kickoff_at": None, "round_label": None}
    if not fixture_id:
        return vazio
    try:
        cur.execute(
            "SELECT referee, match_datetime, round FROM fixtures WHERE fixture_id = %s LIMIT 1",
            (fixture_id,))
        row = cur.fetchone()
        if row:
            return {"referee": row[0], "kickoff_at": row[1], "round_label": row[2]}
        cur.execute(
            "SELECT match_date FROM match_statistics WHERE fixture_id = %s LIMIT 1",
            (fixture_id,))
        row = cur.fetchone()
        return {"referee": None, "kickoff_at": row[0] if row else None, "round_label": None}
    except Exception:
        return vazio


def _closing_odd_for(cur, fixture_id: int | None, market_type: str | None, line: str | None):
    """Odd de fechamento ja' capturada por scripts/capture_closing_odds.py.

    A tabela `closing_odds` existia e nunca tinha sido lida por ninguem --
    capturava-se o dado e ele morria ali. E' o insumo do CLV, que e' a unica
    metrica de vantagem que converge com o volume de picks que a PickIA tem.

    Casa por (fixture, market_type, prefixo da linha) porque `line` guarda o
    rotulo completo ('Under 5.5') e o mesmo mercado pode ter varias linhas."""
    if not fixture_id or not market_type:
        return None
    try:
        cur.execute("""
            SELECT closing_odd FROM closing_odds
            WHERE fixture_id = %s AND market_type = %s
              AND (%s IS NULL OR line = %s)
            ORDER BY captured_at DESC NULLS LAST, id DESC
            LIMIT 1
        """, (fixture_id, market_type, line, line))
        row = cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
    except Exception:
        pass

    # Fallback: ultimo retrato de `odds_snapshots` ANTES do apito inicial.
    #
    # `closing_odds` so' e' preenchida por scripts/capture_closing_odds.py, que
    # precisa rodar perto do horario dos jogos -- e a pasta scripts/ inteira
    # esta no .gitignore, entao esse script nunca chegou a producao. Sem este
    # fallback, `clv` ficaria NULL pra sempre e o painel de desempenho nao teria
    # a unica metrica que converge com o volume de picks que existe hoje.
    #
    # O snapshot resolve isso sem passo operacional novo: capturar_odds.py ja'
    # roda no pipeline diario e agora grava um retrato append-only a cada
    # execucao. "Fechamento" vira "a ultima cotacao registrada antes do jogo",
    # que e' a definicao pratica de closing line. Quanto mais perto do apito a
    # coleta rodar, melhor a aproximacao -- rodar `main.py odds` uma segunda vez
    # perto dos jogos deixa o CLV bem mais preciso, mas ja' funciona com uma.
    try:
        cur.execute("""
            SELECT odd_value FROM odds_snapshots
            WHERE fixture_id = %s
              AND value_name = %s
              AND minutes_to_kickoff >= 0
            ORDER BY minutes_to_kickoff ASC, captured_at DESC
            LIMIT 1
        """, (fixture_id, line))
        row = cur.fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _ai_review_fields(leg: dict) -> dict:
    """Achata o parecer da IA guardado junto do pick em 5 colunas.

    provider/model so' existem em pick gerado a partir de 2026-08-08 (quando
    AIReviewGate._stamp passou a carimbar). Pick anterior tem decision e status
    mas nao tem autor -- fica NULL aqui e a atribuicao retroativa acontece na
    leitura (routers/admin.py::ai_performance infere por pipeline+dia a partir
    de ai_pick_review_events). Preencher NULL com chute aqui congelaria o
    palpite no banco; deixar NULL mantem o dado cru honesto."""
    review = leg.get("ai_review")
    if isinstance(review, str):
        try:
            review = json.loads(review)
        except (ValueError, TypeError):
            review = None
    if not isinstance(review, dict):
        return {"ai_provider": None, "ai_model": None, "ai_decision": None,
                "ai_status": None, "ai_risk": None}
    return {
        "ai_provider": review.get("provider"),
        "ai_model":    review.get("model"),
        "ai_decision": review.get("decision"),
        "ai_status":   review.get("status"),
        "ai_risk":     review.get("risk_level"),
    }


def _build_dimensions(cur, leg: dict, ctx: dict | None, league_id, result, profit) -> dict:
    """Todas as dimensoes de atribuicao de uma perna, num dict so'.

    A maior parte e' derivacao pura (services/pick_engine/attribution.py, com
    teste proprio); o que exige banco fica isolado nas duas funcoes acima."""
    fx = _fixture_dimensions(cur, leg.get("fixture_id"))
    odd = leg.get("odd")
    kickoff = fx["kickoff_at"]
    perfil = competition_profile.get_profile(league_id)
    fechamento = _closing_odd_for(cur, leg.get("fixture_id"), leg.get("market_type"), leg.get("line"))

    return {
        "season": (ctx or {}).get("season"),
        "competition_type": perfil.type,
        "round_phase": competition_profile.classify_round_phase(fx["round_label"]),
        "round_label": fx["round_label"],
        "referee": fx["referee"],
        "kickoff_at": kickoff,
        "kickoff_hour": kickoff.hour if hasattr(kickoff, "hour") else None,
        "pick_side": attribution.pick_side(leg.get("market"), leg.get("line")),
        "is_favorite": (attribution.selection_role(odd) == "favorito"
                        if attribution.selection_role(odd) else None),
        "odd_band": attribution.odd_band(odd),
        "closing_odd": fechamento,
        "clv": attribution.clv(odd, fechamento),
        "ev_realizado": (float(profit) if profit is not None
                         else attribution.realized_ev(result, odd)),
        "engine_version": None,  # preenchido quando o pick passar a carimbar o commit
        **_ai_review_fields(leg),
    }


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
            dim = _build_dimensions(plain_cur, leg, ctx, league_id, result, profit)

            # As dimensoes entram no DO UPDATE tambem, nao so' no INSERT: o
            # fechamento da linha (e portanto o CLV) so' existe DEPOIS que o
            # pick foi gravado, e a sincronizacao roda continuamente junto da
            # checagem de resultado. Se so' o INSERT preenchesse, todo pick
            # ficaria com clv NULL pra sempre -- que e' exatamente o tipo de
            # campo morto que esta auditoria encontrou em varios lugares.
            plain_cur.execute("""
                INSERT INTO picks_ledger (
                    source_table, source_id, leg_number, pick_type, source_system,
                    fixture_id, match_date, home_team_id, away_team_id, home_team, away_team,
                    league_id, market, market_type, line, odd, bet_house,
                    confidence, probability, ev, stake_pct, stake_units, reasoning,
                    result, profit, created_at,
                    season, competition_type, round_phase, round_label, referee,
                    kickoff_at, kickoff_hour, pick_side, is_favorite, odd_band,
                    closing_odd, clv, ev_realizado, engine_version,
                    ai_provider, ai_model, ai_decision, ai_status, ai_risk
                ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s,
                          %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s)
                ON CONFLICT (source_table, source_id, leg_number) DO UPDATE SET
                    result = EXCLUDED.result,
                    profit = EXCLUDED.profit,
                    closing_odd = COALESCE(EXCLUDED.closing_odd, picks_ledger.closing_odd),
                    clv = COALESCE(EXCLUDED.clv, picks_ledger.clv),
                    ev_realizado = COALESCE(EXCLUDED.ev_realizado, picks_ledger.ev_realizado),
                    season = COALESCE(EXCLUDED.season, picks_ledger.season),
                    competition_type = COALESCE(EXCLUDED.competition_type, picks_ledger.competition_type),
                    round_phase = COALESCE(EXCLUDED.round_phase, picks_ledger.round_phase),
                    round_label = COALESCE(EXCLUDED.round_label, picks_ledger.round_label),
                    referee = COALESCE(EXCLUDED.referee, picks_ledger.referee),
                    kickoff_at = COALESCE(EXCLUDED.kickoff_at, picks_ledger.kickoff_at),
                    kickoff_hour = COALESCE(EXCLUDED.kickoff_hour, picks_ledger.kickoff_hour),
                    pick_side = COALESCE(EXCLUDED.pick_side, picks_ledger.pick_side),
                    is_favorite = COALESCE(EXCLUDED.is_favorite, picks_ledger.is_favorite),
                    odd_band = COALESCE(EXCLUDED.odd_band, picks_ledger.odd_band),
                    ai_provider = COALESCE(EXCLUDED.ai_provider, picks_ledger.ai_provider),
                    ai_model = COALESCE(EXCLUDED.ai_model, picks_ledger.ai_model),
                    ai_decision = COALESCE(EXCLUDED.ai_decision, picks_ledger.ai_decision),
                    ai_status = COALESCE(EXCLUDED.ai_status, picks_ledger.ai_status),
                    ai_risk = COALESCE(EXCLUDED.ai_risk, picks_ledger.ai_risk),
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
                dim["season"], dim["competition_type"], dim["round_phase"], dim["round_label"],
                dim["referee"], dim["kickoff_at"], dim["kickoff_hour"], dim["pick_side"],
                dim["is_favorite"], dim["odd_band"], dim["closing_odd"], dim["clv"],
                dim["ev_realizado"], dim["engine_version"],
                dim["ai_provider"], dim["ai_model"], dim["ai_decision"],
                dim["ai_status"], dim["ai_risk"],
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
