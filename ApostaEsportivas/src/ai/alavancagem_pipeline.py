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
from ai.ai_suggestions_service import translate_market, is_market_reasoning_coherent, dedup_odds, _market_type_from_name as _classify_market_type
from ai.prompts.team_prompt_builder import TeamPromptBuilder

load_dotenv(find_dotenv())

AI_MODEL_NAME  = os.getenv("AI_MODEL_ALAVANCAGEM", os.getenv("AI_MODEL_NAME"))
WC_LEAGUE_ID   = 1
ODD_MIN        = 1.45
ODD_MAX        = 1.55
ODD_TARGET     = 1.50
_COMBO_ODD_MIN = 1.08  # mínimo individual para combinações (produto deve cair em ODD_MIN-ODD_MAX)
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

OBJETIVO: ODD COMBINADA entre {odd_min}-{odd_max} (alvo ~{odd_target}).
Simples: 1 pick com odd direta em {odd_min}-{odd_max}.
Combinacao: 2 picks de jogos DIFERENTES onde odd_1 × odd_2 resulta em {odd_min}-{odd_max} — o PRODUTO e o que vale.
Consistencia acima de tudo: 9/10 @ 1.22 > 6/10 @ 1.48. Nenhum pick com confidence>={conf_min} → no_bet.

Realize toda a analise INTERNAMENTE. NÃO escreva texto, markdown, raciocinio ou comentario fora do JSON.
SAIDA: apenas JSON valido. Proibido qualquer caractere antes ou depois. Comeca com {{ e termina com }}.\
"""


USER_PROMPT_TEMPLATE = """\
ALAVANCAGEM Copa do Mundo — pick mais seguro do dia.
Faixa ODD COMBINADA obrigatoria: {odd_min}-{odd_max} | Alvo: ~{odd_target}

CONTEXTO SITUACIONAL (analise ANTES de qualquer pick):
Leia a classificacao (standings) e determine a situacao de cada time:
  PRECISA GANHAR → jogo aberto, mais pressao, mais atividade esperada. Incorpore na estimativa da taxa real.
  EMPATE BASTA → pode fechar defensivamente, menos atividade esperada. Incorpore na estimativa da taxa real.
  JA CLASSIFICADO/ELIMINADO → possivel rotacao → reduza peso da amostra, declare no reasoning.
  CONFLITO situacao vs padrao estatistico → declare no reasoning, reduza confidence se contexto e dados divergirem.

OPCAO A (simples): 1 pick isolado com odd individual entre {odd_min}-{odd_max}.
OPCAO B (combinacao): 2 picks de jogos DIFERENTES onde odd_1 × odd_2 cai em {odd_min}-{odd_max}.
  REGRA DE SELECAO — filtre ANTES de analisar:
  - Odd individual MINIMA para combinacao: 1.21 (pois 1.21×1.21=1.464 ≥ {odd_min}). Se odd < 1.21 → DESCARTE imediato.
  - Odd individual MAXIMA para combinacao: 1.26 (pois 1.26×1.26=1.588 > {odd_max}). Se odd > 1.26 → DESCARTE imediato.
  - Faixa valida por pick em combinacao: 1.21–1.26.
  - Calcule odd_1 × odd_2 explicitamente antes de confirmar. Produto fora de {odd_min}-{odd_max} → INVALIDO.
  - Exemplos validos: 1.21×1.22=1.476 ✓ | 1.22×1.25=1.525 ✓ | 1.23×1.22=1.501 ✓
  - Exemplos invalidos: 1.13×1.13=1.277 ✗ | 1.20×1.20=1.44 ✗ | 1.28×1.28=1.638 ✗
  - Criterio de qualidade por pick: taxa>=65% + amostra>=5 + confidence>={conf_min}.
    Calcule taxa_real pelos dados historicos. Nao combine pick sem taxa>=65%.

Criterios de cada pick: league_id=1 | amostra>=5 | taxa>=65% | confidence>={conf_min}
CARTOES: use apenas se arbitro com >=3 jogos na temporada E historico dos dois times com >=5 jogos e taxa>=60%. Sem esses dois → nao use cartoes como pick.

--- FIXTURES DA COPA + DADOS ---
{fixtures_formatados}

