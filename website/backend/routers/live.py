import os
import re
import json
import time
import logging
import threading
import requests
from decimal import Decimal
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from database import get_connection
from auth_utils import get_current_user
from settlement_bridge import settlement, stat_sheet
import market_form

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


# ─────────────────────────────────────────────────────────────────────────────
# ODD PRE-JOGO
#
# POR QUE ISTO EXISTE: /pick-odd so' sabia ler odd AO VIVO, e devolvia None pra
# qualquer jogo que ainda nao tinha comecado -- ou seja, pra quase todo clique
# em "Apostei", ja' que o normal e' apostar antes da bola rolar. Nesses casos o
# front caia na odd salva no pick, que foi coletada quando o motor rodou, horas
# antes. O usuario lia isso como "so' atualiza pra menos": a unica vez que a odd
# mudava era com o jogo em andamento, e ai ela costuma ter caido.
#
# Nao ha travamento de direcao em lugar nenhum, nem aqui nem no caminho ao vivo:
# o que vier da casa e' o que vale, subindo ou descendo.
# ─────────────────────────────────────────────────────────────────────────────

_odds_pre_cache: dict[int, tuple[float, list]] = {}
_TTL_PRE = 60  # segundos · odd pre-jogo nao se mexe tao rapido quanto a ao vivo

# Padrao quando a tabela `bookmakers` nao existe ou esta vazia · mesmos ids do
# coletor (collectors/odds_collector_service.py): 8 = Bet365, 32 = Betano.
_CASAS_PADRAO = {8, 32}


_casas_cache: tuple[float, set] | None = None
_TTL_CASAS = 300  # segundos · lista de casas muda por acao manual no /admin


def _casas_ativas() -> set:
    """Casas que valem pra buscar odd, da tabela `bookmakers` (coluna `ativo`).

    Mesma regra do coletor, inclusive o fallback: tabela ausente ou vazia quase
    sempre significa "ninguem cadastrou ainda", nao "desliguem tudo" -- e sem
    fallback o clique em Apostei simplesmente nunca acharia odd.

    Em cache de 5 minutos porque um bilhete de tres pernas chamaria isto tres
    vezes, e cada conexao nova ao banco custa ~154ms (ver database.py:71-82) --
    seria mais tempo de banco do que de API so' pra reler uma lista que muda
    quando alguem mexe no /admin.
    """
    global _casas_cache
    agora = time.time()
    if _casas_cache and agora - _casas_cache[0] < _TTL_CASAS:
        return _casas_cache[1]
    conn = None
    casas = _CASAS_PADRAO
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT bookmaker_id FROM bookmakers WHERE ativo")
        ids = {r["bookmaker_id"] for r in cur.fetchall()}
        cur.close()
        casas = ids or _CASAS_PADRAO
    except Exception:
        casas = _CASAS_PADRAO
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    _casas_cache = (agora, casas)
    return casas


def _fetch_prematch_odds(fid: int) -> list:
    """Odds pre-jogo (/odds) da fixture · lista de bookmakers da API-Football.

    Uma chamada so', sem filtrar por casa na querystring: /odds aceita uma casa
    por requisicao, entao filtrar la' custaria uma chamada por casa. Vem tudo e
    o filtro acontece aqui, que e' de graca.
    """
    now = time.time()
    if fid in _odds_pre_cache:
        ts, cached = _odds_pre_cache[fid]
        if now - ts < _TTL_PRE:
            return cached
    try:
        r = requests.get(f"{API_BASE}/odds", headers=_headers(),
                         params={"fixture": fid}, timeout=10)
        items = r.json().get("response", [])
        data = items[0].get("bookmakers", []) if items else []
    except Exception as e:
        logger.error("[PRE ODDS] fixture %s: %s", fid, e)
        data = _odds_pre_cache.get(fid, (0, []))[1]  # mantem cache antigo no erro
    _odds_pre_cache[fid] = (now, data)
    return data


# Nomes de aposta pre-jogo na API-Football, por market_type salvo no pick.
# Mesma politica do mapa ao vivo: familia sem equivalente claro fica de fora e
# _find_prematch_odd devolve None, o que faz o front usar a odd ja' salva.
_PRE_OVERUNDER_NAMES = {
    "goals":   {"goals over/under", "over/under", "total goals"},
    "corners": {"corners over under", "total corners", "corners over/under"},
    "cards":   {"cards over/under", "total cards", "cards over under"},
}


def _valor_over_under(texto: str) -> tuple[str | None, float | None]:
    """'Over 2.5' -> ('over', 2.5). Na odd pre-jogo a linha vem grudada no
    rotulo do valor, diferente da odd ao vivo, que traz `handicap` em campo
    proprio."""
    m = re.match(r"^\s*(over|under|mais de|menos de)\s+([0-9]+(?:[.,][0-9]+)?)\s*$",
                 texto or "", re.IGNORECASE)
    if not m:
        return None, None
    direcao = m.group(1).lower()
    direcao = "over" if direcao in ("over", "mais de") else "under"
    try:
        return direcao, float(m.group(2).replace(",", "."))
    except ValueError:
        return None, None


def _find_prematch_odd(market_type: str | None, line: str | None,
                       bookmakers: list, casas: set) -> tuple[float | None, str | None]:
    """(melhor odd pre-jogo, nome da casa) pro mercado/linha do pick.

    Melhor = maior odd entre as casas ativas, que e' o mesmo criterio que o
    coletor usa pra escolher a odd publicada no pick. Best-effort e silencioso
    igual ao caminho ao vivo: sem correspondencia clara devolve (None, None).
    """
    mtype = (market_type or "").lower()
    direction, line_val = _extract_line(line)

    def _alvo() -> set:
        """Rotulos de valor aceitos pra este mercado, ja' em minuscula."""
        if mtype == "btts":
            return {"yes"} if direction in ("yes", "sim") else {"no", "nao", "não"}
        if mtype == "double_chance":
            l = (line or "").lower().replace(" ", "")
            if "home/draw" in l or "draw/home" in l or "casaempate" in l:
                return {"home/draw"}
            if "draw/away" in l or "away/draw" in l or "empatevisitante" in l:
                return {"draw/away"}
            if "home/away" in l or "away/home" in l or "casavisitante" in l:
                return {"home/away"}
            return set()
        if mtype in ("result_1x2", "outcome"):
            l = (line or "").lower().strip()
            return {{"1": "home", "casa": "home", "home": "home", "mandante": "home",
                     "x": "draw", "empate": "draw", "draw": "draw",
                     "2": "away", "visitante": "away", "away": "away", "fora": "away",
                     }.get(l, "")} - {""}
        return set()

    nomes_ou: set = _PRE_OVERUNDER_NAMES.get(mtype, set())
    nomes_diretos = {
        "btts":          {"both teams score", "both teams to score"},
        "double_chance": {"double chance"},
        "result_1x2":    {"match winner", "fulltime result", "1x2"},
        "outcome":       {"match winner", "fulltime result", "1x2"},
    }.get(mtype, set())

    if not nomes_ou and not nomes_diretos:
        return None, None
    if nomes_ou and (direction not in ("over", "under") or line_val is None):
        return None, None

    melhor: float | None = None
    casa_melhor: str | None = None

    for bk in bookmakers:
        if bk.get("id") not in casas:
            continue
        for bet in bk.get("bets", []):
            nome = (bet.get("name") or "").lower().strip()
            if nome not in nomes_ou and nome not in nomes_diretos:
                continue
            alvos = _alvo()
            for v in bet.get("values", []):
                rotulo = (v.get("value") or "").strip()
                try:
                    odd = float(v["odd"])
                except (TypeError, ValueError, KeyError):
                    continue
                if nome in nomes_ou:
                    d, val = _valor_over_under(rotulo)
                    if d != direction or val is None or abs(val - line_val) >= 0.01:
                        continue
                elif rotulo.lower() not in alvos:
                    continue
                if melhor is None or odd > melhor:
                    melhor, casa_melhor = odd, bk.get("name")

    return melhor, casa_melhor


