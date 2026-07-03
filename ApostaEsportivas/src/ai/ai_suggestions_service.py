import os
import re
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv, find_dotenv
from anthropic import Anthropic, RateLimitError

from utils.db_utils import get_connection
from services.odds_service import OddsService
from services.pick_math_service import analyze_fixture_markets, rank_market_candidates, build_reasoning
from ai.prompts import get_prompt, SYSTEM_PROMPT
from collectors.odds_collector_service import MARKET_TYPE_MAP as _BET_ID_TYPE_MAP

load_dotenv(find_dotenv())


# ============================================================
# CONTEXTO WEB — busca informações sobre o jogo via Tavily
# ============================================================
def fetch_web_context(home_team: str, away_team: str, competition: str, match_date: str) -> str:
    """Busca contexto externo sobre o jogo via Tavily API (opcional).
    Retorna string vazia se TAVILY_API_KEY não estiver configurada.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return "Sem contexto web disponível (TAVILY_API_KEY não configurada)."

    queries = [
        f"{home_team} vs {away_team} {competition} {match_date} preview statistics",
        f"{competition} {match_date} cards fouls referee history",
    ]

    results = []
    for query in queries:
        try:
            payload = json.dumps({
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 3,
                "include_answer": True,
            }).encode()
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
                if data.get("answer"):
                    results.append(f"[{query}]\n{data['answer'][:500]}")
                for r in data.get("results", [])[:2]:
                    snippet = r.get("content", "")[:300]
                    if snippet:
                        results.append(f"Fonte: {r.get('url','')}\n{snippet}")
        except (urllib.error.URLError, Exception) as e:
            print(f"[WEB] Falha na busca '{query}': {e}")
            continue

    if not results:
        return "Busca web sem resultados para este jogo."

    return "\n\n".join(results[:5])

# ============================================================
# TRADUÇÃO DE MERCADOS (inglês → português)
# ============================================================
_MARKET_MAP = {
    # Resultado
    "match winner":                         "Resultado Final (1X2)",
    "double chance":                         "Dupla Chance",
    "double chance - 1st half":             "Dupla Chance - 1º Tempo",
    "first half winner":                    "Vencedor do 1º Tempo",
    "asian handicap":                       "Handicap Asiático",
    # BTTS
    "both teams score":                     "Ambas as Equipes Marcam",
    "both teams to score":                  "Ambas as Equipes Marcam",
    "both teams score - first half":        "Ambas Marcam - 1º Tempo",
    "both teams to score - first half":     "Ambas Marcam - 1º Tempo",
    "both teams score first half":          "Ambas Marcam - 1º Tempo",
    # Gols FT
    "goals over/under":                     "Gols Mais/Menos",
    "total goals":                          "Gols Mais/Menos",
    # Gols 1º Tempo
    "goals over/under first half":          "Gols Mais/Menos - 1º Tempo",
    "goals over/under - first half":        "Gols Mais/Menos - 1º Tempo",
    "goals over/under 1st half":            "Gols Mais/Menos - 1º Tempo",
    # Gols 2º Tempo
    "goals over/under - second half":       "Gols Mais/Menos - 2º Tempo",
    "goals over/under second half":         "Gols Mais/Menos - 2º Tempo",
    "goals over/under 2nd half":            "Gols Mais/Menos - 2º Tempo",
    # Gols por time
    "total - home":                         "Total de Gols Casa",
    "total - away":                         "Total de Gols Visitante",
    "home team total goals":                "Total de Gols Casa",
    "away team total goals":                "Total de Gols Visitante",
    "home team total goals(1st half)":      "Total de Gols Casa (1º Tempo)",
    "away team total goals(1st half)":      "Total de Gols Visitante (1º Tempo)",
    "home team total goals - 1st half":     "Total de Gols Casa (1º Tempo)",
    "away team total goals - 1st half":     "Total de Gols Visitante (1º Tempo)",
    # Escanteios FT
    "corners over under":                   "Escanteios Mais/Menos",
    "corners over/under":                   "Escanteios Mais/Menos",
    "total corners":                        "Escanteios Mais/Menos",
    "corners 1x2":                          "Escanteios 1x2",
    "home corners over/under":              "Escanteios Casa Mais/Menos",
    "away corners over/under":              "Escanteios Visitante Mais/Menos",
    # Escanteios 1º Tempo
    "total corners (1st half)":             "Total de Escanteios (1º Tempo)",
    "corners over/under - 1st half":        "Total de Escanteios (1º Tempo)",
    "home total corners (1st half)":        "Escanteios Casa (1º Tempo)",
    "away total corners (1st half)":        "Escanteios Visitante (1º Tempo)",
    # Escanteios 2º Tempo
    "total corners (2nd half)":             "Total de Escanteios (2º Tempo)",
    "corners over/under - 2nd half":        "Total de Escanteios (2º Tempo)",
    # Cartões FT
    "cards over/under":                     "Cartões Mais/Menos",
    "home team total cards":                "Total de Cartões Casa",
    "away team total cards":                "Total de Cartões Visitante",
    "home team cards":                      "Total de Cartões Casa",
    "away team cards":                      "Total de Cartões Visitante",
}

# Padrões para mercados com nome de time: "[Time] - Goals Over/Under" → "[Time] - Gols Mais/Menos"
_TEAM_PATTERNS = [
    (r"^(.+?)\s*-\s*goals over/under\s*$",         r"\1 - Gols Mais/Menos"),
    (r"^(.+?)\s*-\s*total goals?\s*$",              r"\1 - Total de Gols"),
    (r"^(.+?)\s*-\s*corners over/?under\s*$",       r"\1 - Escanteios Mais/Menos"),
    (r"^(.+?)\s*-\s*total corners?\s*$",            r"\1 - Total de Escanteios"),
    (r"^(.+?)\s*-\s*cards over/?under\s*$",         r"\1 - Cartões Mais/Menos"),
    (r"^(.+?)\s*-\s*total cards?\s*$",              r"\1 - Total de Cartões"),
]


def translate_market(market: str) -> str:
    """Converte nomes de mercado do inglês para o português."""
    if not market:
        return market
    key = market.strip().lower()
    if key in _MARKET_MAP:
        return _MARKET_MAP[key]
    for pattern, replacement in _TEAM_PATTERNS:
        if re.match(pattern, key, re.IGNORECASE):
            return re.sub(pattern, replacement, market.strip(), flags=re.IGNORECASE)
    return market  # já em português ou desconhecido


_COHERENCE_KEYWORDS: dict[str, list[str]] = {
    "cards":   ["cartão", "cartões", "card", "amarelo", "yellow", "vermelho", "red card", "disciplin"],
    "corners": ["escanteio", "canto", "corner"],
    "goals":   ["gol", "goal", "marcar", "score", "btts", "over", "under"],
}

def _market_type_from_name(market: str) -> str | None:
    """Classifica market_type a partir do nome. Retorna None quando não reconhecido
    para que o caller use keyword matching no texto em vez de forçar "result"."""
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
    if any(x in m for x in ["1x2", "resultado", "winner", "vencedor",
                              "dupla chance", "handicap", "match winner"]):
        return "result"
    return None  # desconhecido — não force "result", deixa keyword matching agir

def normalize_structured_odds(odds: list) -> list:
    """Combina value_name + line_value em um campo 'line' unificado.
    Ex: {"value":"Over","line":"2.5"} → {"value":"Over","line":"Over 2.5"}.
    Necessário antes de dedup_odds para preservar Over E Under de uma mesma linha."""
    result = []
    for o in odds:
        item = dict(o)
        value = str(item.get("value", "") or "").strip()
        line  = str(item.get("line", "") or "").strip()
        if value and line and not line.lower().startswith(value.lower()):
            item["line"] = f"{value} {line}"
        elif value and not line:
            item["line"] = value
        result.append(item)
    return result


def dedup_odds(odds: list) -> list:
    """Para cada (market_name, line), mantém apenas a entrada com maior odd entre casas de aposta.
    Espera odds já normalizadas (line = 'Over 2.5', não '2.5') para preservar Over/Under."""
    seen: dict[tuple, dict] = {}
    for o in odds:
        key = (
            str(o.get("market_name", o.get("market", ""))).strip().lower(),
            str(o.get("line", "")).strip().lower(),
        )
        cur_odd = float(o.get("best_odd") or o.get("odd", 0))
        if key not in seen or cur_odd > float(seen[key].get("best_odd") or seen[key].get("odd", 0)):
            seen[key] = o
    return list(seen.values())


def is_market_reasoning_coherent(market: str, reasoning: str) -> bool:
    """Retorna False se o reasoning fala exclusivamente de outro tipo de mercado."""
    mtype = _market_type_from_name(market)
    if mtype not in _COHERENCE_KEYWORDS:
        return True
    r = reasoning.lower()
    own_kws   = _COHERENCE_KEYWORDS[mtype]
    other_kws = [kw for t, kws in _COHERENCE_KEYWORDS.items() if t != mtype for kw in kws]
    if any(kw in r for kw in other_kws) and not any(kw in r for kw in own_kws):
        return False
    return True


MODEL        = os.getenv("AI_MODEL_NAME")
BANKROLL     = float(os.getenv("BANKROLL", "1000"))
VIP_ODD_MIN  = 1.30
VIP_ODD_MAX  = 1.95


# ============================================================
# SANITIZAÇÃO
# ============================================================
def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


_LAST10_SKIP = {
    # IDs e metadados sem valor analítico
    "fixture_id", "league_id", "season",
    # shots_on não está no formato descrito no prompt e raramente influencia o pick
    "home_shots_on", "away_shots_on",
    # total_cards = total_yellow_cards + total_red_cards (redundante)
    "total_cards",
}

def format_last10(rows) -> str:
    clean = []
    for r in rows:
        item = {}
        for k, v in r.items():
            if k in _LAST10_SKIP:
                continue
            if isinstance(v, (datetime, date)):
                item[k] = v.isoformat()
            elif isinstance(v, Decimal):
                item[k] = float(v)
            else:
                item[k] = v
        clean.append(item)
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def _parse_suggestions(raw: str) -> list | None:
    """Extrai a lista de sugestões do JSON retornado pela IA. Retorna None se inválido."""
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    parsed = json.loads(raw)
    if isinstance(parsed, dict) and "suggestions" in parsed:
        data = parsed["suggestions"]
    elif isinstance(parsed, list):
        data = parsed
    else:
        return None
    return data if isinstance(data, list) else None


# ============================================================
# SERVICE PRINCIPAL
# ============================================================
class AISuggestionsService:

    def __init__(self):
        self.odds_service = OddsService()
        self.client = Anthropic()

    # --------------------------------------------------------
    # IDENTIFICA TIPO DE MERCADO
    # --------------------------------------------------------
    def detect_market_type(self, market: str) -> str:
        m = market.lower()
        if "corner" in m or "escanteio" in m:
            return "corners"
        if "card" in m or "cartão" in m or "cartões" in m:
            return "cards"
        if "shot" in m:
            return "shots"
        if "goal" in m or "gol" in m:
            return "goals"
        if any(x in m for x in ["1x2", "result", "winner", "home", "away", "draw", "dupla chance", "handicap"]):
            return "result"
        return "unknown"

    # --------------------------------------------------------
    # MÉDIAS CALCULADAS A PARTIR DO HISTÓRICO RECENTE
    # --------------------------------------------------------
    @staticmethod
    def _compute_avgs(matches: list, is_home_ctx: bool) -> dict:
        """Computa médias de gols feitos/cedidos, escanteios e cartões do histórico recente."""
        if not matches:
            return {}
        n = len(matches)
        gf_k  = "home_goals"         if is_home_ctx else "away_goals"
        ga_k  = "away_goals"         if is_home_ctx else "home_goals"
        cf_k  = "home_corners"       if is_home_ctx else "away_corners"
        ca_k  = "away_corners"       if is_home_ctx else "home_corners"
        yf_k  = "home_yellow_cards"  if is_home_ctx else "away_yellow_cards"
        rf_k  = "home_red_cards"     if is_home_ctx else "away_red_cards"

        def avg(key):
            return round(sum((m.get(key) or 0) for m in matches) / n, 2)

        gf = [(m.get(gf_k) or 0) for m in matches]
        ga = [(m.get(ga_k) or 0) for m in matches]
        tg = [(m.get("total_goals") or 0) for m in matches]
        tc = [(m.get("total_corners") or 0) for m in matches]

        return {
            "jogos": n,
            "gols_feitos_media":       round(sum(gf) / n, 2),
            "gols_cedidos_media":      round(sum(ga) / n, 2),
            "total_gols_media":        round(sum(tg) / n, 2),
            "escanteios_feitos_media": avg(cf_k),
            "escanteios_cedidos_media": avg(ca_k),
            "total_escanteios_media":  round(sum(tc) / n, 2),
            "amarelos_media":          avg(yf_k),
            "vermelhos_media":         avg(rf_k),
            "btts_pct":                round(sum(1 for g, a in zip(gf, ga) if g > 0 and a > 0) / n * 100, 1),
            "over_2_5_pct":            round(sum(1 for t in tg if t > 2.5) / n * 100, 1),
        }

    # --------------------------------------------------------
    # MONTA BLOCO DE DADOS
    # --------------------------------------------------------
    def _build_dados(
        self,
        fx,
        home_stats,
        away_stats,
        last10_home,
        last10_away,
        total_home,
        total_away,
        standings_stats,
        odds_map,
        referee_stats,
    ) -> str:
        def to_json(obj):
            return json.dumps(sanitize(obj), ensure_ascii=False, separators=(',', ':'))

        referee_block = to_json(referee_stats) if referee_stats else '"Arbitro nao identificado ou sem historico na temporada"'

        # Histórico total só é enviado quando o venue-específico é insuficiente (< 10 jogos)
        include_total_home = len(last10_home) < 10
        include_total_away = len(last10_away) < 10

        total_home_block = f"\nHISTÓRICO TOTAL CASA\n{format_last10(total_home[:10])}" if include_total_home else ""
        total_away_block = f"\nHISTÓRICO TOTAL FORA\n{format_last10(total_away[:10])}" if include_total_away else ""

        home_avgs = self._compute_avgs(last10_home, is_home_ctx=True)
        away_avgs = self._compute_avgs(last10_away, is_home_ctx=False)
        avgs_home_block = f"\nMÉDIAS RECENTES CASA (feitas/cedidas)\n{to_json(home_avgs)}" if home_avgs else ""
        avgs_away_block = f"\nMÉDIAS RECENTES FORA (feitas/cedidas)\n{to_json(away_avgs)}" if away_avgs else ""

        # Campos do fixture relevantes para análise (remove IDs e metadados)
        fx_slim = {k: v for k, v in sanitize(fx).items()
                   if k not in {"home_team_id", "away_team_id", "season", "status"}}

        return f"""
