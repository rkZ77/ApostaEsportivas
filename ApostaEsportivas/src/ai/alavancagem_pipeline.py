"""
ALAVANCAGEM — Pipeline multi-liga
Objetivo: 1 pick diario (simples, dupla ou tripla) com odd combinada 1.45-1.55.
Busca mercados de qualquer liga disponivel no dia.
Exclusivo VIP.
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
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
from services.national_team_profile_service import NationalTeamProfileService
from services.ai_performance_service import AIPerformanceService
from ai.ai_suggestions_service import translate_market, is_market_reasoning_coherent, dedup_odds, normalize_structured_odds, _market_type_from_name as _classify_market_type
from ai.prompts.team_prompt_builder import TeamPromptBuilder

_performance_svc = AIPerformanceService()

load_dotenv(find_dotenv())

AI_MODEL_NAME      = os.getenv("AI_MODEL_ALAVANCAGEM", os.getenv("AI_MODEL_NAME"))
WC_LEAGUE_ID       = 1          # Copa do Mundo — mantido para enriquecimento de contexto
ODD_COMBINED_MIN   = 1.45       # odd combinada mínima (produto final)
ODD_COMBINED_MAX   = 1.55       # odd combinada máxima (produto final)
ODD_TARGET         = 1.50       # alvo ideal
ODD_INDIVIDUAL_MIN = 1.05       # mínimo por pick individual (para combos)
ODD_INDIVIDUAL_MAX = 1.55       # máximo por pick individual (simples)
CONFIDENCE_MIN     = 0.72
MAX_FIXTURES       = 15

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
Voce e QUANTBET-ALAVANCAGEM, especializado em montar o pick mais seguro do dia para alavancar banca.

OBJETIVO: ODD COMBINADA entre {odd_min} e {odd_max} (alvo ~{odd_target}).
- Simples: 1 pick com odd individual entre {odd_min}-{odd_max}.
- Dupla: 2 picks (mesmo jogo ou jogos diferentes) onde odd_1 x odd_2 cai em {odd_min}-{odd_max}.
- Tripla: 3 picks (mesmo jogo ou jogos diferentes) onde odd_1 x odd_2 x odd_3 cai em {odd_min}-{odd_max}.
Consistencia acima de tudo: 9/10 @ 1.12 > 6/10 @ 1.45. Nenhum pick sem confidence>={conf_min} -> no_bet.

REGRA CRITICA: odd_combined DEVE estar em [{odd_min},{odd_max}]. Nenhuma excecao.
  Calcule o produto EXPLICITAMENTE antes de emitir o JSON: odd_combined = odd_1 × odd_2 (× odd_3).
  Se o produto < {odd_min} ou > {odd_max}: descarte e tente outro combo, ou emita no_bet.
  Emitir odd_combined diferente do produto real e PROIBIDO — o sistema recalcula e rejeita.

REGRA DIVERSIFICACAO (dupla/tripla): picks com mercado IDENTICO sao PROIBIDOS e rejeitados automaticamente.
  Exemplos invalidos: "Total de Gols Casa Over 1.5" + "Total de Gols Casa Over 1.5" (mesmo mercado).
  Combine mercados diferentes: ex. gols totais + escanteios, ou gols casa + resultado, etc.

Realize toda a analise INTERNAMENTE. Proibido texto fora do JSON.
SAIDA: apenas JSON valido. Comeca com {{ e termina com }}.\
"""


