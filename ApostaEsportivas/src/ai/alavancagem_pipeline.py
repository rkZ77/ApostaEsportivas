"""
ALAVANCAGEM — Pipeline Copa do Mundo
Objetivo: 1 pick diario (ou combinacao de 2) da Copa com odd alvo ~1.50 (faixa 1.40-1.60).
Banca composita: inicia em R$50, reinveste ganhos a cada GREEN.
Exclusivo VIP. Ativo apenas durante a Copa do Mundo.
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
from ai.ai_suggestions_service import translate_market
from ai.prompts.team_prompt_builder import TeamPromptBuilder

load_dotenv(find_dotenv())

AI_MODEL_NAME  = os.getenv("AI_MODEL_ALAVANCAGEM", os.getenv("AI_MODEL_NAME"))
WC_LEAGUE_ID   = 1
ODD_MIN        = 1.40
ODD_MAX        = 1.60
ODD_TARGET     = 1.50
CONFIDENCE_MIN = 0.72
BANKROLL_INIT  = 50.0
MAX_FIXTURES   = 10

client               = Anthropic()
odds_svc             = OddsService()
standings_svc        = StandingsService()
team_stats_svc       = TeamStatsService()
match_stats_svc      = MatchStatsService()
national_team_svc    = NationalTeamProfileService()
team_prompt_builder  = TeamPromptBuilder()


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
Voce e QUANTBET-ALAVANCAGEM, especializado em selecionar o pick mais seguro do dia em jogos da Copa do Mundo FIFA.

OBJETIVO: 1 pick (ou combinacao de 2 picks de jogos diferentes) com odd combinada entre 1.40-1.60. Odd alvo ~1.50. Prioridade maxima: seguranca e consistencia.

LOGICA:
- 1 pick isolado com odd 1.40-1.60 e consistencia alta → preferivel
- Se nao houver → combine 2 picks de jogos DIFERENTES para compor odd 1.40-1.60
- Combinacao: ambos com confidence>=0.70 individualmente — nao combine fraco com forte
- Consistencia vale tudo: 9/10 confirmando@1.45 > 7/10 confirmando@1.58
- Amostra minima: 5 jogos no venue correto | 2+ confirmadores independentes
- Linha Over/Under: escolha SEMPRE a mais conservadora dentro da faixa (Over mais baixo, Under mais alto).
  Exemplo: Over 1.5 @ 1.45 e Over 2.5 @ 1.58 disponíveis → escolha Over 1.5 @ 1.45.
- Mercados proibidos: Match Winner (1X2) — use Dupla Chance se quiser resultado.
- Nenhum pick com confidence>={conf_min} → no_bet

SAIDA: apenas JSON valido. Sua resposta comeca com {{ e termina com }}. Nenhum texto fora do JSON.\
"""


USER_PROMPT_TEMPLATE = """\
ALAVANCAGEM Copa do Mundo — pick mais seguro do dia. Odd alvo: ~{odd_target} | Faixa: {odd_min}-{odd_max}

Opcao A: 1 pick isolado odd {odd_min}-{odd_max}
Opcao B: 2 picks de jogos DIFERENTES com odd combinada {odd_min}-{odd_max}
Criterios: league_id=1 | amostra>=5 no venue | taxa>=65% | confidence>={conf_min} | EV>0 | combinacao: mercados independentes

--- FIXTURES DA COPA + DADOS ---
{fixtures_formatados}

FILTRAR: odd {odd_min}-{odd_max}→candidatos A. odd 1.10-{odd_max}→candidatos B. Amostra<5→descarte.
AVALIAR: taxa=confirmados/total (>=0.65) | prob_real=taxa ponderada temporal (1.0,0.85,0.70...) | EV=(prob_real×odd)-1>0
CONFIDENCE=(Consistencia×0.40)+(Amostra×0.25)+(Confirmadores×0.20)+(Estabilidade×0.15)
  Consistencia: >=0.80→1.0|0.70-0.79→0.8|0.65-0.69→0.6 | Amostra: 10+→1.0|5-9→0.7 | Confirmadores: 3+→1.0|2→0.7|1→0.3 | Estabilidade: ultimos3→1.0|media→0.5
MONTAR: Prefira A. B somente sem A valido ou confidence media significativamente maior. Empate→maior consistencia. Sem valido→no_bet.
Verificacao: league_id=1? amostra>=5? taxa>=65%? confidence>={conf_min}? odd {odd_min}-{odd_max}? EV>0?

SAIDA JSON:
Simples: {{"tipo":"simples","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market":"","line":"","odd":0.00,"bet_house":"","prob_real":0.00,"confidence":0.00,"reasoning":"FATO: X/Y (taxa Z%). CONFIRMADORES:[...]. CONCLUSAO:padrao solido."}},"pick_2":null,"odd_combined":0.00,"confidence_media":0.00}}
Combinacao: {{"tipo":"combinacao","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market":"","line":"","odd":0.00,"bet_house":"","prob_real":0.00,"confidence":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"pick_2":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market":"","line":"","odd":0.00,"bet_house":"","prob_real":0.00,"confidence":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"odd_combined":0.00,"confidence_media":0.00}}
Sem pick: {{"no_bet":true,"motivo":"criterio que falhou"}}
"""


