import os
import json
import psycopg2
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv, find_dotenv
from anthropic import Anthropic

from services.odds_service import OddsService
from services.standings_service import StandingsService
from services.team_stats_service import TeamStatsService
from services.match_stats_service import MatchStatsService

load_dotenv(find_dotenv())

# ============================================================
# CONFIG
# ============================================================
AI_MODEL_NAME = os.getenv("AI_MODEL_NAME")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

client          = Anthropic()
odds_svc        = OddsService()
standings_svc   = StandingsService()
team_stats_svc  = TeamStatsService()
match_stats_svc = MatchStatsService()


# ============================================================
# DB CONNECTION
# ============================================================
def get_db():
    return psycopg2.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )


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
# RANK SIZE — escala com o número de sugestões do dia
# Top 3 é sempre fixo; picks bônus adicionados conforme volume
# ============================================================
def compute_rank_size(n_suggestions: int) -> int:
    if n_suggestions >= 13:
        return 5
    if n_suggestions >= 10:
        return 4
    return 3


def _build_rank_schema(rank_size: int) -> str:
    items = [
        f'  "rank{i}": {{"id": 0, "prob_green": 0.00, "resumo": "frase curta explicando por que é este pick"}}'
        for i in range(1, rank_size + 1)
    ]
    return "{\n" + ",\n".join(items) + "\n}"


# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """Você é um analista quantitativo sênior especializado em validação e ranking estatístico de apostas esportivas.

Sua função é revisar sugestões geradas pelo sistema VIP e selecionar as melhores com maior probabilidade real de acerto (green), ordenadas por qualidade.

PRINCÍPIOS:
- NÃO confie cegamente no confidence original — ele pode estar inflado
- Avalie exclusivamente pelo que os dados mostram — sem favorecimento de mercado
- Cada pick deve envolver times DIFERENTES — nenhum time (home ou away) se repete no ranking
- Valide o reasoning contra os dados brutos fornecidos
- Prefira padrão claro e consistente a odds atrativas com reasoning fraco

SAÍDA: apenas JSON válido. Sua resposta começa com { e termina com }. Nenhum texto fora do JSON."""


# ============================================================
# USER PROMPT — injetado com rank_size, sugestões e schema
# ============================================================
USER_PROMPT_TEMPLATE = """
Analise as sugestões abaixo e selecione as {rank_size} melhores, seguindo as etapas em ordem.

--- SUGESTÕES DO DIA + DADOS BRUTOS ---

{sugestoes_formatadas}

--- ETAPA 1: VALIDAÇÃO ---
Para cada sugestão: confirme se a odd existe nos dados; verifique se os números do reasoning batem com estatísticas e histórico; conte quantos jogos recentes confirmam o padrão.

--- ETAPA 2: PONTUAÇÃO (0.0–1.0 por critério) ---

A) COERÊNCIA ESTATÍSTICA (peso 0.40):
   1.0=dados confirmam | 0.7=parcialmente | 0.4=inconsistência | 0.0=genérico/contradiz

B) ESTABILIDADE DO MERCADO (peso 0.25):
   1.0=8+/10 jogos confirmam | 0.7=6-7/10 | 0.4=4-5/10 | 0.0=sem padrão

C) FORÇA DO REASONING (peso 0.20):
   1.0=cita dado numérico dos dados brutos | 0.7=lógica com alguma base | 0.3=superficial | 0.0=genérico

D) EV (peso 0.10): ajuste fino entre empatados. Não priorize isoladamente.

E) ODDS (peso 0.05):
   1.0=odd 1.40–1.90 | 0.7=1.90–2.20 | 0.4=>2.20 | 0.0=<1.30 ou >2.80

--- ETAPA 3: PROB_GREEN ---
prob_green = (A×0.40) + (B×0.25) + (C×0.20) + (D×0.10) + (E×0.05)
Limites: min=0.55, max=0.92

--- ETAPA 4: SELEÇÃO COM DIVERSIDADE ---
1. Ordene por prob_green (maior primeiro)
2. Selecione {rank_size} picks: pule se home OU away já aparece em pick selecionado
3. Empate: prefira maior coerência → menor variância
4. Nunca repita sugestão nem invente IDs

Verificação: {rank_size} picks? Nenhum time repetido? IDs existem nas sugestões? prob_green ∈ [0.55, 0.92]?

