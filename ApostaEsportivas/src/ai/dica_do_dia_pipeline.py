"""
DICA DO DIA · Pipeline de Alta Acertividade
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
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
from services.national_team_profile_service import NationalTeamProfileService
from services.ai_performance_service import AIPerformanceService
from ai.ai_suggestions_service import translate_market, is_market_reasoning_coherent, dedup_odds, normalize_structured_odds, AISuggestionsService
from collectors.odds_collector_service import MARKET_TYPE_MAP as _BET_ID_TYPE_MAP

_performance_svc = AIPerformanceService()


def _detect_market_type(market: str) -> str | None:
    """Mesma lógica de _market_type_from_name em ai_suggestions_service · mantidas em sync.
    Retorna None para mercados não reconhecidos em vez de 'unknown' ou 'result' errado."""
    m = market.lower()
    if "shot" in m or "chute" in m:
        return "shots"
    if "corner" in m or "escanteio" in m:
        return "corners"
    if "card" in m or "cartão" in m or "cartões" in m:
        return "cards"
    if "btts" in m or "ambas" in m or "ambos" in m:
        return "btts"
    if "goal" in m or "gol" in m:
        return "goals"
    if "placar exato" in m or "correct score" in m or "exact score" in m:
        return "correct_score"
    if any(x in m for x in ["1x2", "result", "winner", "dupla chance", "handicap",
                              "resultado", "vencedor", "match winner"]):
        return "result"
    return None
from ai.prompts.team_prompt_builder import TeamPromptBuilder

load_dotenv(find_dotenv())

AI_MODEL_NAME  = os.getenv("AI_MODEL_DICA", os.getenv("AI_MODEL_NAME"))
WC_LEAGUE_ID   = 1
ODD_MIN        = 1.30
ODD_MAX        = 1.80
CONFIDENCE_MIN = 0.72
MAX_FIXTURES   = 3

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

OBJETIVO: acertividade maxima. Nao busque o maior EV nem a odd mais atrativa · busque o padrao mais repetivel e confirmado pelos dados.
Consistencia vale mais que EV: prefira 8/10 jogos confirmando @ 1.25 do que 5/10 @ 1.60.
Odd entre 1.30 e 1.80. Confidence >= 0.72. Se nenhum pick atender → no_bet. Prefira no_bet a um pick fraco.

ESTILO: PROIBIDO usar travessao (—) em qualquer campo de texto do JSON (reasoning, motivo). Use ponto, virgula ou dois-pontos no lugar.

Realize toda a analise INTERNAMENTE. NÃO escreva texto, markdown, raciocinio ou comentario fora do JSON.
Retorne APENAS o objeto JSON final. Proibido qualquer caractere antes ou depois do JSON. Comeca com {{ e termina com }}.\
"""


