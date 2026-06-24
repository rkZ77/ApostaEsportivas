import os
import json
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv, find_dotenv
from anthropic import Anthropic

from utils.db_utils import get_connection
from services.fixtures_service import FixturesService
from services.odds_service import OddsService
from services.standings_service import StandingsService
from services.team_stats_service import TeamStatsService
from services.match_stats_service import MatchStatsService, NATIONAL_TEAM_LEAGUE_IDS
from services.ai_performance_service import AIPerformanceService
from services.national_team_profile_service import NationalTeamProfileService
from ai.ai_suggestions_service import translate_market, is_market_reasoning_coherent, dedup_odds, normalize_structured_odds, _market_type_from_name as _classify_market_type
from ai.prompts.team_prompt_builder import TeamPromptBuilder

load_dotenv(find_dotenv())

# ============================================================
# CONFIG
# ============================================================
AI_MODEL_NAME  = os.getenv("AI_MODEL_NAME")
BANKROLL       = float(os.getenv("BANKROLL", "1000"))
PICK_ODD_MIN   = 1.00
PICK_ODD_MAX   = 2.50

client              = Anthropic()
fixtures_svc        = FixturesService()
odds_svc            = OddsService()
standings_svc       = StandingsService()
team_stats_svc      = TeamStatsService()
match_stats_svc     = MatchStatsService()
performance_svc     = AIPerformanceService()
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
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """Você é um analista quantitativo especializado em apostas múltiplas (combinadas) com base estatística rigorosa.

PRINCÍPIOS INEGOCIÁVEIS:
- Só monte múltipla se AMBOS os picks tiverem score_base >= 0.65. Prefira no_bet a múltipla fraca.
- Correlação é o maior inimigo. Cada pick deve ser de jogo DIFERENTE e mercado INDEPENDENTE.
  Teste: "Se A ganhar, B fica mais fácil ou mais difícil?" — qualquer influência = DESCARTE.
- Odd individual: 1.00–2.50. Odd total: 2.00–3.00. Fora dessas faixas = inválido.
- Avalie TODOS os mercados — gols, escanteios, cartões, Dupla Chance, Handicap. Escolha por consistência estatística.
- Cartões: só use se árbitro (>=3 jogos) E histórico dos times (>=5 jogos, >=60%) confirmarem. Sem ambos → nao use cartoes nesta multipla.
- Odd copiada dos dados — nunca inventar. Match Winner (1X2 direto) proibido.

COMBINAÇÕES IDEAIS: mercados de categorias diferentes + jogos de ligas sem relação estatística.
Os detalhes de execução (varredura, score, correlação, montagem, conflitos proibidos) estão no prompt do usuário.

SAÍDA OBRIGATÓRIA: realize toda a análise INTERNAMENTE. NÃO escreva texto, markdown, títulos ou raciocínio fora do JSON.
Sua resposta começa com { e termina com }. Nenhum caractere antes ou depois do JSON."""