# ============================================================
# TABELA
# ============================================================
def create_table():
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_alavancagem (
            id              SERIAL PRIMARY KEY,
            match_date      DATE UNIQUE,
            tipo            TEXT NOT NULL DEFAULT 'simples',
            fixture_id_1    INTEGER,
            home_team_1     TEXT,
            away_team_1     TEXT,
            market_1        TEXT,
            line_1          TEXT,
            odd_1           NUMERIC,
            bet_house_1     TEXT,
            confidence_1    NUMERIC,
            prob_real_1     NUMERIC,
            reasoning_1     TEXT,
            fixture_id_2    INTEGER,
            home_team_2     TEXT,
            away_team_2     TEXT,
            market_2        TEXT,
            line_2          TEXT,
            odd_2           NUMERIC,
            bet_house_2     TEXT,
            confidence_2    NUMERIC,
            prob_real_2     NUMERIC,
            reasoning_2     TEXT,
            odd_combined    NUMERIC,
            confidence_media NUMERIC,
            stake           NUMERIC,
            potential_return NUMERIC,
            bankroll_before NUMERIC,
            result          TEXT,
            profit          NUMERIC,
            bankroll_after  NUMERIC,
            checked_at      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# BANKROLL — pega o ultimo valor da serie
# ============================================================
def get_current_bankroll() -> float:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT bankroll_after, result
        FROM picks_alavancagem
        WHERE match_date < CURRENT_DATE
        ORDER BY match_date DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return BANKROLL_INIT

    bankroll_after, result = row[0], row[1]

    # Se o ultimo resultado foi RED (perdeu), reinicia a serie
    if result == "RED":
        print(f"[ALAVANCAGEM] Serie reiniciada apos RED. Voltando para R${BANKROLL_INIT:.2f}")
        return BANKROLL_INIT

    # Se ainda nao tem resultado (pendente), usa o bankroll_before + ganho potencial (nao reinveste ate confirmar)
    if result is None and bankroll_after is None:
        cur2 = get_connection().cursor()
        cur2.execute("""
            SELECT bankroll_before FROM picks_alavancagem
            WHERE match_date < CURRENT_DATE
            ORDER BY match_date DESC LIMIT 1
        """)
        r = cur2.fetchone()
        cur2.close()
        return float(r[0]) if r else BANKROLL_INIT

    return float(bankroll_after) if bankroll_after else BANKROLL_INIT


# ============================================================
# VERIFICA SE JA EXISTE PICK HOJE
# ============================================================
def has_today_pick() -> bool:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM picks_alavancagem WHERE match_date = CURRENT_DATE")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count >= 1


# ============================================================
# BUSCA FIXTURES DA COPA COM ODDS NA FAIXA
# ============================================================
def get_wc_fixtures_with_odds() -> list[dict]:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT DISTINCT f.fixture_id, f.home_team_id, f.away_team_id,
               f.home_team, f.away_team, f.season,
               f.match_datetime
        FROM fixtures f
        INNER JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE f.league_id = %s
          AND f.match_datetime::date = CURRENT_DATE
          AND f.status = 'NS'
          AND ov.odd_value BETWEEN %s AND %s
        ORDER BY f.match_datetime
        LIMIT %s
    """, (WC_LEAGUE_ID, ODD_MIN - 0.10, ODD_MAX + 0.10, MAX_FIXTURES))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "fixture_id":   r[0],
            "home_team_id": r[1],
            "away_team_id": r[2],
            "home_team":    r[3],
            "away_team":    r[4],
            "season":       r[5],
            "match_datetime": str(r[6]),
        }
        for r in rows
    ]


# ============================================================
# CARREGA CONTEXTO DO FIXTURE
# ============================================================
def _load_fixture_context(fixture_id, home_team_id, away_team_id, season) -> dict:
    ctx = {}
    try:
        ctx["home_standing"] = standings_svc.get_team_standing(home_team_id, WC_LEAGUE_ID, season)
    except Exception:
        ctx["home_standing"] = None
    try:
        ctx["away_standing"] = standings_svc.get_team_standing(away_team_id, WC_LEAGUE_ID, season)
    except Exception:
        ctx["away_standing"] = None
    try:
        ctx["home_stats"] = team_stats_svc.get_stats(home_team_id, WC_LEAGUE_ID, season, "HOME")
    except Exception:
        ctx["home_stats"] = None
    try:
        ctx["away_stats"] = team_stats_svc.get_stats(away_team_id, WC_LEAGUE_ID, season, "AWAY")
    except Exception:
        ctx["away_stats"] = None
    try:
        ctx["last10_home"] = match_stats_svc.get_all_matches(home_team_id, season, WC_LEAGUE_ID, is_home=True)
    except Exception:
        ctx["last10_home"] = []
    try:
        ctx["last10_away"] = match_stats_svc.get_all_matches(away_team_id, season, WC_LEAGUE_ID, is_home=False)
    except Exception:
        ctx["last10_away"] = []
    try:
        ctx["odds"] = odds_svc.load_odds_by_fixture(fixture_id)
    except Exception:
        ctx["odds"] = []
    return ctx


# ============================================================
# PERFIL DE SELEÇÕES (Copa)
# ============================================================
def _get_copa_profiles_text(fixture_id: int, home_team_id: int, away_team_id: int, season: int) -> str:
    try:
        home_profile = national_team_svc.get_team_profile(home_team_id, season, fixture_id=fixture_id)
        away_profile = national_team_svc.get_team_profile(away_team_id, season, fixture_id=fixture_id)
        return team_prompt_builder.get_world_cup_context(home_profile, away_profile)
    except Exception as e:
        print(f"[ALAVANCAGEM] Erro ao buscar perfis de seleção: {e}")
        return ""


# ============================================================
# FORMATA CONTEXTO PARA O PROMPT
# ============================================================
def _format_fixtures(fixtures: list[dict]) -> str:
    parts = []
    for f in fixtures:
        ctx = _load_fixture_context(
            f["fixture_id"], f["home_team_id"], f["away_team_id"], f["season"]
        )
        profiles_text = _get_copa_profiles_text(
            f["fixture_id"], f["home_team_id"], f["away_team_id"], f["season"]
        )
        ctx_trimmed = {k: (v[:8] if isinstance(v, list) else v) for k, v in ctx.items()}
        fixture_block = json.dumps(_clean({
            "fixture_id":     f["fixture_id"],
            "home_team":      f["home_team"],
            "away_team":      f["away_team"],
            "league_id":      WC_LEAGUE_ID,
            "match_datetime": f["match_datetime"],
            **ctx_trimmed,
        }), ensure_ascii=False, separators=(',', ':'))

        if profiles_text:
            parts.append(f"{profiles_text}\n\n--- DADOS ESTATÍSTICOS ---\n{fixture_block}")
        else:
            parts.append(fixture_block)
    return "\n\n---\n\n".join(parts)


# ============================================================
# CHAMA A IA
# ============================================================
def run_alavancagem_llm(fixtures: list[dict]) -> dict:
    fixtures_formatados = _format_fixtures(fixtures)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        odd_min=ODD_MIN,
        odd_max=ODD_MAX,
        odd_target=ODD_TARGET,
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
                system=SYSTEM_PROMPT.format(conf_min=CONFIDENCE_MIN),
                messages=[{"role": "user", "content": user_prompt}],
            )
            break
        except RateLimitError:
            if attempt == MAX_RETRIES:
                raise Exception(f"[ALAVANCAGEM] Rate limit após {MAX_RETRIES} tentativas — abortando.")
            print(f"[ALAVANCAGEM] Rate limit (tentativa {attempt}/{MAX_RETRIES}) — aguardando {RATE_LIMIT_WAIT}s...")
            time.sleep(RATE_LIMIT_WAIT)
        except Exception as e:
            raise Exception(f"[ALAVANCAGEM] Erro na API Anthropic: {e}")

    raw = response.content[0].text.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise Exception(f"[ALAVANCAGEM] JSON não encontrado na resposta:\n{raw[:500]}")
    raw = raw[start:end]
    try:
        return json.loads(raw)
    except Exception as e:
        raise Exception(f"[ALAVANCAGEM] JSON inválido: {e}\n{raw[:300]}")


# ============================================================
# SALVA NO BANCO
# ============================================================
def save_pick(result: dict, bankroll: float):
    if result.get("no_bet"):
        print(f"[ALAVANCAGEM] no_bet: {result.get('motivo')}")
        return

    p1   = result["pick_1"]
    p2   = result.get("pick_2")
    tipo = result.get("tipo", "simples")
    odd_combined      = float(result["odd_combined"])
    confidence_media  = float(result.get("confidence_media", p1["confidence"]))
    stake             = 1.0  # 1 unidade = 100% da banca no sistema alavancagem
    potential_return  = round(odd_combined, 2)  # retorno em unidades

    # Traduz mercados
    p1["market"] = translate_market(p1["market"])
    if p2:
        p2["market"] = translate_market(p2["market"])

    print(f"[ALAVANCAGEM] Pick selecionado ({tipo}):")
    print(f"  {p1['home_team']} x {p1['away_team']} | {p1['market']} {p1.get('line','')} @ {p1['odd']}")
    if p2:
        print(f"  + {p2['home_team']} x {p2['away_team']} | {p2['market']} {p2.get('line','')} @ {p2['odd']}")
    print(f"  Odd combinada: {odd_combined} | Stake: 1u (R${bankroll:.2f}) | Retorno potencial: {potential_return:.2f}u")

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO picks_alavancagem
            (match_date, tipo,
             fixture_id_1, home_team_1, away_team_1, market_1, line_1, odd_1, bet_house_1, confidence_1, prob_real_1, reasoning_1,
             fixture_id_2, home_team_2, away_team_2, market_2, line_2, odd_2, bet_house_2, confidence_2, prob_real_2, reasoning_2,
             odd_combined, confidence_media, stake, potential_return, bankroll_before)
        VALUES
            (CURRENT_DATE, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s)
    """, (
        tipo,
        p1.get("fixture_id"), p1["home_team"], p1["away_team"],
        p1["market"], p1.get("line"), p1["odd"], p1.get("bet_house"),
        p1.get("confidence"), p1.get("prob_real"), p1.get("reasoning"),
        p2.get("fixture_id") if p2 else None,
        p2["home_team"] if p2 else None, p2["away_team"] if p2 else None,
        p2["market"] if p2 else None, p2.get("line") if p2 else None,
        p2["odd"] if p2 else None, p2.get("bet_house") if p2 else None,
        p2.get("confidence") if p2 else None, p2.get("prob_real") if p2 else None,
        p2.get("reasoning") if p2 else None,
        odd_combined, confidence_media, stake, potential_return, bankroll,
    ))
    conn.commit()
    cur.close()
    conn.close()
    print("[ALAVANCAGEM] Pick salvo com sucesso.")


# ============================================================
# PIPELINE COMPLETO
# ============================================================
def run_alavancagem_pipeline() -> dict | None:
    print("📈 Iniciando pipeline ALAVANCAGEM...")

    create_table()

    if has_today_pick():
        print("✅ Pick de alavancagem já existe para hoje.")
        return None

    bankroll = get_current_bankroll()
    print(f"💰 Bankroll atual: R${bankroll:.2f}")

    print(f"🔍 Buscando jogos da Copa do Mundo com odds {ODD_MIN}-{ODD_MAX}...")
    fixtures = get_wc_fixtures_with_odds()

    if not fixtures:
        print("❌ Nenhum jogo da Copa do Mundo encontrado hoje.")
        return None

    print(f"⚽ {len(fixtures)} jogo(s) encontrado(s)")
    print("🤖 Enviando para IA selecionar o pick mais seguro...")

    result = run_alavancagem_llm(fixtures)

    if result.get("no_bet"):
        print(f"⚠️  no_bet: {result.get('motivo')}")
        return None

    save_pick(result, bankroll)
    return result