--- SAÍDA JSON ---

{rank_schema}
"""


# ============================================================
# CARREGA DADOS BRUTOS COMPLETOS DO FIXTURE
# Espelha exatamente os blocos enviados pelo ai_suggestions_service
# ============================================================
def load_fixture_context(
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

    fixture = _clean({
        "fixture_id":    fixture_id,
        "league_id":     league_id,
        "season":        season,
        "home_team_id":  home_team_id,
        "away_team_id":  away_team_id,
    })

    return {
        "fixture":     fixture,
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
# FORMATA SUGESTÕES + DADOS BRUTOS COMPLETOS PARA A IA
# ============================================================
def format_suggestions_for_llm(suggestions: list) -> str:
    lines = []
    for i, s in enumerate(suggestions, 1):
        lines.append("=" * 60)
        lines.append(f"SUGESTÃO #{i}  (id: {s['id']})")
        lines.append("=" * 60)
        lines.append(f"Jogo        : {s['home_team_name']} x {s['away_team_name']}")
        lines.append(f"Data        : {s['match_date']}")
        lines.append(f"Mercado     : {s['market']}")
        lines.append(f"Market Type : {s.get('market_type', '?')}")
        lines.append(f"Linha       : {s['line']}")
        lines.append(f"Odd         : {s['odd']}")
        lines.append(f"Casa        : {s['bet_house']}")
        lines.append(f"EV          : {s['ev']}")
        lines.append(f"Confidence  : {s['confidence']}")
        lines.append(f"Reasoning   : {s['reasoning']}")

        ctx = s.get("context")
        if ctx:
            if ctx.get("fixture"):
                lines.append(f"\nFIXTURE:")
                lines.append(json.dumps(ctx["fixture"], ensure_ascii=False))
            if ctx.get("standings"):
                lines.append(f"\nCLASSIFICAÇÃO:")
                lines.append(json.dumps(ctx["standings"], ensure_ascii=False))
            if ctx.get("odds"):
                lines.append(f"\nMERCADOS E ODDS:")
                lines.append(json.dumps(ctx["odds"], ensure_ascii=False))
            if ctx.get("home_stats"):
                lines.append(f"\nESTATÍSTICAS CASA ({s['home_team_name']}):")
                lines.append(json.dumps(ctx["home_stats"], ensure_ascii=False))
            if ctx.get("away_stats"):
                lines.append(f"\nESTATÍSTICAS FORA ({s['away_team_name']}):")
                lines.append(json.dumps(ctx["away_stats"], ensure_ascii=False))
            if ctx.get("last10_home"):
                lines.append(f"\nLAST10 CASA ({s['home_team_name']}):")
                lines.append(json.dumps(ctx["last10_home"], ensure_ascii=False))
            if ctx.get("last10_away"):
                lines.append(f"\nLAST10 FORA ({s['away_team_name']}):")
                lines.append(json.dumps(ctx["last10_away"], ensure_ascii=False))
            if ctx.get("total_home"):
                lines.append(f"\nTOTAL CASA ({s['home_team_name']}):")
                lines.append(json.dumps(ctx["total_home"], ensure_ascii=False))
            if ctx.get("total_away"):
                lines.append(f"\nTOTAL FORA ({s['away_team_name']}):")
                lines.append(json.dumps(ctx["total_away"], ensure_ascii=False))

        lines.append("")
    return "\n".join(lines)


# ============================================================
# CHECK — JÁ TEM RANKING HOJE?
# ============================================================
def has_today_ranking() -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM picks_vip WHERE match_date = CURRENT_DATE")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count >= 3


# ============================================================
# BUSCA SUGESTÕES DO DIA — JOIN com fixtures para league_id/season
# ============================================================
def get_today_suggestions() -> list:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            s.id, s.fixture_id, s.match_date,
            s.home_team_id, s.away_team_id,
            s.home_team_name, s.away_team_name,
            s.market, s.market_type, s.line, s.odd,
            s.bet_house, s.ev, s.confidence, s.reasoning,
            f.league_id, f.season
        FROM picks_vip s
        JOIN fixtures f USING (fixture_id)
        WHERE s.match_date = CURRENT_DATE
        ORDER BY s.confidence DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "id":             r[0],
            "fixture_id":     r[1],
            "match_date":     r[2].isoformat() if isinstance(r[2], date) else r[2],
            "home_team_id":   r[3],
            "away_team_id":   r[4],
            "home_team_name": r[5],
            "away_team_name": r[6],
            "market":         r[7],
            "market_type":    r[8],
            "line":           r[9],
            "odd":            float(r[10]) if r[10] is not None else None,
            "bet_house":      r[11],
            "ev":             float(r[12]) if r[12] is not None else None,
            "confidence":     float(r[13]) if r[13] is not None else None,
            "reasoning":      r[14],
            "league_id":      r[15],
            "season":         r[16],
        })
    return result


# ============================================================
# CHAMADA À IA — RANKING COM CoT
# ============================================================
def run_ranking_llm(suggestions: list, rank_size: int) -> dict:
    sugestoes_formatadas = format_suggestions_for_llm(suggestions)
    rank_schema          = _build_rank_schema(rank_size)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        rank_size=rank_size,
        sugestoes_formatadas=sugestoes_formatadas,
        rank_schema=rank_schema,
    )

    try:
        response = client.messages.create(
            model=AI_MODEL_NAME,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        raise Exception(f"[RANKING] Erro na API Anthropic: {e}")

    raw = response.content[0].text.strip()

    try:
        return json.loads(raw)
    except Exception as e:
        raise Exception(f"[RANKING] JSON inválido: {e}\nRAW:\n{raw[:500]}")


# ============================================================
# STAKE POR POSIÇÃO
# Top 3 = picks principais | rank 4-5 = picks bônus (stake menor)
#
# Tabela de stakes por rank:
#   Rank 1 → 4% base  (+1% se prob_green >= 0.78) = 4–5%
#   Rank 2 → 3% base  (+1% se prob_green >= 0.78) = 3–4%
#   Rank 3 → 2% base  (+1% se prob_green >= 0.78) = 2–3%
#   Rank 4 → 1.5%
#   Rank 5 → 1.0%
#   Teto absoluto: 5%
#   Ex (bankroll R$1000): rank1=R$40-50 | rank2=R$30-40 | rank3=R$20-30
# ============================================================
def calculate_stake_by_rank(rank_pos: int, prob_green: float, bankroll: float = 1000.0):
    base = {1: 0.04, 2: 0.03, 3: 0.02, 4: 0.015, 5: 0.01}.get(rank_pos, 0.01)

    if prob_green >= 0.78:
        base += 0.01

    stake_pct = min(base, 0.05)
    stake     = round(bankroll * stake_pct, 2)
    return stake, round(stake_pct, 4)


# ============================================================
# CRIA TABELA SE NÃO EXISTIR
# ============================================================
def create_ranked_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_vip (
            id                 SERIAL PRIMARY KEY,
            suggestion_id      INTEGER,
            fixture_id         INTEGER,
            match_date         DATE,
            home_team_name     TEXT,
            away_team_name     TEXT,
            market             TEXT,
            line               TEXT,
            odd                NUMERIC,
            stake              NUMERIC,
            stake_pct          NUMERIC,
            bet_house          TEXT,
            ev                 NUMERIC,
            confidence         NUMERIC,
            reasoning_original TEXT,
            prob_green         NUMERIC,
            rank_position      INTEGER,
            rank_resumo        TEXT,
            result             TEXT,
            profit             NUMERIC,
            sent_free          BOOLEAN DEFAULT FALSE,
            checked_at         TIMESTAMP,
            created_at         TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# SALVA RANKING NO BANCO (dinâmico: rank_size picks)
# ============================================================
def save_ranking(suggestions: list, ranking: dict, rank_size: int):
    conn    = get_db()
    cur     = conn.cursor()
    sug_map = {s["id"]: s for s in suggestions}

    for pos in range(1, rank_size + 1):
        key = f"rank{pos}"
        if key not in ranking:
            print(f"[RANKING] {key} não encontrado na resposta da IA — pulando.")
            continue

        item   = ranking[key]
        sug_id = item["id"]
        prob   = float(item["prob_green"] or 0.5)
        resumo = item.get("resumo", "")

        if sug_id not in sug_map:
            print(f"[RANKING] ID {sug_id} não existe nas sugestões — pulando.")
            continue

        sug              = sug_map[sug_id]
        stake, stake_pct = calculate_stake_by_rank(pos, prob)

        cur.execute("""
            INSERT INTO picks_vip
            (suggestion_id, fixture_id, match_date,
             home_team_name, away_team_name,
             market, line, odd, stake, stake_pct,
             bet_house, ev, confidence,
             reasoning_original, prob_green, rank_position, rank_resumo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            sug["id"], sug["fixture_id"], sug["match_date"],
            sug["home_team_name"], sug["away_team_name"],
            sug["market"], sug["line"], sug["odd"],
            stake, stake_pct,
            sug["bet_house"], sug["ev"], sug["confidence"],
            sug["reasoning"], prob, pos, resumo,
        ))

        label = "PRINCIPAL" if pos <= 3 else "BÔNUS"
        print(
            f"[SAVE] #{pos} [{label}] {sug['home_team_name']} x {sug['away_team_name']} | "
            f"{sug['market']} {sug['line']} | odd {sug['odd']} | "
            f"prob_green {round(prob * 100)}% | stake R${stake}"
        )

    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# GERA MENSAGEM PARA O GRUPO FREE