# ============================================================
# USER PROMPT
# ============================================================
USER_PROMPT_TEMPLATE = """
CALIBRACAO: {desempenho}
gap>+0.10 n>=10→reduza score_base | hit<0.50 n>=15→score_base max 0.60 | n<10→ignore | multiplas.hit<0.35→score_combo>=0.70

--- JOGOS DO DIA + DADOS ---
{fixtures_formatados}

CONTEXTO SITUACIONAL (analise ANTES de qualquer mercado, para cada jogo):
Leia a classificacao (standings) e determine a situacao de cada time:
  PRECISA GANHAR → jogo aberto, mais pressao, mais atividade esperada. Incorpore na estimativa da taxa real.
  EMPATE BASTA → pode fechar defensivamente, menos atividade esperada. Incorpore na estimativa da taxa real.
  JA CLASSIFICADO/ELIMINADO → possivel rotacao → reduza Q 1 nivel, declare no reasoning.
  CONFLITO situacao vs padrao estatistico → declare no reasoning, reduza confidence se contexto e dados divergirem.
  Em multipla: se os dois picks forem de jogos com contexto situacional oposto, verifique se nao ha correlacao indireta.

ETAPA 1 — VARREDURA E MELHOR MERCADO POR JOGO:
Avalie TODOS os mercados das odds — gols, cantos, cartões, dupla chance, handicap.
Nao existe mercado preferido: o vencedor e o de MAIOR CONSISTENCIA ESTATISTICA, independente do tipo.

FORMATO DAS ODDS (quando disponivel):
  best_odd, best_bookmaker, bookmakers_count

FORMATO DO HISTORICO: cada jogo contem home_goals/away_goals/home_corners/away_corners/home_yellow_cards/away_yellow_cards/opponent_rank.
  HISTORICO CASA → time analisado e mandante: feitos = home_goals, home_corners, home_yellow_cards...
  HISTORICO FORA → time analisado e visitante: feitos = away_goals, away_corners, away_yellow_cards...

Calcule a taxa de ocorrencia real com base nos dados historicos. Descarte mercados com taxa < 65% ou amostra < 5 jogos.
Selecione mercados com taxa >= 65% e padrao confirmado por >=2 indicadores.

FORMULA SCORE_BASE (alinhada com VIP):
C (Consistência): taxa histórica real dos dois times no contexto correto; VAZIO→0.40; ESCASSO→máx 0.65
Q (Amostra): RICO(8+)=1.00 | MODERADO(4-7)=0.75 | ESCASSO(1-3)=0.45 | VAZIO=0.20
K (Confirmação): indicadores independentes 3+=1.00 | 2=0.70 | 1=0.40 | 0=0.10
  Bonus: bookmakers_count>=3 → K +0.05 | bookmakers_count=1 → K −0.05
score_base = (C×0.45)+(Q×0.25)+(K×0.30) → range [0.20,0.92]
Odds: se odd fora de 1.00-2.50 → DESCARTE. Descarte jogo se score_base<0.55 ou sem linha válida.

SMART SAFE LINE — SELECAO DE LINHA (obrigatorio para Over/Under com multiplas linhas):
  1. Liste todas as linhas do mercado nas odds.
  2. Calcule: implied_prob=1/odd | edge=taxa_real−implied_prob | EV=taxa_real×odd−1
  3. Descarte: odd<1.60 → "odd<min" | edge<0.05 → "edge<5%" | EV≤0 → "EV nao positivo"
  4. Das aprovadas: maior taxa_real. Empate: maior edge.
  5. Sem aprovadas: fallback para linha mais conservadora >=1.01.
  No reasoning: "SMART SAFE LINE|Linhas:[...]|Rejeitadas:[linha @odd — motivo]|Escolhida:[linha @odd — taxa=X%, edge=Y%, EV=Z%]"

FEITOS vs CEDIDOS — aplique a TODOS os mercados:
  Total agregado (Over/Under gols/cantos/cartões, BTTS):
    Primário: feitos_A_contexto + feitos_B_contexto (o que cada time PRODUZ por jogo).
    Validação: cedidos_A_contexto + cedidos_B_contexto (o que cada time CONCEDE).
    Diferença ≤15%: sinal forte. Diferença >15%: reduza K 1 nível no score_base.
  Mercado de time: feitos do time no seu contexto + cedidos do adversário no contexto oposto.
  Resultado/Handicap: feitos_A vs cedidos_B (ataque A vs defesa B) + feitos_B vs cedidos_A.

QUALIDADE DO ADVERSARIO: cada jogo no historico contem "opponent_rank" (posicao na tabela).
rank 1-6 (top)→peso 2.0 | rank 7-12 (mid)→peso 1.0 | rank 13+ (fraco)→peso 0.5 | null→peso 1.0
Taxa real = soma(stat × peso) / soma(pesos). Declare no reason: "taxa bruta X% → ponderada Y%".
Para Copa do Mundo: use "weighted_goals_against" do campo quality_breakdown no perfil da selecao.

ETAPA 2 — CORRELACAO ESTRITA:
Antes de montar, responda: "Se A ganhar, B fica mais difícil?" → Sim = DESCARTE.
PROIBIDO — Tipo A (mesmo jogo, logicamente impossíveis):
  - Mesmo fixture_id em qualquer seleção
  - Over + Under do MESMO market_type no MESMO jogo
  - BTTS Sim + Under 2.5 (mesmo jogo): BTTS implica ≥2 gols, sabota Under
  - BTTS Sim + Under 1.5 (mesmo jogo): impossível
  - Handicap/Resultado (vitória por margem) + Under gols (mesmo jogo): contradição
PROIBIDO — Tipo B (jogos diferentes, estatisticamente correlacionados):
  - Dois Over de gols em que o argumento é idêntico ("defesas fracas da liga") — sem histórico individual independente
  - Dois picks com o MESMO árbitro como único confirmador
IDEAL: categorias completamente diferentes (ex: escanteios + cartões) + jogos sem relação estatística.
Se restar dúvida sobre independência → NO BET.

ETAPA 3 — MONTAGEM:
score_combo=(A+B)/2, penalizar -0.10 se perfis parecidos/alta variancia. odd_total=odd_A×odd_B (2.00-3.00).
multipla_1=maior score_combo valido | multipla_2=segundo melhor (score_combo>=0.60 apenas). Sem par→no_bet.
FIXTURE E MERCADO ÚNICOS ENTRE MÚLTIPLAS:
  - Dentro de cada múltipla: pick_1.fixture_id ≠ pick_2.fixture_id (obrigatorio).
  - Entre multipla_1 e multipla_2: os fixture_ids devem ser todos diferentes (4 jogos distintos no total).
    Se não houver 4 jogos suficientes, multipla_2 pode reutilizar 1 fixture desde que o market_type seja completamente diferente.
  - PROIBIDO repetir a combinação (fixture_id + market_type) entre multipla_1 e multipla_2.
    Exemplo PROIBIDO: multipla_1 tem França escanteios Over 10 → multipla_2 NÃO pode ter França escanteios (mesmo jogo, mesmo tipo de mercado, qualquer linha).
    Exemplo PROIBIDO: multipla_1 tem Alemanha gols Over 2.5 → multipla_2 NÃO pode ter Alemanha gols (nenhuma linha).
    Se o melhor candidato para multipla_2 repetiria um (fixture_id + market_type) de multipla_1 → descartar e usar o próximo melhor.
Verificacao final: odd individual 1.00-2.50? odd_total 2.00-3.00? market_types diferentes dentro de cada multipla? nenhuma combinacao (fixture_id+market_type) repetida entre multipla_1 e multipla_2? score_base>=0.55?
Se QUALQUER par passar todas as verificacoes → emita JSON de multipla (nao no_bet).

REGRA DE OUTPUT CRITICA:
- Realize TODA a analise internamente — nao escreva texto, markdown ou raciocinio fora do JSON.
- Sua resposta e APENAS o JSON. Comeca com {{ e termina com }}. Nenhum caractere antes ou depois.
- no_bet so se nenhum par valido existir apos todas as etapas.
- O campo "motivo" do no_bet deve ser UMA frase curta (ex: "Nenhum par com score_combo>=0.65 e odd_total 2.00-3.00"). Nao use motivo como rascunho de analise.

SAIDA JSON:
Sem multipla: {{"no_bet":true,"motivo":"razao curta"}}
Com multiplas: {{"multipla_1":{{"name":"MULTIPLA_1","games":[{{"fixture_id":0,"market_id":0,"market":"","line":"","odd":0.00}},{{"fixture_id":0,"market_id":0,"market":"","line":"","odd":0.00}}],"odd_final":0.00,"score_combo":0.00,"reason":"dados que validam + baixa correlacao"}},"multipla_2":{{"name":"MULTIPLA_2","games":[{{"fixture_id":0,"market_id":0,"market":"","line":"","odd":0.00}},{{"fixture_id":0,"market_id":0,"market":"","line":"","odd":0.00}}],"odd_final":0.00,"score_combo":0.00,"reason":"segunda melhor"}}}}
multipla_2 OPCIONAL — inclua so se score_combo>=0.60.
"""


