import os
import json
import time
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from database import get_connection
from auth_utils import get_current_user

_BR_TZ = ZoneInfo("America/Sao_Paulo")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

API_BASE      = "https://v3.football.api-sports.io"
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"}
FT_STATUSES   = {"FT", "AET", "PEN"}

# TTL adaptativo: jogos ao vivo → curto; não iniciados → médio; encerrados → longo
_TTL_LIVE = 10   # segundos · atualiza depressa durante o jogo
_TTL_NS   = 60   # segundos · jogo ainda não começou
_TTL_FT   = 300  # segundos · encerrado, dados não mudam

_fix_cache:   dict[int, tuple[float, dict]] = {}
_stats_cache: dict[int, tuple[float, list]] = {}
_odds_live_cache: dict[int, tuple[float, list]] = {}


def _cache_ttl(status: str) -> int:
    if status in LIVE_STATUSES:
        return _TTL_LIVE
    if status in FT_STATUSES:
        return _TTL_FT
    return _TTL_NS


def _headers():
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _fetch_fixture(fid: int) -> dict:
    now = time.time()
    if fid in _fix_cache:
        ts, cached = _fix_cache[fid]
        status = cached.get("fixture", {}).get("status", {}).get("short", "NS")
        if now - ts < _cache_ttl(status):
            return cached
    try:
        r = requests.get(f"{API_BASE}/fixtures", headers=_headers(),
                         params={"id": fid, "timezone": "America/Sao_Paulo"}, timeout=10)
        items = r.json().get("response", [])
        data  = items[0] if items else {}
    except Exception as e:
        logger.error("[LIVE] fixture %s: %s", fid, e)
        data = _fix_cache.get(fid, (0, {}))[1]  # mantém cache antigo em caso de erro
    _fix_cache[fid] = (now, data)
    return data


def _fetch_stats(fid: int, status: str) -> list:
    now = time.time()
    if fid in _stats_cache:
        ts, cached = _stats_cache[fid]
        if now - ts < _cache_ttl(status):
            return cached
    try:
        r = requests.get(f"{API_BASE}/fixtures/statistics", headers=_headers(),
                         params={"fixture": fid}, timeout=10)
        data = r.json().get("response", [])
    except Exception as e:
        logger.error("[LIVE STATS] fixture %s: %s", fid, e)
        data = _stats_cache.get(fid, (0, []))[1]  # mantém cache antigo em caso de erro
    _stats_cache[fid] = (now, data)
    return data


def _fetch_live_odds(fid: int) -> list:
    """Odds ao vivo (repreçadas em tempo real pela API conforme o jogo
    evolui) via /odds/live -- usado só no momento em que o usuário abre o
    modal de aposta pra um jogo já em andamento. Cache curto (mesmo TTL de
    stats ao vivo, sempre _TTL_LIVE aqui pois só é chamado pra jogos já
    confirmados como ao vivo)."""
    now = time.time()
    if fid in _odds_live_cache:
        ts, cached = _odds_live_cache[fid]
        if now - ts < _TTL_LIVE:
            return cached
    try:
        r = requests.get(f"{API_BASE}/odds/live", headers=_headers(),
                         params={"fixture": fid}, timeout=10)
        items = r.json().get("response", [])
        data = items[0].get("odds", []) if items else []
    except Exception as e:
        logger.error("[LIVE ODDS] fixture %s: %s", fid, e)
        data = _odds_live_cache.get(fid, (0, []))[1]  # mantém cache antigo em caso de erro
    _odds_live_cache[fid] = (now, data)
    return data


# Nomes de mercado ao vivo (API-Football) por market_type salvo no pick --
# só as familias que o motor de picks realmente gera hoje (goals/corners/
# cards over-under). Familias sem equivalente claro ao vivo (handicap,
# shots, offsides) nao entram aqui -- _find_live_odd devolve None pra elas,
# e o front cai pra odd ja salva (mesmo comportamento de antes desta feature).
_LIVE_OVERUNDER_NAMES = {
    "goals":   {"match goals", "over/under line", "goals over/under"},
    "corners": {"total corners", "match corners"},
    "cards":   {"total cards"},
}


def _find_live_odd(market_type: str | None, line: str | None, odds_markets: list) -> float | None:
    """Acha a melhor odd ao vivo que corresponde ao mercado/linha salvos no
    pick. Best-effort e silencioso: qualquer mercado sem correspondência
    clara retorna None (nunca lança erro, nunca bloqueia o fluxo -- o
    front usa a odd já salva nesse caso, igual já funcionava antes)."""
    mtype = (market_type or "").lower()
    direction, line_val = _extract_line(line)

    if mtype in _LIVE_OVERUNDER_NAMES and direction in ("over", "under") and line_val is not None:
        wanted_names = _LIVE_OVERUNDER_NAMES[mtype]
        best = None
        for m in odds_markets:
            if (m.get("name") or "").lower() not in wanted_names:
                continue
            for v in m.get("values", []):
                if v.get("suspended") or (v.get("value") or "").lower() != direction:
                    continue
                try:
                    handicap = float(v.get("handicap"))
                    odd = float(v["odd"])
                except (TypeError, ValueError):
                    continue
                if abs(handicap - line_val) < 0.01 and (best is None or odd > best):
                    best = odd
        return best

    if mtype == "btts":
        want_yes = direction in ("yes", "sim")
        for m in odds_markets:
            name = (m.get("name") or "").lower()
            if "both teams to score" not in name or "half" in name:
                continue
            for v in m.get("values", []):
                if v.get("suspended"):
                    continue
                if ((v.get("value") or "").lower() == "yes") == want_yes:
                    try:
                        return float(v["odd"])
                    except (TypeError, ValueError):
                        continue
        return None

    if mtype == "double_chance":
        l = (line or "").lower().replace(" ", "")
        if "home/draw" in l or "draw/home" in l or "casaempate" in l:
            wants = "home or draw"
        elif "draw/away" in l or "away/draw" in l or "empatevisitante" in l:
            wants = "away or draw"
        elif "home/away" in l or "away/home" in l or "casavisitante" in l:
            wants = "home or away"
        else:
            return None
        for m in odds_markets:
            if (m.get("name") or "").lower() != "double chance":
                continue
            for v in m.get("values", []):
                if v.get("suspended"):
                    continue
                if (v.get("value") or "").lower() == wants:
                    try:
                        return float(v["odd"])
                    except (TypeError, ValueError):
                        continue
        return None

    if mtype in ("result_1x2", "outcome"):
        l = (line or "").lower().strip()
        wants = {"1": "home", "casa": "home", "home": "home", "mandante": "home",
                 "x": "draw", "empate": "draw", "draw": "draw",
                 "2": "away", "visitante": "away", "away": "away", "fora": "away"}.get(l)
        if not wants:
            return None
        for m in odds_markets:
            if (m.get("name") or "").lower() not in ("fulltime result", "match winner"):
                continue
            for v in m.get("values", []):
                if v.get("suspended"):
                    continue
                if (v.get("value") or "").lower() == wants:
                    try:
                        return float(v["odd"])
                    except (TypeError, ValueError):
                        continue
        return None

    return None