def odd_atual(fixture_id: int, market_type: str | None,
              line: str | None) -> tuple[float | None, str | None, str | None]:
    """(odd, origem, status) pro mercado/linha de uma fixture. Origem e'
    'live', 'prematch' ou None.

    Ponto unico de "qual e' a odd agora" pra qualquer tipo de pick: o pick
    simples chama uma vez, o bilhete chama uma vez por perna. Jogo encerrado
    devolve None -- odd de jogo que ja' acabou nao existe, e insistir so'
    gastaria quota de API.
    """
    fix_data = _fetch_fixture(fixture_id)
    status = fix_data.get("fixture", {}).get("status", {}).get("short", "NS")

    if status in FT_STATUSES:
        return None, None, status

    if status in LIVE_STATUSES:
        odd = _find_live_odd(market_type, line, _fetch_live_odds(fixture_id))
        return odd, ("live" if odd is not None else None), status

    odd, _casa = _find_prematch_odd(market_type, line,
                                    _fetch_prematch_odds(fixture_id), _casas_ativas())
    return odd, ("prematch" if odd is not None else None), status


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

    2. Contador ausente NAO vira 0. A chave simplesmente nao entra no dict, e
       quem le trata "chave ausente" como desconhecido. Era esse 0 fabricado
       que gradeou o pick de escanteios do Fortaleza x Palmeiras como RED com
       o jogo tendo 10 escanteios.

    3. (2026-08-26) Campo VAZIO dentro de folha PUBLICADA e' zero, nao
       ausencia -- a regra vive em utils/stat_sheet e o backend agora le pela
       mesma funcao do motor em vez de ter a sua. A API escreve "ninguem foi
       expulso" como `"Red Cards": null`, e trata-lo como desconhecido deixava
       TODO mercado de cartao sem liquidar ao vivo: _stat_value soma
       ("Yellow Cards", "Red Cards") e devolve None se qualquer um faltar.
    """
    parsed: list[dict] = []
    ids: list = []
    for team in raw:
        d = {chave: int(valor) for chave, valor in stat_sheet.ler_folha(
            team.get("statistics") or []).items()}
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
    # "Finalizações no Gol" e' como a casa escreve chute NO ALVO em PT, e
    # nenhuma das chaves acima pegava esse nome -- ele caia na regra generica
    # de `is_shots` logo abaixo (por conter "finaliza") e era liquidado contra
    # o total de chutes, ~25 por jogo contra ~8,5 no alvo. Toda linha Under
    # estourava por construcao: 13 RED em 18 picks desse mercado em PROD
    # (-11,26u), e NOVE deles tinham ganhado na folha. O `mtype` gravado ja'
    # salvava o caso aqui -- este bloco protege quem nao tem market_type.
    is_shots_on_target = mtype == "shots_on_target" or any(
        k in m_nospace for k in ["shotontarget", "shotongoal", "shotsontarget"]
    ) or any(k in m for k in ["chute no alvo", "chute a gol", "chutes a gol",
                              "finalizacao no alvo", "finalização no alvo",
                              "ção no gol", "ções no gol",
                              "cao no gol", "coes no gol"])
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
    # Regra unica, em market_form -- a serie do "Entenda esta analise" precisa
    # do MESMO escopo pra escolher os jogos que entram nas barras. Ver a
    # docstring de market_form.escopo_do_mercado.
    _side = market_form.escopo_do_mercado(m)
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
        # Valor = gols do time que MENOS marcou. "Ambas marcam" acontece
        # exatamente quando esse numero e' >= 1, entao ele decide o mercado
        # igual ao 1.0/0.0 que ficava aqui antes -- todo consumidor compara com
        # 1.0 (_pick_status logo abaixo, e o travamento de is_locked), e a
        # comparacao da o mesmo veredito nos dois formatos.
        #
        # O que muda e' o que sobra depois da decisao: 1.0/0.0 e' um booleano
        # disfarcado de numero, e por isso "Como esse mercado vem se
        # comportando" nao tinha o que desenhar pra BTTS e a secao inteira
        # sumia do "Entenda esta analise" (achado pelo usuario em 2026-08-08,
        # comparando com os cards de escanteios). O minimo do placar E' o
        # contador que o mercado observa, jogo a jogo, com limiar em 0.5.
        #
        # Placar ausente devolve None, nunca 0: 0 aqui afirma "alguem levou a
        # zero", e folha sem placar nao sustenta essa afirmacao -- mesma regra
        # que _stat_side ja aplica aos outros contadores.
        if home_goals is None or away_goals is None:
            return None, "Ambas Marcam", None
        return float(min(int(home_goals), int(away_goals))), "Ambas Marcam", None

    # ── Goals ──
    # Gols nao le folha de estatistica (o placar chega por parametro), mas o
    # ESCOPO e' a mesma pergunta das outras familias -- por isso sai do mesmo
    # lugar. Tinha uma copia inline aqui, com a mesma lista de palavras, e duas
    # definicoes da mesma regra e' como o bug de mando de 2026-08-08 nasceu.
    if is_goals:
        if _side == "home":
            return float(home_goals or 0), "Gols Casa", direction
        if _side == "away":
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


#: Horas depois do apito a partir das quais uma estatistica ausente deixa de
#: ser "ainda nao publicaram" e passa a ser "nunca vao publicar".
_HORAS_PARA_ANULAR = int(os.getenv("PICK_VOID_SEM_ESTATISTICA_HORAS", "12"))


def _anulacao_sem_estatistica(leg: dict) -> str | None:
    """PUSH pra perna encerrada que NUNCA vai poder ser liquidada.

    O QUE ESTAVA ACONTECENDO
    ------------------------
    Pick de mercado estatistico cujo provedor nao publica a folha do jogo nao
    tinha estado final nenhum: `_calc_result` devolve None (certissimo -- sem o
    numero, inventar um resultado e' pior que nao ter), ninguem gravava nada, e
    o pick ficava "Pendente" pra sempre. Foi o que travou a multipla #137
    (Macara x Santos, Sudamericana, 20/08): jogo FT 0-0, /fixtures/statistics
    devolvendo `results: 0`, e o bilhete inteiro preso por causa de uma perna
    que a outra ponta nunca vai responder. A varredura automatica desiste
    depois de _SWEEP_MAX_AGE_DAYS, entao o pick nao volta sozinho -- so' fica.

    POR QUE PUSH E NAO RED
    ----------------------
    E' o que a casa faz com mercado que nao pode ser conferido: anula a perna,
    devolve a entrada. Em bilhete combinado `settlement.combine_legs` da' fator
    1 pra perna anulada, entao a multipla passa a pagar so' as pernas que
    sobraram -- que e' exatamente o tratamento certo, e nao um RED que puniria
    o usuario por uma falha do provedor.

    POR QUE SO' DEPOIS DE 24H E SO' COM MOTIVO NOMEADO
    -------------------------------------------------
    Anular cedo demais atropela estatistica que so' entra horas depois do
    apito. E anular QUALQUER pick que nao resolveu transformaria um bug nosso
    (mapeamento de mercado errado, por exemplo) em PUSH silencioso -- o pior
    resultado possivel, porque some com a evidencia. Por isso aqui so' entram
    as duas causas que sabemos ser definitivas:

      a) mercado depende de estatistica e a folha do jogo nao existe;
      b) jogo foi pra prorrogacao e a folha soma os 120 minutos, sem o recorte
         de 90 que a casa usa pra liquidar (ver a nota em _calc_result).

    Qualquer outro pick que nao resolveu continua pendente e visivel de
    proposito: isso e' bug pra investigar, nao pick pra anular.
    """
    if leg.get("status") not in FT_STATUSES:
        return None
    if not leg.get("precisa_stats"):
        return None

    if leg.get("current_val") is None:
        motivo = "provedor nao publicou a estatistica"
    elif leg.get("went_to_extra_time"):
        motivo = "prorrogacao sem recorte de 90 minutos"
    else:
        return None

    inicio = leg.get("kickoff_ts")
    if not inicio or (time.time() - float(inicio)) < _HORAS_PARA_ANULAR * 3600:
        return None

    logger.warning(
        "[AUTO-RESULT] fixture %s (%s %s) anulada como PUSH: %s",
        leg.get("fixture_id"), leg.get("market"), leg.get("line"), motivo,
    )
    return settlement.PUSH


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
        ) or _anulacao_sem_estatistica(leg)
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


def _save_live_pick_result(pick_id: int, result: str, odd: float, conn) -> None:
    """Grava resultado de pick Ao Vivo.

    Nao usa _save_market_pick_result porque picks_live tem duas colunas de
    estado, nao uma: `result` fala a lingua do settlement (GREEN/RED/PUSH/
    HALF-*) e `status` fala do ciclo de vida (ACTIVE/EXPIRED/SETTLED). Gravar
    so' `result` deixaria um pick liquidado marcado como ACTIVE, e a aba
    mostraria "ao vivo" um pick que ja acabou.

    A matematica do resultado nao muda em nada: vem de _calc_result, igual a
    de todos os outros produtos.
    """
    profit = _profit_for_result(result, odd)
    c = conn.cursor()
    c.execute("""
        UPDATE picks_live
        SET result = %s, profit = %s, status = 'SETTLED', settled_at = NOW()
        WHERE id = %s AND result IS NULL
    """, (result, profit, pick_id))
    _sync_followed_result(pick_id, "live", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] live #%s -> %s (%+.4fu)", pick_id, result, profit)


def _bilhete_morto(legs_results: list[str | None]) -> bool:
    """Uma perna RED já mata a múltipla/alavancagem · não precisa esperar o resto.

    Existe como função porque o atalho estava escrito à mão em quatro lugares e
    nos quatro do mesmo jeito errado: `legs_results = ["RED"] * len(legs_out)`.
    Isso fechava o bilhete certo e, no caminho, CARIMBAVA RED em toda perna --
    inclusive nas que ganharam e nas que nem tinham jogado. O usuário via uma
    múltipla RED com as duas pernas marcadas com X e ia conferir: nenhuma tinha
    perdido de verdade.

    O commit ffffbf31 corrigiu a TELA (perna passou a ler o resultado dela), o
    que só deixou o dado errado aparecer em vez de a tela inventá-lo. A origem
    era esta: quem escreve. Bilhete e perna são duas perguntas diferentes e
    agora só o bilhete usa o atalho.
    """
    return any(r == settlement.RED for r in legs_results)


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


def _gravar_resultado_das_pernas(cur, tabela: str, pick_id: int,
                                 legs_results: list[str | None]) -> str | None:
    """Anota o resultado de CADA perna dentro do JSONB `games`.

    POR QUE ISTO EXISTE: este caminho gravava só o resultado do BILHETE, e a
    lista de pernas ficava com `result: null` pra sempre. Sem esse dado, o card
    da múltipla não tinha como saber qual perna bateu, e a tela caía num
    palpite: bilhete RED pintava TODAS as pernas de vermelho. Numa múltipla de
    duas em que uma deu GREEN, o usuário via duas derrotas · uma delas
    inventada pela tela.

    O job em lote (ai_result_checker_multiplas) sempre fez isso; foi a
    resolução automática por visita, que é a que roda de fato hoje, que nasceu
    sem. Mesma escrita, no mesmo UPDATE do bilhete.

    Devolve o JSON pronto ou None quando não há o que anotar.
    """
    cur.execute(f"SELECT games FROM {tabela} WHERE id = %s", (pick_id,))
    linha = cur.fetchone()
    if not linha or not linha["games"]:
        return None
    pernas = linha["games"]
    if isinstance(pernas, str):
        try:
            pernas = json.loads(pernas)
        except Exception:
            return None
    if not isinstance(pernas, list) or len(pernas) != len(legs_results):
        # Ordem/tamanho divergentes: anotar pelo índice colocaria o resultado de
        # uma perna em cima de outra. Melhor não anotar nada.
        return None
    for perna, r in zip(pernas, legs_results):
        if isinstance(perna, dict):
            perna["result"] = r
    return json.dumps(pernas, default=str)


def _save_multipla_result(pick_id: int, legs_results: list[str | None],
                          total_odd: float, conn, legs_odds: list | None = None,
                          forced_result: str | None = None) -> None:
    """`forced_result` fecha o BILHETE sem exigir todas as pernas encerradas ·
    uma perna RED já mata a múltipla. As pernas continuam guardando o resultado
    DELAS, incluindo `None` pra quem ainda não jogou. Ver _leg_result_do_bilhete."""
    result = forced_result or _multipla_combined_result(legs_results, legs_odds, total_odd)
    if result is None:
        return
    if forced_result:
        # Com perna em aberto não dá pra recompor a odd efetiva em combine_legs,
        # e nem precisa: bilhete morto por perna perdida paga -1u, seja qual for
        # o resto.
        profit = _profit_for_result(result, total_odd)
    else:
        profit = _combined_profit(legs_results, legs_odds, total_odd, result)
    c = conn.cursor()
    games_json = _gravar_resultado_das_pernas(c, "picks_multiplas", pick_id, legs_results)
    if games_json is not None:
        c.execute("UPDATE picks_multiplas SET result=%s, profit=%s, games=%s "
                  "WHERE id=%s AND result IS NULL",
                  (result, profit, games_json, pick_id))
    else:
        c.execute("UPDATE picks_multiplas SET result=%s, profit=%s WHERE id=%s AND result IS NULL",
                  (result, profit, pick_id))
    _sync_followed_result(pick_id, "multipla", result, c)
    conn.commit()
    c.close()
    logger.info("[AUTO-RESULT] multipla #%s → %s (%+.4fu)", pick_id, result, profit)


def _save_alavancagem_result(pick_id: int, legs_results: list[str | None],
                             odd_combined: float, conn,
                             legs_odds: list | None = None,
                             forced_result: str | None = None) -> None:
    """Mesmo contrato de `_save_multipla_result` · ver a nota de forced_result lá."""
    result = forced_result or _multipla_combined_result(legs_results, legs_odds, odd_combined)
    if result is None:
        return
    if forced_result:
        profit = _profit_for_result(result, odd_combined)
    else:
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
    kickoff_ts = fix.get("timestamp")
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

    precisa_stats = _leg_needs_stats(market, market_type)
    home_stats, away_stats = {}, {}
    if (status in LIVE_STATUSES or status in FT_STATUSES) and precisa_stats:
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
        "precisa_stats": precisa_stats,
        "kickoff_ts":    kickoff_ts,
    }


@router.get("/fixture/{fixture_id}/live-stats")
def get_fixture_live_stats(fixture_id: int, current_user: dict = Depends(get_current_user)):
    """Retorna estatísticas ao vivo de um jogo (escanteios, chutes, cartões, posse)."""
    return _montar_live_stats(fixture_id)


@router.get("/live-stats")
def get_live_stats_bulk(fixture_ids: str, current_user: dict = Depends(get_current_user)):
    """Mesma coisa que a rota acima, para varios jogos de uma vez.

    A tela de Jogos abria UMA requisicao por partida ao vivo, a cada 30
    segundos. Numa rodada com oito jogos simultaneos eram oito requisicoes por
    ciclo, cada uma passando pela checagem de sessao e por um slot do pool.

    Aqui o `_fetch_fixtures_bulk` pre-aquece o cache de todas as partidas numa
    chamada so' a API-Football (ate' 20 por vez, limite deles), e o resto sai do
    cache. Mesmo formato de resposta da rota individual, chaveado por id em
    texto -- igual /is-live faz.
    """
    try:
        fids = [int(x) for x in fixture_ids.split(",") if x.strip()]
    except ValueError:
        return {}
    fids = fids[:50]
    if not fids:
        return {}
    _fetch_fixtures_bulk(fids)
    return {str(fid): _montar_live_stats(fid) for fid in fids}


def _montar_live_stats(fixture_id: int) -> dict:
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
    """Odd atual do mercado, buscada na API-Football no momento da consulta --
    chamado quando o usuário clica em "Apostei", antes de abrir o modal.

    Jogo ao vivo lê /odds/live; jogo ainda não começado lê /odds (pré-jogo).
    Antes, o segundo caso devolvia odd=None e o front caía na odd salva no
    pick, coletada quando o motor rodou: na prática a odd só era atualizada
    para quem apostava com o jogo em andamento.

    Best-effort e silencioso em todos os caminhos: mercado sem correspondência
    clara, jogo encerrado ou API fora devolvem odd=None, nunca erro. Não existe
    limite de direção -- a odd volta como está na casa, maior ou menor que a
    do pick."""
    odd, origem, status = odd_atual(fixture_id, market_type, line)
    return {
        "odd": odd,
        "source": origem,
        "is_live": status in LIVE_STATUSES,
        "status": status,
    }


def _pernas_do_bilhete(cur, pick_id: int, pick_type: str) -> list[dict]:
    """Pernas de uma múltipla ou de uma alavancagem, no mesmo formato.

    Múltipla guarda as pernas num JSONB (`games`); alavancagem guarda em
    colunas numeradas (`fixture_id_1`, `market_type_1`, ...). Os dois viram a
    mesma lista aqui pra que a atualização de odd seja uma função só.
    """
    if pick_type == "multipla":
        cur.execute("SELECT games FROM picks_multiplas WHERE id = %s", (pick_id,))
        row = cur.fetchone()
        if not row:
            return []
        legs = row["games"]
        if isinstance(legs, str):
            try:
                legs = json.loads(legs)
            except Exception:
                legs = []
        return [
            {"fixture_id": l.get("fixture_id"), "market_type": l.get("market_type"),
             "line": l.get("line"), "odd": float(l.get("odd") or 0)}
            for l in (legs or []) if isinstance(l, dict)
        ]

    cur.execute("""
        SELECT fixture_id_1, market_type_1, line_1, odd_1,
               fixture_id_2, market_type_2, line_2, odd_2,
               fixture_id_3, market_type_3, line_3, odd_3
        FROM picks_alavancagem WHERE id = %s
    """, (pick_id,))
    row = cur.fetchone()
    if not row:
        return []
    pernas = []
    for i in (1, 2, 3):
        if not row[f"fixture_id_{i}"] or row[f"odd_{i}"] is None:
            continue
        pernas.append({
            "fixture_id":  row[f"fixture_id_{i}"],
            "market_type": row[f"market_type_{i}"],
            "line":        row[f"line_{i}"],
            "odd":         float(row[f"odd_{i}"]),
        })
    return pernas


@router.get("/ticket-odd")
def get_current_ticket_odd(pick_id: int, pick_type: str,
                           current_user: dict = Depends(get_current_user)):
    """Odd combinada atual de múltipla ou alavancagem.

    Bilhete não tem odd própria numa casa: ele é o produto das pernas. Então
    cada perna é reconsultada (mesmo caminho do pick simples, ao vivo ou
    pré-jogo) e o produto é recalculado. Perna que não puder ser atualizada
    entra com a odd salva e o bilhete volta marcado como `partial`, para a tela
    dizer que a atualização foi parcial em vez de fingir precisão.

    Sem isso, múltipla e alavancagem eram os únicos tipos em que "Apostei"
    nunca conferia a odd: o modal abria direto com o número da geração.
    """
    if pick_type not in ("multipla", "alavancagem"):
        return {"odd": None, "original_odd": None, "partial": True, "legs": []}

    conn = get_connection()
    cur = conn.cursor()
    try:
        pernas = _pernas_do_bilhete(cur, pick_id, pick_type)
    finally:
        cur.close()
        conn.close()

    if not pernas:
        return {"odd": None, "original_odd": None, "partial": True, "legs": []}

    combinada = 1.0
    original  = 1.0
    parcial   = False
    detalhe   = []
    for perna in pernas:
        salva = perna["odd"] or 0
        original *= salva or 1
        atual, origem, _status = (None, None, None)
        if perna["fixture_id"]:
            atual, origem, _status = odd_atual(perna["fixture_id"], perna["market_type"], perna["line"])
        usada = atual if atual else salva
        if not atual:
            parcial = True
        combinada *= usada or 1
        detalhe.append({
            "fixture_id": perna["fixture_id"],
            "odd": round(usada, 2) if usada else None,
            "original_odd": round(salva, 2) if salva else None,
            "source": origem,
        })

    return {
        "odd": round(combinada, 2),
        "original_odd": round(original, 2),
        "partial": parcial,
        "legs": detalhe,
    }


def _alavancagem_stakes(cur, user_id: int) -> dict:
    """{pick_id: quanto o usuario apostou naquele pick de alavancagem}.

    Reconstroi a serie: comeca na semente configurada (`alav_bankroll_init`),
    multiplica pela odd a cada GREEN e volta pra semente a cada RED. O valor
    apostado num pick e' o saldo ANTES dele, entao o saldo so' avanca depois
    de registrar o pick corrente.

    Dicionario vazio quando o usuario nao configurou a banca de alavancagem --
    nesse caso a tela nao tem o que anunciar e cai no comportamento antigo.
    """
    cur.execute("SELECT alav_bankroll_init FROM user_banca WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row or row["alav_bankroll_init"] is None:
        return {}

    inicial = float(row["alav_bankroll_init"])
    cur.execute("""
        SELECT pa.id, pa.result, pa.odd_combined
        FROM user_followed_picks uf
        JOIN picks_alavancagem pa ON pa.id = uf.pick_id
        WHERE uf.user_id = %s AND uf.pick_type = 'alavancagem'
        ORDER BY pa.match_date ASC, pa.id ASC
    """, (user_id,))

    saldo = inicial
    stakes: dict = {}
    for pick in cur.fetchall():
        stakes[pick["id"]] = round(saldo, 2)
        if pick["result"] == "GREEN":
            saldo = round(saldo * float(pick["odd_combined"] or 1), 2)
        elif pick["result"] == "RED":
            saldo = inicial
    return stakes


#: Dias depois do jogo a partir dos quais a estatistica ausente deixa de ser
#: "ainda nao publicaram" e passa a ser "nunca vao publicar".
#:
#: Boost e Jogador contam em DIAS, e nao nas 12 horas de `_HORAS_PARA_ANULAR`,
#: porque as duas tabelas guardam `match_date` (DATE puro, sem hora) e nao o
#: horario do apito. Contar hora a partir de uma data sem hora seria inventar
#: precisao -- e errar pro lado de anular cedo demais e' justamente o que a
#: regra do VIP evita. Um dia inteiro de folga cobre qualquer jogo da data.
_DIAS_PARA_ANULAR = int(os.getenv("PICK_VOID_SEM_ESTATISTICA_DIAS", "1"))


def _anular_sem_estatistica(cur, conn, today_br, resolved) -> None:
    """PUSH pro pick de Boost/Jogador que NUNCA vai poder ser liquidado.

    E' a mesma regra que `_anulacao_sem_estatistica` ja' aplicava em VIP, free e
    multipla, estendida em 2026-08-28 aos dois produtos que liquidam por conta
    propria e por isso tinham ficado de fora.

    O SINTOMA QUE ISSO FECHA
    ------------------------
    Os dois blocos acima so' liquidam quando a estatistica EXISTE -- e estao
    certos nisso: inventar numero e' pior que nao ter (primeira invariante do
    settlement, a que foi violada em 05/08 e gravou RED num pick GREEN). O
    efeito colateral e' que um jogo cuja folha o provedor nunca publica deixa o
    pick "Pendente" pra sempre: a varredura desiste depois de
    _SWEEP_MAX_AGE_DAYS e ninguem volta nele. Foi o que travou a multipla #137
    em 20/08, do outro lado.

    PUSH, e nao RED, pelo mesmo motivo da casa: mercado que nao pode ser
    conferido devolve a entrada. Punir o usuario por falha do provedor seria
    cobrar dele um erro que nao e' nosso nem dele.

    SO' COM O JOGO ENCERRADO E MOTIVO NOMEADO. As duas consultas exigem
    `ms.status IN ('FT','AET','PEN')`: sem isso, um jogo adiado ou cancelado
    viraria PUSH silencioso, e pick que nao resolveu por BUG nosso (mapeamento
    de mercado errado, por exemplo) tem que continuar pendente e visivel --
    isso e' bug pra investigar, nao pick pra anular.
    """
    limite = today_br - timedelta(days=_DIAS_PARA_ANULAR)

    # Jogador · a linha do jogador nao existe, ou a coluna do mercado veio NULL.
    try:
        cur.execute("""
            SELECT pp.id, pp.odd, pp.player_name, pp.method, pp.fixture_id
              FROM picks_player_stats pp
              JOIN match_statistics ms ON ms.fixture_id = pp.fixture_id
             WHERE pp.result IS NULL
               AND pp.match_date <= %s
               AND ms.status IN ('FT','AET','PEN')
               AND NOT EXISTS (
                     SELECT 1 FROM player_match_stats pms
                      WHERE pms.fixture_id = pp.fixture_id
                        AND pms.player_id  = pp.player_id)
        """, (limite,))
        for p in cur.fetchall():
            try:
                logger.warning(
                    "[AUTO-RESULT] player_stats #%s (%s · %s, fixture %s) anulado "
                    "como PUSH: provedor nao publicou a folha do jogador",
                    p["id"], p["player_name"], p["method"], p["fixture_id"])
                _save_market_pick_result(
                    "picks_player_stats", p["id"], "player_stats",
                    settlement.PUSH, float(p["odd"] or 1), conn)
                resolved["player_stats"] += 1
            except Exception as e:
                logger.error("[AUTO-RESULT] anulacao player_stats #%s erro: %s", p["id"], e)
    except Exception as e:
        logger.error("[AUTO-RESULT] anulacao player_stats query erro: %s", e)

    # Boost · falta o placar do intervalo (o caso comum) ou o total de gols.
    try:
        cur.execute("""
            SELECT pb.id, pb.odd, pb.fixture_id,
                   ms.total_goals, ms.home_goals_ht
              FROM picks_boost pb
              JOIN match_statistics ms ON ms.fixture_id = pb.fixture_id
             WHERE pb.result IS NULL
               AND pb.match_date <= %s
               AND ms.status IN ('FT','AET','PEN')
               AND (ms.total_goals   IS NULL
                 OR ms.home_goals_ht IS NULL
                 OR ms.away_goals_ht IS NULL)
        """, (limite,))
        for p in cur.fetchall():
            try:
                motivo = ("provedor nao publicou o total de gols"
                          if p["total_goals"] is None
                          else "provedor nao publicou o placar do intervalo")
                logger.warning(
                    "[AUTO-RESULT] boost #%s (fixture %s) anulado como PUSH: %s",
                    p["id"], p["fixture_id"], motivo)
                _save_market_pick_result(
                    "picks_boost", p["id"], "boost",
                    settlement.PUSH, float(p["odd"] or 1), conn)
                resolved["boost"] += 1
            except Exception as e:
                logger.error("[AUTO-RESULT] anulacao boost #%s erro: %s", p["id"], e)
    except Exception as e:
        logger.error("[AUTO-RESULT] anulacao boost query erro: %s", e)


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

    # Alavancagem nao aposta UNIDADES, aposta a BANCA INTEIRA e a compoe.
    #
    # Todo o resto do site dimensiona por Kelly (stake_units x unit_value), e
    # por isso `user_followed_picks.stake_units` grava 1.00 pra alavancagem --
    # um placeholder, nao uma quantidade. "Minhas Apostas" multiplicava esse 1
    # pelo unit_value da banca geral e anunciava R$10 numa aposta de R$30.
    # Reportado em 2026-08-14 pelo usuario, com a banca de alavancagem em R$30.
    #
    # O valor certo e' a banca de alavancagem NO MOMENTO daquele pick: a semente
    # composta pelos GREENs anteriores e reiniciada a cada RED -- a mesma regra
    # de /banca/alavancagem-serie, que e' quem o card ja consulta pra dizer
    # quanto apostar. Aqui ela e' repetida sobre os picks JA RESOLVIDOS pra
    # reconstruir o saldo que valia em cada aposta.
    alav_stake_por_pick = _alavancagem_stakes(cur, user_id)

    # Group pick_ids by type for batch queries
    vip_ids         = [r["pick_id"] for r in followed if r["pick_type"] == "vip"]
    free_ids        = [r["pick_id"] for r in followed if r["pick_type"] == "free"]
    multipla_ids    = [r["pick_id"] for r in followed if r["pick_type"] == "multipla"]
    alavancagem_ids = [r["pick_id"] for r in followed if r["pick_type"] == "alavancagem"]
    # Picks Ao Vivo seguidos (2026-08-11). Antes deste bloco eles caiam fora de
    # todos os `if/elif` do laco la embaixo e sumiam de "Minhas Apostas" em
    # silencio -- a aposta existia em user_followed_picks e nao aparecia em
    # lugar nenhum. Lista vazia em qualquer ambiente sem motor Live, entao
    # nada muda pro pre-jogo.
    live_ids        = [r["pick_id"] for r in followed if r["pick_type"] == "live"]

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

    live_map: dict = {}
    if live_ids:
        # try/except porque picks_live so' existe onde o motor Live ja rodou.
        # Sem ele, uma linha orfa de user_followed_picks (tabela apagada,
        # ambiente sem o motor) derrubaria "Minhas Apostas" inteiro.
        try:
            cur.execute("""
                SELECT id, fixture_id, market, market_type, line, odd, result,
                       home_team_name AS home_team, away_team_name AS away_team,
                       home_team_id, away_team_id, match_date, league_id
                FROM picks_live WHERE id = ANY(%s)
            """, (live_ids,))
            live_map = {r["id"]: r for r in cur.fetchall()}
        except Exception as e:
            conn.rollback()
            logger.error("[LIVE] picks_live indisponivel em my-picks: %s", e)
            live_map = {}

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
    for p in live_map.values():
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

        # ── AO VIVO ─────────────────────────────────────────────────────────
        # Mesma forma do bloco vip/free acima, com dois desvios obrigatorios:
        # a tabela de gravacao e' picks_live (passar 'live' pro
        # _save_single_result gravaria em picks_free, porque la' qualquer tipo
        # diferente de 'vip' cai no else) e o resultado tambem fecha o
        # `status` do ciclo de vida.
        elif pick_type == "live":
            p = live_map.get(pick_id)
            if not p:
                continue
            is_today = (p["match_date"] == today_br)
            if p["result"] is not None and not is_today:
                continue

            odd = float(p["odd"] or 1)
            leg = _enrich_leg(
                p["fixture_id"], p["market"], p["line"],
                p["home_team"], p["away_team"],
                p["home_team_id"], p["away_team_id"], odd,
                market_type=p.get("market_type"),
            )

            final_result = p["result"]
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
                    _save_live_pick_result(pick_id, auto_res, odd, conn)
                    final_result = auto_res
                    if not is_today:
                        continue

            result.append({
                "pick_id":        pick_id,
                "pick_type":      "live",
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
                    morto       = _bilhete_morto(leg_results)
                    if morto or all(r is not None for r in leg_results):
                        final_result = "RED" if morto else _multipla_combined_result(leg_results, leg_odds, total_odd)
                        if final_result:
                            _save_multipla_result(pick_id, leg_results, total_odd, conn, leg_odds,
                                                  forced_result="RED" if morto else None)
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
                    morto       = _bilhete_morto(leg_results)
                    if morto or all(r is not None for r in leg_results):
                        final_result = "RED" if morto else _multipla_combined_result(leg_results, leg_odds, odd_combined)
                        if final_result:
                            _save_alavancagem_result(pick_id, leg_results, odd_combined, conn, leg_odds,
                                                     forced_result="RED" if morto else None)
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
                    # Valor em REAIS, ja resolvido no servidor. A tela nao tem
                    # como derivar isso de stake_units: alavancagem nao usa
                    # unidade nenhuma (ver _alavancagem_stakes).
                    "stake_amount":   alav_stake_por_pick.get(pick_id),
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

def _fixtures_nao_iniciadas(cur, agora_br: datetime) -> set:
    """Fixtures cujo apito inicial ainda não chegou, pela tabela local.

    Uma consulta ao banco, zero chamada de API -- e é o filtro que mais corta
    custo na varredura: pick publicado de manhã pra jogo das 21h não tem NADA
    a resolver antes das 21h, mas era reconsultado na API em toda passada
    (`match_date <= hoje` entra no filtro desde 00:00). Com a varredura
    automática ligada isso seria a maior fonte de consumo de cota do sistema.

    O default é seguro nos dois sentidos: fixture ausente da tabela (jogo
    antigo já expurgado, pick gravado sem fixture correspondente) NÃO entra no
    conjunto e portanto continua sendo resolvida como antes. Só sai da fila
    quem o banco afirma que ainda vai começar.

    `fixtures.match_datetime` está gravado em horário de Brasília SEM fuso (o
    coletor converte na entrada, ver collectors/fixture_collector_service.py
    ::get_fixtures_by_date), então a comparação é contra o relógio de Brasília.
    Comparar com NOW() do Postgres, que é UTC, adiantaria o corte em 3 horas e
    liberaria pra varredura justamente os jogos que ainda não começaram.
    """
    try:
        cur.execute(
            "SELECT fixture_id FROM fixtures WHERE match_datetime > %s",
            (agora_br,),
        )
        return {r["fixture_id"] for r in cur.fetchall()}
    except Exception as e:
        logger.error("[AUTO-RESULT] fixtures nao iniciadas: %s", e)
        return set()  # sem o filtro a varredura só fica mais cara, nunca errada


def _leg_nao_iniciada(fid: int, market: str, line: str, odd: float,
                      market_type: str | None = None,
                      home_team: str = "", away_team: str = "") -> dict:
    """Perna de bilhete cujo jogo ainda não começou: nada a liquidar, zero API.

    Existe porque perna de múltipla/alavancagem NÃO pode simplesmente ser
    pulada como um pick simples: o resultado do bilhete sai de combinar TODAS
    as pernas, e uma lista mais curta faria `all(r is not None)` concluir que
    o bilhete inteiro fechou com pernas de menos -- gravando um combinado
    errado. A perna entra na lista, com o mesmo veredito que a chamada de API
    daria (`is_ft` e `is_locked` falsos -> `_locked_leg_result` devolve None),
    só que sem gastar a chamada.
    """
    return {
        "fixture_id": fid, "market": market, "line": line, "odd": odd,
        "market_type": market_type, "home_team": home_team, "away_team": away_team,
        "status": "NS", "elapsed": None,
        "home_goals": 0, "away_goals": 0,
        "current_val": None, "line_val": None,
        "home_stats": {}, "away_stats": {},
        "is_live": False, "is_ft": False, "is_locked": False,
        "went_to_extra_time": False,
    }


def resolve_all_pending(max_age_days: int | None = None) -> dict:
    """
    Tenta resolver todos os picks pendentes usando dados ao vivo da API.
    Retorna contagem de resolvidos por tipo.

    Dois caminhos chegam aqui, com apetites diferentes de custo:

    - botão do /admin (`POST /api/admin/resolve-picks`), sem argumento: varre
      TODO pick pendente, por mais velho que seja. É a rede de segurança
      manual, e o custo é aceitável porque é uma vez, quando alguém pede.
    - varredura automática (`maybe_resolve_pending`), com `max_age_days`: só
      olha a janela recente. Sem esse corte, pick que nunca vai resolver (jogo
      adiado, estatística que o provedor não publicou) seria reconsultado na
      API em TODA passada, pra sempre -- um vazamento de cota que só cresce.

    Em ambos os casos jogo que ainda não começou fica de fora (não há o que
    liquidar) e os fixtures são buscados em lote.
    """
    conn = get_connection()
    cur  = conn.cursor()
    resolved: dict = {"vip": 0, "free": 0, "multipla": 0, "alavancagem": 0,
                      "faltas": 0, "goleiros": 0,
                      # Motores de 27/08. A chave `goleiros` continua acima
                      # porque a tabela antiga ainda tem pendencia historica a
                      # resolver -- ela parou de CRESCER, nao de existir.
                      "player_stats": 0, "boost": 0,
                      # Ao Vivo entrou na varredura em 28/08. Ate' aqui ele so'
                      # era liquidado pelo caminho das picks SEGUIDAS.
                      "live": 0}
    today_br = datetime.now(_BR_TZ).date()
    agora_br = datetime.now(_BR_TZ).replace(tzinfo=None)
    desde = today_br - timedelta(days=max_age_days) if max_age_days is not None else None

    # Filtro de data das tabelas de pick. `match_date <= hoje` sozinho pega
    # pick de qualquer época; com `desde` a varredura automática se limita à
    # janela recente. Os dois parâmetros seguem posicionais pra não mexer nas
    # queries que já existiam.
    _janela = "AND match_date >= %s" if desde is not None else ""

    def _args(*extra):
        return (today_br, *( (desde,) if desde is not None else () ), *extra)

    try:
        nao_iniciados = _fixtures_nao_iniciadas(cur, agora_br)
        # ── VIP ──────────────────────────────────────────────────────────────
        try:
            cur.execute(f"""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team_name AS home_team, away_team_name AS away_team,
                       home_team_id, away_team_id
                FROM picks_vip
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
                {_janela}
            """, _args())
            pendentes_vip = [p for p in cur.fetchall()
                             if p["fixture_id"] not in nao_iniciados]
            _fetch_fixtures_bulk([p["fixture_id"] for p in pendentes_vip])
            for p in pendentes_vip:
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
                        res = res or _anulacao_sem_estatistica(leg)
                        if res:
                            _save_single_result(p["id"], "vip", res, odd, conn)
                            resolved["vip"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] vip #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] vip query erro: %s", e)

        # ── FREE ─────────────────────────────────────────────────────────────
        try:
            cur.execute(f"""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team, away_team, home_team_id, away_team_id
                FROM picks_free
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
                {_janela}
            """, _args())
            pendentes_free = [p for p in cur.fetchall()
                              if p["fixture_id"] not in nao_iniciados]
            _fetch_fixtures_bulk([p["fixture_id"] for p in pendentes_free])
            for p in pendentes_free:
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
                        res = res or _anulacao_sem_estatistica(leg)
                        if res:
                            _save_single_result(p["id"], "free", res, odd, conn)
                            resolved["free"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] free #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] free query erro: %s", e)

        # ── AO VIVO ──────────────────────────────────────────────────────────
        # Mesma forma do VIP/Free acima. Faltava aqui, e o buraco era so' de
        # ALCANCE, nao de matematica: o Ao Vivo ja' era liquidado -- mas so'
        # dentro da lista de picks SEGUIDAS (o caminho que monta a banca do
        # usuario). Pick ao vivo publicada que ninguem seguiu nunca passava
        # por aquele codigo e ficava pendente pra sempre, sem resultado na
        # aba e fora de toda estatistica publica.
        #
        # Dois desvios obrigatorios em relacao ao bloco do VIP, os mesmos que
        # _save_live_pick_result ja' documenta: a tabela e' picks_live (mandar
        # 'live' pro _save_single_result gravaria em picks_free, porque la'
        # tudo que nao e' 'vip' cai no else) e o resultado tambem fecha o
        # `status` do ciclo de vida, senao um pick liquidado seguiria
        # aparecendo como ACTIVE.
        try:
            cur.execute(f"""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team_name AS home_team, away_team_name AS away_team,
                       home_team_id, away_team_id
                FROM picks_live
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
                {_janela}
            """, _args())
            pendentes_live = [p for p in cur.fetchall()
                              if p["fixture_id"] not in nao_iniciados]
            _fetch_fixtures_bulk([p["fixture_id"] for p in pendentes_live])
            for p in pendentes_live:
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
                        res = res or _anulacao_sem_estatistica(leg)
                        if res:
                            _save_live_pick_result(p["id"], res, odd, conn)
                            resolved["live"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] live #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] live query erro: %s", e)

        # ── MÚLTIPLA ─────────────────────────────────────────────────────────
        try:
            cur.execute(
                "SELECT id, games, total_odd FROM picks_multiplas "
                f"WHERE result IS NULL AND match_date <= %s {_janela}",
                _args(),
            )
            multiplas = cur.fetchall()
            _fetch_fixtures_bulk([
                g.get("fixture_id")
                for p in multiplas
                for g in (json.loads(p["games"]) if isinstance(p["games"], str)
                          else (p["games"] or []))
                if isinstance(g, dict) and g.get("fixture_id")
                and g.get("fixture_id") not in nao_iniciados
            ] if multiplas else [])
            for p in multiplas:
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
                        # Perna de jogo que não começou entra como stub: sem
                        # chamada de API, mas SEM sumir da lista -- ver
                        # _leg_nao_iniciada.
                        if fid in nao_iniciados:
                            legs_out.append(_leg_nao_iniciada(
                                fid, leg_data.get("market", ""), leg_data.get("line", ""),
                                float(leg_data.get("odd", 1)),
                                market_type=leg_data.get("market_type"),
                                home_team=home, away_team=away,
                            ))
                            continue
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
                    if _bilhete_morto(leg_results):
                        _save_multipla_result(p["id"], leg_results, total_odd, conn, leg_odds,
                                              forced_result="RED")
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
            cur.execute(f"""
                SELECT id, fixture_id_1, fixture_id_2, fixture_id_3,
                       market_1, market_type_1, line_1, odd_1, home_team_1, away_team_1,
                       market_2, market_type_2, line_2, odd_2, home_team_2, away_team_2,
                       market_3, market_type_3, line_3, odd_3, home_team_3, away_team_3,
                       odd_combined
                FROM picks_alavancagem
                WHERE result IS NULL AND match_date <= %s
                {_janela}
            """, _args())
            alavancagens = cur.fetchall()
            _fetch_fixtures_bulk([
                fid for p in alavancagens for i in (1, 2, 3)
                if (fid := p.get(f"fixture_id_{i}")) and fid not in nao_iniciados
            ])
            for p in alavancagens:
                try:
                    legs_out = []
                    for i in (1, 2, 3):
                        fid = p.get(f"fixture_id_{i}")
                        if not fid:
                            continue
                        if fid in nao_iniciados:
                            legs_out.append(_leg_nao_iniciada(
                                fid, p.get(f"market_{i}", "") or "",
                                p.get(f"line_{i}", "") or "",
                                float(p.get(f"odd_{i}") or 1),
                                market_type=p.get(f"market_type_{i}"),
                                home_team=p.get(f"home_team_{i}", "") or "",
                                away_team=p.get(f"away_team_{i}", "") or "",
                            ))
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
                    if _bilhete_morto(leg_results):
                        _save_alavancagem_result(p["id"], leg_results, odd_combined, conn, leg_odds,
                                                 forced_result="RED")
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
            cur.execute(f"""
                SELECT id, fixture_id, market, market_type, line, odd,
                       home_team, away_team, home_team_id, away_team_id
                FROM picks_faltas
                WHERE result IS NULL AND fixture_id IS NOT NULL AND match_date <= %s
                {_janela}
            """, _args())
            pendentes_faltas = [p for p in cur.fetchall()
                                if p["fixture_id"] not in nao_iniciados]
            _fetch_fixtures_bulk([p["fixture_id"] for p in pendentes_faltas])
            for p in pendentes_faltas:
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
                        res = res or _anulacao_sem_estatistica(leg)
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
        #
        # Por isso este bloco fica FORA da janela de `max_age_days`: o corte
        # existe pra nao gastar cota reconsultando pick velho, e aqui nao ha
        # cota pra gastar. Pick de goleiro atrasado (a estatistica do jogador
        # as vezes so' entra horas depois) continua sendo resolvido assim que
        # o dado aparece, em qualquer varredura.
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

        # ── PLAYER STATS ─────────────────────────────────────────────────────
        # Generalizacao do bloco de defesas logo acima. A diferenca e' que a
        # coluna que liquida o pick NAO esta escrita aqui: ela vem no proprio
        # pick, em `stat_column`, gravada pelo motor a partir do catalogo de
        # metodos. E' o que faz um metodo novo (cruzamentos, impedimentos) nao
        # exigir um ramo novo neste arquivo.
        #
        # A lista de colunas aceitas e' fechada mesmo assim: `stat_column` vai
        # pra SQL por f-string, e um valor vindo do banco nao e' desculpa pra
        # confiar nele.
        #
        # FORA da janela de `max_age_days` pelo mesmo motivo do bloco de
        # defesas: nao ha' chamada de API aqui, entao nao ha' cota pra
        # economizar, e a estatistica de jogador as vezes so' entra horas
        # depois do apito.
        _COLUNAS_PLAYER_STATS = {
            "saves", "shots_on", "shots_total", "fouls_committed",
            "tackles_total", "passes_total",
        }
        try:
            cur.execute("""
                SELECT DISTINCT stat_column
                  FROM picks_player_stats
                 WHERE result IS NULL AND stat_column IS NOT NULL
            """)
            colunas = [r["stat_column"] for r in cur.fetchall()
                       if r["stat_column"] in _COLUNAS_PLAYER_STATS]
            for coluna in colunas:
                cur.execute(f"""
                    SELECT pp.id, pp.line_value, pp.odd, pp.player_name, pp.method,
                           pms.{coluna} AS valor
                    FROM picks_player_stats pp
                    JOIN player_match_stats pms
                      ON pms.fixture_id = pp.fixture_id
                     AND pms.player_id  = pp.player_id
                    WHERE pp.result IS NULL
                      AND pp.stat_column = %s
                      AND pp.match_date <= %s
                      AND pms.{coluna} IS NOT NULL
                """, (coluna, today_br))
                for p in cur.fetchall():
                    try:
                        linha = int(p["line_value"] or 0)
                        # "N ou mais": GREEN quando valor >= N. Nunca empata --
                        # a linha e' inteira e o mercado e' "ou mais", entao
                        # nao existe PUSH aqui (mesma regra do pick de defesas).
                        res = "GREEN" if int(p["valor"]) >= linha else "RED"
                        _save_market_pick_result(
                            "picks_player_stats", p["id"], "player_stats", res,
                            float(p["odd"] or 1), conn)
                        resolved["player_stats"] += 1
                    except Exception as e:
                        logger.error("[AUTO-RESULT] player_stats #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] player_stats query erro: %s", e)

        # ── PICK BOOST ───────────────────────────────────────────────────────
        # Duas pernas na MESMA partida: Over 1.5 no jogo inteiro e Under 2.5 no
        # primeiro tempo. As duas precisam pagar; uma verde e uma vermelha e'
        # RED, nao "meio verde".
        #
        # As duas colunas de resultado por perna existem pra responder a unica
        # pergunta util depois de um RED: QUAL perna quebrou. Sem elas, um mes
        # de picks vermelhos nao diria se o problema e' o modelo de gols do
        # jogo ou o de primeiro tempo -- que sao modelos diferentes, com
        # amostras diferentes.
        #
        # Estatistica ausente nunca vira zero: se `total_goals` ou o placar do
        # intervalo nao estiverem publicados, o pick fica pendente. E' a
        # primeira invariante do settlement, e foi violar ela que gravou RED
        # num pick GREEN em 05/08.
        try:
            cur.execute("""
                SELECT pb.id, pb.odd,
                       ms.total_goals,
                       ms.home_goals_ht, ms.away_goals_ht
                  FROM picks_boost pb
                  JOIN match_statistics ms ON ms.fixture_id = pb.fixture_id
                 WHERE pb.result IS NULL
                   AND pb.match_date <= %s
                   AND ms.status IN ('FT','AET','PEN')
                   AND ms.total_goals   IS NOT NULL
                   AND ms.home_goals_ht IS NOT NULL
                   AND ms.away_goals_ht IS NOT NULL
            """, (today_br,))
            for p in cur.fetchall():
                try:
                    gols_ft = int(p["total_goals"])
                    gols_ht = int(p["home_goals_ht"]) + int(p["away_goals_ht"])
                    res_ft = "GREEN" if gols_ft > 1.5 else "RED"
                    res_ht = "GREEN" if gols_ht < 2.5 else "RED"
                    res = "GREEN" if (res_ft == "GREEN" and res_ht == "GREEN") else "RED"
                    c = conn.cursor()
                    c.execute("""UPDATE picks_boost
                                    SET result_ft = %s, result_ht = %s
                                  WHERE id = %s AND result IS NULL""",
                              (res_ft, res_ht, p["id"]))
                    c.close()
                    _save_market_pick_result(
                        "picks_boost", p["id"], "boost", res, float(p["odd"] or 1), conn)
                    resolved["boost"] += 1
                except Exception as e:
                    logger.error("[AUTO-RESULT] boost #%s erro: %s", p["id"], e)
        except Exception as e:
            logger.error("[AUTO-RESULT] boost query erro: %s", e)

        # ── ANULACAO POR FALTA DE ESTATISTICA · Boost e Jogador ─────────────
        _anular_sem_estatistica(cur, conn, today_br, resolved)

    finally:
        cur.close()
        conn.close()

    logger.info("[AUTO-RESULT] resolvidos: %s", resolved)
    return resolved


# ─── Gatilho sob demanda ─────────────────────────────────────────────────────
#
# O problema que isto resolve: a matemática de liquidação sempre esteve pronta
# (resolve_all_pending acima resolve tanto o jogo encerrado quanto o pick que
# já travou no meio, via `is_locked`), mas desde que o scheduler foi removido
# em 2026-08-01 ninguém a chamava sozinho. Na prática o pick ficava "Pendente"
# no site pra TODO MUNDO até alguém abrir o /admin e clicar. A única exceção
# era oportunista e privada: quem tinha SEGUIDO o pick e abria "Minhas
# Apostas" resolvia os próprios, e só os próprios.
#
# A alternativa óbvia seria devolver um job de intervalo fixo. Ela foi
# descartada de propósito: um laço de 5 em 5 min bate na API-Football 24/7,
# inclusive de madrugada com o site vazio, e foi justamente esse consumo que
# motivou a remoção do scheduler. Aqui a varredura é puxada por visita: quando
# alguém abre a tela de picks/resultados, o backend olha se vale a pena varrer
# e, se valer, varre em segundo plano. Site parado não gasta nada -- e site
# parado é exatamente quando não importa que o resultado demore.
#
# Três freios, nesta ordem, do mais barato pro mais caro:
#   1. relógio  -- no máximo uma varredura a cada _SWEEP_INTERVAL segundos
#   2. banco    -- só varre se existir pick pendente de jogo que já começou
#   3. API      -- só então as chamadas, já filtradas e em lote

#: Intervalo mínimo entre duas varreduras. 3 min cobre bem o "deu green no
#: meio": escanteio e cartão mudam numa escala de minutos, não de segundos.
_SWEEP_INTERVAL = int(os.getenv("PICK_SWEEP_INTERVAL_SECONDS", "180"))

#: Janela da varredura automática. Pick mais velho que isso não é reconsultado
#: sozinho -- sem esse corte, pick que nunca vai resolver (jogo adiado,
#: estatística que o provedor não publicou) viraria custo fixo e permanente,
#: consultado em toda passada pra sempre. O botão do /admin continua varrendo
#: tudo, sem janela.
_SWEEP_MAX_AGE_DAYS = int(os.getenv("PICK_SWEEP_MAX_AGE_DAYS", "3"))

_sweep_lock = threading.Lock()
_sweep_state: dict = {"last": 0.0, "running": False}


def _varredura_habilitada() -> bool:
    """A varredura automática só existe em PRODUÇÃO.

    Três ambientes rodam este mesmo código e só um deles deve gastar cota da
    API-Football sozinho:

    - dev: banco próprio, mas a cota da API é a MESMA conta de produção (só
      existe uma chave). Uma janela aberta no dev consumiria a cota do site
      real sem nenhum usuário do outro lado. Foi o pedido explícito do usuário
      em 2026-08-09: "em dev eu não quero que fica rodando, só em produção".
    - noprod: pior ainda, aponta pro banco de PRODUÇÃO -- gravaria resultado e
      notificaria o usuário real em duplicata com o serviço de verdade.
    - produção: o único que varre.

    `PICK_SWEEP=off` desliga na mão em qualquer ambiente, sem redeploy de
    código, se algum dia a cota apertar. O disparo manual pelo /admin
    (`POST /api/admin/resolve-picks`) não passa por aqui e continua valendo em
    todo ambiente -- ação de gente é sempre permitida, é o automático que
    precisa declarar intenção.
    """
    from runtime_env import is_production, side_effects_enabled
    if os.getenv("PICK_SWEEP", "on").strip().lower() in ("off", "0", "false", "no"):
        return False
    return is_production() and side_effects_enabled()


def _ha_pendente_em_jogo() -> bool:
    """Existe pick pendente de jogo que já começou? Só banco, zero API.

    É o freio que faz a varredura custar nada no caso comum. Na maior parte do
    dia a resposta é não (os picks do dia ainda nem começaram, ou já foram
    todos resolvidos), e aí nenhuma chamada de API acontece.

    Uma resposta falsamente positiva é inofensiva -- a varredura roda e não
    acha nada. Por isso o SQL prefere errar pra esse lado: `LEFT JOIN` com
    `match_datetime IS NULL` conta como "pode ter começado", igual ao default
    de _fixtures_nao_iniciadas.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            desde = datetime.now(_BR_TZ).date() - timedelta(days=_SWEEP_MAX_AGE_DAYS)
            agora_br = datetime.now(_BR_TZ).replace(tzinfo=None)
            for tabela in ("picks_vip", "picks_free", "picks_faltas"):
                cur.execute(f"""
                    SELECT 1
                    FROM {tabela} p
                    LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
                    WHERE p.result IS NULL
                      AND p.fixture_id IS NOT NULL
                      AND p.match_date BETWEEN %s AND %s
                      AND (f.match_datetime IS NULL OR f.match_datetime <= %s)
                    LIMIT 1
                """, (desde, datetime.now(_BR_TZ).date(), agora_br))
                if cur.fetchone():
                    return True
            # Bilhetes combinados não têm fixture_id em coluna própria (múltipla
            # guarda as pernas em JSON), então aqui a pergunta é só pela data --
            # são poucos por dia e o custo de um falso positivo é uma varredura
            # que não acha nada.
            for tabela in ("picks_multiplas", "picks_alavancagem"):
                cur.execute(f"""
                    SELECT 1 FROM {tabela}
                    WHERE result IS NULL AND match_date BETWEEN %s AND %s
                    LIMIT 1
                """, (desde, datetime.now(_BR_TZ).date()))
                if cur.fetchone():
                    return True
            cur.execute("""
                SELECT 1
                FROM picks_goleiros pg
                JOIN player_match_stats pms
                  ON pms.fixture_id = pg.fixture_id AND pms.player_id = pg.player_id
                WHERE pg.result IS NULL AND pms.saves IS NOT NULL
                LIMIT 1
            """)
            if cur.fetchone():
                return True
            # Motores de 27/08. Sem estas duas perguntas a varredura nunca
            # disparava por causa deles: `maybe_resolve_pending` so' gasta uma
            # thread quando ha' o que resolver, e "o que resolver" era uma
            # lista escrita a mao que nao conhecia as tabelas novas -- os picks
            # ficariam pendentes ate' alguem abrir outra pendencia por acaso.
            cur.execute("""
                SELECT 1 FROM picks_player_stats pp
                JOIN player_match_stats pms
                  ON pms.fixture_id = pp.fixture_id AND pms.player_id = pp.player_id
                WHERE pp.result IS NULL
                LIMIT 1
            """)
            if cur.fetchone():
                return True
            cur.execute("""
                SELECT 1 FROM picks_boost pb
                JOIN match_statistics ms ON ms.fixture_id = pb.fixture_id
                WHERE pb.result IS NULL
                  AND ms.status IN ('FT','AET','PEN')
                  AND ms.total_goals IS NOT NULL
                LIMIT 1
            """)
            if cur.fetchone():
                return True
            # Ao vivo (29/08), pela MESMA razao das duas perguntas acima: o
            # pick ao vivo era liquidado por `resolve_all_pending`, mas nada
            # aqui perguntava por ele. Num dia so' com pendencia ao vivo o
            # freio respondia "nao ha' o que resolver" e a varredura nunca
            # disparava · ficava mascarado porque quase sempre havia pick de
            # pre-jogo pendente junto.
            #
            # A guarda de existencia e' a mesma que o resto do modulo ja' usa
            # com picks_live: a tabela vem do motor, nao das migracoes do site.
            cur.execute("SELECT to_regclass('public.picks_live') IS NOT NULL AS existe")
            if not cur.fetchone()["existe"]:
                return False
            cur.execute("""
                SELECT 1
                FROM picks_live p
                LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
                WHERE p.result IS NULL
                  AND p.fixture_id IS NOT NULL
                  AND p.match_date BETWEEN %s AND %s
                  AND (f.match_datetime IS NULL OR f.match_datetime <= %s)
                LIMIT 1
            """, (desde, datetime.now(_BR_TZ).date(), agora_br))
            return cur.fetchone() is not None
        finally:
            cur.close()
    except Exception as e:
        logger.error("[AUTO-RESULT] checagem de pendentes: %s", e)
        return False  # na dúvida NÃO gasta cota; a próxima visita tenta de novo
    finally:
        if conn is not None:
            conn.close()