# ============================================================
# CARREGA DADOS BRUTOS COMPLETOS DO FIXTURE
# 9 blocos — mesmo padrão do ai_suggestions_service
# ============================================================
def load_fixture_context(
    fixture_id: int,
    home_team_id: int,
    away_team_id: int,
    league_id: int,
    season: str,
) -> dict:
    fixture = _clean({
        "fixture_id":   fixture_id,
        "league_id":    league_id,
        "season":       season,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
    })

    try:
        home_standing = standings_svc.get_team_standing(home_team_id, league_id, season)
        away_standing = standings_svc.get_team_standing(away_team_id, league_id, season)
    except Exception:
        home_standing, away_standing = None, None

    is_national = league_id in NATIONAL_TEAM_LEAGUE_IDS
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
# FORMATA FIXTURES + DADOS BRUTOS COMPLETOS PARA A IA
# 9 blocos por jogo (mesmo padrão do VIP)
# ============================================================
def format_fixtures_for_llm(fixtures: list) -> str:
    lines = []
    for i, fx_data in enumerate(fixtures, 1):
        fx  = fx_data["fixture"]
        ctx = fx_data["context"]

        lines.append("=" * 60)
        lines.append(f"JOGO #{i}  (fixture_id: {fx['fixture_id']})")
        lines.append(f"{fx['home_team']} x {fx['away_team']}")
        lines.append(f"Data: {fx['match_datetime']}  Liga: {fx.get('league_name', fx['league_id'])}")
        lines.append("=" * 60)

        # Perfis de seleção para jogos da Copa do Mundo (versão compacta)
        if fx.get("league_id") == 1:
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
                print(f"[MULTIPLA] Erro ao buscar perfis Copa fixture {fx['fixture_id']}: {e}")

        _j = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':'))

        lines.append("\nFIXTURE:")
        lines.append(_j(ctx["fixture"]))

        if ctx.get("standings"):
            lines.append("\nCLASSIFICAÇÃO:")
            lines.append(_j(ctx["standings"]))

        if ctx.get("odds"):
            odds_all = [
                o for o in dedup_odds(normalize_structured_odds(ctx["odds"]))
                if PICK_ODD_MIN <= float(o.get("best_odd") or 0) <= PICK_ODD_MAX
            ]
            lines.append(f"\nMERCADOS E ODDS (faixa {PICK_ODD_MIN}-{PICK_ODD_MAX}, {len(odds_all)} mercados):")
            lines.append(_j(odds_all))

        if ctx.get("home_stats"):
            lines.append(f"\nESTATÍSTICAS CASA ({fx['home_team']}):")
            lines.append(_j(ctx["home_stats"]))

        if ctx.get("away_stats"):
            lines.append(f"\nESTATÍSTICAS FORA ({fx['away_team']}):")
            lines.append(_j(ctx["away_stats"]))

        if ctx.get("last10_home"):
            lines.append(f"\nLAST10 CASA ({fx['home_team']}):")
            lines.append(_j(ctx["last10_home"][:15]))

        if ctx.get("last10_away"):
            lines.append(f"\nLAST10 FORA ({fx['away_team']}):")
            lines.append(_j(ctx["last10_away"][:15]))

        if ctx.get("total_home"):
            lines.append(f"\nTOTAL CASA ({fx['home_team']}):")
            lines.append(_j(ctx["total_home"][:15]))

        if ctx.get("total_away"):
            lines.append(f"\nTOTAL FORA ({fx['away_team']}):")
            lines.append(_j(ctx["total_away"][:15]))

        lines.append("")
    return "\n".join(lines)