# Top 3 = picks principais (sempre) | rank 4-5 = picks bônus
# ============================================================
def generate_free_message(suggestions: list, ranking: dict, rank_size: int) -> str:
    sug_map = {s["id"]: s for s in suggestions}
    today   = datetime.now().strftime("%d/%m/%Y")

    lines = []
    lines.append("🏆 *PICKS DO DIA*")
    lines.append(f"📅 {today}")
    lines.append("─" * 30)

    primary_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}

    for pos in range(1, rank_size + 1):
        key = f"rank{pos}"
        if key not in ranking:
            continue

        item   = ranking[key]
        sug_id = item["id"]
        prob   = float(item["prob_green"] or 0.5)

        if sug_id not in sug_map:
            continue

        s    = sug_map[sug_id]
        conf = round(prob * 100)

        if pos == 4:
            lines.append("\n─── 🎁 PICKS BÔNUS ───")

        emoji = primary_emojis.get(pos, "🎯")
        lines.append(f"\n{emoji} *Pick {pos}*")
        lines.append(f"⚽ {s['home_team_name']} x {s['away_team_name']}")
        lines.append(f"📊 {s['market']} → *{s['line']}*")
        lines.append(f"💰 Odd: *{s['odd']}* | Casa: {s['bet_house']}")
        lines.append(f"📈 Confiança: *{conf}%*")

    lines.append("\n─" * 30)
    lines.append("🔒 Análise completa + picks exclusivos no VIP")
    lines.append("👉 Entre em contato para assinar")

    return "\n".join(lines)