USER_PROMPT_TEMPLATE = """\
ALAVANCAGEM Copa do Mundo — pick mais seguro do dia para alavancar banca.
ODD COMBINADA obrigatoria: {odd_min}-{odd_max} | Alvo: ~{odd_target}

--- PICKS ANTERIORES (calibracao por time) ---
Ultimos picks gerados para os times de hoje (todos os pipelines). Use para identificar padroes de acerto/erro.
resultado: GREEN=acertou | RED=errou | pendente=sem resultado ainda.
{picks_anteriores}
---

FORMATOS POSSIVEIS:
  SIMPLES : 1 pick com odd individual entre {odd_min}-{odd_max}.
  DUPLA   : 2 picks onde odd_1 × odd_2 ∈ [{odd_min},{odd_max}]. Mesmo jogo ou jogos diferentes.
  TRIPLA  : 3 picks onde odd_1 × odd_2 × odd_3 ∈ [{odd_min},{odd_max}]. Mesmo jogo ou jogos diferentes.

FAIXAS DE ODD INDIVIDUAL (para produto cair em {odd_min}-{odd_max}):
  Simples : {odd_min}-{odd_max}.
  Dupla   : ~1.20-1.40 cada (maximo simetrico 1.245×1.245≈1.55).
  Tripla  : ~1.08-1.28 cada (maximo simetrico 1.157×1.157×1.157≈1.55).
  Regra: calcule o produto EXPLICITAMENTE antes de confirmar. Fora de {odd_min}-{odd_max} → INVALIDO.

CONTEXTO SITUACIONAL (analise ANTES de qualquer pick):
  Leia standings e determine a situacao de cada selecao:
  PRECISA GANHAR → jogo aberto, mais pressao, mais atividade esperada.
  EMPATE BASTA → pode fechar defensivamente, menos atividade esperada.
  JA CLASSIFICADO/ELIMINADO → possivel rotacao → reduza peso da amostra, declare no reasoning.
  CONFLITO situacao vs dados → declare no reasoning, reduza confidence se contexto e dados divergirem.

CRITERIOS POR PICK: amostra>=5 | taxa_real>=65% | confidence>={conf_min}
CARTOES: so use se arbitro com >=3 jogos E historico dos times com >=5 jogos e taxa>=60%.

--- FIXTURES COPA DO MUNDO + DADOS ---
{fixtures_formatados}

QUALIDADE: use "weighted_goals_against" (Copa>Eliminatorias>Amistoso). Declare ponderacao no reasoning.
HISTORICO: home_*/away_* → CASA=mandante, FORA=visitante. FEITOS vs CEDIDOS: feitos_A+feitos_B (primario), cedidos_A+cedidos_B (validacao). Divergencia >15% → reduza Confirmadores.
CONFIDENCE=(C×0.45)+(Q×0.25)+(K×0.30) | C=taxa_real; Q: RICO(8+)=1.00,MOD(4-7)=0.75,ESC(1-3)=0.45,VAZIO=0.20; K: 3+=1.00,2=0.70,1=0.40,0=0.10.
SMART SAFE LINE: edge=taxa_real−1/odd | EV=taxa_real×odd−1. Descarte: edge<0.05|EV≤0. Reasoning: "SMART SAFE LINE|Escolhida:[taxa=X%,EV=Z%]".
SELECAO: maior confidence_media. Empate → SIMPLES. Sem candidato valido com criterios: no_bet.
VERIFICACAO (interna): odd_combined={odd_min}..{odd_max}. Fora da faixa → tente outro combo ou no_bet.

SAIDA JSON:
Simples: {{"tipo":"simples","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"reasoning":"FATO:X/Y(taxa Z%). CONFIRMADORES:[...]. CONCLUSAO:padrao solido."}},"pick_2":null,"pick_3":null,"odd_combined":0.00,"confidence_media":0.00}}
Dupla: {{"tipo":"dupla","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"pick_2":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"pick_3":null,"odd_combined":0.00,"confidence_media":0.00}}
Tripla: {{"tipo":"tripla","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"pick_2":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"pick_3":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"odd_combined":0.00,"confidence_media":0.00}}
Sem pick: {{"no_bet":true,"motivo":"criterio que falhou"}}
prob_real = taxa_real do mercado escolhido (0.00-1.00).
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
            result          TEXT,
            profit          NUMERIC,
            checked_at      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    # Garante colunas opcionais que podem não existir em instalações antigas
    for col_def in [
        "checked_at    TIMESTAMP",
        "prob_real_1   NUMERIC",
        "prob_real_2   NUMERIC",
        "market_type_1 TEXT",
        "market_type_2 TEXT",
        "fixture_id_3  INTEGER",
        "home_team_3   TEXT",
        "away_team_3   TEXT",
        "market_3      TEXT",
        "market_type_3 TEXT",
        "line_3        TEXT",
        "odd_3         NUMERIC",
        "bet_house_3   TEXT",
        "confidence_3  NUMERIC",
        "prob_real_3   NUMERIC",
        "reasoning_3   TEXT",
    ]:
        try:
            cur.execute(f"ALTER TABLE picks_alavancagem ADD COLUMN IF NOT EXISTS {col_def}")
        except Exception:
            conn.rollback()
    conn.commit()
    cur.close()
    conn.close()


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
# BUSCA FIXTURES DA COPA COM ODDS NA FAIXA INDIVIDUAL
# ============================================================
def get_wc_fixtures_with_odds() -> list[dict]:
    """Busca fixtures da Copa de hoje com ao menos uma odd na faixa individual válida para combos."""
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
    """, (WC_LEAGUE_ID, ODD_INDIVIDUAL_MIN, ODD_INDIVIDUAL_MAX + 0.10, MAX_FIXTURES))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "fixture_id":     r[0],
            "home_team_id":   r[1],
            "away_team_id":   r[2],
            "home_team":      r[3],
            "away_team":      r[4],
            "league_id":      WC_LEAGUE_ID,
            "season":         r[5],
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
    # Histórico cross-competition: últimos 15 jogos em qualquer competição
    try:
        ctx["last10_home"] = match_stats_svc.get_last_n_all_competitions(home_team_id, limit=15)
    except Exception:
        ctx["last10_home"] = []
    try:
        ctx["last10_away"] = match_stats_svc.get_last_n_all_competitions(away_team_id, limit=15)
    except Exception:
        ctx["last10_away"] = []
    try:
        ctx["odds"] = odds_svc.load_odds_structured(fixture_id) or odds_svc.load_odds_by_fixture(fixture_id)
    except Exception:
        ctx["odds"] = []
    return ctx


