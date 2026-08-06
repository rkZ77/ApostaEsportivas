import os
import re
import json
import time
import logging
import requests
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from database import get_connection
from auth_utils import get_current_user
from settlement_bridge import settlement

_BR_TZ = ZoneInfo("America/Sao_Paulo")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live"])

API_BASE      = "https://v3.football.api-sports.io"
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT"}
FT_STATUSES   = {"FT", "AET", "PEN"}

# TTL adaptativo: jogos ao vivo → curto; não iniciados → médio; encerrados → longo
# TTL_LIVE alinhado ao polling mais rápido do front (15s, ver LivePicks.tsx)
# pra maioria dos polls bater em cache em vez de sempre errar (era 10s < 15s de poll = miss garantido)
_TTL_LIVE = 20   # segundos · atualiza depressa durante o jogo
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


def _fetch_fixtures_bulk(fids: list[int]) -> None:
    """Pré-aquece o cache de fixtures em lote via /fixtures?ids=1-2-3 (até 20
    por chamada, limite da API-Football), reduzindo N chamadas individuais
    a ceil(N/20). Só busca fixtures com cache expirado/ausente; o que não
    vier na resposta em lote (erro, id inválido) cai no fallback individual
    de _fetch_fixture -- puramente aditivo, nunca piora o comportamento
    anterior."""
    now = time.time()
    stale = []
    for fid in fids:
        cached = _fix_cache.get(fid)
        if cached is None:
            stale.append(fid)
            continue
        ts, data = cached
        status = data.get("fixture", {}).get("status", {}).get("short", "NS")
        if now - ts >= _cache_ttl(status):
            stale.append(fid)
    if not stale:
        return
    for i in range(0, len(stale), 20):
        batch = stale[i:i + 20]
        try:
            r = requests.get(f"{API_BASE}/fixtures", headers=_headers(),
                             params={"ids": "-".join(str(f) for f in batch),
                                     "timezone": "America/Sao_Paulo"}, timeout=10)
            items = r.json().get("response", [])
        except Exception as e:
            logger.error("[LIVE] bulk fixtures %s: %s", batch, e)
            continue
        fetched_now = time.time()
        by_id = {item.get("fixture", {}).get("id"): item for item in items}
        for fid in batch:
            data = by_id.get(fid)
            if data is not None:
                _fix_cache[fid] = (fetched_now, data)


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


def _parse_stats(raw: list, home_id: int | None = None,
                 away_id: int | None = None) -> tuple[dict, dict]:
    """(stats casa, stats fora) da resposta de /fixtures/statistics.

    Duas correcoes em relacao a versao anterior, ambas de dado errado e nao
    de estilo:

    1. O lado sai do team.id, nao da POSICAO na lista. A API nao garante que
       o indice 0 seja o mandante (o coletor em lote sempre comparou o id --
       ver collectors/match_statistics_sync_service.py); aqui a ordem era
       assumida, entao todo mercado de UM lado (Escanteios Casa, Cartoes
       Visitante, handicap) podia ser liquidado com o numero do adversario.
       Sem os ids, cai na ordem da resposta como antes.

    2. Contador ausente ou null NAO vira 0. A chave simplesmente nao entra no
       dict, e quem le trata "chave ausente" como desconhecido. Era esse 0
       fabricado que gradeou o pick de escanteios do Fortaleza x Palmeiras
       como RED com o jogo tendo 10 escanteios.
    """
    parsed: list[dict] = []
    ids: list = []
    for team in raw:
        d: dict = {}
        for s in team.get("statistics", []):
            key = s.get("type")
            val = s.get("value")
            if key is None or val is None:
                continue  # nao publicado -> ausente, nunca zero
            if isinstance(val, str):
                val = val.replace("%", "").strip()
            try:
                d[key] = int(float(val))
            except (TypeError, ValueError):
                continue
        parsed.append(d)
        ids.append((team.get("team") or {}).get("id"))

    if not parsed:
        return {}, {}

    if home_id is not None and away_id is not None:
        by_id = {tid: d for tid, d in zip(ids, parsed) if tid is not None}
        if home_id in by_id and away_id in by_id:
            return by_id[home_id], by_id[away_id]

    home = parsed[0] if len(parsed) > 0 else {}
    away = parsed[1] if len(parsed) > 1 else {}
    return home, away


def _extract_line(line_str: str | None) -> tuple[str | None, float | None]:
    """Returns (direction, numeric_value). direction: 'over'|'under'|'result'|raw.

    Delega a leitura em services/settlement.py::parse_line -- mesma gramatica
    do job em lote. A versao anterior so' entendia a linha quando o texto
    COMECAVA com "over "/"under "/"mais de "/"menos de ": "Acima de 9.5" ou
    "Total Over 9.5" caiam no `return l, None`, sem numero, e o mercado
    seguia sem liquidar. O valor sai como float aqui so' porque e' o que o
    resto deste modulo (barra de progresso, JSON do front) consome; toda
    DECISAO de resultado usa o Decimal do settlement.
    """
    if not line_str:
        return None, None
    parsed = settlement.parse_line(line_str)
    value = float(parsed["value"]) if parsed["value"] is not None else None
    if parsed["op"] in ("over", "under"):
        return parsed["op"], value
    return line_str.strip().lower(), value


