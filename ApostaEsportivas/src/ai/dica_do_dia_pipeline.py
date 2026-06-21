"""
DICA DO DIA — Pipeline de Alta Acertividade
Objetivo: 1 pick diario com odd 1.39-1.60, maximo de consistencia estatistica.
Fallback: qualquer liga com dados suficientes e padrao claro.
"""

import os
import json
import time
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv, find_dotenv
from anthropic import Anthropic, RateLimitError

from utils.db_utils import get_connection
from services.odds_service import OddsService
from services.standings_service import StandingsService
from services.team_stats_service import TeamStatsService
from services.match_stats_service import MatchStatsService
from services.national_team_profile_service import NationalTeamProfileService
from ai.ai_suggestions_service import translate_market, is_market_reasoning_coherent
from ai.prompts.team_prompt_builder import TeamPromptBuilder

load_dotenv(find_dotenv())

AI_MODEL_NAME  = os.getenv("AI_MODEL_DICA", os.getenv("AI_MODEL_NAME"))
WC_LEAGUE_ID   = 1
ODD_MIN        = 1.39
ODD_MAX        = 1.60
CONFIDENCE_MIN = 0.72
MAX_FIXTURES   = 12

client              = Anthropic()
odds_svc            = OddsService()
standings_svc       = StandingsService()
team_stats_svc      = TeamStatsService()
match_stats_svc     = MatchStatsService()
national_team_svc   = NationalTeamProfileService()
team_prompt_builder = TeamPromptBuilder()


# ============================================================
# SERIALIZAÇÃO
# ============================================================
def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


# ============================================================
# PROMPTS
# ============================================================
SYSTEM_PROMPT = """\
Voce e QUANTBET-DICA, especializado em selecionar o pick MAIS SEGURO do dia com base em padrao estatistico consistente.

OBJETIVO: acertividade maxima. Nao busque o maior EV nem a odd mais atrativa — busque o padrao mais repetivel e confirmado pelos dados.
Consistencia vale mais que EV: prefira 8/10 jogos confirmando @ 1.25 do que 5/10 @ 1.60.
Odd entre 1.39 e 1.60. Confidence >= 0.72. Se nenhum pick atender → no_bet. Prefira no_bet a um pick fraco.

Realize toda a analise INTERNAMENTE. NÃO escreva texto, markdown, raciocinio ou comentario fora do JSON.
Retorne APENAS o objeto JSON final. Proibido qualquer caractere antes ou depois do JSON. Comeca com {{ e termina com }}.\
"""