def _parse_stats(raw: list) -> tuple[dict, dict]:
    home, away = {}, {}
    for i, team in enumerate(raw):
        d = {}
        for s in team.get("statistics", []):
            val = s.get("value")
            try:
                val = int(val) if val is not None else 0
            except Exception:
                val = 0
            d[s["type"]] = val
        if i == 0:
            home = d
        else:
            away = d
    return home, away


def _extract_line(line_str: str | None) -> tuple[str | None, float | None]:
    """Returns (direction, numeric_value). direction: 'over'|'under'|'result'|raw."""
    if not line_str:
        return None, None
    l = line_str.strip().lower()
    for prefix in ("over ", "mais de "):
        if l.startswith(prefix):
            try:
                return "over", float(l[len(prefix):].replace(",", "."))
            except Exception:
                pass
    for prefix in ("under ", "menos de "):
        if l.startswith(prefix):
            try:
                return "under", float(l[len(prefix):].replace(",", "."))
            except Exception:
                pass
    return l, None


def _stat_for_market(market: str, line: str, home_stats: dict, away_stats: dict,
                     home_goals: int, away_goals: int,
                     market_type: str | None = None) -> tuple[float | None, str, str | None]:
    """Returns (current_value, stat_label, direction_for_bar).

    market_type (from DB column) takes priority over keyword matching so that
    picks created with structured market data resolve to the correct stat even
    when the free-text market name is ambiguous or in a different language.
    """
    m     = (market or "").lower()
    mtype = (market_type or "").lower()
    direction, _ = _extract_line(line)

    # mtype == "result" só conta como resultado quando a direção não é over/under,
    # porque Over X.Y e Under X.Y nunca são mercados de resultado (1x2/dupla chance).
    # Isso protege contra market_type mal classificado no banco.
    _mtype_is_result = mtype == "result" and direction not in ("over", "under")

    # Dispatch determinístico: market_type do banco + fallback em keywords do texto
    is_corners = mtype == "corners" or any(k in m for k in ["escanteio", "corner"])
    is_cards   = mtype == "cards"   or any(k in m for k in ["cart", "card"])
    is_fouls   = any(k in m for k in ["falta", "foul"])
    is_saves   = any(k in m for k in ["defesa", "save", "goleiro"])
    # "shots" (chutes totais, ~20-25/jogo) e "shots_on_target" (chutes NO
    # ALVO, ~8-10/jogo) sao familias DIFERENTES -- mesmo gap ja documentado
    # em pick_engine/stats_model.py, achado aqui com dado real de producao:
    # "Total ShotOnGoal" (chutes no alvo) sendo somado como Shots on Goal +
    # Shots off Goal (= chutes totais), estourando a linha Under e dando
    # RED errado (pick #114, fixture 1520774: 4 chutes no alvo vs 13
    # chutes totais numa linha Under 9.5).
    m_nospace = m.replace(" ", "")
    is_shots_on_target = mtype == "shots_on_target" or any(
        k in m_nospace for k in ["shotontarget", "shotongoal", "shotsontarget"]
    ) or any(k in m for k in ["chute no alvo", "chute a gol", "finalizacao no alvo", "finalização no alvo"])
    is_shots = not is_shots_on_target and (
        mtype == "shots" or any(k in m for k in ["chute", "shot", "finaliza"])
    )
    # "impediment" tambem casa com "impedimento"/"impedimentos" (PT) --
    # mesma lista usada em services/ai_result_checker_service.py, achado
    # como gap real validando os resultados de hoje: o motor ja sugere
    # esse mercado, mas nada aqui sabia resolver o status ao vivo.
    is_offsides = any(k in m for k in ["impediment", "offside"])
    is_btts    = mtype == "btts"    or any(k in m for k in ["ambas", "btts", "ambos"])
    is_goals   = mtype == "goals"   or any(k in m for k in ["gol", "goal"])
    is_result  = _mtype_is_result   or direction == "result" or \
                 any(k in m for k in ["resultado", "dupla chance", "1x2", "vencedor"])

    # ── Corners ──
    if is_corners:
        hc = home_stats.get("Corner Kicks", 0)
        ac = away_stats.get("Corner Kicks", 0)
        if "casa" in m or "home" in m:
            return float(hc), "Escanteios Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(ac), "Escanteios Fora", direction
        return float(hc + ac), "Escanteios", direction

    # ── Cards ──
    if is_cards:
        hy = home_stats.get("Yellow Cards", 0)
        hr = home_stats.get("Red Cards", 0)
        ay = away_stats.get("Yellow Cards", 0)
        ar = away_stats.get("Red Cards", 0)
        if "casa" in m or "home" in m:
            return float(hy + hr), "Cartões Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(ay + ar), "Cartões Fora", direction
        return float(hy + hr + ay + ar), "Cartões", direction

    # ── Fouls ──
    if is_fouls:
        hf = home_stats.get("Fouls", 0)
        af = away_stats.get("Fouls", 0)
        return float(hf + af), "Faltas", direction

    # ── Saves ──
    if is_saves:
        hs = home_stats.get("Goalkeeper Saves", 0)
        as_ = away_stats.get("Goalkeeper Saves", 0)
        return float(hs + as_), "Defesas do Goleiro", direction

    # ── Shots on Goal (chutes NO ALVO) ──
    if is_shots_on_target:
        hs = home_stats.get("Shots on Goal", 0)
        as_ = away_stats.get("Shots on Goal", 0)
        if "casa" in m or "home" in m:
            return float(hs), "Chutes no Alvo Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(as_), "Chutes no Alvo Fora", direction
        return float(hs + as_), "Chutes no Alvo", direction

    # ── Shots (chutes totais) ──
    if is_shots:
        hs = home_stats.get("Total Shots", 0)
        as_ = away_stats.get("Total Shots", 0)
        if "casa" in m or "home" in m:
            return float(hs), "Chutes Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(as_), "Chutes Fora", direction
        return float(hs + as_), "Chutes", direction

    # ── Offsides ──
    if is_offsides:
        ho = home_stats.get("Offsides", 0)
        ao = away_stats.get("Offsides", 0)
        if "casa" in m or "home" in m:
            return float(ho), "Impedimentos Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(ao), "Impedimentos Fora", direction
        return float(ho + ao), "Impedimentos", direction

    # ── BTTS ──
    if is_btts:
        both = int(home_goals or 0) > 0 and int(away_goals or 0) > 0
        return (1.0 if both else 0.0), "Ambas Marcam", None

    # ── Goals ──
    if is_goals:
        if "casa" in m or "home" in m:
            return float(home_goals or 0), "Gols Casa", direction
        if any(k in m for k in ["fora", "away", "visitante"]):
            return float(away_goals or 0), "Gols Fora", direction
        return float((home_goals or 0) + (away_goals or 0)), "Gols", direction

    # ── Correct Score / Placar Exato ──
    if mtype == "correct_score" or "placar exato" in m:
        return None, "Placar Exato", "correct_score"

    # ── Result / Dupla Chance ──
    if is_result:
        return None, "Placar", "result"

    return None, market or "", direction