# Mercados que realmente leem home_stats/away_stats dentro de _stat_for_market
# (corners/cards/fouls/saves/shots/shots_on_target/offsides) -- mesmas
# keywords/market_types do dispatch abaixo. Usado só pra decidir se vale a
# pena chamar /fixtures/statistics; se ficar dessincronizado da lista de
# keywords abaixo o pior caso é uma chamada a mais (nunca um dado errado,
# pois quem calcula o valor continua sendo só _stat_for_market).
# handicap_corners/handicap_cards entram aqui tambem -- _calc_result precisa
# de home/away separados (nao so' o total que _stat_for_market devolveria)
# pra resolver o lado do handicap, ver _resolve_asian_handicap.
_STATS_MARKET_TYPES = {
    "corners", "cards", "fouls", "saves", "shots", "shots_on_target", "offsides",
    "handicap_corners", "handicap_cards",
}
_STATS_KEYWORDS = (
    "escanteio", "corner", "cart", "card", "falta", "foul",
    "defesa", "save", "goleiro",
    "chute", "shot", "finaliza",
    "impediment", "offside",
)


def _leg_needs_stats(market: str | None, market_type: str | None) -> bool:
    """market_type bate contra o set primeiro; keyword no texto do mercado e'
    sempre checado tambem (nao so' quando market_type esta vazio) -- pior
    caso de um falso positivo aqui e' uma chamada a API a mais, nunca dado
    errado (quem calcula o valor e' so' _stat_for_market/_calc_result)."""
    mtype = (market_type or "").lower()
    if mtype in _STATS_MARKET_TYPES:
        return True
    m = (market or "").lower()
    return any(k in m for k in _STATS_KEYWORDS)


# Cartao vermelho vale 2 pontos -- mesma convencao de
# services/pick_engine/stats_model.py::_cards_points e do checker em lote.
_STAT_WEIGHTS = {"Red Cards": 2}


def _stat_value(stats: dict, keys: tuple) -> float | None:
    """Soma dos contadores `keys` de um lado, ou None se qualquer um deles
    ainda nao foi publicado. Ausencia NUNCA e' somada como zero."""
    total = 0.0
    for key in keys:
        value = stats.get(key)
        if value is None:
            return None
        total += value * _STAT_WEIGHTS.get(key, 1)
    return total


def _stat_side(home_stats: dict, away_stats: dict, keys: tuple, side: str) -> float | None:
    home_val = _stat_value(home_stats, keys)
    away_val = _stat_value(away_stats, keys)
    if side == "home":
        return home_val
    if side == "away":
        return away_val
    if home_val is None or away_val is None:
        return None
    return home_val + away_val


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

    # ── Mercados que dependem da folha de estatistica ────────────────────────
    # Um so' caminho pras 6 familias, em vez de 6 blocos repetindo a mesma
    # forma. E, o principal: o valor vem de _stat_side(), que devolve None
    # quando o provedor ainda nao publicou aquele contador -- nenhum
    # `.get(chave, 0)` sobrou aqui. Ver services/settlement.py, invariante 1.
    _side = ("home" if ("casa" in m or "home" in m)
             else "away" if any(k in m for k in ["fora", "away", "visitante"])
             else "total")
    for flag, keys, labels in (
        (is_corners,         ("Corner Kicks",),                   ("Escanteios Casa", "Escanteios Fora", "Escanteios")),
        (is_cards,           ("Yellow Cards", "Red Cards"),       ("Cartões Casa", "Cartões Fora", "Cartões")),
        (is_fouls,           ("Fouls",),                          ("Faltas Casa", "Faltas Fora", "Faltas")),
        (is_saves,           ("Goalkeeper Saves",),               ("Defesas Casa", "Defesas Fora", "Defesas do Goleiro")),
        (is_shots_on_target, ("Shots on Goal",),                  ("Chutes no Alvo Casa", "Chutes no Alvo Fora", "Chutes no Alvo")),
        (is_shots,           ("Total Shots",),                    ("Chutes Casa", "Chutes Fora", "Chutes")),
        (is_offsides,        ("Offsides",),                       ("Impedimentos Casa", "Impedimentos Fora", "Impedimentos")),
    ):
        if not flag:
            continue
        label = labels[0] if _side == "home" else labels[1] if _side == "away" else labels[2]
        return _stat_side(home_stats, away_stats, keys, _side), label, direction

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
    """Se um pick de resultado (1x2/dupla chance) esta ganhando ou perdendo AGORA.

    So' traduz o veredito de services/settlement.py::settle_outcome pro
    vocabulario do ticker ao vivo. Manter uma tabela propria de formatos de
    linha aqui era o que fazia o "GREEN provisorio" mostrado durante o jogo
    divergir do resultado final gravado -- linha nao reconhecida vira
    "neutral" (indefinido), nunca "losing".
    """
    result, _factor = settlement.settle_outcome(
        home_goals, away_goals, line_str, home_team, away_team)
    if result == settlement.GREEN:
        return "winning"
    if result == settlement.RED:
        return "losing"
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


# _extract_handicap_side_value() e _resolve_asian_handicap() foram removidas:
# eram uma copia da matematica de handicap que ja existia no job em lote, e
# manter as duas em paralelo e' a origem das divergencias que esta auditoria
# encontrou. Quem faz isso agora e' services/settlement.py (parse_line +
# settle_asian_handicap), usado pelos dois caminhos.