USER_PROMPT_TEMPLATE = """\
Selecione EXATAMENTE 1 pick (DICA DO DIA) — o mais seguro e consistente.
Prioridade: Copa do Mundo (league_id=1) — venue NAO se aplica (sede neutra); use historico total (ultimos 15 jogos, todos competicoes) + stats especificas da Copa. Amostra>=5 no historico global.

Avalie TODOS os mercados das odds: gols (Over/Under, BTTS, asiático), escanteios, cartoes, Dupla Chance, Handicap Asiático.
Nao existe mercado preferido — escolha o com maior consistencia estatistica nos dados.
Criterios obrigatorios: odd {odd_min}-{odd_max} | amostra>=5 (Copa: historico total; outros: venue correto) | taxa>=65% | >=2 confirmadores | confidence>={conf_min} | EV>0 ou (EV>-0.05 e confidence>=0.72)

CARTÕES — regra especial: volatilidade MÉDIA (taxa jogo-a-jogo tem alta variância). Só selecione cartões como dica se AMBAS as condições forem satisfeitas: (a) árbitro com >=3 jogos na temporada E (b) histórico dos dois times com >=5 jogos e taxa >=60% no venue. Sem esses dois dados confirmados → prefira gols ou escanteios.

--- FIXTURES + DADOS ---
{fixtures_formatados}

CALCULO:
A) Taxa=confirmados/total_amostra (>=0.65). Amostra: 10+→1.0 | 5-9→0.7 | <5→descarte. (Copa: total_amostra=historico global conforme descrito acima; outros: venue correto)
B) prob_real: taxa ponderada temporalmente (recente=1.0, 0.9, 0.8...) + home/away_stats + standings
C) CONFIDENCE=(Consistencia×0.40)+(Amostra×0.25)+(Confirmadores×0.20)+(Estabilidade×0.15)
   Consistencia: >=0.80→1.0 | 0.70-0.79→0.8 | 0.65-0.69→0.6 | Confirmadores: 3+→1.0 | 2→0.7 | 1→0.3 | Estabilidade: ultimos 3→1.0 | so media→0.5

QUALIDADE DO ADVERSARIO: cada jogo no historico contem "opponent_rank" (posicao na tabela).
  NUNCA trate jogos vs tops e fracos com o mesmo peso:
  rank 1-6 (top)→peso 2.0 | rank 7-12 (mid)→peso 1.0 | rank 13+ (fraco)→peso 0.5 | null→peso 1.0
  Taxa ponderada = soma(taxa_jogo × peso) / soma(pesos). Declare: "taxa bruta X% → ponderada Y%".
  Para Copa do Mundo: use "quality_breakdown" do perfil — "weighted_goals_against" em vez da media bruta.

Ordene por confidence. Empate: maior taxa → maior amostra. Sem valido → no_bet.

Verificacao: odd {odd_min}-{odd_max}? amostra>=5? taxa>=65%? 2+ confirmadores? confidence>={conf_min}? EV>0 ou (EV>-0.05 e conf>=0.72)?

SAIDA JSON:
Pick: {{"pick": {{"fixture_id":0,"home_team":"","away_team":"","league_id":0,"league_name":"","market":"","line":"","odd":0.00,"bet_house":"","prob_real":0.00,"edge":0.00,"confidence":0.00,"reasoning":"FATO: X/Y (taxa Z%). CONFIRMADORES: [...]. CONCLUSAO: odd subestima prob real."}}}}
Sem pick: {{"no_bet":true,"motivo":"criterio que falhou"}}
"""


# ============================================================
# CARREGA CONTEXTO COMPLETO DO FIXTURE
# ============================================================
def _load_fixture_context(
    fixture_id: int,
    home_team_id: int,
    away_team_id: int,
    league_id: int,
    season: str,
) -> dict:
    try:
        home_standing = standings_svc.get_team_standing(home_team_id, league_id, season)
        away_standing = standings_svc.get_team_standing(away_team_id, league_id, season)
    except Exception:
        home_standing, away_standing = None, None

    try:
        home_stats = team_stats_svc.get_stats(home_team_id, league_id, season, "HOME")
    except Exception:
        home_stats = None

    try:
        away_stats = team_stats_svc.get_stats(away_team_id, league_id, season, "AWAY")
    except Exception:
        away_stats = None

    try:
        last10_home = match_stats_svc.get_all_matches(home_team_id, season, league_id, is_home=True)
    except Exception:
        last10_home = []

    try:
        last10_away = match_stats_svc.get_all_matches(away_team_id, season, league_id, is_home=False)
    except Exception:
        last10_away = []

    try:
        total_home = match_stats_svc.get_total_matches(home_team_id, season, league_id)
    except Exception:
        total_home = []

    try:
        total_away = match_stats_svc.get_total_matches(away_team_id, season, league_id)
    except Exception:
        total_away = []

    try:
        odds = odds_svc.load_odds_by_fixture(fixture_id)
    except Exception:
        odds = []

    return {
        "standings":   _clean({"home": home_standing, "away": away_standing}),
        "home_stats":  _clean(home_stats),
        "away_stats":  _clean(away_stats),
        "last10_home": _clean(last10_home),
        "last10_away": _clean(last10_away),
        "total_home":  _clean(total_home),
        "total_away":  _clean(total_away),
        "odds":        _clean(odds),
    }


