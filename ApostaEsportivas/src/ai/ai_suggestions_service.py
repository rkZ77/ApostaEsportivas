import os
import re
import json
import time
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv, find_dotenv
from anthropic import Anthropic, RateLimitError

from utils.db_utils import get_connection
from services.odds_service import OddsService
from ai.prompts import get_prompt, SYSTEM_PROMPT

load_dotenv(find_dotenv())

# ============================================================
# TRADUÇÃO DE MERCADOS (inglês → português)
# ============================================================
_MARKET_MAP = {
    "match winner":                    "Resultado Final (1X2)",
    "double chance":                   "Dupla Chance",
    "both teams score":                "Ambas as Equipes Marcam",
    "both teams to score":             "Ambas as Equipes Marcam",
    "asian handicap":                  "Handicap Asiático",
    "goals over/under":                "Gols Mais/Menos",
    "goals over/under first half":     "Gols Mais/Menos - 1º Tempo",
    "goals over/under - second half":  "Gols Mais/Menos - 2º Tempo",
    "goals over/under second half":    "Gols Mais/Menos - 2º Tempo",
    "corners over under":              "Escanteios Mais/Menos",
    "corners over/under":              "Escanteios Mais/Menos",
    "corners 1x2":                     "Escanteios 1x2",
    "cards over/under":                "Cartões Mais/Menos",
    "home corners over/under":         "Escanteios Casa Mais/Menos",
    "away corners over/under":         "Escanteios Visitante Mais/Menos",
    "home total corners (1st half)":   "Escanteios Casa (1º Tempo)",
    "away total corners (1st half)":   "Escanteios Visitante (1º Tempo)",
    "total corners (1st half)":        "Total de Escanteios (1º Tempo)",
    "total corners (2nd half)":        "Total de Escanteios (2º Tempo)",
    "home team total cards":           "Total de Cartões Casa",
    "away team total cards":           "Total de Cartões Visitante",
    "home team total goals(1st half)": "Total de Gols Casa (1º Tempo)",
    "away team total goals(1st half)": "Total de Gols Visitante (1º Tempo)",
    "total - home":                    "Total de Gols Casa",
    "total - away":                    "Total de Gols Visitante",
    "first half winner":               "Vencedor do 1º Tempo",
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

        # Histórico total só é enviado quando o venue-específico é insuficiente (< 8 jogos)
        # Caso contrário é redundante e desperdiça ~2.000 tokens por fixture
        include_total_home = len(last10_home) < 8
        include_total_away = len(last10_away) < 8

        total_home_block = f"\nHISTÓRICO TOTAL CASA\n{format_last10(total_home[:8])}" if include_total_home else ""
        total_away_block = f"\nHISTÓRICO TOTAL FORA\n{format_last10(total_away[:8])}" if include_total_away else ""

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

HISTÓRICO CASA
{format_last10(last10_home[:8])}

HISTÓRICO FORA
{format_last10(last10_away[:8])}
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
    ):
        odds_map = odds_preloaded if odds_preloaded is not None else self.odds_service.load_odds_by_fixture(fx["fixture_id"])
        if not odds_map:
            print(f"[AI] Sem odds para fixture {fx['fixture_id']}")
            return []

        # Filtra mercados bloqueados e odds fora da faixa válida
        _BLOCKED_MARKETS = {"match winner", "resultado final (1x2)", "1x2"}
        odds_map = [
            o for o in odds_map
            if o.get("market_name", "").strip().lower() not in _BLOCKED_MARKETS
            and 1.38 <= float(o.get("odd", 0)) <= 1.92
        ]

        # Deduplica: para cada (market_name, line) mantém apenas a maior odd (melhor valor)
        # O banco tem 10+ casas por mercado — a IA só precisa de 1 referência por linha
        _seen: dict[tuple, dict] = {}
        for o in odds_map:
            key = (o.get("market_name", "").strip().lower(), str(o.get("line", "")).strip())
            if key not in _seen or float(o.get("odd", 0)) > float(_seen[key].get("odd", 0)):
                _seen[key] = o
        odds_map = list(_seen.values())
        print(f"[AI] {len(odds_map)} odds únicas (1.38-1.92) para fixture {fx['fixture_id']}")

        # Traduz mercados para português APÓS dedup (dedup usa nome inglês como chave)
        # Inclui o time no nome para mercados específicos (ex: "Total de Cartões Visitante (Athletic Club)")
        # Mantém market_id para rastreamento
        odds_for_ai = []
        for o in odds_map:
            item = dict(o)
            raw = item.get("market_name", "")
            pt = translate_market(raw)
            if pt != raw:
                item["market_name"] = f"{pt} ({item['team']})" if item.get("team") else pt
            odds_for_ai.append(item)
        odds_map = odds_for_ai

        dados = self._build_dados(
            fx, home_stats, away_stats,
            last10_home, last10_away,
            total_home, total_away,
            standings_stats, odds_map,
            referee_stats,
        )
        
        # NOVO: Usar prompt customizado se fornecido (Copa do Mundo)
        if custom_prompt:
            desempenho = performance_str or '{"status":"sem historico suficiente ainda"}'
            user_prompt = custom_prompt.format(dados=dados, desempenho=desempenho)
            print(f"[AI] Usando prompt PERSONALIZADO para fixture {fx['fixture_id']}")
        else:
            prompt_template = get_prompt(league_id)
            desempenho = performance_str or '{"status":"sem historico suficiente ainda"}'
            user_prompt = prompt_template.format(dados=dados, desempenho=desempenho)
            print(f"[AI] Usando prompt liga {league_id} -> fixture {fx['fixture_id']}")

        data = self._call_api(user_prompt, fx["fixture_id"])
        if not data:
            return []

        before = len(data)
        data = [s for s in data if 1.40 <= float(s.get("odd", 0)) <= 1.90]
        if len(data) < before:
            print(f"[AI] {before - len(data)} sugestao(es) descartada(s) por odd fora de 1.40-1.90")
        if not data:
            print(f"[AI] Nenhuma sugestao com odd entre 1.40-1.90 para fixture {fx['fixture_id']}")
            return []

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
    # CÁLCULO DE STAKE (Kelly fracionado — 25% Kelly)
    #
    # Faixa: 2% mínimo, 5% máximo do bankroll
    # --------------------------------------------------------
    def calculate_stake(self, confidence, odd):
        # Stake calculado no frontend com banca real do usuário (½ Kelly personalizado)
        return None, None

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
    ):
        # 1. Carrega odds uma única vez (usada pela IA e pelo lookup de market_id)
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
        )

        if not suggestions:
            print(f"[RESULT] IA não retornou sugestões — {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        # 3. IA escolhe o melhor pick (is_best_pick), fallback para maior EV
        chosen = self.pick_best(suggestions)

        if not chosen:
            print(f"[RESULT] Nenhuma sugestão válida após pick — {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        if float(chosen.get("ev", 0)) <= 0:
            print(f"[RESULT] EV ≤ 0 ({round(float(chosen['ev'])*100,1)}%) — pick descartado para {fx.get('home_team')} x {fx.get('away_team')}")
            return []

        def _find_market_id(om_full: list, line: str, odd_val: float) -> int | None:
            line_n = str(line).strip().lower()
            for o in om_full:
                if (str(o.get("line", "")).strip().lower() == line_n
                        and abs(float(o.get("odd", 0)) - odd_val) < 0.001):
                    return o.get("market_id")
            return None

        chosen_market_id = _find_market_id(
            odds_map_full,
            chosen.get("line", ""),
            float(chosen.get("odd", 0)),
        )

        odd  = float(chosen["odd"])
        conf = float(chosen["confidence"])
        ev   = float(chosen["ev"])

        # Garante que o mercado seja salvo em português
        chosen["market"] = translate_market(chosen["market"])

        stake, stake_pct = self.calculate_stake(conf, odd)

        print(
            f"\n[SAVE] {fx['home_team']} x {fx['away_team']} | "
            f"{chosen['market']} {chosen['line']} | odd {odd} | "
            f"edge {round(float(chosen.get('edge', 0)) * 100, 1)}% | "
            f"conf {round(conf * 100)}% | EV {ev} | "
            f"stake calculado no frontend"
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
                confidence, stake, stake_pct, ev, reasoning,
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
                self.detect_market_type(chosen["market"]),
                chosen_market_id,
                conf,
                stake,
                stake_pct,
                ev,
                chosen.get("reasoning", ""),
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return [chosen]