def _pick_status(current: float | None, line_str: str | None,
                 home_goals: int = 0, away_goals: int = 0,
                 home_team: str | None = None, away_team: str | None = None) -> str:
    if current is None:
        return "neutral"
    direction, line_val = _extract_line(line_str)
    if direction == "over" and line_val is not None:
        return "winning" if current > line_val else "losing"
    if direction == "under" and line_val is not None:
        return "winning" if current < line_val else "losing"
    if direction == "result":
        return _result_pick_status(line_str or "", home_goals, away_goals, home_team, away_team)
    # BTTS: line é "yes"/"sim" ou "no"/"não" · current=1.0 → ambas marcaram
    if direction in ("yes", "sim"):
        return "winning" if current >= 1.0 else "losing"
    if direction in ("no", "não", "nao"):
        return "winning" if current < 1.0 else "losing"
    return "neutral"


def _result_pick_status(line_str: str, home_goals: int, away_goals: int,
                        home_team: str | None = None, away_team: str | None = None) -> str:
    """Determina se um pick de resultado (1x2/dupla chance) está ganhando ou perdendo.

    Aceita linhas em vários formatos: "1"/"2"/"x", "home"/"away"/"draw",
    nome literal do time (ex: "Fortaleza EC") ou dupla chance combinando
    qualquer um desses formatos com o time/empate.
    """
    hg, ag = int(home_goals or 0), int(away_goals or 0)
    cur = "1" if hg > ag else "2" if ag > hg else "x"
    l   = line_str.lower().strip()

    home_n = (home_team or "").lower().strip()
    away_n = (away_team or "").lower().strip()

    _TOKEN_MAP = {
        "1": "1", "home": "1", "casa": "1",
        "2": "2", "away": "2", "fora": "2", "visitante": "2",
        "x": "x", "draw": "x", "empate": "x",
    }
    if home_n and l == home_n:
        l = "1"
    elif away_n and l == away_n:
        l = "2"
    elif l in _TOKEN_MAP:
        l = _TOKEN_MAP[l]

    if l in ("1", "2", "x"):
        return "winning" if cur == l else "losing"
    if l in ("1 ou x", "1 ou empate", "home ou draw", "casa ou empate"):
        return "winning" if cur in ("1", "x") else "losing"
    if l in ("x ou 2", "empate ou 2", "draw ou away", "empate ou fora"):
        return "winning" if cur in ("x", "2") else "losing"
    if l in ("1 ou 2", "home ou away", "casa ou fora"):
        return "winning" if cur in ("1", "2") else "losing"
    # Formato cru da API-Football pro mercado Double Chance ("Home/Draw",
    # "Draw/Away", "Home/Away") -- e' o formato que o motor deterministico
    # grava direto (services/ai_result_checker_service.py tinha o mesmo gap,
    # corrigido antes; faltava aqui tambem, achado validando os resultados
    # de hoje -- sem isso o pick ficava "neutral" a partida toda e nunca
    # resolvia sozinho ao vivo).
    l_slash = l.replace(" ", "")
    if l_slash in ("home/draw", "draw/home"):
        return "winning" if cur in ("1", "x") else "losing"
    if l_slash in ("draw/away", "away/draw"):
        return "winning" if cur in ("x", "2") else "losing"
    if l_slash in ("home/away", "away/home"):
        return "winning" if cur in ("1", "2") else "losing"
    # Dupla chance escrita com nome do time, ex: "Fortaleza EC ou Empate"
    if home_n and "empate" in l and home_n in l:
        return "winning" if cur in ("1", "x") else "losing"
    if away_n and "empate" in l and away_n in l:
        return "winning" if cur in ("2", "x") else "losing"
    if home_n and away_n and home_n in l and away_n in l:
        return "winning" if cur in ("1", "2") else "losing"
    return "neutral"


def _correct_score_pick_status(line_str: str, home_goals: int, away_goals: int) -> str:
    """Status ao vivo do placar exato · verifica se o placar atual bate com o previsto."""
    try:
        parts = line_str.strip().replace("-", ":").split(":")
        ph, pa = int(parts[0]), int(parts[1])
    except Exception:
        return "neutral"
    hg, ag = int(home_goals or 0), int(away_goals or 0)
    return "winning" if (hg == ph and ag == pa) else "losing"


def _calc_result(market: str, line: str, cur_val: float | None,
                 home_goals: int, away_goals: int,
                 market_type: str | None = None,
                 home_team: str | None = None, away_team: str | None = None) -> str | None:
    """Resultado definitivo de um pick com jogo encerrado.

    Suporta handicap asiático quarter-ball (.25 / .75):
      Over X.25: GREEN se cur>X, HALF-LOSS se cur==X, RED se cur<X
      Over X.75: GREEN se cur>X+1, HALF-WIN se cur==X+1, RED se cur<=X
      Under X.25: GREEN se cur<X, HALF-WIN se cur==X, RED se cur>X
      Under X.75: GREEN se cur<=X, HALF-LOSS se cur==X+1, RED se cur>X+1
    Linhas inteiras (.0): PUSH quando cur==line.
    Linhas em .5: nunca PUSH (stats são inteiros).
    market_type do banco tem prioridade sobre keyword matching.
    """
    m     = (market or "").lower()
    mtype = (market_type or "").lower()

    direction, line_val = _extract_line(line)

    _mtype_is_result = mtype == "result" and direction not in ("over", "under")

    is_result = _mtype_is_result or direction == "result" or \
                any(k in m for k in ["resultado", "dupla chance", "1x2", "vencedor"])
    is_btts   = mtype == "btts"  or any(k in m for k in ["ambas", "btts", "ambos"])

    # ── Placar Exato · compara placar real com previsto (ex: "3:0") ───────────
    if mtype == "correct_score" or "placar exato" in m:
        try:
            parts = (line or "").strip().replace("-", ":").split(":")
            ph, pa = int(parts[0]), int(parts[1])
        except Exception:
            return None
        hg, ag = int(home_goals or 0), int(away_goals or 0)
        return "GREEN" if (hg == ph and ag == pa) else "RED"

    # ── Resultado / 1x2 / Dupla Chance · não depende de cur_val ──────────────
    if is_result:
        pst = _result_pick_status(line, home_goals, away_goals, home_team, away_team)
        if pst == "winning":  return "GREEN"
        if pst == "losing":   return "RED"
        return None  # "neutral" = linha não reconhecida, não resolve

    # ── BTTS · usa cur_val (1.0 = ambas marcaram, 0.0 = não) ─────────────────
    if is_btts:
        if cur_val is None:
            return None
        both_scored = cur_val >= 1.0
        direction, _ = _extract_line(line)
        if direction in ("no", "não", "nao"):
            return "RED" if both_scored else "GREEN"
        return "GREEN" if both_scored else "RED"

    # ── Mercados estatísticos (gols, escanteios, cartões…) ────────────────────
    if cur_val is None:
        return None

    if direction in ("over", "under") and line_val is not None:
        frac = round(line_val % 1, 2)  # 0.0 | 0.25 | 0.5 | 0.75
        v    = int(cur_val)             # stats são sempre inteiros

        if direction == "over":
            if frac == 0.25:
                f = int(line_val)
                if v > f:   return "GREEN"
                if v == f:  return "HALF-LOSS"
                return "RED"
            elif frac == 0.75:
                c = int(line_val) + 1
                if v > c:   return "GREEN"
                if v == c:  return "HALF-WIN"
                return "RED"
            else:  # .0 ou .5
                if v > line_val:   return "GREEN"
                if v < line_val:   return "RED"
                return "PUSH"      # só possível em linhas .0

        else:  # under
            if frac == 0.25:
                f = int(line_val)
                if v < f:   return "GREEN"
                if v == f:  return "HALF-WIN"
                return "RED"
            elif frac == 0.75:
                c = int(line_val) + 1
                if v < c:   return "GREEN"
                if v == c:  return "HALF-LOSS"
                return "RED"
            else:
                if v < line_val:   return "GREEN"
                if v > line_val:   return "RED"
                return "PUSH"

    return None