# ============================================================
# FORMATA FIXTURES PARA O PROMPT
# ============================================================
def _format_fixtures_for_llm(fixtures_with_context: list) -> str:
    lines = []
    for i, item in enumerate(fixtures_with_context, 1):
        fx  = item["fixture"]
        ctx = item["context"]

        is_wc   = fx["league_id"] == WC_LEAGUE_ID
        wc_tag  = " — COPA DO MUNDO FIFA" if is_wc else ""

        lines.append("=" * 60)
        lines.append(f"FIXTURE #{i}  (fixture_id: {fx['fixture_id']}){wc_tag}")
        lines.append(f"{fx['home_team']} x {fx['away_team']}")
        lines.append(f"Liga: {fx.get('league_name', '')} (league_id: {fx['league_id']})")
        lines.append(f"Data: {fx['match_datetime']}")
        lines.append("=" * 60)

        # Perfis de seleção para jogos da Copa do Mundo
        if is_wc:
            try:
                home_profile = national_team_svc.get_team_profile(
                    fx["home_team_id"], fx["season"], fixture_id=fx["fixture_id"]
                )
                away_profile = national_team_svc.get_team_profile(
                    fx["away_team_id"], fx["season"], fixture_id=fx["fixture_id"]
                )
                profiles_text = team_prompt_builder.get_compact_wc_context(home_profile, away_profile)
                if profiles_text:
                    lines.append(profiles_text)
            except Exception as e:
                print(f"[DICA] Erro ao buscar perfis Copa fixture {fx['fixture_id']}: {e}")

        _j = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':'))

        if ctx.get("standings"):
            lines.append("\nCLASSIFICACAO:")
            lines.append(_j(ctx["standings"]))

        all_odds = ctx.get("odds", [])
        odds_in_range = [o for o in all_odds if ODD_MIN <= o.get("odd", 0) <= ODD_MAX]
        odds_other    = [o for o in all_odds if not (ODD_MIN <= o.get("odd", 0) <= ODD_MAX)]

        if odds_in_range:
            lines.append(f"\nODDS NA FAIXA {ODD_MIN}-{ODD_MAX} (CANDIDATOS DICA DO DIA):")
            lines.append(_j(odds_in_range))
        if odds_other:
            lines.append("\nOUTRAS ODDS (contexto):")
            lines.append(_j(odds_other[:15]))

        if ctx.get("home_stats"):
            lines.append(f"\nESTATISTICAS CASA ({fx['home_team']}):")
            lines.append(_j(ctx["home_stats"]))
        if ctx.get("away_stats"):
            lines.append(f"\nESTATISTICAS FORA ({fx['away_team']}):")
            lines.append(_j(ctx["away_stats"]))
        if ctx.get("last10_home"):
            lines.append(f"\nLAST10 CASA ({fx['home_team']}):")
            lines.append(_j(ctx["last10_home"][:8]))
        if ctx.get("last10_away"):
            lines.append(f"\nLAST10 FORA ({fx['away_team']}):")
            lines.append(_j(ctx["last10_away"][:8]))
        if ctx.get("total_home") and len(ctx.get("last10_home", [])) < 8:
            lines.append(f"\nTOTAL CASA ({fx['home_team']}):")
            lines.append(_j(ctx["total_home"][:8]))
        if ctx.get("total_away") and len(ctx.get("last10_away", [])) < 8:
            lines.append(f"\nTOTAL FORA ({fx['away_team']}):")
            lines.append(_j(ctx["total_away"][:8]))

        lines.append("")
    return "\n".join(lines)