def _calc_result(market: str, line: str, cur_val: float | None,
                 home_goals: int, away_goals: int,
                 market_type: str | None = None,
                 home_team: str | None = None, away_team: str | None = None,
                 home_stats: dict | None = None, away_stats: dict | None = None,
                 went_to_extra_time: bool = False) -> str | None:
    """Resultado definitivo de um pick com jogo encerrado.

    Suporta over/under com handicap asiático quarter-ball (.25 / .75):
      Over X.25: GREEN se cur>X, HALF-LOSS se cur==X, RED se cur<X
      Over X.75: GREEN se cur>X+1, HALF-WIN se cur==X+1, RED se cur<=X
      Under X.25: GREEN se cur<X, HALF-WIN se cur==X, RED se cur>X
      Under X.75: GREEN se cur<=X, HALF-LOSS se cur==X+1, RED se cur>X+1
    Linhas inteiras (.0): PUSH quando cur==line.
    Linhas em .5: nunca PUSH (stats são inteiros).
    market_type do banco tem prioridade sobre keyword matching.

    Handicap Asiático (gols/escanteios/cartões): bug real encontrado em
    produção (pick VIP travado em "Pendente" apesar do jogo já ter
    resultado) -- _stat_for_market() não tinha nenhum branch pra market_type
    "handicap"/"handicap_goals"/"handicap_corners"/"handicap_cards" (só
    goals/corners/cards/btts/result/etc. como mercado "reto"), então cur_val
    chegava sempre None aqui e a função retornava None pra sempre, mesmo com
    o jogo encerrado. Corrigido resolvendo direto por home/away (gols já
    disponíveis nos parâmetros; escanteios/cartões via home_stats/away_stats,
    ver _leg_needs_stats -- precisa dos dois lados separados, não só o total
    que cur_val traria), mesma lógica de
    services/ai_result_checker_service.py::evaluate_handicap (batch job, já
    corrigida lá em 2026-07-17) -- side embutido no texto da linha, apoio a
    quarto-de-bola via _resolve_asian_handicap()."""
    m     = (market or "").lower()
    mtype = (market_type or "").lower()
    home_stats = home_stats or {}
    away_stats = away_stats or {}

    direction, line_val = _extract_line(line)

    _mtype_is_result = mtype == "result" and direction not in ("over", "under")

    is_result = _mtype_is_result or direction == "result" or \
                any(k in m for k in ["resultado", "dupla chance", "1x2", "vencedor"])
    is_btts   = mtype == "btts"  or any(k in m for k in ["ambas", "btts", "ambos"])
    _has_handicap_kw = any(k in m for k in ["handicap", "handi"])
    is_corners_handicap = mtype == "handicap_corners" or (
        _has_handicap_kw and any(k in m for k in ["corner", "escanteio", "canto"])
    )
    is_cards_handicap = mtype == "handicap_cards" or (
        _has_handicap_kw and any(k in m for k in ["cart", "card"])
    )
    is_goals_handicap = not is_corners_handicap and not is_cards_handicap and (
        mtype in ("handicap", "handicap_goals") or _has_handicap_kw
    )

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
        return settlement.settle_outcome(home_goals, away_goals, line, home_team, away_team)[0]

    # ── BTTS ─────────────────────────────────────────────────────────────────
    if is_btts:
        op = settlement.parse_line(line)["op"]
        return settlement.settle_btts(home_goals, away_goals, op)[0]

    # ── Handicap Asiático (gols / escanteios / cartões) ──────────────────────
    # Os tres compartilham a mesma matematica; muda so' de qual contador saem
    # os dois lados. Handicap de escanteios/cartoes precisa dos lados
    # SEPARADOS, nao do cur_val (que e' o total) -- ver _leg_needs_stats.
    if is_goals_handicap or is_corners_handicap or is_cards_handicap:
        parsed = settlement.parse_line(line, home_team, away_team)
        if parsed["value"] is None or parsed["side"] is None:
            return None  # linha não reconhecida → não resolve
        if is_goals_handicap:
            home_val, away_val = home_goals, away_goals
        else:
            if went_to_extra_time:
                return None  # contador dos 90 minutos nao existe na API
            keys = ("Corner Kicks",) if is_corners_handicap else ("Yellow Cards", "Red Cards")
            home_val = _stat_value(home_stats, keys)
            away_val = _stat_value(away_stats, keys)
        return settlement.settle_asian_handicap(
            parsed["side"], parsed["value"], home_val, away_val)[0]

    # ── Mercados estatísticos (gols, escanteios, cartões, faltas, chutes…) ───
    # cur_val None = estatistica ainda nao publicada: o pick NAO e' liquidado
    # e volta a ser avaliado na proxima passada. Toda a aritmetica de linha
    # (inteira/meia/quarto-de-bola, PUSH, HALF-WIN, HALF-LOSS) esta em
    # services/settlement.py -- este modulo nao repete nenhuma regra.
    #
    # Jogo que foi pra prorrogacao: /fixtures/statistics soma os 120 minutos
    # sem separar por periodo, e a casa liquida pelos 90. O contador dos 90
    # minutos nao existe pra nos, entao o pick nao e' liquidado (gols sao a
    # excecao e ja' foram tratados acima, via score.fulltime em home_goals/
    # away_goals). Mesma regra do job em lote
    # (services/ai_result_checker_service.py::evaluate_pick).
    if went_to_extra_time:
        return None

    parsed = settlement.parse_line(line)
    return settlement.settle_over_under(cur_val, parsed["value"], parsed["op"])[0]


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
            home_stats=leg.get("home_stats"), away_stats=leg.get("away_stats"),
            went_to_extra_time=leg.get("went_to_extra_time", False),
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