def _sweep_now() -> None:
    """Corpo da thread de varredura. Libera o `running` aconteça o que acontecer."""
    try:
        resolve_all_pending(max_age_days=_SWEEP_MAX_AGE_DAYS)
    except Exception:
        logger.error("[AUTO-RESULT] varredura sob demanda falhou", exc_info=True)
    finally:
        with _sweep_lock:
            _sweep_state["running"] = False
            _sweep_state["last"] = time.time()


def maybe_resolve_pending() -> bool:
    """Dispara a varredura em segundo plano se for a hora. Devolve se disparou.

    Chamada dos endpoints de leitura de picks/resultados. Nunca levanta, nunca
    bloqueia a resposta: a varredura roda numa thread própria, então a página
    do usuário não espera pela API-Football.

    O relógio só é reiniciado quando a varredura TERMINA (ver `_sweep_now`), e
    não quando começa -- uma varredura lenta não vira gatilho pra próxima
    empilhar em cima.
    """
    if not _varredura_habilitada():
        return False

    agora = time.time()
    with _sweep_lock:
        if _sweep_state["running"]:
            return False
        if agora - _sweep_state["last"] < _SWEEP_INTERVAL:
            return False
        # Marca ANTES de soltar a trava: duas requisições simultâneas (o caso
        # normal, o front busca vários endpoints de uma vez) não podem virar
        # duas varreduras.
        _sweep_state["running"] = True

    try:
        if not _ha_pendente_em_jogo():
            with _sweep_lock:
                _sweep_state["running"] = False
                _sweep_state["last"] = agora  # não repergunta ao banco a cada request
            return False
    except Exception:
        with _sweep_lock:
            _sweep_state["running"] = False
        return False

    threading.Thread(target=_sweep_now, name="pick-sweep", daemon=True).start()
    return True


@router.get("/sweep-status")
def get_sweep_status(current_user: dict = Depends(get_current_user)):
    """Estado da varredura automática · usado pelo /admin pra mostrar quando
    foi a última passada, sem precisar ler log do Railway."""
    with _sweep_lock:
        ultima, rodando = _sweep_state["last"], _sweep_state["running"]
    return {
        "rodando": rodando,
        "ha_quantos_segundos": round(time.time() - ultima) if ultima else None,
        "intervalo_segundos": _SWEEP_INTERVAL,
        "janela_dias": _SWEEP_MAX_AGE_DAYS,
    }


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