# ============================================================
# DB — BUSCA FIXTURES COM ODDS NA FAIXA
# ============================================================
def get_fixtures_with_odds_in_range() -> list:
    """Fixtures de hoje com pelo menos 1 odd entre ODD_MIN e ODD_MAX. WC primeiro."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("""
        SELECT DISTINCT
            f.fixture_id,
            f.league_id,
            COALESCE(l.name, 'Unknown') AS league_name,
            f.season,
            f.home_team_id,
            f.away_team_id,
            f.home_team,
            f.away_team,
            f.match_datetime,
            f.status,
            (f.league_id = %s) AS is_world_cup
        FROM fixtures f
        LEFT JOIN leagues l ON f.league_id = l.league_id
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE DATE(f.match_datetime) = CURRENT_DATE
          AND f.status IN ('NS', 'TBD', 'LIVE')
          AND ov.odd_value BETWEEN %s AND %s
        ORDER BY (f.league_id = %s) DESC, f.match_datetime ASC
        LIMIT %s
    """, (WC_LEAGUE_ID, ODD_MIN, ODD_MAX, WC_LEAGUE_ID, MAX_FIXTURES))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "fixture_id":     r[0],
            "league_id":      r[1],
            "league_name":    r[2],
            "season":         r[3],
            "home_team_id":   r[4],
            "away_team_id":   r[5],
            "home_team":      r[6],
            "away_team":      r[7],
            "match_datetime": r[8].isoformat() if hasattr(r[8], "isoformat") else str(r[8]),
            "status":         r[9],
            "is_world_cup":   bool(r[10]),
        }
        for r in rows
    ]


# ============================================================
# DB — VERIFICACAO / CRIACAO / SALVAMENTO
# ============================================================
def has_today_dica() -> bool:
    conn  = get_connection()
    cur   = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM picks_free WHERE match_date = CURRENT_DATE")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count >= 1


def create_dica_table():
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_free (
            id            SERIAL PRIMARY KEY,
            fixture_id    INTEGER,
            match_date    DATE UNIQUE,
            home_team     TEXT,
            away_team     TEXT,
            home_team_id  INTEGER,
            away_team_id  INTEGER,
            league_id     INTEGER,
            league_name   TEXT,
            market        TEXT,
            line          TEXT,
            odd           NUMERIC,
            bet_house     TEXT,
            confidence    NUMERIC,
            prob_real     NUMERIC,
            edge          NUMERIC,
            reasoning     TEXT,
            result        TEXT,
            profit        NUMERIC,
            sent          BOOLEAN DEFAULT FALSE,
            created_at    TIMESTAMP DEFAULT NOW()
        );
        ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS home_team_id INTEGER;
        ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS away_team_id INTEGER;
    """)
    conn.commit()
    cur.close()
    conn.close()


def save_dica(pick: dict) -> None:
    pick["market"] = translate_market(pick["market"])
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO picks_free
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id,
             league_id, league_name, market, line, odd, bet_house,
             market_id, confidence, prob_real, edge, reasoning)
        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date) DO UPDATE SET
            fixture_id   = EXCLUDED.fixture_id,
            home_team    = EXCLUDED.home_team,
            away_team    = EXCLUDED.away_team,
            home_team_id = EXCLUDED.home_team_id,
            away_team_id = EXCLUDED.away_team_id,
            league_id    = EXCLUDED.league_id,
            league_name  = EXCLUDED.league_name,
            market       = EXCLUDED.market,
            line         = EXCLUDED.line,
            odd          = EXCLUDED.odd,
            bet_house    = EXCLUDED.bet_house,
            market_id    = EXCLUDED.market_id,
            confidence   = EXCLUDED.confidence,
            prob_real    = EXCLUDED.prob_real,
            edge         = EXCLUDED.edge,
            reasoning    = EXCLUDED.reasoning
    """, (
        pick["fixture_id"],
        pick["home_team"],
        pick["away_team"],
        pick.get("home_team_id"),
        pick.get("away_team_id"),
        pick["league_id"],
        pick.get("league_name", ""),
        pick["market"],
        pick["line"],
        float(pick["odd"]),
        pick.get("bet_house", ""),
        pick.get("market_id"),
        float(pick["confidence"]),
        float(pick.get("prob_real", 0)),
        float(pick.get("edge", 0)),
        pick["reasoning"],
    ))
    conn.commit()
    cur.close()
    conn.close()


def mark_dica_sent(match_date: date) -> None:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE picks_free SET sent = TRUE WHERE match_date = %s",
        (match_date,)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_today_dica() -> dict | None:
    """Busca a dica de hoje no banco para envio."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT fixture_id, match_date, home_team, away_team,
               league_id, league_name, market, line, odd, bet_house,
               confidence, prob_real, edge, reasoning, sent
        FROM picks_free
        WHERE match_date = CURRENT_DATE
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    return {
        "fixture_id":  row[0],
        "match_date":  row[1],
        "home_team":   row[2],
        "away_team":   row[3],
        "league_id":   row[4],
        "league_name": row[5],
        "market":      row[6],
        "line":        row[7],
        "odd":         float(row[8]) if row[8] is not None else None,
        "bet_house":   row[9],
        "confidence":  float(row[10]) if row[10] is not None else None,
        "prob_real":   float(row[11]) if row[11] is not None else None,
        "edge":        float(row[12]) if row[12] is not None else None,
        "reasoning":   row[13],
        "sent":        row[14],
    }