_RESULT_TO_FACTOR = {
    settlement.GREEN: 1, settlement.HALF_WIN: 0.5, settlement.PUSH: 0,
    settlement.HALF_LOSS: -0.5, settlement.RED: -1,
}


def _profit_for_result(result: str, odd: float) -> float:
    """Lucro por unidade apostada para cada tipo de resultado.

    Mesma tabela de services/settlement.py::profit_units -- e' a que o painel
    do usuario tambem usa (routers/banca.py::_compute_follow_pnl)."""
    factor = _RESULT_TO_FACTOR.get(result)
    if factor is None:
        return -1.0
    profit = settlement.profit_units(factor, odd)
    return round(float(profit), 4) if profit is not None else -1.0


def _sync_followed_result(pick_id: int, pick_type: str, result: str, c) -> None:
    """Sincroniza resultado na user_followed_picks para todos que seguiram este pick."""
    c.execute(
        "UPDATE user_followed_picks SET result=%s WHERE pick_id=%s AND pick_type=%s",
        (result, pick_id, pick_type),
    )
    # Ponto único por onde todo resultado passa (auto-save ao vivo, encerramento
    # e revisão tardia do provedor), então o sino é alimentado aqui em vez de nos
    # 6 call sites. notify_pick_result engole as próprias exceções.
    from routers.notifications import notify_pick_result
    notify_pick_result(c, pick_id, pick_type, result)


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


def _save_market_pick_result(tabela: str, pick_id: int, pick_type: str,
                             result: str, odd: float, conn) -> None:
    """Grava resultado nas tabelas de mercado proprio (picks_faltas,
    picks_goleiros).

    Separado de _save_single_result porque aquele resolve o nome da tabela a
    partir de pick_type ('vip' -> picks_vip, qualquer outra coisa ->
    picks_free) -- passar 'faltas' por la gravaria silenciosamente na
    picks_free. O nome da tabela vem so de chamada interna, nunca de entrada
    do usuario.
    """
    profit = _profit_for_result(result, odd)
    c = conn.cursor()
    c.execute(f"UPDATE {tabela} SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, pick_type, result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] %s #%s → %s (%+.4fu)", pick_type, pick_id, result, profit)


def _multipla_combined_result(legs_results: list[str | None],
                              legs_odds: list | None = None,
                              ticket_odd=None) -> str | None:
    """Resultado combinado de uma multipla/alavancagem.

    Delega em services/settlement.py::combine_legs. A regra antiga
    ("qualquer mistura -> PUSH") zerava um bilhete que na pratica ainda
    pagava: GREEN + PUSH e' o produto das pernas que sobraram, nao um
    empate. Sem as odds das pernas nao da' pra recalcular o bilhete, entao
    ai o combinado so' resolve nos casos em que a odd nao importa (RED por
    perna perdida, ou GREEN pleno).
    """
    if any(r is None for r in legs_results):
        return None  # nem todas as pernas encerradas
    if legs_odds is not None and len(legs_odds) == len(legs_results):
        return settlement.combine_legs(legs_results, legs_odds, ticket_odd)[0]
    if any(r == settlement.RED for r in legs_results):
        return settlement.RED
    if all(r == settlement.GREEN for r in legs_results):
        return settlement.GREEN
    return None  # mistura sem as odds das pernas -> nao arrisca um numero errado


def _combined_profit(legs_results: list[str], legs_odds: list | None,
                     ticket_odd, result: str) -> float:
    """Lucro do bilhete. Com as odds das pernas, sai da conta exata de
    settlement.combine_legs (perna anulada entra com fator 1, meia perna com
    meio fator); sem elas, cai na tabela padrao pela odd do bilhete."""
    if legs_odds is not None and len(legs_odds) == len(legs_results):
        _label, profit, _eff = settlement.combine_legs(legs_results, legs_odds, ticket_odd)
        if profit is not None:
            return round(float(profit), 4)
    return _profit_for_result(result, ticket_odd)


def _save_multipla_result(pick_id: int, legs_results: list[str | None],
                          total_odd: float, conn, legs_odds: list | None = None) -> None:
    result = _multipla_combined_result(legs_results, legs_odds, total_odd)
    if result is None:
        return
    profit = _combined_profit(legs_results, legs_odds, total_odd, result)
    c = conn.cursor()
    c.execute("UPDATE picks_multiplas SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, "multipla", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] multipla #%s → %s (%+.4fu)", pick_id, result, profit)