QUALIDADE DOS DADOS (Copa do Mundo):
  Cada perfil de selecao inclui "quality_breakdown" com stats separados por tipo de competicao.
  Use "weighted_goals_against" em vez da media bruta — Copa>Eliminatorias>Amistoso.
  Declare: "bruto X gols/j → ponderado Y gols/j (Z jogos Copa, W Eliminatorias, V amistosos)".

PASSO 1 — Candidatos A (simples): avalie mercados com odd individual em {odd_min}-{odd_max}.
PASSO 2 — Candidatos B (se A falhar): busque pares de jogos diferentes com odd individual 1.21–1.26,
  taxa>=65% e amostra>=5 em ambos, cujo produto caia em {odd_min}-{odd_max}.
  Se nenhum par válido existir → no_bet direto.
PASSO 3 — Descartar: amostra<5 | taxa<65% | confidence<{conf_min}.
PASSO 4 — Selecionar: prefira A. Escolha B se a confidence media de B superar A por >=0.05, ou se nao houver A valido.
  Sem pick valido → no_bet.

CALCULOS:
Calcule a taxa de ocorrencia real com base nos dados historicos: taxa ponderada dos ultimos jogos (recente=1.0, anterior=0.9...).
Prefira picks com maior taxa real e maior numero de confirmadores independentes.

FORMATO DO HISTORICO: cada jogo contem home_goals/away_goals/home_corners/away_corners/home_yellow_cards/away_yellow_cards/opponent_rank.
  HISTORICO CASA → time analisado e mandante: feitos = home_goals, home_corners, home_yellow_cards...
  HISTORICO FORA → time analisado e visitante: feitos = away_goals, away_corners, away_yellow_cards...

FEITOS vs CEDIDOS: para todo mercado de total (gols/cantos/cartoes/BTTS):
  Primario: feitos_A_contexto + feitos_B_contexto.
  Validacao: cedidos_A_contexto + cedidos_B_contexto.
  Divergencia >15% → reduza Confirmadores 1 nivel.
  Mercado de time: feitos do time + cedidos do adversario. Resultado: feitos_A vs cedidos_B + feitos_B vs cedidos_A.
CONFIDENCE=(C×0.45)+(Q×0.25)+(K×0.30) — MESMA FORMULA DO VIP
  C (Consistencia): taxa historica real; VAZIO→0.40; ESCASSO→max 0.65
  Q (Amostra): RICO(8+)=1.00 | MODERADO(4-7)=0.75 | ESCASSO(1-3)=0.45 | VAZIO=0.20
  K (Confirmadores): 3+=1.00 | 2=0.70 | 1=0.40 | 0=0.10
  Bonus: bookmakers_count>=3 → K +0.05 | bookmakers_count=1 → K −0.05

SMART SAFE LINE — SELECAO DE LINHA (obrigatorio para Over/Under com multiplas linhas):
  Odd minima para linha na alavancagem: {odd_min} (respeita a faixa do pipeline).
  1. Liste todas as linhas do mercado nas odds.
  2. Calcule: implied_prob=1/odd | edge=taxa_real−implied_prob | EV=taxa_real×odd−1
  3. Descarte: odd fora da faixa {odd_min}-{odd_max} | edge<0.05 | EV≤0
  4. Das aprovadas: maior taxa_real. Empate: maior edge.
  5. Sem aprovadas: fallback linha mais proxima da faixa {odd_min}-{odd_max}.
  No reasoning: "SMART SAFE LINE|Linhas:[...]|Rejeitadas:[linha @odd — motivo]|Escolhida:[linha @odd — taxa=X%, edge=Y%, EV=Z%]"

VERIFICACAO FINAL obrigatoria: calcule odd_combined = odd_1 × odd_2 (ou odd_1 se simples).
  Se odd_combined < {odd_min} ou > {odd_max} → no_bet imediato.