# ============================================================
# CHAMADA A IA
# ============================================================
def run_dica_llm(fixtures_with_context: list) -> dict:
    fixtures_formatados = _format_fixtures_for_llm(fixtures_with_context)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        odd_min=ODD_MIN,
        odd_max=ODD_MAX,
        conf_min=CONFIDENCE_MIN,
        fixtures_formatados=fixtures_formatados,
    )

    RATE_LIMIT_WAIT = 65
    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=AI_MODEL_NAME,
                max_tokens=8096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            break
        except RateLimitError:
            if attempt == MAX_RETRIES:
                raise Exception(f"[DICA] Rate limit após {MAX_RETRIES} tentativas — abortando.")
            print(f"[DICA] Rate limit (tentativa {attempt}/{MAX_RETRIES}) — aguardando {RATE_LIMIT_WAIT}s...")
            time.sleep(RATE_LIMIT_WAIT)
        except Exception as e:
            raise Exception(f"[DICA] Erro na API Anthropic: {e}")

    raw = response.content[0].text.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise Exception(f"[DICA] JSON não encontrado na resposta:\n{raw[:500]}")
    raw = raw[start:end]

    try:
        return json.loads(raw)
    except Exception as e:
        raise Exception(f"[DICA] JSON invalido: {e}\nRAW:\n{raw[:500]}")


# ============================================================
# GERA MENSAGEM TELEGRAM
# ============================================================
def generate_dica_message(pick: dict) -> str:
    today    = datetime.now().strftime("%d/%m/%Y")
    is_wc    = pick.get("league_id") == WC_LEAGUE_ID
    conf_pct = round(float(pick["confidence"]) * 100)
    prob_pct = round(float(pick.get("prob_real", 0)) * 100, 1)
    edge_pct = round(float(pick.get("edge", 0)) * 100, 1)
    sep      = "─────────────────────"

    liga_tag = (
        "🌍 <b>COPA DO MUNDO FIFA 2026</b>"
        if is_wc
        else f"⚽ <b>{pick.get('league_name', 'Liga')}</b>"
    )

    return (
        f"🎯 <b>DICA DO DIA — HPS TIPSTER</b>\n"
        f"{sep}\n"
        f"📅 {today}\n"
        f"{liga_tag}\n"
        f"{sep}\n"
        f"⚽ <b>Jogo</b>\n"
        f"🏟 {pick['home_team']} x {pick['away_team']}\n"
        f"{sep}\n"
        f"📊 <b>Mercado:</b> {pick['market']}\n"
        f"📏 <b>Linha:</b> {pick['line']}\n"
        f"💰 <b>Odd:</b> <b>{pick['odd']}</b>\n"
        f"🏦 <b>Casa:</b> {pick.get('bet_house', '-')}\n"
        f"{sep}\n"
        f"📈 <b>Confianca IA:</b> {conf_pct}%\n"
        f"🔬 <b>Prob. Real:</b> {prob_pct}%\n"
        f"📐 <b>Edge:</b> +{edge_pct}%\n"
        f"{sep}\n"
        f"🧠 <b>Analise Tecnica</b>\n"
        f"{pick['reasoning']}\n"
        f"{sep}\n"
        f"⚠️ <i>Aposte com responsabilidade. Gestao de banca e fundamental.</i>\n"
        f"⬛ <b>HPS TIPSTER</b>"
    )