_ODDS_MAX_ITEMS = 80  # limite de itens de odds por fixture enviados à IA


# ============================================================
# PERFIL DE SELEÇÕES (Copa) — versão compacta para alavancagem
# ============================================================
def _get_copa_profiles_text(fixture_id: int, home_team_id: int, away_team_id: int, season: int) -> str:
    try:
        home_profile = national_team_svc.get_team_profile(home_team_id, season, fixture_id=fixture_id)
        away_profile = national_team_svc.get_team_profile(away_team_id, season, fixture_id=fixture_id)
        return team_prompt_builder.get_compact_wc_context(home_profile, away_profile)
    except Exception as e:
        print(f"[ALAVANCAGEM] Erro ao buscar perfis de seleção: {e}")
        return ""


# ============================================================
# FORMATA CONTEXTO PARA O PROMPT
# ============================================================
def _format_fixtures(fixtures: list[dict], preloaded_contexts: dict | None = None) -> str:
    """Formata fixtures para o prompt da IA.
    preloaded_contexts: dict[fixture_id -> ctx] para evitar re-carregar dados.
    """
    parts = []
    for f in fixtures:
        fid = f["fixture_id"]
        if preloaded_contexts and fid in preloaded_contexts:
            import copy as _copy
            ctx = _copy.deepcopy(preloaded_contexts[fid])
        else:
            ctx = _load_fixture_context(fid, f["home_team_id"], f["away_team_id"], f["season"])
        profiles_text = _get_copa_profiles_text(fid, f["home_team_id"], f["away_team_id"], f["season"])

        all_odds = ctx.pop("odds", [])
        filtered_odds = [
            o for o in dedup_odds(normalize_structured_odds(all_odds))
            if ODD_INDIVIDUAL_MIN <= float(o.get("best_odd") or 0) <= ODD_INDIVIDUAL_MAX
        ][:_ODDS_MAX_ITEMS]

        # Outras listas: limitar a 5 itens
        ctx_trimmed = {k: (v[:5] if isinstance(v, list) else v) for k, v in ctx.items()}
        ctx_trimmed["odds"] = filtered_odds

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
def run_alavancagem_llm(fixtures: list[dict], preloaded_contexts: dict | None = None) -> dict:
    """Call 2: análise completa. Usa preloaded_contexts para evitar re-carregamento."""
    fixtures_formatados = _format_fixtures(fixtures, preloaded_contexts=preloaded_contexts)

    # Coleta picks anteriores para todos os times dos fixtures do dia
    all_teams = [t for fx in fixtures for t in [fx.get("home_team"), fx.get("away_team")] if t]
    picks_anteriores = _performance_svc.get_team_picks_str(all_teams, limit=15)
    print(f"[ALAVANCAGEM] Picks anteriores injetados para {len(all_teams)} times")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        odd_min=ODD_COMBINED_MIN,
        odd_max=ODD_COMBINED_MAX,
        odd_target=ODD_TARGET,
        conf_min=CONFIDENCE_MIN,
        fixtures_formatados=fixtures_formatados,
        picks_anteriores=picks_anteriores,
    )
    RATE_LIMIT_WAIT = 65
    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=AI_MODEL_NAME,
                max_tokens=8096,
                system=SYSTEM_PROMPT.format(
                    conf_min=CONFIDENCE_MIN,
                    odd_min=ODD_COMBINED_MIN,
                    odd_max=ODD_COMBINED_MAX,
                    odd_target=ODD_TARGET,
                ),
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
    if start == -1:
        raise Exception(f"[ALAVANCAGEM] JSON não encontrado na resposta:\n{raw[:500]}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
        return obj
    except Exception as e:
        raise Exception(f"[ALAVANCAGEM] JSON inválido: {e}\n{raw[start:start+300]}")


# ============================================================
# SALVA NO BANCO
# ============================================================
def save_pick(result: dict) -> bool:
    if result.get("no_bet"):
        print(f"[ALAVANCAGEM] no_bet: {result.get('motivo')}")
        return False

    p1   = result["pick_1"]
    p2   = result.get("pick_2")
    p3   = result.get("pick_3")
    tipo = result.get("tipo", "simples")

    # Valida coerência mercado↔reasoning
    if not is_market_reasoning_coherent(p1.get("market", ""), p1.get("reasoning", "")):
        print(f"[ALAVANCAGEM] REJEITADO pick_1 — reasoning incoerente com mercado '{p1.get('market')}'")
        return False
    if p2 and not is_market_reasoning_coherent(p2.get("market", ""), p2.get("reasoning", "")):
        print(f"[ALAVANCAGEM] pick_2 removido — reasoning incoerente. Downgrade para simples.")
        p2 = None; p3 = None; tipo = "simples"
        result["odd_combined"] = p1.get("odd", result["odd_combined"])
    if p3 and not is_market_reasoning_coherent(p3.get("market", ""), p3.get("reasoning", "")):
        print(f"[ALAVANCAGEM] pick_3 removido — reasoning incoerente. Downgrade para dupla.")
        p3 = None
        tipo = "dupla"

    # Recalcula odd_combined a partir das legs (ignora valor declarado pela IA)
    legs_odds = [float(p1["odd"])]
    if p2: legs_odds.append(float(p2["odd"]))
    if p3: legs_odds.append(float(p3["odd"]))
    odd_combined_real = round(legs_odds[0] * (legs_odds[1] if len(legs_odds) > 1 else 1) * (legs_odds[2] if len(legs_odds) > 2 else 1), 4)

    if abs(odd_combined_real - float(result["odd_combined"])) > 0.05:
        print(f"[ALAVANCAGEM] odd_combined declarada={result['odd_combined']:.2f} ≠ produto real={odd_combined_real:.2f} — usando produto real.")
    odd_combined = odd_combined_real

    # Validação hard: rejeita se odd_combined real fora da faixa permitida
    if not (ODD_COMBINED_MIN <= odd_combined <= ODD_COMBINED_MAX):
        print(f"[ALAVANCAGEM] REJEITADO — odd_combined real={odd_combined:.2f} fora da faixa {ODD_COMBINED_MIN}-{ODD_COMBINED_MAX}.")
        return False

    # Rejeita dupla/tripla com mercados idênticos (picks correlacionados sem valor)
    markets = [p1.get("market", "").lower()]
    if p2: markets.append(p2.get("market", "").lower())
    if p3: markets.append(p3.get("market", "").lower())
    if len(markets) > 1 and len(set(markets)) == 1:
        print(f"[ALAVANCAGEM] REJEITADO — todas as legs com mercado idêntico: '{markets[0]}'. Picks correlacionados.")
        return False

    confidence_media = float(result.get("confidence_media", p1["confidence"]))

    # Traduz mercados
    p1["market"] = translate_market(p1["market"])
    if p2:
        p2["market"] = translate_market(p2["market"])
    if p3:
        p3["market"] = translate_market(p3["market"])

    print(f"[ALAVANCAGEM] Pick selecionado ({tipo}):")
    print(f"  {p1['home_team']} x {p1['away_team']} | {p1['market']} {p1.get('line','')} @ {p1['odd']}")
    if p2:
        print(f"  + {p2['home_team']} x {p2['away_team']} | {p2['market']} {p2.get('line','')} @ {p2['odd']}")
    if p3:
        print(f"  + {p3['home_team']} x {p3['away_team']} | {p3['market']} {p3.get('line','')} @ {p3['odd']}")
    print(f"  Odd combinada: {odd_combined:.2f}")

    mtype1 = _classify_market_type(p1["market"])
    mtype2 = _classify_market_type(p2["market"]) if p2 else None
    mtype3 = _classify_market_type(p3["market"]) if p3 else None

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO picks_alavancagem
            (match_date, tipo,
             fixture_id_1, home_team_1, away_team_1, market_1, market_type_1, line_1, odd_1, bet_house_1, confidence_1, prob_real_1, reasoning_1,
             fixture_id_2, home_team_2, away_team_2, market_2, market_type_2, line_2, odd_2, bet_house_2, confidence_2, prob_real_2, reasoning_2,
             fixture_id_3, home_team_3, away_team_3, market_3, market_type_3, line_3, odd_3, bet_house_3, confidence_3, prob_real_3, reasoning_3,
             odd_combined, confidence_media)
        VALUES
            (CURRENT_DATE, %s,
             %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
             %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
             %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
             %s,%s)
    """, (
        tipo,
        p1.get("fixture_id"), p1["home_team"], p1["away_team"],
        p1["market"], mtype1, p1.get("line"), p1["odd"], p1.get("bet_house"),
        p1.get("confidence"), p1.get("prob_real"), p1.get("reasoning"),
        p2.get("fixture_id") if p2 else None,
        p2["home_team"] if p2 else None, p2["away_team"] if p2 else None,
        p2["market"] if p2 else None, mtype2,
        p2.get("line") if p2 else None,
        p2["odd"] if p2 else None, p2.get("bet_house") if p2 else None,
        p2.get("confidence") if p2 else None, p2.get("prob_real") if p2 else None,
        p2.get("reasoning") if p2 else None,
        p3.get("fixture_id") if p3 else None,
        p3["home_team"] if p3 else None, p3["away_team"] if p3 else None,
        p3["market"] if p3 else None, mtype3,
        p3.get("line") if p3 else None,
        p3["odd"] if p3 else None, p3.get("bet_house") if p3 else None,
        p3.get("confidence") if p3 else None, p3.get("prob_real") if p3 else None,
        p3.get("reasoning") if p3 else None,
        odd_combined, confidence_media,
    ))
    conn.commit()
    cur.close()
    conn.close()
    print("[ALAVANCAGEM] Pick salvo com sucesso.")
    return True


# ============================================================
# PIPELINE COMPLETO
# ============================================================
def run_alavancagem_pipeline() -> dict | None:
    print("📈 Iniciando pipeline ALAVANCAGEM...")

    create_table()

    if has_today_pick():
        print("✅ Pick de alavancagem já existe para hoje.")
        return None

    print(f"🔍 Buscando jogos da Copa do Mundo (odd combinada alvo {ODD_COMBINED_MIN}-{ODD_COMBINED_MAX})...")
    fixtures = get_wc_fixtures_with_odds()

    if not fixtures:
        print("❌ Nenhum jogo da Copa do Mundo encontrado hoje.")
        return None

    print(f"⚽ {len(fixtures)} jogo(s) encontrado(s)")
    print("🔄 Carregando dados dos fixtures...")

    # Pré-carrega contextos uma vez para usar nas duas chamadas
    preloaded: dict[int, dict] = {}
    for f in fixtures:
        try:
            ctx = _load_fixture_context(f["fixture_id"], f["home_team_id"], f["away_team_id"], f["season"])
            preloaded[f["fixture_id"]] = ctx
        except Exception as e:
            print(f"  [WARN] Erro ao carregar fixture {f['fixture_id']}: {e}")

    if not preloaded:
        print("❌ Nenhum fixture com dados carregados.")
        return None

    # ── IA: análise completa com retry se odd sair da faixa ──────────────────
    MAX_PICK_RETRIES = 2
    result = None
    for attempt in range(1, MAX_PICK_RETRIES + 2):
        print(f"🤖 Chamando IA (tentativa {attempt}/{MAX_PICK_RETRIES + 1})...")
        result = run_alavancagem_llm(fixtures, preloaded_contexts=preloaded)

        if result.get("no_bet"):
            print(f"⚠️  no_bet: {result.get('motivo')}")
            return None

        odd_combined = float(result.get("odd_combined", 0))
        if ODD_COMBINED_MIN <= odd_combined <= ODD_COMBINED_MAX:
            break  # IA acertou a faixa — prossegue
        print(f"[ALAVANCAGEM] Tentativa {attempt}: odd_combined={odd_combined:.2f} fora de {ODD_COMBINED_MIN}-{ODD_COMBINED_MAX} — retentando...")
        if attempt == MAX_PICK_RETRIES + 1:
            print(f"[ALAVANCAGEM] IA não convergiu para faixa válida após {attempt} tentativas — abortando.")
            return None

    saved = save_pick(result)
    return result if saved else None


if __name__ == "__main__":
    run_alavancagem_pipeline()