SAIDA JSON:
Simples: {{"tipo":"simples","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"reasoning":"FATO: X/Y (taxa Z%). CONFIRMADORES:[...]. CONCLUSAO:padrao estatistico solido."}},"pick_2":null,"odd_combined":0.00,"confidence_media":0.00}}
Combinacao: {{"tipo":"combinacao","pick_1":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"pick_2":{{"fixture_id":0,"home_team":"","away_team":"","league_id":1,"market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"reasoning":"FATO:X/Y(taxa Z%)."}},"odd_combined":0.00,"confidence_media":0.00}}
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
            result          TEXT,
            profit          NUMERIC,
            checked_at      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    # Garante colunas opcionais que podem não existir em instalações antigas
    for col_def in [
        "checked_at  TIMESTAMP",
        "prob_real_1 NUMERIC",
        "prob_real_2 NUMERIC",
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
    """, (WC_LEAGUE_ID, _COMBO_ODD_MIN, ODD_MAX + 0.10, MAX_FIXTURES))
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

        # Odds: sem filtro de odd — a IA escolhe o melhor conforme o prompt
        all_odds = ctx.pop("odds", [])
        filtered_odds = dedup_odds(all_odds)[:_ODDS_MAX_ITEMS]

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
                system=SYSTEM_PROMPT.format(
                    conf_min=CONFIDENCE_MIN,
                    odd_min=ODD_MIN,
                    odd_max=ODD_MAX,
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
def save_pick(result: dict):
    if result.get("no_bet"):
        print(f"[ALAVANCAGEM] no_bet: {result.get('motivo')}")
        return

    p1   = result["pick_1"]
    p2   = result.get("pick_2")
    tipo = result.get("tipo", "simples")

    # Valida coerência mercado↔reasoning
    if not is_market_reasoning_coherent(p1.get("market", ""), p1.get("reasoning", "")):
        print(f"[ALAVANCAGEM] REJEITADO pick_1 — reasoning incoerente com mercado '{p1.get('market')}'")
        return
    if p2 and not is_market_reasoning_coherent(p2.get("market", ""), p2.get("reasoning", "")):
        print(f"[ALAVANCAGEM] pick_2 removido — reasoning incoerente com mercado '{p2.get('market')}'. Downgrade para simples.")
        p2 = None
        tipo = "simples"
        result["pick_2"] = None
        result["tipo"] = "simples"
        result["odd_combined"] = p1.get("odd", result["odd_combined"])

    odd_combined      = float(result["odd_combined"])

    # Validação hard: rejeita se odd_combined fora da faixa permitida
    if not (ODD_MIN <= odd_combined <= ODD_MAX):
        print(f"[ALAVANCAGEM] REJEITADO — odd_combined={odd_combined:.2f} fora da faixa {ODD_MIN}-{ODD_MAX}. Retornando no_bet.")
        return
    confidence_media  = float(result.get("confidence_media", p1["confidence"]))

    # Traduz mercados
    p1["market"] = translate_market(p1["market"])
    if p2:
        p2["market"] = translate_market(p2["market"])

    print(f"[ALAVANCAGEM] Pick selecionado ({tipo}):")
    print(f"  {p1['home_team']} x {p1['away_team']} | {p1['market']} {p1.get('line','')} @ {p1['odd']}")
    if p2:
        print(f"  + {p2['home_team']} x {p2['away_team']} | {p2['market']} {p2.get('line','')} @ {p2['odd']}")
    print(f"  Odd combinada: {odd_combined}")

    conn = get_connection()
    cur  = conn.cursor()
    mtype1 = _classify_market_type(p1["market"])
    mtype2 = _classify_market_type(p2["market"]) if p2 else None

    cur.execute("""
        INSERT INTO picks_alavancagem
            (match_date, tipo,
             fixture_id_1, home_team_1, away_team_1, market_1, market_type_1, line_1, odd_1, bet_house_1, confidence_1, prob_real_1, reasoning_1,
             fixture_id_2, home_team_2, away_team_2, market_2, market_type_2, line_2, odd_2, bet_house_2, confidence_2, prob_real_2, reasoning_2,
             odd_combined, confidence_media)
        VALUES
            (CURRENT_DATE, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s)
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
        odd_combined, confidence_media,
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

    print(f"🔍 Buscando jogos da Copa do Mundo com odds {ODD_MIN}-{ODD_MAX}...")
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

    # ── IA: análise completa com contextos pré-carregados ─────────────────────
    print("🤖 Chamando IA com análise completa...")
    result = run_alavancagem_llm(fixtures, preloaded_contexts=preloaded)

    if result.get("no_bet"):
        print(f"⚠️  no_bet: {result.get('motivo')}")
        return None

    save_pick(result)
    return result


if __name__ == "__main__":
    run_alavancagem_pipeline()