# ============================================================
# BACKFILL team IDs para picks existentes sem IDs
# ============================================================
def _backfill_team_ids():
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            UPDATE picks_free pf
            SET home_team_id = f.home_team_id,
                away_team_id = f.away_team_id
            FROM fixtures f
            WHERE f.fixture_id = pf.fixture_id
              AND pf.match_date = CURRENT_DATE
              AND (pf.home_team_id IS NULL OR pf.away_team_id IS NULL)
              AND f.home_team_id IS NOT NULL
        """)
        if cur.rowcount:
            print(f"[DICA] Backfill: {cur.rowcount} pick(s) atualizado(s) com team IDs.")
        conn.commit()
    except Exception as e:
        print(f"[DICA] Backfill erro: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ============================================================
# PIPELINE COMPLETO
# ============================================================
def run_dica_pipeline() -> dict | None:
    print("🎯 Iniciando pipeline DICA DO DIA...")

    create_dica_table()

    if has_today_dica():
        _backfill_team_ids()
        print("✅ Dica do dia ja existe para hoje. Nada a fazer.")
        return None

    print(f"🔍 Buscando fixtures com odds na faixa {ODD_MIN}-{ODD_MAX}...")
    fixtures = get_fixtures_with_odds_in_range()

    if not fixtures:
        print("❌ Nenhum fixture com odds na faixa encontrado hoje.")
        return None

    wc_count = sum(1 for f in fixtures if f["is_world_cup"])
    print(f"📊 {len(fixtures)} fixture(s) encontrado(s) [{wc_count} Copa do Mundo]")

    print("🔄 Carregando dados brutos...")
    fixtures_with_context = []
    for fx in fixtures:
        try:
            ctx = _load_fixture_context(
                fx["fixture_id"],
                fx["home_team_id"],
                fx["away_team_id"],
                fx["league_id"],
                fx["season"],
            )
            if not ctx.get("odds"):
                print(f"  [SKIP] Sem odds estruturadas para {fx['home_team']} x {fx['away_team']}")
                continue
            fixtures_with_context.append({"fixture": fx, "context": ctx})
        except Exception as e:
            print(f"  [WARN] Erro ao carregar fixture {fx['fixture_id']}: {e}")

    if not fixtures_with_context:
        print("❌ Nenhum fixture com dados completos disponivel.")
        return None

    print(f"🤖 Enviando {len(fixtures_with_context)} fixture(s) para a IA selecionar a Dica do Dia...")
    result = run_dica_llm(fixtures_with_context)

    if result.get("no_bet"):
        print(f"[DICA] NO BET — {result.get('motivo', 'criterios nao atingidos')}")
        return None

    pick = result.get("pick")
    if not pick:
        print("[DICA] Resposta da IA sem pick valido.")
        return None

    if not is_market_reasoning_coherent(pick.get("market", ""), pick.get("reasoning", "")):
        print(f"[DICA] REJEITADO — reasoning incoerente com mercado '{pick.get('market')}'. Retornando no_bet.")
        return None

    # Enriquecer pick com IDs de time e market_id do fixture original
    fid = pick.get("fixture_id")
    if fid:
        src_fc = next((fc for fc in fixtures_with_context if fc["fixture"]["fixture_id"] == fid), None)
        if src_fc:
            src = src_fc["fixture"]
            pick.setdefault("home_team_id", src.get("home_team_id"))
            pick.setdefault("away_team_id", src.get("away_team_id"))
            # Lookup market_id pela (line, odd) nas odds do contexto
            pick_line = str(pick.get("line", "")).strip().lower()
            pick_odd  = float(pick.get("odd", 0))
            for o in src_fc["context"].get("odds", []):
                if (str(o.get("line", "")).strip().lower() == pick_line
                        and abs(float(o.get("odd", 0)) - pick_odd) < 0.001):
                    pick["market_id"] = o.get("market_id")
                    break

    odd        = float(pick.get("odd", 0))
    confidence = float(pick.get("confidence", 0))

    if not (ODD_MIN <= odd <= ODD_MAX):
        print(f"[DICA] WARN: IA retornou odd {odd} fora da faixa {ODD_MIN}-{ODD_MAX} — descartado.")
        return None

    if confidence < CONFIDENCE_MIN:
        print(f"[DICA] WARN: IA retornou confidence {confidence:.2f} abaixo do minimo {CONFIDENCE_MIN} — descartado.")
        return None

    league_tag = "COPA DO MUNDO" if pick.get("league_id") == WC_LEAGUE_ID else pick.get("league_name", "")
    print(f"\n[DICA] Pick selecionado ({league_tag}):")
    print(f"  {pick['home_team']} x {pick['away_team']}")
    print(f"  {pick['market']} | linha: {pick['line']} | odd {odd} | conf {round(confidence * 100)}%")

    create_dica_table()
    save_dica(pick)

    msg = generate_dica_message(pick)
    print("\n📣 Mensagem gerada:")
    print("─" * 40)
    print(msg)
    print("─" * 40)

    print("\n✅ DICA DO DIA gerada com sucesso!")
    return pick


# ============================================================
# EXECUCAO DIRETA
# ============================================================
if __name__ == "__main__":
    run_dica_pipeline()