# ============================================================
# PIPELINE COMPLETO
# ============================================================
def run_ranking_pipeline() -> dict | None:
    print("🔍 Verificando ranking do dia...")

    if has_today_ranking():
        print("✅ Ranking de hoje já existe. Nada a fazer.")
        return None

    print("📋 Buscando sugestões do dia...")
    suggestions = get_today_suggestions()

    if not suggestions:
        print("❌ Nenhuma sugestão encontrada hoje.")
        return None

    rank_size = compute_rank_size(len(suggestions))
    print(f"📊 {len(suggestions)} sugestão(ões) → Top {rank_size} para hoje "
          f"({'3 principais' if rank_size == 3 else f'3 principais + {rank_size - 3} bônus'})")

    print(f"🔍 Carregando dados brutos para {len(suggestions)} sugestão(ões)...")
    for s in suggestions:
        try:
            s["context"] = load_fixture_context(
                s["fixture_id"],
                s["home_team_id"],
                s["away_team_id"],
                s["league_id"],
                s["season"],
            )
        except Exception as e:
            print(f"  [WARN] Contexto não carregado para fixture {s['fixture_id']}: {e}")
            s["context"] = None

    print("🤖 Enviando para IA ranquear...")
    ranking = run_ranking_llm(suggestions, rank_size)

    print("💾 Salvando ranking no banco...")
    create_ranked_table()
    save_ranking(suggestions, ranking, rank_size)

    print("\n📣 Mensagem para o grupo free:")
    print("─" * 40)
    msg = generate_free_message(suggestions, ranking, rank_size)
    print(msg)
    print("─" * 40)

    print("\n✅ Pipeline de ranking concluído!")
    return ranking


# ============================================================
# EXECUÇÃO DIRETA
# ============================================================
if __name__ == "__main__":
    run_ranking_pipeline()