def _locked_leg_result(leg: dict) -> str | None:
    """
    Retorna resultado definitivo de uma leg se já determinado, else None.
    FT  → resultado completo via _calc_result.
    Bloqueado antes do FT (over/under cujo valor já cruzou a linha) → RED ou GREEN antecipado.
    Linhas fracionárias (.25/.75): early-lock só quando o resultado final é inequivocamente GREEN.
    """
    if leg["is_ft"]:
        return _calc_result(
            leg["market"], leg["line"],
            leg["current_val"], leg["home_goals"], leg["away_goals"],
            market_type=leg.get("market_type"),
            home_team=leg.get("home_team"), away_team=leg.get("away_team"),
        )
    if leg.get("is_locked"):
        direction, line_val = _extract_line(leg["line"])
        cur = leg.get("current_val")
        if cur is not None and line_val is not None:
            frac = round(line_val % 1, 2)
            v    = int(cur)
            if direction == "under" and cur >= line_val:
                return "RED"    # Under X com cur >= X: impossível de recuperar
            if direction == "over":
                # Só trava como GREEN se o resultado final não pode ser HALF-WIN
                # .25: GREEN garantido quando v > floor  (v == floor → HALF-LOSS no FT)
                # .75: GREEN garantido apenas quando v > ceil (v == ceil → HALF-WIN no FT)
                # .0 / .5: GREEN garantido quando v > line_val
                if frac == 0.25 and v > int(line_val):   return "GREEN"
                if frac == 0.75 and v > int(line_val)+1: return "GREEN"
                if frac not in (0.25, 0.75) and cur > line_val: return "GREEN"
    return None


def _profit_for_result(result: str, odd: float) -> float:
    """Lucro por unidade apostada para cada tipo de resultado."""
    o = float(odd)
    if result == "GREEN":      return round(o - 1, 4)
    if result == "HALF-WIN":   return round((o - 1) / 2, 4)
    if result == "PUSH":       return 0.0
    if result == "HALF-LOSS":  return -0.5
    return -1.0  # RED


def _sync_followed_result(pick_id: int, pick_type: str, result: str, c) -> None:
    """Sincroniza resultado na user_followed_picks para todos que seguiram este pick."""
    c.execute(
        "UPDATE user_followed_picks SET result=%s WHERE pick_id=%s AND pick_type=%s",
        (result, pick_id, pick_type),
    )


def _save_single_result(pick_id: int, pick_type: str, result: str, odd: float, conn) -> None:
    profit = _profit_for_result(result, odd)
    tbl = "picks_vip" if pick_type == "vip" else "picks_free"
    c = conn.cursor()
    c.execute(f"UPDATE {tbl} SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, pick_type, result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] %s #%s → %s (%+.4fu)", pick_type, pick_id, result, profit)


def _multipla_combined_result(legs_results: list[str | None]) -> str | None:
    """Resultado combinado de uma múltipla: qualquer RED → RED, qualquer HALF → propaga."""
    if any(r is None for r in legs_results):
        return None  # nem todas as pernas encerradas
    if any(r == "RED" for r in legs_results):
        return "RED"
    if all(r == "GREEN" for r in legs_results):
        return "GREEN"
    # mix de GREEN, PUSH, HALF-WIN, HALF-LOSS → PUSH
    return "PUSH"


def _save_multipla_result(pick_id: int, legs_results: list[str | None],
                          total_odd: float, conn) -> None:
    result = _multipla_combined_result(legs_results)
    if result is None:
        return
    profit = _profit_for_result(result, total_odd)
    c = conn.cursor()
    c.execute("UPDATE picks_multiplas SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, "multipla", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] multipla #%s → %s (%+.4fu)", pick_id, result, profit)


def _save_alavancagem_result(pick_id: int, legs_results: list[str | None],
                             odd_combined: float, conn) -> None:
    result = _multipla_combined_result(legs_results)
    if result is None:
        return
    profit = _profit_for_result(result, odd_combined)
    c = conn.cursor()
    c.execute("UPDATE picks_alavancagem SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, "alavancagem", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] alavancagem #%s → %s (%+.2fu)", pick_id, result, profit)


def _save_bingo_result(pick_id: int, game_results: list[str | None],
                       odd_final: float, conn) -> None:
    """Resultado combinado do bingo a partir do resultado JA combinado de cada
    jogo (um por game_results, ver combine-por-jogo em get_live_my_picks/
    resolve_all_pending -- cada jogo em si ja e' um _multipla_combined_result
    das suas proprias pernas antes de chegar aqui)."""
    result = _multipla_combined_result(game_results)
    if result is None:
        return
    profit = _profit_for_result(result, odd_final)
    c = conn.cursor()
    c.execute("UPDATE picks_bingo SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, "bingo", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] bingo #%s → %s (%+.4fu)", pick_id, result, profit)


def _enrich_leg(fid: int, market: str, line: str,
                home_team: str, away_team: str,
                home_team_id: int | None, away_team_id: int | None,
                odd: float,
                market_type: str | None = None) -> dict:
    fix_data   = _fetch_fixture(fid)
    fix        = fix_data.get("fixture", {})
    goals      = fix_data.get("goals", {})
    league_id  = fix_data.get("league", {}).get("id")
    status     = fix.get("status", {}).get("short", "NS")
    elapsed    = fix.get("status", {}).get("elapsed")
    home_goals = int(goals.get("home") or 0)
    away_goals = int(goals.get("away") or 0)

    home_stats, away_stats = {}, {}
    if status in LIVE_STATUSES or status in FT_STATUSES:
        home_stats, away_stats = _parse_stats(_fetch_stats(fid, status))

    cur_val, stat_label, direction = _stat_for_market(
        market, line, home_stats, away_stats, home_goals, away_goals, market_type
    )
    _, line_val = _extract_line(line)
    pst = _pick_status(cur_val, line, home_goals, away_goals, home_team, away_team) if cur_val is not None \
          else _result_pick_status(line, home_goals, away_goals, home_team, away_team) if direction == "result" \
          else _correct_score_pick_status(line, home_goals, away_goals) if direction == "correct_score" \
          else "neutral"

    # Locked: resultado já determinado e irreversível
    is_ft     = status in FT_STATUSES
    is_locked = is_ft
    if not is_ft and cur_val is not None:
        # BTTS: uma vez que ambas marcaram (cur_val=1) não tem como voltar
        is_btts_market = "btts" in (market_type or "").lower() or \
                         any(k in (market or "").lower() for k in ("ambas", "btts"))
        if is_btts_market and cur_val >= 1.0:
            is_locked = True
        elif line_val is not None:
            frac_lv = round(line_val % 1, 2)
            v_int   = int(cur_val)
            if direction == "under" and cur_val >= line_val:
                is_locked = True   # já estourou: impossível de recuperar
            if direction == "over":
                if frac_lv == 0.25 and v_int > int(line_val):   is_locked = True
                elif frac_lv == 0.75 and v_int > int(line_val): is_locked = True
                elif frac_lv not in (0.25, 0.75) and cur_val > line_val: is_locked = True

    return {
        "fixture_id":   fid,
        "league_id":    league_id,
        "home_team":    home_team,
        "away_team":    away_team,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "market":       market,
        "market_type":  market_type,
        "line":         line,
        "odd":          odd,
        "status":       status,
        "elapsed":      elapsed,
        "home_goals":   home_goals,
        "away_goals":   away_goals,
        "stat_label":   stat_label,
        "current_val":  cur_val,
        "line_val":     line_val,
        "pick_status":  pst,
        "is_live":      status in LIVE_STATUSES,
        "is_ft":        is_ft,
        "is_locked":    is_locked,
    }