# ============================================================
# CHECK — JÁ TEM MÚLTIPLA HOJE?
# ============================================================
def has_today_multipla() -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM picks_multiplas WHERE match_date = CURRENT_DATE")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count >= 1


# ============================================================
# BUSCA FIXTURES DO DIA DIRETAMENTE (independente do VIP)
# ============================================================
def get_today_fixtures() -> list:
    return fixtures_svc.get_fixtures_today()


# ============================================================
# CHAMADA À IA — análise completa
# ============================================================
def run_multipla_llm(fixtures: list) -> dict:
    fixtures_formatados = format_fixtures_for_llm(fixtures)
    desempenho = performance_svc.format_for_prompt()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        fixtures_formatados=fixtures_formatados,
        desempenho=desempenho,
    )

    try:
        response = client.messages.create(
            model=AI_MODEL_NAME,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        raise Exception(f"[MULTIPLA] Erro na API Anthropic: {e}")

    raw = response.content[0].text.strip()
    start = raw.find("{")
    if start == -1:
        raise Exception(f"[MULTIPLA] JSON não encontrado na resposta:\n{raw[:500]}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
        return obj
    except Exception as e:
        raise Exception(f"[MULTIPLA] JSON inválido: {e}\nRAW:\n{raw[start:start+500]}")


# ============================================================
# CRIA TABELA SE NÃO EXISTIR
# ============================================================
def create_multipla_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS picks_multiplas (
            id            SERIAL PRIMARY KEY,
            multipla_name TEXT,
            games         JSONB,
            total_odd     NUMERIC,
            stake         NUMERIC,
            stake_pct     NUMERIC,
            score_combo   NUMERIC,
            match_date    DATE,
            result        TEXT,
            profit        NUMERIC,
            sent          BOOLEAN DEFAULT FALSE,
            reasoning     TEXT,
            created_at    TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("ALTER TABLE picks_multiplas ADD COLUMN IF NOT EXISTS score_combo NUMERIC;")
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# STAKE PARA MÚLTIPLAS (conservador — max 3u)
# ============================================================
def calculate_multipla_stake(score_combo: float) -> tuple[float, int]:
    if score_combo >= 0.80:
        return 0.03, 3
    elif score_combo >= 0.70:
        return 0.02, 2
    else:
        return 0.01, 1


# ============================================================
# SALVA MÚLTIPLA NO BANCO
# ============================================================
def save_multipla(name: str, games_info: list, fx_map: dict, reasoning: str, score_combo: float):
    conn = get_connection()
    cur = conn.cursor()

    for g in games_info:
        if "market" in g:
            g["market"] = translate_market(g["market"])
        # Garante market_type em cada leg para resolução correta no live.py
        if not g.get("market_type"):
            g["market_type"] = _classify_market_type(g.get("market", ""))
        # Enriquece com nomes e IDs dos times para exibição independente da tabela fixtures
        fx = fx_map.get(g.get("fixture_id"))
        if fx:
            if "home_team" not in g:
                g["home_team"] = fx.get("home_team", "")
                g["away_team"] = fx.get("away_team", "")
            if not g.get("home_team_id"):
                g["home_team_id"] = fx.get("home_team_id")
                g["away_team_id"] = fx.get("away_team_id")

    total_odd = 1.0
    for g in games_info:
        odd = g.get("odd")
        if odd:
            total_odd *= float(odd)
    total_odd = round(total_odd, 2)

    match_date = datetime.now().date()
    for g in games_info:
        fx = fx_map.get(g.get("fixture_id"))
        if fx:
            dt = fx["match_datetime"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            if hasattr(dt, "date"):
                match_date = dt.date()
            break

    stake_pct, stake_units = calculate_multipla_stake(score_combo)

    cur.execute("""
        INSERT INTO picks_multiplas
        (multipla_name, games, total_odd, stake_pct, stake, score_combo, match_date, reasoning)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        name,
        json.dumps(games_info, default=str),
        total_odd,
        stake_pct,
        stake_units,
        round(score_combo, 4),
        match_date,
        reasoning,
    ))

    conn.commit()
    cur.close()
    conn.close()

    print(f"[SAVE] {name} | odd total {total_odd} | score {round(score_combo * 100)}% | stake {stake_units}u")

    return total_odd


# ============================================================
# GERA MENSAGEM PARA O GRUPO (TELEGRAM/WHATSAPP)
# ============================================================
def generate_multipla_message(resultados: dict, fx_map: dict) -> str:
    today = datetime.now().strftime("%d/%m/%Y")

    lines = []
    lines.append("🎯 *MÚLTIPLAS DO DIA*")
    lines.append(f"📅 {today}")
    lines.append("─" * 30)

    emojis = {"MULTIPLA_1": "🥇", "MULTIPLA_2": "🥈"}

    for name, info in resultados.items():
        emoji = emojis.get(name, "🎲")
        games_data = info.get("games_data", [])

        lines.append(f"\n{emoji} *{name}*")
        for g in games_data:
            fx = fx_map.get(g.get("fixture_id"))
            if fx:
                lines.append(f"  ⚽ {fx['home_team']} x {fx['away_team']}")
                lines.append(f"  📊 {g['market']} → *{g['line']}*")
                lines.append(f"  💰 Odd: {g['odd']}")
                lines.append("")

        lines.append(f"  🎯 Odd total: *{info['odd']}*")
        lines.append(f"  📈 Score: *{info['score']}%*")

    lines.append("\n─" * 30)
    lines.append("🔒 Picks simples completos no VIP")
    lines.append("👉 Entre em contato para assinar")

    return "\n".join(lines)


# ============================================================
# PIPELINE COMPLETO
# ============================================================
def run_multipla_pipeline() -> dict | None:
    print("[MULTIPLA] Verificando multiplas do dia...")

    if has_today_multipla():
        print("[MULTIPLA] Multipla de hoje ja existe. Nada a fazer.")
        return None

    print("[MULTIPLA] Buscando fixtures do dia...")
    fixtures_raw = get_today_fixtures()

    if len(fixtures_raw) < 2:
        print("[MULTIPLA] Menos de 2 fixtures disponiveis — sem multipla.")
        return None

    print(f"[MULTIPLA] Carregando dados para {len(fixtures_raw)} fixture(s)...")
    fixtures = []
    fx_map   = {}

    for fx in fixtures_raw:
        try:
            ctx = load_fixture_context(
                fx["fixture_id"],
                fx["home_team_id"],
                fx["away_team_id"],
                fx["league_id"],
                fx["season"],
            )
            if not ctx.get("odds"):
                print(f"  [SKIP] Sem odds para {fx['home_team']} x {fx['away_team']} — ignorando.")
                continue

            fixtures.append({"fixture": fx, "context": ctx})
            fx_map[fx["fixture_id"]] = fx

        except Exception as e:
            print(f"  [WARN] Erro ao carregar {fx['fixture_id']}: {e}")

    if len(fixtures) < 2:
        print("[MULTIPLA] Menos de 2 fixtures com odds disponiveis — sem multipla.")
        return None

    # ── IA: análise completa de todos os jogos ────────────────────────────────
    print(f"[MULTIPLA] Chamando IA com {len(fixtures)} jogo(s)...")
    try:
        multipla_json = run_multipla_llm(fixtures)
    except Exception as e:
        print(f"[MULTIPLA] Erro na IA: {e}")
        return None

    if multipla_json.get("no_bet"):
        motivo = multipla_json.get("motivo", "criterios nao atingidos")
        print(f"[MULTIPLA] NO BET — {motivo}")
        return None

    create_multipla_table()

    resultados = {}

    for key in ["multipla_1", "multipla_2"]:
        if key not in multipla_json:
            continue

        group      = multipla_json[key]
        name       = group["name"]
        reasoning  = group.get("reason", "")
        score      = float(group.get("score_combo", 0))
        games_info = group.get("games", [])

        # Filtra jogos com reasoning incoerente com o mercado
        games_info = [
            g for g in games_info
            if is_market_reasoning_coherent(g.get("market", ""), g.get("reasoning", ""))
        ]
        removed = len(group.get("games", [])) - len(games_info)
        if removed:
            print(f"[MULTIPLA] {name} — {removed} jogo(s) removido(s) por incoerência mercado↔reasoning")

        valid_fids = [g["fixture_id"] for g in games_info if g.get("fixture_id") in fx_map]
        if len(valid_fids) < 2:
            print(f"[MULTIPLA] {name} — fixture_ids invalidos retornados pela IA, pulando.")
            continue

        total_odd = save_multipla(name, games_info, fx_map, reasoning, score)

        resultados[name] = {
            "odd":      total_odd,
            "score":    round(score * 100),
            "games_data": games_info,
        }

    if not resultados:
        print("[MULTIPLA] Nenhuma multipla valida salva.")
        return None

    print("\n[MULTIPLA] Mensagem para o grupo:")
    print("-" * 40)
    msg = generate_multipla_message(resultados, fx_map)
    print(msg)
    print("-" * 40)

    print("[MULTIPLA] Pipeline concluido!")
    return resultados


# ============================================================
# EXECUÇÃO DIRETA
# ============================================================
if __name__ == "__main__":
    run_multipla_pipeline()