USER_PROMPT_TEMPLATE = """\
Selecione EXATAMENTE 1 pick (DICA DO DIA) · o mais seguro e consistente.
Prioridade: Copa do Mundo (league_id=1) · venue NAO se aplica (sede neutra); use historico total (ultimos 15 jogos, todos competicoes) + stats especificas da Copa. Amostra>=5 no historico global.
SEDE NEUTRA (Copa): nao existe vantagem de mando. Proibido usar "mandante"/"visitante"/"em casa"/"fora de casa" como justificativa no reasoning para qualquer selecao nesta competicao · use so o nome das selecoes.

CONTEXTO SITUACIONAL (analise ANTES de qualquer mercado):
Leia a classificacao (standings) e determine a situacao de cada time:
  PRECISA GANHAR → jogo aberto, mais gols/cantos esperados, mais pressao. Incorpore na estimativa da taxa real.
  EMPATE BASTA → pode fechar defensivamente, menos atividade esperada. Incorpore na estimativa da taxa real.
  JA CLASSIFICADO/ELIMINADO → possivel rotacao de titulares → reduza Q 1 nivel, declare no reasoning.
  CONFLITO situacao vs padrao estatistico → declare no reasoning, reduza confidence se contexto e dados divergirem.

Avalie TODOS os mercados das odds: gols (Over/Under, BTTS, asiático), escanteios, cartoes, Dupla Chance, Handicap Asiático.
Nao existe mercado preferido · escolha o com maior consistencia estatistica nos dados.
Criterios obrigatorios: odd {odd_min}-{odd_max} | amostra>=5 (Copa: historico total; outros: venue correto) | taxa>=65% | >=2 confirmadores | confidence>={conf_min}

CARTÕES · regra especial: volatilidade MÉDIA (taxa jogo-a-jogo tem alta variância). Só selecione cartões como dica se AMBAS as condições forem satisfeitas: (a) árbitro com >=3 jogos na temporada E (b) histórico dos dois times com >=5 jogos e taxa >=60% no venue. Sem esses dois dados confirmados → nao use cartoes como dica.

--- PICKS ANTERIORES (calibracao por time) ---
Ultimos picks gerados para os times destes fixtures (todos os pipelines).
Use para identificar padroes de acerto/erro por time e mercado · nao como substituto da analise estatistica.
resultado: GREEN=acertou | RED=errou | pendente=sem resultado ainda.
{picks_anteriores}

--- FIXTURES + DADOS ---
{fixtures_formatados}

ANALISE:
Calcule a taxa de ocorrencia real voce mesmo com base nos dados historicos: taxa ponderada temporalmente (recente=1.0, anterior=0.9...).
Taxa = confirmados / total_amostra. Descarte mercados com taxa < 65% ou amostra < 5 jogos.
Selecione o mercado com MAIOR CONSISTENCIA ESTATISTICA que atenda os criterios.

FORMATO DAS ODDS (quando disponivel):
  best_odd      → melhor odd disponivel
  best_bookmaker→ casa com best_odd
  bookmakers_count → numero de casas

FORMATO DO HISTORICO: cada jogo contem home_goals/away_goals/home_corners/away_corners/home_yellow_cards/away_yellow_cards/opponent_rank.
  HISTORICO CASA → time analisado e mandante: feitos = home_goals, home_corners, home_yellow_cards...
  HISTORICO FORA → time analisado e visitante: feitos = away_goals, away_corners, away_yellow_cards...

A) Taxa=confirmados/total_amostra (>=0.65). Amostra: 10+→1.0 | 5-9→0.7 | <5→descarte.
   FEITOS vs CEDIDOS (conceitos DIFERENTES · nunca apresente lado a lado sem combinar):
     Formula obrigatoria para todo mercado de total (gols/cantos/cartoes/BTTS) e de time:
       valor_esperado = (feitos_do_time × 0.5) + (cedido_pelo_adversario × 0.5)
     Calcule esse valor UMA UNICA VEZ; nunca mostre um numero preliminar e troque por outro
     depois no reasoning (proibido "recalibrando"/"corrigindo" com valor diferente).
     Divergencia feitos vs cedidos >15% → declare e reduza Confirmadores 1 nivel.
     Resultado/Handicap: combine feitos_A×0.5+cedidos_B×0.5 vs feitos_B×0.5+cedidos_A×0.5.
B) Taxa ponderada temporalmente (recente=1.0, 0.9, 0.8...) + home/away_stats + standings.
C) CONFIDENCE = (C×0.45)+(Q×0.25)+(K×0.30) · MESMA FORMULA DO VIP
   C (Consistencia): taxa historica real; VAZIO→0.40; ESCASSO→max 0.65
   Q (Amostra): RICO(8+)=1.00 | MODERADO(4-7)=0.75 | ESCASSO(1-3)=0.45 | VAZIO=0.20
      Taxa alta (ex. 80%+) baseada em <15 jogos totais → trate Q como MODERADO no maximo, declare amostra pequena.
   K (Confirmadores): 3+=1.00 | 2=0.70 | 1=0.40 | 0=0.10
   Bonus: bookmakers_count>=3 → K +0.05 | bookmakers_count=1 → K −0.05
   Desconto: sede neutra+mata-mata, escalacao incerta, ou amostra do grupo Copa <5 jogos → reduza K 1 nivel cada, declare no reasoning.

QUALIDADE DO ADVERSARIO: opponent_rank top(1-6)→peso 2.0 | mid(7-12)→1.0 | fraco(13+)→0.5 | null→1.0.
Taxa real=soma(stat×peso)/soma(pesos). Declare: "taxa bruta X%→ponderada Y%". Copa: use weighted_goals_for/against e weighted_corners_for/against (ataque E defesa, ambos ja ponderados); "amostra_suficiente_para_alta_confianca"=false → declare limitacao.

CONTRAPONTO: antes de concluir, declare 1 fato que enfraquece a tese (ou "sem contraponto relevante") e por que a tese ainda se sustenta.

SMART SAFE LINE (Over/Under com multiplas linhas): edge=taxa_real−1/odd | EV=taxa_real×odd−1.
Descarte: odd<1.60 | edge<0.05 | EV≤0. Escolha maior taxa_real. Sem aprovada: fallback odd>=1.01.
Reasoning: "SMART SAFE LINE|Linhas:[...]|Rejeitadas:[motivo]|Escolhida:[taxa=X%,edge=Y%,EV=Z%]"

Ordene por confidence. Empate: maior taxa → maior amostra. Sem valido → no_bet.

Verificacao: odd {odd_min}-{odd_max}? amostra>=5? taxa>=65%? 2+ confirmadores? confidence>={conf_min}? SMART SAFE LINE aplicado?

SAIDA JSON:
Pick: {{"pick": {{"fixture_id":0,"home_team":"","away_team":"","league_id":0,"league_name":"","market_id":0,"market":"","line":"","odd":0.00,"bet_house":"","confidence":0.00,"prob_real":0.00,"edge":0.00,"reasoning":"FATO: X/Y (taxa Z%). CONFIRMADORES:[...]. SMART SAFE LINE|Linhas:[...]|Rejeitadas:[...]|Escolhida:[linha @odd]. CONCLUSAO: padrao estatistico solido."}}}}
Sem pick: {{"no_bet":true,"motivo":"criterio que falhou"}}
prob_real = taxa_real do mercado escolhido (0.00-1.00). edge = prob_real - (1/odd).
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

    is_national = league_id in NATIONAL_TEAM_LEAGUE_IDS
    # Stats de seleções são salvas com league_id=1 pelo process_national_team
    stats_league_id = 1 if is_national else league_id

    try:
        home_stats = team_stats_svc.get_stats(home_team_id, stats_league_id, season, "HOME")
    except Exception:
        home_stats = None

    try:
        away_stats = team_stats_svc.get_stats(away_team_id, stats_league_id, season, "AWAY")
    except Exception:
        away_stats = None

    if is_national:
        # Seleções: usa últimos 15 jogos em QUALQUER competição
        try:
            last10_home = match_stats_svc.get_last_n_all_competitions(home_team_id, limit=15)
        except Exception:
            last10_home = []
        try:
            last10_away = match_stats_svc.get_last_n_all_competitions(away_team_id, limit=15)
        except Exception:
            last10_away = []
        total_home = last10_home
        total_away = last10_away
    else:
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
        odds = odds_svc.load_odds_structured(fixture_id)
        if not odds:
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
# FORMATA FIXTURES PARA O PROMPT (CALL 2 · análise completa)
# ============================================================
def _format_fixtures_for_llm(fixtures_with_context: list) -> str:
    lines = []
    for i, item in enumerate(fixtures_with_context, 1):
        fx  = item["fixture"]
        ctx = item["context"]

        is_wc   = fx["league_id"] == WC_LEAGUE_ID
        wc_tag  = " · COPA DO MUNDO FIFA" if is_wc else ""

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

        all_odds = [
            o for o in dedup_odds(normalize_structured_odds(ctx.get("odds", [])))
            if ODD_MIN <= float(o.get("best_odd") or 0) <= ODD_MAX
        ]

        if all_odds:
            lines.append(f"\nMERCADOS E ODDS (faixa {ODD_MIN}-{ODD_MAX}, {len(all_odds)} mercados):")
            lines.append(_j(all_odds))

        if ctx.get("home_stats"):
            lines.append(f"\nESTATISTICAS CASA ({fx['home_team']}):")
            lines.append(_j(ctx["home_stats"]))
        if ctx.get("away_stats"):
            lines.append(f"\nESTATISTICAS FORA ({fx['away_team']}):")
            lines.append(_j(ctx["away_stats"]))
        if ctx.get("last10_home"):
            lines.append(f"\nLAST10 CASA ({fx['home_team']}):")
            lines.append(_j(ctx["last10_home"][:6]))
        if ctx.get("last10_away"):
            lines.append(f"\nLAST10 FORA ({fx['away_team']}):")
            lines.append(_j(ctx["last10_away"][:6]))
        if ctx.get("total_home") and len(ctx.get("last10_home", [])) < 6:
            lines.append(f"\nTOTAL CASA ({fx['home_team']}):")
            lines.append(_j(ctx["total_home"][:6]))
        if ctx.get("total_away") and len(ctx.get("last10_away", [])) < 6:
            lines.append(f"\nTOTAL FORA ({fx['away_team']}):")
            lines.append(_j(ctx["total_away"][:6]))

        lines.append("")
    return "\n".join(lines)


# ============================================================
# DB · BUSCA FIXTURES COM ODDS NA FAIXA
# ============================================================
def get_fixtures_with_odds_in_range() -> list:
    """Fixtures de hoje com pelo menos 1 odd entre ODD_MIN e ODD_MAX. Ligas mais atrativas primeiro."""
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
            (f.league_id = %s) AS is_world_cup,
            CASE f.league_id
                WHEN 1   THEN 1
                WHEN 2   THEN 2
                WHEN 3   THEN 3
                WHEN 848 THEN 4
                WHEN 39  THEN 5
                WHEN 140 THEN 6
                WHEN 135 THEN 7
                WHEN 78  THEN 8
                WHEN 61  THEN 9
                WHEN 94  THEN 10
                WHEN 88  THEN 11
                WHEN 13  THEN 12
                WHEN 11  THEN 13
                WHEN 71  THEN 14
                WHEN 72  THEN 15
                ELSE 99
            END AS league_priority
        FROM fixtures f
        LEFT JOIN leagues l ON f.league_id = l.league_id
        JOIN odds_values ov ON ov.fixture_id = f.fixture_id
        WHERE DATE(f.match_datetime) = CURRENT_DATE
          AND f.status IN ('NS', 'TBD', 'LIVE')
          AND ov.odd_value BETWEEN %s AND %s
        ORDER BY league_priority ASC, f.match_datetime ASC
        LIMIT %s
    """, (WC_LEAGUE_ID, ODD_MIN, ODD_MAX, MAX_FIXTURES))

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
# DB · VERIFICACAO / CRIACAO / SALVAMENTO
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
        ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS stake_pct NUMERIC;
        ALTER TABLE picks_free ADD COLUMN IF NOT EXISTS stake_units INTEGER;
    """)
    conn.commit()
    cur.close()
    conn.close()


def save_dica(pick: dict) -> None:
    pick["market"] = translate_market(pick["market"])
    odd  = float(pick["odd"])
    conf = float(pick["confidence"])
    ev   = float(pick.get("edge") or 0)
    # Fallback: se a IA não retornou edge, deriva do EV (conf × odd - 1)
    if ev <= 0 and conf > 0 and odd > 1:
        ev = max(0.0, conf * odd - 1.0)
    stake_pct, stake_units = AISuggestionsService.calculate_stake(conf, odd, ev, pick_type="free")

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO picks_free
            (fixture_id, match_date, home_team, away_team,
             home_team_id, away_team_id,
             league_id, league_name, market, market_type, line, odd, bet_house,
             market_id, confidence, prob_real, edge, reasoning,
             stake_pct, stake_units)
        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (match_date) DO UPDATE SET
            fixture_id   = EXCLUDED.fixture_id,
            home_team    = EXCLUDED.home_team,
            away_team    = EXCLUDED.away_team,
            home_team_id = EXCLUDED.home_team_id,
            away_team_id = EXCLUDED.away_team_id,
            league_id    = EXCLUDED.league_id,
            league_name  = EXCLUDED.league_name,
            market       = EXCLUDED.market,
            market_type  = EXCLUDED.market_type,
            line         = EXCLUDED.line,
            odd          = EXCLUDED.odd,
            bet_house    = EXCLUDED.bet_house,
            market_id    = EXCLUDED.market_id,
            confidence   = EXCLUDED.confidence,
            prob_real    = EXCLUDED.prob_real,
            edge         = EXCLUDED.edge,
            reasoning    = EXCLUDED.reasoning,
            stake_pct    = EXCLUDED.stake_pct,
            stake_units  = EXCLUDED.stake_units
    """, (
        pick["fixture_id"],
        pick["home_team"],
        pick["away_team"],
        pick.get("home_team_id"),
        pick.get("away_team_id"),
        pick["league_id"],
        pick.get("league_name", ""),
        pick["market"],
        _BET_ID_TYPE_MAP.get(pick.get("market_id")) or _detect_market_type(pick["market"]),
        pick["line"],
        odd,
        pick.get("bet_house", ""),
        pick.get("market_id"),
        conf,
        float(pick.get("prob_real", 0)),
        ev,
        pick["reasoning"],
        stake_pct,
        stake_units,
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

    # Coleta picks anteriores para todos os times dos fixtures do dia
    all_teams = []
    for fwc in fixtures_with_context:
        fx = fwc.get("fixture") or fwc
        all_teams += [fx.get("home_team"), fx.get("away_team")]
    teams = [t for t in all_teams if t]
    picks_anteriores = _performance_svc.get_team_picks_str(teams, limit=10)
    print(f"[DICA] Picks anteriores injetados para {len(teams)} times")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        odd_min=ODD_MIN,
        odd_max=ODD_MAX,
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
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            break
        except RateLimitError:
            if attempt == MAX_RETRIES:
                raise Exception(f"[DICA] Rate limit após {MAX_RETRIES} tentativas · abortando.")
            print(f"[DICA] Rate limit (tentativa {attempt}/{MAX_RETRIES}) · aguardando {RATE_LIMIT_WAIT}s...")
            time.sleep(RATE_LIMIT_WAIT)
        except Exception as e:
            raise Exception(f"[DICA] Erro na API Anthropic: {e}")

    raw = response.content[0].text.strip()
    start = raw.find("{")
    if start == -1:
        raise Exception(f"[DICA] JSON não encontrado na resposta:\n{raw[:500]}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
        return obj
    except Exception as e:
        raise Exception(f"[DICA] JSON invalido: {e}\nRAW:\n{raw[start:start+500]}")


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
        f"🎯 <b>DICA DO DIA · HPS TIPSTER</b>\n"
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

    # ── IA: análise completa de todos os fixtures ─────────────────────────────
    print(f"🤖 Chamando IA com {len(fixtures_with_context)} fixture(s)...")
    result = run_dica_llm(fixtures_with_context)

    if result.get("no_bet"):
        print(f"[DICA] NO BET · {result.get('motivo', 'criterios nao atingidos')}")
        return None

    pick = result.get("pick")
    if not pick:
        print("[DICA] Resposta da IA sem pick valido.")
        return None

    if not is_market_reasoning_coherent(pick.get("market", ""), pick.get("reasoning", "")):
        print(f"[DICA] REJEITADO · reasoning incoerente com mercado '{pick.get('market')}'. Retornando no_bet.")
        return None

    # Enriquecer pick com IDs de time e market_id
    fid = pick.get("fixture_id")
    if fid:
        src_fc = next((fc for fc in fixtures_with_context if fc["fixture"]["fixture_id"] == fid), None)
        if src_fc:
            src = src_fc["fixture"]
            pick.setdefault("home_team_id", src.get("home_team_id"))
            pick.setdefault("away_team_id", src.get("away_team_id"))

    # market_id: fonte primária = JSON de saída da IA (copiado das odds enviadas)
    # Fallback: lookup por nome + linha + odd nas odds do fixture
    if not pick.get("market_id"):
        src_fc = next((fc for fc in fixtures_with_context if fc["fixture"]["fixture_id"] == fid), None)
        if src_fc:
            pick_market = str(pick.get("market", "")).strip().lower()
            pick_line   = str(pick.get("line", "")).strip().lower()
            pick_odd    = float(pick.get("odd", 0))
            for o in src_fc["context"].get("odds", []):
                o_market = str(o.get("market_name", "") or o.get("market_pt", "")).strip().lower()
                o_line   = str(o.get("line", "") or o.get("line_value", "")).strip().lower()
                o_odd    = float(o.get("best_odd") or o.get("odd", 0))
                if o_market == pick_market and o_line == pick_line and abs(o_odd - pick_odd) < 0.05:
                    pick["market_id"] = o.get("market_id")
                    break

    odd        = float(pick.get("odd", 0))
    confidence = float(pick.get("confidence", 0))

    if not (ODD_MIN <= odd <= ODD_MAX):
        print(f"[DICA] WARN: IA retornou odd {odd} fora da faixa {ODD_MIN}-{ODD_MAX} · descartado.")
        return None

    if confidence < CONFIDENCE_MIN:
        print(f"[DICA] WARN: IA retornou confidence {confidence:.2f} abaixo do minimo {CONFIDENCE_MIN} · descartado.")
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