@router.get("/fixture/{fixture_id}/live-stats")
def get_fixture_live_stats(fixture_id: int, current_user: dict = Depends(get_current_user)):
    """Retorna estatísticas ao vivo de um jogo (escanteios, chutes, cartões, posse)."""
    data = _fetch_fixture(fixture_id)
    if not data:
        return {}
    fx     = data.get("fixture", {})
    status = fx.get("status", {}).get("short", "NS")
    goals  = data.get("goals", {})

    stats_raw = _fetch_stats(fixture_id, status)
    home_s, away_s = {}, {}
    for i, team in enumerate(stats_raw):
        d: dict = {}
        for s in team.get("statistics", []):
            key = s["type"]
            val = s.get("value")
            if val is None:
                d[key] = 0
            elif isinstance(val, str) and val.endswith("%"):
                try:
                    d[key] = int(val.rstrip("%"))
                except Exception:
                    d[key] = 0
            else:
                try:
                    d[key] = int(val)
                except Exception:
                    d[key] = 0
        if i == 0:
            home_s = d
        else:
            away_s = d

    return {
        "status":           status,
        "elapsed":          fx.get("status", {}).get("elapsed"),
        "home_goals":       goals.get("home"),
        "away_goals":       goals.get("away"),
        "home_corners":     home_s.get("Corner Kicks", 0),
        "away_corners":     away_s.get("Corner Kicks", 0),
        "home_shots_on":    home_s.get("Shots on Goal", 0),
        "away_shots_on":    away_s.get("Shots on Goal", 0),
        "home_yellow":      home_s.get("Yellow Cards", 0),
        "away_yellow":      away_s.get("Yellow Cards", 0),
        "home_possession":  home_s.get("Ball Possession", 0),
        "away_possession":  away_s.get("Ball Possession", 0),
    }


@router.get("/pick-odd")
def get_current_pick_odd(fixture_id: int, market_type: str = "", line: str = "",
                         current_user: dict = Depends(get_current_user)):
    """Odd atual do mercado, buscada na API-Football no momento da consulta
    -- chamado quando o usuário abre o modal de aposta. Jogo ainda não
    começado (NS/TBD): devolve odd=None (sem mudança, front usa a odd já
    salva no pick, igual sempre funcionou). Jogo ao vivo: busca /odds/live
    e tenta achar a linha equivalente (best-effort, ver _find_live_odd) --
    se não achar correspondência, também devolve None, nunca erro."""
    fix_data = _fetch_fixture(fixture_id)
    status = fix_data.get("fixture", {}).get("status", {}).get("short", "NS")
    if status not in LIVE_STATUSES:
        return {"odd": None, "is_live": False, "status": status}
    odds_markets = _fetch_live_odds(fixture_id)
    odd = _find_live_odd(market_type, line, odds_markets)
    return {"odd": odd, "is_live": True, "status": status}