def _save_alavancagem_result(pick_id: int, legs_results: list[str | None],
                             odd_combined: float, conn,
                             legs_odds: list | None = None) -> None:
    result = _multipla_combined_result(legs_results, legs_odds, odd_combined)
    if result is None:
        return
    profit = _combined_profit(legs_results, legs_odds, odd_combined, result)
    c = conn.cursor()
    c.execute("UPDATE picks_alavancagem SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
              (result, profit, pick_id))
    _sync_followed_result(pick_id, "alavancagem", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] alavancagem #%s → %s (%+.2fu)", pick_id, result, profit)


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

    # Jogo decidido na prorrogacao/penaltis: `goals` ja' traz os gols do tempo
    # extra somados, e casa de aposta liquida pelos 90 minutos. score.fulltime
    # e' o placar dos 90 (fixture 1567308: goals 3x2, fulltime 2x2) -- e' ele
    # que vale pra 1X2, dupla chance, BTTS, handicap de gols e total de gols.
    went_to_extra_time = status in ("AET", "PEN")
    if went_to_extra_time:
        ft90 = (fix_data.get("score") or {}).get("fulltime") or {}
        if ft90.get("home") is not None and ft90.get("away") is not None:
            home_goals = int(ft90["home"])
            away_goals = int(ft90["away"])

    # Os ids dos times saem do proprio /fixtures quando nao vierem do pick --
    # e' o que garante que a folha de estatistica seja atribuida ao lado certo
    # (ver _parse_stats), sem depender da ordem da resposta.
    fix_teams  = fix_data.get("teams", {}) or {}
    stats_home_id = home_team_id or (fix_teams.get("home") or {}).get("id")
    stats_away_id = away_team_id or (fix_teams.get("away") or {}).get("id")

    home_stats, away_stats = {}, {}
    if (status in LIVE_STATUSES or status in FT_STATUSES) and _leg_needs_stats(market, market_type):
        home_stats, away_stats = _parse_stats(
            _fetch_stats(fid, status), stats_home_id, stats_away_id)

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
        "home_stats":   home_stats,
        "away_stats":   away_stats,
        "went_to_extra_time": went_to_extra_time,
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