FIXTURE
{to_json(fx_slim)}

CLASSIFICAÇÃO
{to_json(standings_stats)}

MERCADOS E ODDS
{to_json(odds_map)}

ESTATÍSTICAS CASA
{to_json(home_stats)}

ESTATÍSTICAS FORA
{to_json(away_stats)}
{avgs_home_block}
{avgs_away_block}

HISTÓRICO CASA
{format_last10(last10_home[:10])}

HISTÓRICO FORA
{format_last10(last10_away[:10])}
{total_home_block}
{total_away_block}
ÁRBITRO
{referee_block}
"""

    # --------------------------------------------------------
    # CHAMA A API (com retry em caso de JSON inválido)
    # --------------------------------------------------------
    def _call_api(self, user_prompt: str, fixture_id: int) -> list:
        messages = [{"role": "user", "content": user_prompt}]
        RATE_LIMIT_WAIT = 65   # segundos de espera ao receber 429
        MAX_RATE_RETRIES = 3   # tentativas após rate limit

        for attempt in range(1, 3):
            rate_retries = 0
            while True:
                try:
                    response = self.client.messages.create(
                        model=MODEL,
                        max_tokens=8096,
                        system=SYSTEM_PROMPT,
                        messages=messages,
                    )
                    break  # sucesso, sai do loop de rate limit
                except RateLimitError as e:
                    rate_retries += 1
                    if rate_retries > MAX_RATE_RETRIES:
                        print(f"[AI API ERROR] Rate limit após {MAX_RATE_RETRIES} tentativas — abortando fixture {fixture_id}")
                        return []
                    print(f"[AI RATE LIMIT] Rate limit atingido (tentativa {rate_retries}/{MAX_RATE_RETRIES}) "
                          f"— aguardando {RATE_LIMIT_WAIT}s...")
                    time.sleep(RATE_LIMIT_WAIT)
                except Exception as e:
                    print(f"[AI API ERROR] tentativa {attempt}: {e}")
                    return []

            raw = response.content[0].text.strip()

            try:
                data = _parse_suggestions(raw)
                if data is not None:
                    return data
                print(f"[AI] Retorno inesperado (tentativa {attempt}):", raw[:200])
            except Exception as e:
                print(f"[AI JSON ERROR] tentativa {attempt}: {e}\nRAW:\n{raw[:300]}")

            if attempt == 1:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": 'JSON inválido ou fora do formato esperado. Retorne APENAS {"suggestions": [...]} com exatamente 3 objetos, cada um contendo o campo "is_best_pick" (true em exatamente 1, false nos outros 2).',
                })
                print(f"[AI] Retry para fixture {fixture_id}...")

        return []

    # --------------------------------------------------------
    # FORMATA ODDS ESTRUTURADAS (com no-vig) PARA O PROMPT DA IA (Call 2)
    # --------------------------------------------------------
    def _format_structured_odds_for_ai(self, structured_odds: list[dict]) -> list[dict]:
        """Converte odds estruturadas para o formato que a IA recebe na Call 2 (análise).
        Sem filtro de odd — cada prompt define o range permitido. Bloqueia só Match Winner."""
        _BLOCKED = {
            "match winner", "resultado final (1x2)", "1x2",
            "first half winner", "vencedor do 1º tempo",
        }

        result = []
        for m in structured_odds:
            raw_name = m.get("market_name", "").strip()
            if raw_name.lower() in _BLOCKED:
                continue

            best_odd = m.get("best_odd", 0)
            if not best_odd or best_odd <= 1.0:
                continue

            pt_name    = m.get("market_pt") or translate_market(raw_name)
            team       = m.get("team")
            translated = pt_name != raw_name
            if team and translated:
                pt_name = f"{pt_name} ({team})"

            value_raw = m.get("value", "")
            line_raw  = m.get("line", "")
            combined_line = f"{value_raw} {line_raw}".strip() if line_raw else value_raw

            result.append({
                "market_id":        m.get("market_id"),
                "market_name":      pt_name,
                "market_type":      m.get("market_type"),
                "value":            value_raw,
                "line":             combined_line,
                "best_odd":         best_odd,
                "best_bookmaker":   m.get("best_bookmaker"),
                "bookmakers_count": m.get("bookmakers_count", 1),
                "odds_range":       m.get("odds_range"),
            })

        print(f"[AI] {len(result)} mercados (sem filtro de odd) | total bruto: {len(structured_odds)}")
        return result

    # --------------------------------------------------------
    # GERA 3 SUGESTÕES — CÁLCULO DETERMINÍSTICO (SEM IA)
    #
    # Decisão do usuário (2026-07-02): a IA fazia tanto a leitura de
    # contexto quanto a matemática (taxa/confidence/edge/EV/escolha de
    # linha) dentro do prompt, o que causava inconsistência entre
    # execuções (mesma entrada, contas diferentes). pick_math_service
    # agora calcula tudo em Python (determinístico, sempre o mesmo
    # resultado para o mesmo dado) e escolhe os 3 mercados finais +
    # is_best_pick. Reasoning é gerado por template a partir dos
    # números calculados — sem chamada de IA nesta etapa.
    # --------------------------------------------------------
    def generate_suggestions_math(self, fx, last10_home, last10_away, odds_preloaded=None) -> list:
        raw_odds = odds_preloaded if odds_preloaded is not None else \
            self.odds_service.load_odds_structured(fx["fixture_id"])
        if not raw_odds:
            print(f"[MATH] Sem odds para fixture {fx['fixture_id']}")
            return []

        raw_odds_vip = [o for o in raw_odds if VIP_ODD_MIN <= float(o.get("best_odd") or 0) <= VIP_ODD_MAX]
        if not raw_odds_vip:
            print(f"[MATH] Nenhuma odd na faixa {VIP_ODD_MIN}-{VIP_ODD_MAX} para fixture {fx['fixture_id']}")
            return []

        match_dt = fx.get("match_datetime")
        if isinstance(match_dt, str):
            match_dt = datetime.fromisoformat(match_dt)
        reference_date = match_dt.date() if isinstance(match_dt, datetime) else date.today()

        candidates = analyze_fixture_markets(raw_odds_vip, last10_home, last10_away, reference_date=reference_date)
        picks = rank_market_candidates(candidates)

        if not picks:
            print(f"[MATH] Nenhum mercado passou nos filtros (taxa>=65%, amostra>=5, confidence>=0.55) "
                  f"— {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        suggestions = []
        for c in picks:
            suggestions.append({
                "market_id":    c["market_id"],
                "market":       c["market_name"],
                "line":         c["value_label"],
                "odd":          c["odd"],
                "bet_house":    c["best_bookmaker"],
                "confidence":   c["confidence"],
                "is_best_pick": c.get("is_best_pick", False),
                "probability":  c["taxa_real"],
                "edge":         float(c["edge"]),
                "ev":           float(c["ev"]),
                "market_type":  c["market_type"],
                "reasoning":    build_reasoning(c),
            })

        print(f"\n[MATH] {fx.get('home_team')} x {fx.get('away_team')} — {len(suggestions)} sugestões (determinístico):")
        for i, p in enumerate(suggestions, 1):
            marker = " <BEST>" if p["is_best_pick"] else ""
            print(f"  [{i}] {p['market']} | {p['line']} | odd {p['odd']} "
                  f"| edge {p['edge']*100:+.1f}% | conf {p['confidence']*100:.0f}%{marker}")

        return suggestions

    # --------------------------------------------------------
    # IA — GERA 3 SUGESTÕES (legado — não usado mais em generate_and_save,
    # mantido para referência/comparação manual)
    # --------------------------------------------------------
    def generate_suggestions(
        self,
        fx,
        home_stats,
        away_stats,
        last10_home,
        last10_away,
        total_home,
        total_away,
        standings_stats,
        referee_stats=None,
        league_id: int = 0,
        performance_str: str | None = None,
        picks_anteriores_str: str | None = None,
        custom_prompt: str | None = None,
        odds_preloaded: list | None = None,
        web_context: str | None = None,
    ):
        # Detecta se as odds já estão no formato estruturado (best_odd agregado)
        # ou no formato legado (lista plana de odds brutas por bookmaker)
        raw_odds = odds_preloaded if odds_preloaded is not None else \
            self.odds_service.load_odds_structured(fx["fixture_id"])

        if not raw_odds:
            print(f"[AI] Sem odds para fixture {fx['fixture_id']}")
            return []

        is_structured = bool(raw_odds) and "best_bookmaker" in raw_odds[0]

        if is_structured:
            raw_odds_vip = [o for o in raw_odds if VIP_ODD_MIN <= float(o.get("best_odd") or 0) <= VIP_ODD_MAX]
            odds_map = self._format_structured_odds_for_ai(raw_odds_vip)
        else:
            # Fallback legado: odds brutas (formato antigo, chamadas externas)
            _BLOCKED_MARKETS = {"match winner", "resultado final (1x2)", "1x2"}
            odds_filtered = [
                o for o in raw_odds
                if o.get("market_name", "").strip().lower() not in _BLOCKED_MARKETS
                and float(o.get("odd", 0) or o.get("best_odd", 0)) > 1.0
            ]
            _seen: dict[tuple, dict] = {}
            for o in odds_filtered:
                key = (o.get("market_name", "").strip().lower(), str(o.get("line", "")).strip())
                odd_val = float(o.get("odd", 0) or o.get("best_odd", 0))
                if key not in _seen or odd_val > float(_seen[key].get("odd", _seen[key].get("best_odd", 0))):
                    _seen[key] = o
            odds_for_ai = []
            for o in _seen.values():
                item = dict(o)
                raw = item.get("market_name", "")
                pt = translate_market(raw)
                if pt != raw:
                    item["market_name"] = f"{pt} ({item['team']})" if item.get("team") else pt
                odds_for_ai.append(item)
            odds_map = odds_for_ai
            print(f"[AI] {len(odds_map)} odds únicas (legado) para fixture {fx['fixture_id']}")

        dados = self._build_dados(
            fx, home_stats, away_stats,
            last10_home, last10_away,
            total_home, total_away,
            standings_stats, odds_map,
            referee_stats,
        )
        
        # Busca contexto web se não fornecido externamente
        if web_context is None:
            match_date_str = fx.get("match_datetime", "")
            if isinstance(match_date_str, datetime):
                match_date_str = match_date_str.strftime("%Y-%m-%d")
            web_context = fetch_web_context(
                fx.get("home_team", ""),
                fx.get("away_team", ""),
                fx.get("league_name", f"league_{league_id}"),
                str(match_date_str)[:10],
            )

        desempenho = performance_str or '{"status":"sem historico suficiente ainda"}'
        picks_anteriores = picks_anteriores_str or '{"status":"sem picks anteriores para estes times"}'

        if custom_prompt:
            user_prompt = custom_prompt.format(
                dados=dados, desempenho=desempenho,
                contexto_web=web_context, picks_anteriores=picks_anteriores,
            )
            print(f"[AI] Usando prompt PERSONALIZADO para fixture {fx['fixture_id']}")
        else:
            prompt_template = get_prompt(league_id)
            user_prompt = prompt_template.format(
                dados=dados, desempenho=desempenho,
                contexto_web=web_context, picks_anteriores=picks_anteriores,
            )
            print(f"[AI] Usando prompt liga {league_id} -> fixture {fx['fixture_id']}")

        data = self._call_api(user_prompt, fx["fixture_id"])
        if not data:
            return []

        before = len(data)
        data = [s for s in data if 1.01 <= float(s.get("odd", 0)) <= 2.00]
        if len(data) < before:
            print(f"[AI] {before - len(data)} sugestao(es) descartada(s) por odd fora de 1.01-2.00")
        if not data:
            print(f"[AI] Nenhuma sugestao com odd entre 1.01-2.00 para fixture {fx['fixture_id']}")
            return []

        # Rejeita picks com reasoning inconsistente com o mercado (ex: cartões falando de gols)
        before = len(data)
        data = [s for s in data if self._check_market_reasoning_match(s)]
        if len(data) < before:
            print(f"[AI] {before - len(data)} sugestao(es) descartada(s) por incoerência mercado↔reasoning")

        print(f"\n[AI] {fx.get('home_team')} x {fx.get('away_team')} — {len(data)} sugestões geradas:")
        for i, p in enumerate(data, 1):
            print(
                f"  [{i}] {p.get('market', '?')} | linha: {p.get('line', '?')} "
                f"| odd {p.get('odd', '?')} "
                f"| edge {round(float(p.get('edge', 0)) * 100, 1)}% "
                f"| conf {round(float(p.get('confidence', 0)) * 100)}%"
            )

        return data

    # --------------------------------------------------------
    # VALIDA COERÊNCIA MERCADO ↔ REASONING
    # --------------------------------------------------------
    _MARKET_KEYWORDS: dict[str, list[str]] = {
        "cards":   ["cartão", "cartões", "card", "amarelo", "yellow", "vermelho", "red card", "disciplin"],
        "corners": ["escanteio", "canto", "corner"],
        "goals":   ["gol", "goal", "marcar", "score", "btts", "over", "under"],
    }

    def _check_market_reasoning_match(self, pick: dict) -> bool:
        """Rejeita pick se o reasoning analisar tipo de evento diferente do mercado."""
        market   = pick.get("market", "").lower()
        reasoning = pick.get("reasoning", "").lower()
        mtype = self.detect_market_type(market)

        if mtype not in self._MARKET_KEYWORDS:
            return True  # mercado desconhecido — não rejeita

        own_kws   = self._MARKET_KEYWORDS[mtype]
        other_kws = [kw for t, kws in self._MARKET_KEYWORDS.items() if t != mtype for kw in kws]

        has_own   = any(kw in reasoning for kw in own_kws)
        has_other = any(kw in reasoning for kw in other_kws)

        if has_other and not has_own:
            print(f"[AI VALIDATE] Rejeitando pick '{pick.get('market')}' — reasoning fala de outro mercado (mtype={mtype})")
            return False
        return True

    # Limiares para pick stat_strong (forte estatisticamente mas EV levemente negativo)
    # Conf >= 72% + EV > -5% → pick válido, stake reduzido pelo frontend
    _STAT_STRONG_CONF      = 0.72
    _EV_STAT_STRONG_FLOOR  = -0.05   # pior EV aceito para stat_strong
    _EV_VETO_HARD          = -0.05   # abaixo disso: descarte sempre

    @staticmethod
    def _is_stat_strong(ev: float, conf: float) -> bool:
        """Pick sem EV mas com base estatística sólida — apostar menos."""
        return (ev <= 0
                and ev > AISuggestionsService._EV_STAT_STRONG_FLOOR
                and conf >= AISuggestionsService._STAT_STRONG_CONF)

    # --------------------------------------------------------
    # IA ESCOLHE 1 DAS 3 (via is_best_pick)
    # Fallback para maior EV se campo ausente
    # --------------------------------------------------------
    def pick_best(self, suggestions: list) -> dict | None:
        if not suggestions:
            return None

        # Tenta usar a escolha da IA
        ai_pick = next((s for s in suggestions if s.get("is_best_pick") is True), None)

        if ai_pick:
            odd  = float(ai_pick.get("odd", 0))
            conf = float(ai_pick.get("confidence", 0))
            ev   = round((conf * odd) - 1, 4)
            ai_pick["ev"] = ev
            print(f"\n[PICK] Selecionado: {ai_pick.get('market')} | {ai_pick.get('line')} "
                  f"| odd {odd} | EV {round(ev * 100, 1)}% | conf {round(conf * 100)}%")
            for s in suggestions:
                if s is not ai_pick:
                    o = float(s.get("odd", 0))
                    c = float(s.get("confidence", 0))
                    print(f"  [NÃO SELECIONADO] {s.get('market')} | {s.get('line')} "
                          f"| EV {round((c*o-1)*100, 1)}% | conf {round(c*100)}%")

            # EV negativo: tenta alternativa com EV positivo primeiro
            if ev <= 0:
                alternatives = [
                    (round((float(s.get("odd", 0)) * float(s.get("confidence", 0))) - 1, 4),
                     float(s.get("confidence", 0)), s)
                    for s in suggestions if s is not ai_pick
                ]
                positive = sorted(
                    [(e, c, s) for e, c, s in alternatives if e > 0],
                    key=lambda x: (x[0], x[1]), reverse=True
                )
                if positive:
                    best_ev, best_conf, best = positive[0]
                    best["ev"] = best_ev
                    print(f"[PICK] EV negativo no is_best_pick — alternativa EV>0: "
                          f"{best.get('market')} | {best.get('line')} | EV {round(best_ev*100,1)}%")
                    return best

                # Sem alternativa positiva: aceita se for stat_strong
                if self._is_stat_strong(ev, conf):
                    ai_pick["stat_strong"] = True
                    print(f"[PICK] STAT-STRONG: EV {round(ev*100,1)}% negativo mas conf {round(conf*100)}% ≥ 72% — stake reduzido")
                    return ai_pick

            return ai_pick

        # Fallback: campo ausente → Python escolhe por maior EV
        print("[PICK] is_best_pick ausente — fallback para maior EV")
        scored = []
        for s in suggestions:
            try:
                odd  = float(s.get("odd", 0))
                conf = float(s.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            ev = (conf * odd) - 1
            scored.append((ev, conf, s))

        if not scored:
            return None

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_ev, best_conf, best = scored[0]
        best["ev"] = round(best_ev, 4)

        print(f"\n[PICK] Fallback EV: {best.get('market')} | {best.get('line')} "
              f"| odd {best.get('odd')} | EV {round(best_ev * 100, 1)}% | conf {round(best_conf * 100)}%")
        for ev, conf, s in scored[1:]:
            print(f"  [NÃO SELECIONADO] {s.get('market')} | {s.get('line')} "
                  f"| EV {round(ev * 100, 1)}% | conf {round(conf * 100)}%")

        return best

    # --------------------------------------------------------
    # CÁLCULO DE STAKE — ½ Kelly fracionado
    #
    # Retorna (stake_pct, stake_units_ref)
    #   stake_pct      → fração da banca a apostar (0.01–0.05)
    #   stake_units_ref→ unidades de referência (escala 1–5u)
    #
    # Faixas por nível de confiança + EV:
    #   ≥ 80% conf e EV > 10% → até 5% / 5u
    #   ≥ 72% conf e EV > 5%  → até 4% / 4u
    #   demais positivos       → até 3% / 2-3u
    #   stat_strong (EV ≤ 0)  → 1% / 1u
    # --------------------------------------------------------
    @staticmethod
    def calculate_stake(confidence: float, odd: float, ev: float = 0.0, stat_strong: bool = False, max_units: int = 10) -> tuple[float, int]:
        if stat_strong or ev <= 0:
            return 0.01, 1

        b = float(odd) - 1.0
        p = float(confidence)
        q = 1.0 - p

        if b <= 0 or p <= 0 or p >= 1:
            return 0.01, 1

        kelly = (b * p - q) / b
        if kelly <= 0:
            return 0.01, 1

        half_kelly = kelly * 0.5

        # Cap por nível de confiança — escala com max_units (VIP=10u, Free=5u)
        cap_high = round(max_units * 0.01, 4)                       # 10% p/ VIP, 5% p/ Free
        cap_mid  = round(max_units * 0.008, 4)                      # 8%  p/ VIP, 4% p/ Free
        cap_low  = round(max(0.03, max_units * 0.005), 4)           # 5%  p/ VIP, 3% p/ Free

        if confidence >= 0.80 and ev > 0.10:
            cap = cap_high
        elif confidence >= 0.72 and ev > 0.05:
            cap = cap_mid
        else:
            cap = cap_low

        stake_pct = round(max(0.01, min(cap, half_kelly)), 4)

        # Unidades de referência (1u = 1% da banca)
        ref_units = max(1, min(max_units, round(stake_pct / 0.01)))

        return stake_pct, ref_units

    # --------------------------------------------------------
    # GERAR E SALVAR NO BANCO (com ON CONFLICT para evitar duplicatas)
    # --------------------------------------------------------
    def generate_and_save(
        self,
        fx,
        home_stats,
        away_stats,
        last10_home,
        last10_away,
        total_home,
        total_away,
        standings_stats,
        referee_stats=None,
        league_id: int = 0,
        performance_str: str | None = None,
        picks_anteriores_str: str | None = None,
        custom_prompt: str | None = None,
        web_context: str | None = None,
    ):
        # 1. Carrega odds estruturadas (melhor odd por mercado+linha+side entre as casas)
        #    Fallback para odds brutas se estruturado retornar vazio
        odds_map_full = self.odds_service.load_odds_structured(fx["fixture_id"])
        if not odds_map_full:
            odds_map_full = self.odds_service.load_odds_by_fixture(fx["fixture_id"])

        # 2. Gera 3 sugestões — cálculo determinístico (pick_math_service),
        #    sem chamada de IA (decisão do usuário em 2026-07-02).
        suggestions = self.generate_suggestions_math(
            fx, last10_home, last10_away,
            odds_preloaded=odds_map_full,
        )

        if not suggestions:
            print(f"[RESULT] Nenhum mercado elegível — {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        # 3. Lê o is_best_pick já definido por rank_market_candidates (Python), fallback para maior EV
        chosen = self.pick_best(suggestions)

        if not chosen:
            print(f"[RESULT] Nenhuma sugestão válida após pick — {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        ev_val   = float(chosen.get("ev", 0))
        conf_val = float(chosen.get("confidence", 0))

        def _find_market_id_fallback(om_full: list, market: str, line: str, odd_val: float) -> int | None:
            """Fallback: busca market_id por (nome + linha + odd), com match de nome como critério extra."""
            import re as _re
            line_n    = str(line).strip().lower()
            market_n  = str(market).strip().lower()
            line_numeric = _re.sub(r'^(over|under|yes|no|home|away|1|x|2)\s*', '', line_n).strip()

            # 1ª tentativa: match completo (nome + linha + odd)
            for o in om_full:
                o_odd    = float(o.get("best_odd", 0) or o.get("odd", 0))
                o_line   = str(o.get("line", "") or o.get("line_value", "")).strip().lower()
                o_market = str(o.get("market_name", "") or o.get("market_pt", "")).strip().lower()
                if ((o_line == line_n or (line_numeric and o_line == line_numeric))
                        and abs(o_odd - odd_val) < 0.02
                        and o_market == market_n):
                    return o.get("market_id")

            # 2ª tentativa: apenas linha + odd (comportamento original — menos preciso)
            for o in om_full:
                o_odd  = float(o.get("best_odd", 0) or o.get("odd", 0))
                o_line = str(o.get("line", "") or o.get("line_value", "")).strip().lower()
                if (o_line == line_n or (line_numeric and o_line == line_numeric)) \
                        and abs(o_odd - odd_val) < 0.02:
                    return o.get("market_id")
            return None

        # Fonte primária: market_id do JSON de saída da IA (copiado das odds enviadas)
        chosen_market_id = chosen.get("market_id")

        if chosen_market_id is None:
            # Fallback: lookup por nome+linha+odd nas odds completas
            chosen_market_id = _find_market_id_fallback(
                odds_map_full,
                chosen.get("market", ""),
                chosen.get("line", ""),
                float(chosen.get("odd", 0)),
            )

        if chosen_market_id is None:
            print(
                f"[REJECT] Mercado selecionado não encontrado nas odds: "
                f"'{chosen.get('market')}' linha '{chosen.get('line')}' @ {chosen.get('odd')} — "
                f"pick descartado (não deveria ocorrer no caminho determinístico)."
            )
            return []

        odd  = float(chosen["odd"])
        conf = float(chosen["confidence"])
        ev   = float(chosen["ev"])

        # Garante que o mercado seja salvo em português
        chosen["market"] = translate_market(chosen["market"])

        stat_strong_flag = False
        stake_pct, stake_units = self.calculate_stake(conf, odd, ev, stat_strong_flag)

        print(
            f"\n[SAVE] {fx['home_team']} x {fx['away_team']} | "
            f"{chosen['market']} {chosen['line']} | odd {odd} | "
            f"edge {round(float(chosen.get('edge', 0)) * 100, 1)}% | "
            f"conf {round(conf * 100)}% | EV {ev} | stake {stake_pct*100:.1f}% ({stake_units}u)"
        )

        # 3. Salva no banco — ON CONFLICT ignora duplicata do mesmo fixture
        conn = get_connection()
        cur  = conn.cursor()

        match_dt = fx["match_datetime"]
        if isinstance(match_dt, str):
            match_dt = datetime.fromisoformat(match_dt)

        cur.execute(
            """
            INSERT INTO picks_vip (
                fixture_id, match_date,
                home_team_id, away_team_id,
                home_team_name, away_team_name,
                market, line, odd, bet_house,
                market_type, market_id,
                confidence, ev, probability, reasoning,
                stake_pct, stake_units,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (fixture_id) DO NOTHING
            """,
            (
                fx["fixture_id"],
                match_dt.date(),
                fx["home_team_id"],
                fx["away_team_id"],
                fx["home_team"],
                fx["away_team"],
                chosen["market"],
                chosen["line"],
                odd,
                chosen["bet_house"],
                _BET_ID_TYPE_MAP.get(chosen_market_id) or self.detect_market_type(chosen["market"]),
                chosen_market_id,
                conf,
                ev,
                float(chosen.get("probability", 0) or 0),
                chosen.get("reasoning", ""),
                stake_pct,
                stake_units,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return [chosen]