@router.get("/my-picks")
def get_live_my_picks(current_user: dict = Depends(get_current_user)):
    user_id  = current_user["id"]
    today_br = datetime.now(_BR_TZ).date()
    conn    = get_connection()
    cur     = conn.cursor()

    cur.execute("""
        SELECT pick_id, pick_type, stake_units, cashout_amount, actual_odd, bet_house
        FROM user_followed_picks
        WHERE user_id = %s
    """, (user_id,))
    followed = cur.fetchall()

    if not followed:
        cur.close()
        conn.close()
        return []

    # Group pick_ids by type for batch queries
    vip_ids         = [r["pick_id"] for r in followed if r["pick_type"] == "vip"]
    free_ids        = [r["pick_id"] for r in followed if r["pick_type"] == "free"]
    multipla_ids    = [r["pick_id"] for r in followed if r["pick_type"] == "multipla"]
    alavancagem_ids = [r["pick_id"] for r in followed if r["pick_type"] == "alavancagem"]
    bingo_ids       = [r["pick_id"] for r in followed if r["pick_type"] == "bingo"]

    # ── Batch fetch all pick data ────────────────────────────────────────────
    vip_map: dict = {}
    if vip_ids:
        cur.execute("""
            SELECT id, fixture_id, market, market_type, line, odd, result,
                   home_team_name AS home_team, away_team_name AS away_team,
                   home_team_id, away_team_id, match_date, NULL::integer AS league_id
            FROM picks_vip WHERE id = ANY(%s)
        """, (vip_ids,))
        vip_map = {r["id"]: r for r in cur.fetchall()}

    free_map: dict = {}
    if free_ids:
        cur.execute("""
            SELECT id, fixture_id, market, market_type, line, odd, result,
                   home_team, away_team, home_team_id, away_team_id, match_date, league_id
            FROM picks_free WHERE id = ANY(%s)
        """, (free_ids,))
        free_map = {r["id"]: r for r in cur.fetchall()}

    multipla_map: dict = {}
    if multipla_ids:
        cur.execute("""
            SELECT id, games, total_odd, result, match_date
            FROM picks_multiplas WHERE id = ANY(%s)
        """, (multipla_ids,))
        multipla_map = {r["id"]: r for r in cur.fetchall()}

    alavancagem_map: dict = {}
    if alavancagem_ids:
        cur.execute("""
            SELECT id, fixture_id_1, fixture_id_2,
                   market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
                   market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
                   odd_combined, result, match_date
            FROM picks_alavancagem WHERE id = ANY(%s)
        """, (alavancagem_ids,))
        alavancagem_map = {r["id"]: r for r in cur.fetchall()}

    bingo_map: dict = {}
    if bingo_ids:
        cur.execute("""
            SELECT id, games, odd_final, result, match_date
            FROM picks_bingo WHERE id = ANY(%s)
        """, (bingo_ids,))
        bingo_map = {r["id"]: r for r in cur.fetchall()}

    # Batch fixture lookups for alavancagem team_ids
    alav_fixture_ids = set()
    for p in alavancagem_map.values():
        if p["fixture_id_1"]: alav_fixture_ids.add(p["fixture_id_1"])
        if p["fixture_id_2"]: alav_fixture_ids.add(p["fixture_id_2"])

    alav_fixture_map: dict = {}
    if alav_fixture_ids:
        cur.execute(
            "SELECT fixture_id, home_team_id, away_team_id FROM fixtures WHERE fixture_id = ANY(%s)",
            (list(alav_fixture_ids),),
        )
        alav_fixture_map = {r["fixture_id"]: r for r in cur.fetchall()}

    # Batch fixture lookups for multipla legs (nomes ou IDs faltando)
    multipla_fixture_ids: set = set()
    multipla_stats_ids: set = set()
    for p in multipla_map.values():
        legs_raw = p["games"]
        if isinstance(legs_raw, str):
            try: legs_raw = json.loads(legs_raw)
            except Exception: legs_raw = []
        for leg_data in (legs_raw if isinstance(legs_raw, list) else []):
            fid = leg_data.get("fixture_id")
            if not fid:
                continue
            home = leg_data.get("home") or leg_data.get("home_team") or ""
            away = leg_data.get("away") or leg_data.get("away_team") or ""
            h_id = leg_data.get("home_team_id")
            a_id = leg_data.get("away_team_id")
            if not home or not away:
                multipla_fixture_ids.add(fid)
            if not h_id or not a_id:
                multipla_stats_ids.add(fid)  # busca IDs no match_statistics como fallback

    multipla_fixture_map: dict = {}
    if multipla_fixture_ids:
        cur.execute(
            "SELECT fixture_id, home_team, away_team, home_team_id, away_team_id FROM fixtures WHERE fixture_id = ANY(%s)",
            (list(multipla_fixture_ids),),
        )
        multipla_fixture_map = {r["fixture_id"]: r for r in cur.fetchall()}

    # Fallback: busca IDs dos times em match_statistics (jogos já finalizados saem de fixtures)
    multipla_stats_map: dict = {}
    if multipla_stats_ids:
        cur.execute(
            "SELECT DISTINCT ON (fixture_id) fixture_id, home_team_id, away_team_id FROM match_statistics WHERE fixture_id = ANY(%s)",
            (list(multipla_stats_ids),),
        )
        multipla_stats_map = {r["fixture_id"]: r for r in cur.fetchall()}

    # Batch fixture lookups para os jogos do bingo (mesmo padrao da multipla,
    # mas games[].legs[] tem um nivel de aninhamento a mais -- o fixture_id/
    # nomes/ids vivem no JOGO, nao em cada perna individual)
    bingo_fixture_ids: set = set()
    bingo_stats_ids: set = set()
    for p in bingo_map.values():
        games_raw = p["games"]
        if isinstance(games_raw, str):
            try: games_raw = json.loads(games_raw)
            except Exception: games_raw = []
        for g in (games_raw if isinstance(games_raw, list) else []):
            fid = g.get("fixture_id")
            if not fid:
                continue
            if not g.get("home_team") or not g.get("away_team"):
                bingo_fixture_ids.add(fid)
            if not g.get("home_team_id") or not g.get("away_team_id"):
                bingo_stats_ids.add(fid)

    bingo_fixture_map: dict = {}
    if bingo_fixture_ids:
        cur.execute(
            "SELECT fixture_id, home_team, away_team, home_team_id, away_team_id FROM fixtures WHERE fixture_id = ANY(%s)",
            (list(bingo_fixture_ids),),
        )
        bingo_fixture_map = {r["fixture_id"]: r for r in cur.fetchall()}

    bingo_stats_map: dict = {}
    if bingo_stats_ids:
        cur.execute(
            "SELECT DISTINCT ON (fixture_id) fixture_id, home_team_id, away_team_id FROM match_statistics WHERE fixture_id = ANY(%s)",
            (list(bingo_stats_ids),),
        )
        bingo_stats_map = {r["fixture_id"]: r for r in cur.fetchall()}

    cur.close()

    result = []

    for row in followed:
        pick_id      = row["pick_id"]
        pick_type    = row["pick_type"]
        stake_u      = float(row["stake_units"])
        cashout_amt  = float(row["cashout_amount"]) if row.get("cashout_amount") is not None else None
        actual_odd   = float(row["actual_odd"]) if row.get("actual_odd") is not None else None
        bet_house    = row.get("bet_house")

        # ── VIP / FREE ──────────────────────────────────────────────────────
        if pick_type in ("vip", "free"):
            p = (vip_map if pick_type == "vip" else free_map).get(pick_id)
            if not p:
                continue
            is_today = (p["match_date"] == today_br)
            if p["result"] is not None and not is_today:
                continue

            odd = float(p["odd"] or 1)
            leg = _enrich_leg(
                p["fixture_id"], p["market"], p["line"],
                p["home_team"], p["away_team"],
                p["home_team_id"], p["away_team_id"],
                odd,
                market_type=p.get("market_type"),
            )

            final_result = p["result"]
            # Auto-save quando jogo encerrou OU resultado já irreversível (early lock)
            if final_result is None and (leg["is_ft"] or leg["is_locked"]):
                auto_res = _calc_result(
                    p["market"], p["line"],
                    leg["current_val"], leg["home_goals"], leg["away_goals"],
                    market_type=p.get("market_type"),
                    home_team=p["home_team"], away_team=p["away_team"],
                )
                if auto_res:
                    _save_single_result(pick_id, pick_type, auto_res, odd, conn)
                    final_result = auto_res
                    if not is_today:
                        continue

            result.append({
                "pick_id":        pick_id,
                "pick_type":      pick_type,
                "match_date":     str(p["match_date"]),
                "odd":            odd,
                "actual_odd":     actual_odd,
                "bet_house":      bet_house,
                "stake_units":    stake_u,
                "cashout_amount": cashout_amt,
                "is_live":        leg["is_live"],
                "league_id":      p.get("league_id"),
                "result":         final_result,
                **{k: leg[k] for k in (
                    "fixture_id", "home_team", "away_team",
                    "home_team_id", "away_team_id",
                    "market", "line", "status", "elapsed",
                    "home_goals", "away_goals",
                    "stat_label", "current_val", "line_val",
                    "pick_status", "is_locked",
                )},
            })

        # ── MÚLTIPLA ────────────────────────────────────────────────────────
        elif pick_type == "multipla":
            p = multipla_map.get(pick_id)
            if not p:
                continue
            is_today = (p["match_date"] == today_br)
            if p["result"] is not None and not is_today:
                continue

            legs_raw = p["games"]
            if isinstance(legs_raw, str):
                try: legs_raw = json.loads(legs_raw)
                except Exception: legs_raw = []

            legs_out = []
            for leg_data in (legs_raw if isinstance(legs_raw, list) else []):
                fid = leg_data.get("fixture_id")
                if not fid:
                    continue
                home = leg_data.get("home") or leg_data.get("home_team") or ""
                away = leg_data.get("away") or leg_data.get("away_team") or ""
                h_id = leg_data.get("home_team_id")
                a_id = leg_data.get("away_team_id")
                if not home or not away:
                    fx = multipla_fixture_map.get(fid)
                    if fx:
                        home = home or fx["home_team"] or ""
                        away = away or fx["away_team"] or ""
                        h_id = h_id or fx["home_team_id"]
                        a_id = a_id or fx["away_team_id"]
                # Fallback: IDs via match_statistics (jogos finalizados não estão em fixtures)
                if not h_id or not a_id:
                    ms = multipla_stats_map.get(fid)
                    if ms:
                        h_id = h_id or ms["home_team_id"]
                        a_id = a_id or ms["away_team_id"]
                legs_out.append(_enrich_leg(
                    fid,
                    leg_data.get("market", ""),
                    leg_data.get("line", ""),
                    home, away, h_id, a_id,
                    float(leg_data.get("odd", 1)),
                    market_type=leg_data.get("market_type"),
                ))

            if legs_out:
                total_odd    = float(p["total_odd"] or 1)
                final_result = p["result"]
                if final_result is None:
                    leg_results = [_locked_leg_result(l) for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        leg_results = ["RED"] * len(legs_out)
                    if all(r is not None for r in leg_results):
                        final_result = _multipla_combined_result(leg_results)
                        if final_result:
                            _save_multipla_result(pick_id, leg_results, total_odd, conn)
                            if not is_today:
                                continue

                result.append({
                    "pick_id":        pick_id,
                    "pick_type":      "multipla",
                    "match_date":     str(p["match_date"]),
                    "odd":            total_odd,
                    "actual_odd":     actual_odd,
                    "bet_house":      bet_house,
                    "stake_units":    stake_u,
                    "cashout_amount": cashout_amt,
                    "is_live":        any(l["is_live"] for l in legs_out),
                    "status":         "FT" if final_result else None,
                    "result":         final_result,
                    "legs":           legs_out,
                })

        # ── ALAVANCAGEM ─────────────────────────────────────────────────────
        elif pick_type == "alavancagem":
            p = alavancagem_map.get(pick_id)
            if not p:
                continue
            is_today = (p["match_date"] == today_br)
            if p["result"] is not None and not is_today:
                continue

            legs_out = []
            for i in (1, 2):
                fid = p.get(f"fixture_id_{i}")
                if not fid:
                    continue
                fx = alav_fixture_map.get(fid)
                legs_out.append(_enrich_leg(
                    fid,
                    p.get(f"market_{i}", ""),
                    p.get(f"line_{i}", ""),
                    p.get(f"home_team_{i}", ""),
                    p.get(f"away_team_{i}", ""),
                    fx["home_team_id"] if fx else None,
                    fx["away_team_id"] if fx else None,
                    float(p.get(f"odd_{i}") or 1),
                    market_type=p.get(f"market_type_{i}"),
                ))

            if legs_out:
                odd_combined = float(p["odd_combined"] or 1)
                final_result = p["result"]
                if final_result is None:
                    leg_results = [_locked_leg_result(l) for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        leg_results = ["RED"] * len(legs_out)
                    if all(r is not None for r in leg_results):
                        final_result = _multipla_combined_result(leg_results)
                        if final_result:
                            _save_alavancagem_result(pick_id, leg_results, odd_combined, conn)
                            if not is_today:
                                continue

                result.append({
                    "pick_id":        pick_id,
                    "pick_type":      "alavancagem",
                    "match_date":     str(p["match_date"]),
                    "odd":            odd_combined,
                    "actual_odd":     actual_odd,
                    "bet_house":      bet_house,
                    "stake_units":    stake_u,
                    "cashout_amount": cashout_amt,
                    "is_live":        any(l["is_live"] for l in legs_out),
                    "status":         "FT" if final_result else None,
                    "result":         final_result,
                    "legs":           legs_out,
                })

        # ── BINGO ───────────────────────────────────────────────────────────
        # games[].legs[] tem um nivel de aninhamento a mais que multipla (que e'
        # so uma lista plana de legs) -- cada jogo primeiro combina o resultado
        # das suas proprias pernas (sub-combo), so' depois os jogos entre si se
        # combinam pro resultado final do bilhete. Pernas achatadas numa lista
        # unica no final pro frontend reusar o mesmo card de múltipla/alavancagem.
        elif pick_type == "bingo":
            p = bingo_map.get(pick_id)
            if not p:
                continue
            is_today = (p["match_date"] == today_br)
            if p["result"] is not None and not is_today:
                continue

            games_raw = p["games"]
            if isinstance(games_raw, str):
                try: games_raw = json.loads(games_raw)
                except Exception: games_raw = []

            games_out = []
            for g in (games_raw if isinstance(games_raw, list) else []):
                fid = g.get("fixture_id")
                if not fid:
                    continue
                home = g.get("home_team") or ""
                away = g.get("away_team") or ""
                h_id = g.get("home_team_id")
                a_id = g.get("away_team_id")
                if not home or not away:
                    fx = bingo_fixture_map.get(fid)
                    if fx:
                        home = home or fx["home_team"] or ""
                        away = away or fx["away_team"] or ""
                        h_id = h_id or fx["home_team_id"]
                        a_id = a_id or fx["away_team_id"]
                if not h_id or not a_id:
                    ms = bingo_stats_map.get(fid)
                    if ms:
                        h_id = h_id or ms["home_team_id"]
                        a_id = a_id or ms["away_team_id"]

                legs_enriched = [
                    _enrich_leg(
                        fid,
                        leg_data.get("market", ""),
                        leg_data.get("line", ""),
                        home, away, h_id, a_id,
                        float(leg_data.get("odd", 1)),
                        market_type=leg_data.get("market_type"),
                    )
                    for leg_data in (g.get("legs") or [])
                ]
                if legs_enriched:
                    games_out.append(legs_enriched)

            if games_out:
                odd_final    = float(p["odd_final"] or 1)
                final_result = p["result"]
                if final_result is None:
                    game_results = []
                    for legs_enriched in games_out:
                        leg_results = [_locked_leg_result(l) for l in legs_enriched]
                        if any(r == "RED" for r in leg_results):
                            leg_results = ["RED"] * len(legs_enriched)
                        game_results.append(
                            _multipla_combined_result(leg_results) if all(r is not None for r in leg_results) else None
                        )
                    if any(r == "RED" for r in game_results):
                        game_results = ["RED"] * len(games_out)
                    if all(r is not None for r in game_results):
                        final_result = _multipla_combined_result(game_results)
                        if final_result:
                            _save_bingo_result(pick_id, game_results, odd_final, conn)
                            if not is_today:
                                continue

                flat_legs = [leg for legs_enriched in games_out for leg in legs_enriched]

                result.append({
                    "pick_id":        pick_id,
                    "pick_type":      "bingo",
                    "match_date":     str(p["match_date"]),
                    "odd":            odd_final,
                    "actual_odd":     actual_odd,
                    "bet_house":      bet_house,
                    "stake_units":    stake_u,
                    "cashout_amount": cashout_amt,
                    "is_live":        any(l["is_live"] for l in flat_legs),
                    "status":         "FT" if final_result else None,
                    "result":         final_result,
                    "legs":           flat_legs,
                })

    conn.close()

    # Live picks first, then by date
    result.sort(key=lambda x: (0 if x.get("is_live") else 1, x.get("match_date", "")))
    return result


# ─── Job de background ───────────────────────────────────────────────────────

def resolve_all_pending() -> dict:
    """
    Tenta resolver todos os picks pendentes usando dados ao vivo da API.
    Chamado pelo APScheduler a cada 5 min. Retorna contagem de resolvidos por tipo.
    """
    conn = get_connection()
    cur  = conn.cursor()
    resolved: dict = {"vip": 0, "free": 0, "multipla": 0, "alavancagem": 0, "bingo": 0}

    try:
        # ── VIP ──────────────────────────────────────────────────────────────
        try:
            cur.execute("""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team_name AS home_team, away_team_name AS away_team,
                       home_team_id, away_team_id
                FROM picks_vip WHERE result IS NULL AND fixture_id IS NOT NULL
            """)
            for p in cur.fetchall():
                try:
                    odd = float(p["odd"] or 1)
                    leg = _enrich_leg(p["fixture_id"], p["market"], p["line"],
                                      p["home_team"], p["away_team"],
                                      p["home_team_id"], p["away_team_id"], odd,
                                      market_type=p.get("market_type"))
                    if leg["is_ft"] or leg["is_locked"]:
                        res = _calc_result(p["market"], p["line"],
                                           leg["current_val"], leg["home_goals"], leg["away_goals"],
                                           market_type=p.get("market_type"),
                                           home_team=p["home_team"], away_team=p["away_team"])
                        if res:
                            _save_single_result(p["id"], "vip", res, odd, conn)
                            resolved["vip"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] vip #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] vip query erro: %s", e)

        # ── FREE ─────────────────────────────────────────────────────────────
        try:
            cur.execute("""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team, away_team, home_team_id, away_team_id
                FROM picks_free WHERE result IS NULL AND fixture_id IS NOT NULL
            """)
            for p in cur.fetchall():
                try:
                    odd = float(p["odd"] or 1)
                    leg = _enrich_leg(p["fixture_id"], p["market"], p["line"],
                                      p["home_team"], p["away_team"],
                                      p["home_team_id"], p["away_team_id"], odd,
                                      market_type=p.get("market_type"))
                    if leg["is_ft"] or leg["is_locked"]:
                        res = _calc_result(p["market"], p["line"],
                                           leg["current_val"], leg["home_goals"], leg["away_goals"],
                                           market_type=p.get("market_type"),
                                           home_team=p["home_team"], away_team=p["away_team"])
                        if res:
                            _save_single_result(p["id"], "free", res, odd, conn)
                            resolved["free"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] free #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] free query erro: %s", e)

        # ── MÚLTIPLA ─────────────────────────────────────────────────────────
        try:
            cur.execute("SELECT id, games, total_odd FROM picks_multiplas WHERE result IS NULL")
            for p in cur.fetchall():
                try:
                    games = p["games"]
                    if isinstance(games, str):
                        try:    games = json.loads(games)
                        except: continue
                    if not isinstance(games, list) or not games:
                        continue

                    legs_out = []
                    for leg_data in games:
                        fid = leg_data.get("fixture_id")
                        if not fid:
                            continue
                        home = leg_data.get("home") or leg_data.get("home_team") or ""
                        away = leg_data.get("away") or leg_data.get("away_team") or ""
                        legs_out.append(_enrich_leg(
                            fid,
                            leg_data.get("market", ""),
                            leg_data.get("line", ""),
                            home, away,
                            leg_data.get("home_team_id"),
                            leg_data.get("away_team_id"),
                            float(leg_data.get("odd", 1)),
                            market_type=leg_data.get("market_type"),
                        ))

                    if not legs_out:
                        continue

                    total_odd   = float(p["total_odd"] or 1)
                    leg_results = [_locked_leg_result(l) for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        _save_multipla_result(p["id"], ["RED"] * len(legs_out), total_odd, conn)
                        resolved["multipla"] += 1
                    elif all(r is not None for r in leg_results):
                        _save_multipla_result(p["id"], leg_results, total_odd, conn)
                        resolved["multipla"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] multipla #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] multipla query erro: %s", e)

        # ── ALAVANCAGEM ──────────────────────────────────────────────────────
        try:
            cur.execute("""
                SELECT id, fixture_id_1, fixture_id_2,
                       market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
                       market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
                       odd_combined
                FROM picks_alavancagem WHERE result IS NULL
            """)
            for p in cur.fetchall():
                try:
                    legs_out = []
                    for i in (1, 2):
                        fid = p.get(f"fixture_id_{i}")
                        if not fid:
                            continue
                        c2 = conn.cursor()
                        try:
                            c2.execute(
                                "SELECT home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
                                (fid,),
                            )
                            fx = c2.fetchone()
                        finally:
                            c2.close()
                        legs_out.append(_enrich_leg(
                            fid,
                            p.get(f"market_{i}", ""),
                            p.get(f"line_{i}", ""),
                            p.get(f"home_team_{i}", "") or "",
                            p.get(f"away_team_{i}", "") or "",
                            fx["home_team_id"] if fx else None,
                            fx["away_team_id"] if fx else None,
                            float(p.get(f"odd_{i}") or 1),
                            market_type=p.get(f"market_type_{i}"),
                        ))

                    if not legs_out:
                        continue

                    odd_combined = float(p["odd_combined"] or 1)
                    leg_results  = [_locked_leg_result(l) for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        _save_alavancagem_result(p["id"], ["RED"] * len(legs_out), odd_combined, conn)
                        resolved["alavancagem"] += 1
                    elif all(r is not None for r in leg_results):
                        _save_alavancagem_result(p["id"], leg_results, odd_combined, conn)
                        resolved["alavancagem"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] alavancagem #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] alavancagem query erro: %s", e)

        # ── BINGO ────────────────────────────────────────────────────────────
        try:
            cur.execute("SELECT id, games, odd_final FROM picks_bingo WHERE result IS NULL")
            for p in cur.fetchall():
                try:
                    games = p["games"]
                    if isinstance(games, str):
                        try:    games = json.loads(games)
                        except: continue
                    if not isinstance(games, list) or not games:
                        continue

                    games_out = []
                    for g in games:
                        fid = g.get("fixture_id")
                        if not fid:
                            continue
                        home = g.get("home_team") or ""
                        away = g.get("away_team") or ""
                        legs_enriched = [
                            _enrich_leg(
                                fid,
                                leg_data.get("market", ""),
                                leg_data.get("line", ""),
                                home, away,
                                g.get("home_team_id"),
                                g.get("away_team_id"),
                                float(leg_data.get("odd", 1)),
                                market_type=leg_data.get("market_type"),
                            )
                            for leg_data in (g.get("legs") or [])
                        ]
                        if legs_enriched:
                            games_out.append(legs_enriched)

                    if not games_out:
                        continue

                    odd_final    = float(p["odd_final"] or 1)
                    game_results = []
                    for legs_enriched in games_out:
                        leg_results = [_locked_leg_result(l) for l in legs_enriched]
                        if any(r == "RED" for r in leg_results):
                            leg_results = ["RED"] * len(legs_enriched)
                        game_results.append(
                            _multipla_combined_result(leg_results) if all(r is not None for r in leg_results) else None
                        )

                    if any(r == "RED" for r in game_results):
                        _save_bingo_result(p["id"], ["RED"] * len(games_out), odd_final, conn)
                        resolved["bingo"] += 1
                    elif all(r is not None for r in game_results):
                        _save_bingo_result(p["id"], game_results, odd_final, conn)
                        resolved["bingo"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] bingo #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] bingo query erro: %s", e)

    finally:
        cur.close()
        conn.close()

    logger.info("[AUTO-RESULT] resolvidos: %s", resolved)
    return resolved