@router.get("/is-live")
def get_is_live(fixture_ids: str, current_user: dict = Depends(get_current_user)):
    """Recebe fixture_ids separados por vírgula e devolve quais estão ao vivo
    agora (status real da API-Football, via o mesmo cache/bulk-fetch usado
    no resto do modulo) -- usado pra trocar o badge "Pendente" por "Ao Vivo"
    nos cards de pick quando o jogo ja comecou."""
    try:
        fids = [int(x) for x in fixture_ids.split(",") if x.strip()]
    except ValueError:
        return {}
    fids = fids[:50]
    if not fids:
        return {}
    _fetch_fixtures_bulk(fids)
    result = {}
    for fid in fids:
        cached = _fix_cache.get(fid)
        status = cached[1].get("fixture", {}).get("status", {}).get("short", "NS") if cached else "NS"
        result[str(fid)] = status in LIVE_STATUSES
    return result


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
            SELECT id, fixture_id_1, fixture_id_2, fixture_id_3,
                   market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
                   market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
                   market_3, market_type_3, line_3, odd_3, home_team_3, away_team_3,
                   odd_combined, result, match_date
            FROM picks_alavancagem WHERE id = ANY(%s)
        """, (alavancagem_ids,))
        alavancagem_map = {r["id"]: r for r in cur.fetchall()}

    # Batch fixture lookups for alavancagem team_ids
    alav_fixture_ids = set()
    for p in alavancagem_map.values():
        for _i in (1, 2, 3):
            if p[f"fixture_id_{_i}"]:
                alav_fixture_ids.add(p[f"fixture_id_{_i}"])

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

    cur.close()

    # ── Pré-aquece o cache de fixtures em lote (1 chamada a cada 20 fixtures
    # em vez de 1 chamada por fixture/perna dentro do loop abaixo) ──────────
    all_fixture_ids: set[int] = set()
    for p in vip_map.values():
        if p["fixture_id"]:
            all_fixture_ids.add(p["fixture_id"])
    for p in free_map.values():
        if p["fixture_id"]:
            all_fixture_ids.add(p["fixture_id"])
    for p in multipla_map.values():
        legs_raw = p["games"]
        if isinstance(legs_raw, str):
            try: legs_raw = json.loads(legs_raw)
            except Exception: legs_raw = []
        for leg_data in (legs_raw if isinstance(legs_raw, list) else []):
            fid = leg_data.get("fixture_id")
            if fid:
                all_fixture_ids.add(fid)
    for p in alavancagem_map.values():
        for i in (1, 2, 3):
            fid = p.get(f"fixture_id_{i}")
            if fid:
                all_fixture_ids.add(fid)

    if all_fixture_ids:
        _fetch_fixtures_bulk(list(all_fixture_ids))

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
                    home_stats=leg.get("home_stats"), away_stats=leg.get("away_stats"),
                    went_to_extra_time=leg.get("went_to_extra_time", False),
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
                    leg_odds    = [l.get("odd") for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        leg_results = ["RED"] * len(legs_out)
                    if all(r is not None for r in leg_results):
                        final_result = _multipla_combined_result(leg_results, leg_odds, total_odd)
                        if final_result:
                            _save_multipla_result(pick_id, leg_results, total_odd, conn, leg_odds)
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
            for i in (1, 2, 3):
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
                    leg_odds    = [l.get("odd") for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        leg_results = ["RED"] * len(legs_out)
                    if all(r is not None for r in leg_results):
                        final_result = _multipla_combined_result(leg_results, leg_odds, odd_combined)
                        if final_result:
                            _save_alavancagem_result(pick_id, leg_results, odd_combined, conn, leg_odds)
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

    conn.close()

    # Picks que entraram em jogo viram item no sino. Só abre conexão quando há
    # de fato algo ao vivo · este endpoint é chamado a cada 60s por usuário
    # logado (NotificationContext) e na maior parte do dia a lista é vazia.
    live_now = [p for p in result if p.get("is_live") and not p.get("result")]
    if live_now:
        from routers.notifications import notify_picks_went_live
        notify_picks_went_live(user_id, live_now)

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
    resolved: dict = {"vip": 0, "free": 0, "multipla": 0, "alavancagem": 0,
                      "faltas": 0, "goleiros": 0}
    # Picks de jogos que ainda nem começaram não têm nada pra resolver --
    # sem esse filtro o job (roda a cada 5 min, 24/7) reconsultava a
    # API-Football pra TODO pick pendente do sistema, inclusive os
    # publicados com antecedência pra dias futuros. Maior consumidor de
    # cota do que a própria aba "Minhas Apostas".
    today_br = datetime.now(_BR_TZ).date()

    try:
        # ── VIP ──────────────────────────────────────────────────────────────
        try:
            cur.execute("""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team_name AS home_team, away_team_name AS away_team,
                       home_team_id, away_team_id
                FROM picks_vip
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
            """, (today_br,))
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
                                           home_team=p["home_team"], away_team=p["away_team"],
                                           home_stats=leg.get("home_stats"), away_stats=leg.get("away_stats"),
                                           went_to_extra_time=leg.get("went_to_extra_time", False))
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
                FROM picks_free
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
            """, (today_br,))
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
                                           home_team=p["home_team"], away_team=p["away_team"],
                                           home_stats=leg.get("home_stats"), away_stats=leg.get("away_stats"),
                                           went_to_extra_time=leg.get("went_to_extra_time", False))
                        if res:
                            _save_single_result(p["id"], "free", res, odd, conn)
                            resolved["free"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] free #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] free query erro: %s", e)

        # ── MÚLTIPLA ─────────────────────────────────────────────────────────
        try:
            cur.execute(
                "SELECT id, games, total_odd FROM picks_multiplas WHERE result IS NULL AND match_date <= %s",
                (today_br,),
            )
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
                    leg_odds    = [l.get("odd") for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        _save_multipla_result(p["id"], ["RED"] * len(legs_out), total_odd, conn, leg_odds)
                        resolved["multipla"] += 1
                    elif all(r is not None for r in leg_results):
                        _save_multipla_result(p["id"], leg_results, total_odd, conn, leg_odds)
                        resolved["multipla"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] multipla #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] multipla query erro: %s", e)

        # ── ALAVANCAGEM ──────────────────────────────────────────────────────
        try:
            # A perna 3 existe na tabela (tipo 'tripla') e nao era lida aqui:
            # a tripla seria graduada so' pelas pernas 1 e 2 e paga com
            # odd_combined das tres, virando GREEN indevido sempre que a 3
            # perdesse. Mesmo furo que existia em
            # services/ai_result_checker_alavancagem.py.
            cur.execute("""
                SELECT id, fixture_id_1, fixture_id_2, fixture_id_3,
                       market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
                       market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
                       market_3, market_type_3, line_3, odd_3, home_team_3, away_team_3,
                       odd_combined
                FROM picks_alavancagem
                WHERE result IS NULL AND match_date <= %s
            """, (today_br,))
            for p in cur.fetchall():
                try:
                    legs_out = []
                    for i in (1, 2, 3):
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
                    leg_odds     = [l.get("odd") for l in legs_out]
                    if any(r == "RED" for r in leg_results):
                        _save_alavancagem_result(p["id"], ["RED"] * len(legs_out), odd_combined, conn, leg_odds)
                        resolved["alavancagem"] += 1
                    elif all(r is not None for r in leg_results):
                        _save_alavancagem_result(p["id"], leg_results, odd_combined, conn, leg_odds)
                        resolved["alavancagem"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] alavancagem #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] alavancagem query erro: %s", e)

        # ── FALTAS ───────────────────────────────────────────────────────────
        # Reaproveita a maquina existente: market "Fouls. Total" casa a
        # keyword "foul" em _stat_for_market, que soma home_fouls+away_fouls,
        # e a linha "Over 22.5" parseia normal em _calc_result.
        try:
            cur.execute("""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team, away_team, home_team_id, away_team_id
                FROM picks_faltas
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
            """, (today_br,))
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
                                           home_team=p["home_team"], away_team=p["away_team"],
                                           home_stats=leg.get("home_stats"), away_stats=leg.get("away_stats"),
                                           went_to_extra_time=leg.get("went_to_extra_time", False))
                        if res:
                            _save_market_pick_result("picks_faltas", p["id"], "faltas", res, odd, conn)
                            resolved["faltas"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] faltas #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] faltas query erro: %s", e)

        # ── DEFESAS DE GOLEIRO ───────────────────────────────────────────────
        # Prop de JOGADOR: nao da' pra usar o caminho de time. O total de
        # defesas em match_statistics soma os dois goleiros do time e daria
        # GREEN errado sempre que houvesse substituicao. A fonte certa e'
        # player_match_stats.saves daquele jogador naquele fixture -- que ja
        # esta no banco (o collector roda como parte da coleta), entao aqui
        # nao ha nenhuma chamada de API.
        try:
            cur.execute("""
                SELECT pg.id, pg.line_value, pg.odd, pg.player_name,
                       pms.saves
                FROM picks_goleiros pg
                JOIN player_match_stats pms
                  ON pms.fixture_id = pg.fixture_id
                 AND pms.player_id  = pg.player_id
                WHERE pg.result IS NULL
                  AND pg.match_date <= %s
                  AND pms.saves IS NOT NULL
            """, (today_br,))
            for p in cur.fetchall():
                try:
                    linha = int(p["line_value"] or 0)
                    # "N ou mais defesas": GREEN quando saves >= N. Nunca
                    # empata (a linha e' inteira e o mercado e' "ou mais"),
                    # entao nao existe PUSH aqui.
                    res = "GREEN" if int(p["saves"]) >= linha else "RED"
                    _save_market_pick_result(
                        "picks_goleiros", p["id"], "goleiros", res, float(p["odd"] or 1), conn)
                    resolved["goleiros"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] goleiros #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] goleiros query erro: %s", e)

    finally:
        cur.close()
        conn.close()

    logger.info("[AUTO-RESULT] resolvidos: %s", resolved)
    return resolved


