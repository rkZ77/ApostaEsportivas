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
                    results.append(f"[{query}]\n{data['answer']}")
                for r in data.get("results", [])[:2]:
                    snippet = r.get("content", "")[:400]
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

def dedup_odds(odds: list) -> list:
    """Para cada (market_name, line), mantém apenas a entrada com maior odd entre casas de aposta."""
    seen: dict[tuple, dict] = {}
    for o in odds:
        key = (
            str(o.get("market_name", o.get("market", ""))).strip().lower(),
            str(o.get("line", "")).strip(),
        )
        if key not in seen or float(o.get("odd", 0)) > float(seen[key].get("odd", 0)):
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


MODEL    = os.getenv("AI_MODEL_NAME")
BANKROLL = float(os.getenv("BANKROLL", "1000"))


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


def format_last10(rows) -> str:
    clean = []
    for r in rows:
        item = {}
        for k, v in r.items():
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

        # Histórico total só é enviado quando o venue-específico é insuficiente (< 15 jogos)
        include_total_home = len(last10_home) < 15
        include_total_away = len(last10_away) < 15

        total_home_block = f"\nHISTÓRICO TOTAL CASA\n{format_last10(total_home[:15])}" if include_total_home else ""
        total_away_block = f"\nHISTÓRICO TOTAL FORA\n{format_last10(total_away[:15])}" if include_total_away else ""

        home_avgs = self._compute_avgs(last10_home, is_home_ctx=True)
        away_avgs = self._compute_avgs(last10_away, is_home_ctx=False)
        avgs_home_block = f"\nMÉDIAS RECENTES CASA (feitas/cedidas)\n{to_json(home_avgs)}" if home_avgs else ""
        avgs_away_block = f"\nMÉDIAS RECENTES FORA (feitas/cedidas)\n{to_json(away_avgs)}" if away_avgs else ""

        return f"""
FIXTURE
{to_json(fx)}

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
{format_last10(last10_home[:15])}

HISTÓRICO FORA
{format_last10(last10_away[:15])}
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
    # FORMATA ODDS ESTRUTURADAS (com no-vig) PARA O PROMPT DA IA
    # --------------------------------------------------------
    def _format_structured_odds_for_ai(
        self,
        structured_odds: list[dict],
        min_odd: float = 1.01,
        max_odd: float = 2.00,
    ) -> list[dict]:
        """
        Converte odds estruturadas para o formato que a IA recebe.

        Envia todos os mercados na faixa de odds — sem exigir no_vig_prob.
        Cada pipeline aplica sua própria regra de odds no prompt e na validação final.
        """
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
            if not (min_odd <= best_odd <= max_odd):
                continue

            # Preferência: market_pt do banco (preenchido pelo bet_id, mais confiável)
            # Fallback: tradução em tempo real pelo nome inglês
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
                "no_vig_prob":      m.get("no_vig_prob"),
                "market_ev":        m.get("best_ev"),
                "bookmakers_count": m.get("bookmakers_count", 1),
                "odds_range":       m.get("odds_range"),
                "bookmaker_odds":   m.get("bookmaker_odds", []),
            })

        print(
            f"[AI] {len(result)} mercados ({min_odd}–{max_odd}) "
            f"| total bruto: {len(structured_odds)}"
        )
        return result

    # --------------------------------------------------------
    # IA — GERA 3 SUGESTÕES
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
        custom_prompt: str | None = None,
        odds_preloaded: list | None = None,
        web_context: str | None = None,
    ):
        # Detecta se as odds já estão no formato estruturado (com no_vig_prob)
        # ou no formato legado (lista plana de odds brutas)
        raw_odds = odds_preloaded if odds_preloaded is not None else \
            self.odds_service.load_odds_structured(fx["fixture_id"])

        if not raw_odds:
            print(f"[AI] Sem odds para fixture {fx['fixture_id']}")
            return []

        is_structured = bool(raw_odds) and "no_vig_prob" in raw_odds[0]

        if is_structured:
            # Formato novo: structured odds com no-vig — pipeline padrão
            odds_map = self._format_structured_odds_for_ai(raw_odds)
        else:
            # Fallback legado: odds brutas (formato antigo, chamadas externas)
            _BLOCKED_MARKETS = {"match winner", "resultado final (1x2)", "1x2"}
            odds_filtered = [
                o for o in raw_odds
                if o.get("market_name", "").strip().lower() not in _BLOCKED_MARKETS
                and 1.01 <= float(o.get("odd", 0) or o.get("best_odd", 0)) <= 2.00
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

        if custom_prompt:
            user_prompt = custom_prompt.format(dados=dados, desempenho=desempenho, contexto_web=web_context)
            print(f"[AI] Usando prompt PERSONALIZADO para fixture {fx['fixture_id']}")
        else:
            prompt_template = get_prompt(league_id)
            user_prompt = prompt_template.format(dados=dados, desempenho=desempenho, contexto_web=web_context)
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
            print(f"\n[PICK] IA escolheu: {ai_pick.get('market')} | {ai_pick.get('line')} "
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
    def calculate_stake(confidence: float, odd: float, ev: float = 0.0, stat_strong: bool = False) -> tuple[float, int]:
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

        # Cap por nível de confiança
        if confidence >= 0.80 and ev > 0.10:
            cap = 0.05
        elif confidence >= 0.72 and ev > 0.05:
            cap = 0.04
        else:
            cap = 0.03

        stake_pct = round(max(0.01, min(cap, half_kelly)), 4)

        # Unidades de referência (escala 1-5u para bankroll padrão R$1000, unit R$50)
        # Serve como guia visual — o frontend converte com a banca real do usuário
        ref_units = max(1, min(5, round(stake_pct / 0.01)))

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
        custom_prompt: str | None = None,
        web_context: str | None = None,
    ):
        # 1. Carrega odds estruturadas com no-vig (melhor qualidade de análise)
        #    Fallback para odds brutas se estruturado retornar vazio
        odds_map_full = self.odds_service.load_odds_structured(fx["fixture_id"])
        if not odds_map_full:
            odds_map_full = self.odds_service.load_odds_by_fixture(fx["fixture_id"])

        # 2. IA gera 3 sugestões usando o prompt da competição
        suggestions = self.generate_suggestions(
            fx, home_stats, away_stats,
            last10_home, last10_away,
            total_home, total_away,
            standings_stats,
            referee_stats=referee_stats,
            league_id=league_id,
            custom_prompt=custom_prompt,
            performance_str=performance_str,
            odds_preloaded=odds_map_full,
            web_context=web_context,
        )

        if not suggestions:
            print(f"[RESULT] IA não retornou sugestões — {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        # 3. IA escolhe o melhor pick (is_best_pick), fallback para maior EV
        chosen = self.pick_best(suggestions)

        if not chosen:
            print(f"[RESULT] Nenhuma sugestão válida após pick — {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        ev_val   = float(chosen.get("ev", 0))
        conf_val = float(chosen.get("confidence", 0))

        if ev_val <= 0 and not self._is_stat_strong(ev_val, conf_val):
            print(f"[RESULT] EV {round(ev_val*100,1)}% — sem base estatística suficiente para stat_strong (conf {round(conf_val*100)}%) — descartado para {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        if self._is_stat_strong(ev_val, conf_val):
            print(f"[RESULT] STAT-STRONG aceito: EV {round(ev_val*100,1)}% conf {round(conf_val*100)}% — stake 50% recomendado")

        def _find_market_id(om_full: list, line: str, odd_val: float) -> int | None:
            line_n = str(line).strip().lower()
            # A IA pode retornar "Over 2.5" — extrai só a parte numérica como fallback
            import re as _re
            line_numeric = _re.sub(
                r'^(over|under|yes|no|home|away|1|x|2)\s*', '', line_n
            ).strip()

            for o in om_full:
                o_odd  = float(o.get("best_odd", 0) or o.get("odd", 0))
                o_line = str(o.get("line", "") or o.get("line_value", "")).strip().lower()
                # Match exato OU match do lado numérico
                if (o_line == line_n or (line_numeric and o_line == line_numeric)) \
                        and abs(o_odd - odd_val) < 0.02:
                    return o.get("market_id")
            return None

        chosen_market_id = _find_market_id(
            odds_map_full,
            chosen.get("line", ""),
            float(chosen.get("odd", 0)),
        )

        if chosen_market_id is None:
            print(
                f"[REJECT] IA escolheu mercado não encontrado nas odds: "
                f"'{chosen.get('market')}' linha '{chosen.get('line')}' @ {chosen.get('odd')} — "
                f"mercado não existe ou foi inventado. Pick descartado."
            )
            return []

        odd  = float(chosen["odd"])
        conf = float(chosen["confidence"])
        ev   = float(chosen["ev"])

        # Garante que o mercado seja salvo em português
        chosen["market"] = translate_market(chosen["market"])

        # Sinaliza stat_strong no reasoning para o frontend exibir aviso de stake reduzido
        reasoning = chosen.get("reasoning", "")
        if chosen.get("stat_strong") or self._is_stat_strong(ev, conf):
            if "[STAT-STRONG]" not in reasoning:
                reasoning = f"[STAT-STRONG] Base estatística sólida (conf {round(conf*100)}%) mas EV levemente negativo ({round(ev*100,1)}%) — aposta 50% do stake normal. " + reasoning
            chosen["reasoning"] = reasoning

        stat_strong_flag = bool(chosen.get("stat_strong") or self._is_stat_strong(ev, conf))
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
                stake_pct,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
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
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return [chosen]