# ─── Re-verificação de resultados recentes (revisão tardia do provedor) ──────

# Gols/1x2 praticamente nunca sao revisados pela API depois do apito final --
# só escanteios/cartões têm esse historico (contagem as vezes muda algumas
# horas apos o FT), entao só esses mercados valem o custo extra de cota da API.
_STATS_REVERIFY_MARKET_TYPES = ("corners", "cards", "handicap_corners", "handicap_cards")
_REVERIFY_WINDOW_DAYS = 2


def reverify_recent_stats_results(days: int | None = None,
                                  all_markets: bool = False) -> dict:
    """
    Reconfere picks JA' resolvidos e corrige os que nao batem com a
    estatistica oficial de agora.

    Existe porque `resolve_all_pending` so' olha pick PENDENTE: uma vez
    gravado, o resultado nunca era reconferido. Dois motivos reais pra ele
    estar errado: (a) a API-Football revisa a contagem de escanteios/cartoes
    algumas horas depois do apito, e (b) ate' esta auditoria o pick podia ter
    sido gravado a partir de uma folha de estatistica VAZIA lida como
    zero-a-zero (fixture 1546854, Fortaleza x Palmeiras: 10 escanteios reais,
    Over 9.5 gravado RED).

    days       -- janela em dias (padrao _REVERIFY_WINDOW_DAYS). Use um numero
                  grande pra varrer o historico inteiro numa auditoria.
    all_markets-- False (padrao) so' reconfere escanteios/cartoes, que sao os
                  unicos que a API revisa depois do FT, pra nao gastar cota a
                  toa. True reconfere TODOS os mercados -- e' o modo de
                  auditoria, e o unico que pega gols/1x2/BTTS gravados a
                  partir de dado ausente.

    Sem gatilho automatico desde que o scheduler foi removido (2026-08-01):
    disparar por POST /api/admin/reverify-stats-results.
    """
    conn = get_connection()
    cur  = conn.cursor()
    corrected: list[dict] = []
    checked = 0
    today_br = datetime.now(_BR_TZ).date()
    since = today_br - timedelta(days=days if days is not None else _REVERIFY_WINDOW_DAYS)
    market_filter = "" if all_markets else "AND market_type = ANY(%(market_types)s)"
    params = {"market_types": list(_STATS_REVERIFY_MARKET_TYPES),
              "since": since, "today": today_br}

    try:
        # ── VIP / FREE (perna única, market_type direto na linha) ──────────────
        for table, pick_type, team_cols in (
            ("picks_vip",  "vip",  "home_team_name AS home_team, away_team_name AS away_team"),
            ("picks_free", "free", "home_team, away_team"),
        ):
            try:
                cur.execute(f"""
                    SELECT id, fixture_id, market, market_type, line, odd, result,
                           {team_cols}, home_team_id, away_team_id
                    FROM {table}
                    WHERE result IS NOT NULL AND fixture_id IS NOT NULL
                      {market_filter}
                      AND match_date BETWEEN %(since)s AND %(today)s
                """, params)
                for p in cur.fetchall():
                    checked += 1
                    try:
                        odd = float(p["odd"] or 1)
                        leg = _enrich_leg(p["fixture_id"], p["market"], p["line"],
                                          p["home_team"], p["away_team"],
                                          p["home_team_id"], p["away_team_id"], odd,
                                          market_type=p.get("market_type"))
                        if not leg["is_ft"]:
                            continue
                        computed = _calc_result(p["market"], p["line"],
                                                 leg["current_val"], leg["home_goals"], leg["away_goals"],
                                                 market_type=p.get("market_type"),
                                                 home_team=p["home_team"], away_team=p["away_team"],
                                                 home_stats=leg.get("home_stats"), away_stats=leg.get("away_stats"),
                                           went_to_extra_time=leg.get("went_to_extra_time", False))
                        if computed and computed != p["result"]:
                            profit = _profit_for_result(computed, odd)
                            c = conn.cursor()
                            c.execute(f"UPDATE {table} SET result=%s, profit=%s WHERE id=%s",
                                      (computed, profit, p["id"]))
                            _sync_followed_result(p["id"], pick_type, computed, c)
                            conn.commit()
                            c.close()
                            corrected.append({"table": table, "id": p["id"],
                                               "old": p["result"], "new": computed})
                            logger.warning("[AUTO-RECHECK] %s #%s: %s -> %s (revisao tardia do provedor)",
                                           pick_type, p["id"], p["result"], computed)
                    except Exception as e:
                        logger.error("[AUTO-RECHECK] %s #%s erro: %s", pick_type, p["id"], e)
            except Exception as e:
                logger.error("[AUTO-RECHECK] %s query erro: %s", table, e)

        # ── MÚLTIPLA (pernas em JSON, resultado combinado) ──────────────────────
        try:
            cur.execute("""
                SELECT id, games, total_odd, result
                FROM picks_multiplas
                WHERE result IS NOT NULL AND match_date BETWEEN %s AND %s
            """, (since, today_br))
            for p in cur.fetchall():
                checked += 1
                try:
                    games = p["games"]
                    if isinstance(games, str):
                        games = json.loads(games)
                    if not isinstance(games, list) or not games:
                        continue
                    if not all_markets and not any(
                            g.get("market_type") in _STATS_REVERIFY_MARKET_TYPES for g in games):
                        continue  # nenhuma perna usa mercado sujeito a revisao -- nada a reconferir
                    legs_out = []
                    for g in games:
                        fid = g.get("fixture_id")
                        if not fid:
                            continue
                        home = g.get("home") or g.get("home_team") or ""
                        away = g.get("away") or g.get("away_team") or ""
                        legs_out.append(_enrich_leg(fid, g.get("market", ""), g.get("line", ""), home, away,
                                                     g.get("home_team_id"), g.get("away_team_id"),
                                                     float(g.get("odd", 1)), market_type=g.get("market_type")))
                    if not legs_out or not all(l["is_ft"] for l in legs_out):
                        continue  # so' reconfere quando TODAS as pernas ja encerraram
                    leg_results = [_locked_leg_result(l) for l in legs_out]
                    leg_odds    = [l.get("odd") for l in legs_out]
                    total_odd   = float(p["total_odd"] or 1)
                    computed = _multipla_combined_result(leg_results, leg_odds, total_odd)
                    if computed and computed != p["result"]:
                        profit = _combined_profit(leg_results, leg_odds, total_odd, computed)
                        c = conn.cursor()
                        c.execute("UPDATE picks_multiplas SET result=%s, profit=%s WHERE id=%s",
                                  (computed, profit, p["id"]))
                        _sync_followed_result(p["id"], "multipla", computed, c)
                        conn.commit()
                        c.close()
                        corrected.append({"table": "picks_multiplas", "id": p["id"],
                                           "old": p["result"], "new": computed})
                        logger.warning("[AUTO-RECHECK] multipla #%s: %s -> %s (revisao tardia do provedor)",
                                       p["id"], p["result"], computed)
                except Exception as e:
                    logger.error("[AUTO-RECHECK] multipla #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RECHECK] multipla query erro: %s", e)

        # ── ALAVANCAGEM (ate 3 pernas em colunas separadas, resultado combinado) ─
        try:
            cur.execute("""
                SELECT id, fixture_id_1, fixture_id_2, fixture_id_3,
                       market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
                       market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
                       market_3, market_type_3, line_3, odd_3, home_team_3, away_team_3,
                       odd_combined, result
                FROM picks_alavancagem
                WHERE result IS NOT NULL AND match_date BETWEEN %s AND %s
            """, (since, today_br))
            for p in cur.fetchall():
                checked += 1
                try:
                    if not all_markets and not any(
                            p.get(f"market_type_{i}") in _STATS_REVERIFY_MARKET_TYPES
                            for i in (1, 2, 3)):
                        continue
                    legs_out = []
                    for i in (1, 2, 3):
                        fid = p.get(f"fixture_id_{i}")
                        if not fid:
                            continue
                        c2 = conn.cursor()
                        c2.execute("SELECT home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s", (fid,))
                        fx = c2.fetchone()
                        c2.close()
                        legs_out.append(_enrich_leg(
                            fid, p.get(f"market_{i}", ""), p.get(f"line_{i}", ""),
                            p.get(f"home_team_{i}", "") or "", p.get(f"away_team_{i}", "") or "",
                            fx["home_team_id"] if fx else None, fx["away_team_id"] if fx else None,
                            float(p.get(f"odd_{i}") or 1), market_type=p.get(f"market_type_{i}"),
                        ))
                    if not legs_out or not all(l["is_ft"] for l in legs_out):
                        continue
                    leg_results  = [_locked_leg_result(l) for l in legs_out]
                    leg_odds     = [l.get("odd") for l in legs_out]
                    odd_combined = float(p["odd_combined"] or 1)
                    computed = _multipla_combined_result(leg_results, leg_odds, odd_combined)
                    if computed and computed != p["result"]:
                        profit = _combined_profit(leg_results, leg_odds, odd_combined, computed)
                        c = conn.cursor()
                        c.execute("UPDATE picks_alavancagem SET result=%s, profit=%s WHERE id=%s",
                                  (computed, profit, p["id"]))
                        _sync_followed_result(p["id"], "alavancagem", computed, c)
                        conn.commit()
                        c.close()
                        corrected.append({"table": "picks_alavancagem", "id": p["id"],
                                           "old": p["result"], "new": computed})
                        logger.warning("[AUTO-RECHECK] alavancagem #%s: %s -> %s (revisao tardia do provedor)",
                                       p["id"], p["result"], computed)
                except Exception as e:
                    logger.error("[AUTO-RECHECK] alavancagem #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RECHECK] alavancagem query erro: %s", e)

    finally:
        cur.close()
        conn.close()

    if corrected:
        logger.warning("[AUTO-RECHECK] %d corrigido(s) de %d reconferido(s): %s",
                       len(corrected), checked, corrected)
    return {"checked": checked, "corrected": corrected}
