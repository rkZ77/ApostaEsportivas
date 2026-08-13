import logging
import time

from futebol_agent.api_football import get_fixture_odds, get_live_odds as _get_live_odds

logger = logging.getLogger(__name__)

# Padrao quando a tabela `bookmakers` nao responde. NAO e' a lista final --
# quem manda e a tela "Casas de aposta" do /admin, igual ao coletor de odds
# (ApostaEsportivas/src/collectors/odds_collector_service.py::casas_ativas).
#
# Antes daqui existirem tres listas: {8, 32} no coletor, {8, 32} implicito na
# tabela e {8, 32, 34} cravado neste arquivo. O agente do chat podia cotar uma
# casa que o site nao coleta e da qual nunca publica pick -- o assinante
# perguntava do jogo, recebia uma odd da casa 34, e o card do pick mostrava
# outra casa e outro numero.
BR_BOOKMAKERS = {8, 32}

_CACHE_TTL_S = 300
_cache: tuple[float, set] | None = None


def casas_ativas() -> set:
    """Casas ativas, lidas da mesma tabela que o coletor de odds le.

    Cache de 5 minutos porque este caminho roda por mensagem de chat: consultar
    o banco a cada pergunta e' latencia na frente do usuario pra ler uma linha
    que muda uma vez por mes. O TTL e' o que faz uma edicao no /admin valer sem
    reiniciar o servico.

    Falha -> padrao. O chat nunca pode ficar sem cotar por causa disto.
    """
    global _cache
    agora = time.monotonic()
    if _cache and agora - _cache[0] < _CACHE_TTL_S:
        return _cache[1]

    ids = set(BR_BOOKMAKERS)
    try:
        from database import get_connection
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT bookmaker_id FROM bookmakers WHERE ativo")
            lidos = {r[0] if not isinstance(r, dict) else r["bookmaker_id"]
                     for r in cur.fetchall()}
            cur.close()
            if lidos:
                ids = lidos
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[AGENT-ODDS] tabela bookmakers indisponivel (%s); usando o padrao", e)

    _cache = (agora, ids)
    return ids

VALID_PREMATCH_IDS = {
    1, 2, 12, 13, 5, 8, 16, 17, 6, 34, 105, 106, 26, 35,
    27, 28, 29, 30, 36, 4, 45, 55, 57, 58, 77, 127, 80, 82, 83,
}

_PREMATCH_ORDER = [1, 12, 2, 5, 8, 4, 6, 34, 26, 35, 16, 17, 27, 28, 29, 30, 36, 45, 55, 80]

VALID_LIVE_IDS = {
    59, 72, 48, 33, 25, 36, 69, 29, 49, 177, 43, 37, 20, 19, 180,
    80, 82, 83, 45, 57, 58, 77, 127, 16, 17,
}


def _best_odd(entries: list[dict]) -> dict:
    return max(entries, key=lambda x: float(x["odd"]))


def _collect_prematch_markets(bookmakers: list, filter_ids: set | None = None) -> dict:
    all_markets: dict[int, dict] = {}
    for bm in bookmakers:
        if filter_ids is not None and bm.get("id") not in filter_ids:
            continue
        bm_name = bm.get("name") or bm.get("bookmaker", {}).get("name", "?")
        for bet in bm.get("bets", []):
            bet_id = bet.get("id")
            if bet_id not in VALID_PREMATCH_IDS:
                continue
            if bet_id not in all_markets:
                all_markets[bet_id] = {"name": bet["name"], "outcomes": {}}
            for val in bet["values"]:
                outcome = val["value"]
                all_markets[bet_id]["outcomes"].setdefault(outcome, []).append({
                    "bookmaker": bm_name,
                    "odd": val["odd"],
                })
    return all_markets


async def get_prematch_odds(fixture_id: int) -> dict:
    raw = await get_fixture_odds(fixture_id)
    if not raw:
        return {"error": "sem_cobertura"}
    bookmakers = raw[0].get("bookmakers", [])
    if not bookmakers:
        return {"error": "sem_cobertura"}

    all_markets = _collect_prematch_markets(bookmakers, casas_ativas())
    if not all_markets:
        # Nenhuma casa nossa cotou este jogo. Cotar as outras e' melhor que
        # responder "sem cobertura" numa conversa, mas o numero deixa de ser
        # o mesmo que o card do pick mostra.
        all_markets = _collect_prematch_markets(bookmakers)
    if not all_markets:
        return {"error": "sem_cobertura"}

    ordered: dict[str, dict] = {}
    seen_ids = set()
    for bid in _PREMATCH_ORDER:
        if bid in all_markets:
            entry = all_markets[bid]
            ordered[entry["name"]] = {
                outcome: _best_odd(entries)
                for outcome, entries in entry["outcomes"].items()
            }
            seen_ids.add(bid)
    for bid, entry in all_markets.items():
        if bid not in seen_ids:
            ordered[entry["name"]] = {
                outcome: _best_odd(entries)
                for outcome, entries in entry["outcomes"].items()
            }

    return {"status": "ok", "markets": ordered}


def _filter_main_values(values: list[dict]) -> list[dict]:
    main_vals = [v for v in values if v.get("main") is True]
    return main_vals if main_vals else values


def _parse_live_outcome(v: dict) -> tuple[str, str] | None:
    if v.get("suspended"):
        return None
    value    = v["value"]
    handicap = v.get("handicap")
    key = f"{value} {handicap}" if handicap else value
    return key, v["odd"]


def _parse_live_markets(odds: list) -> dict[str, dict[str, str]]:
    markets: dict[str, dict[str, str]] = {}
    for market in odds:
        if market.get("id") not in VALID_LIVE_IDS:
            continue
        name     = market["name"]
        outcomes: dict[str, str] = {}
        values = _filter_main_values(market.get("values", []))
        for v in values:
            parsed = _parse_live_outcome(v)
            if parsed:
                outcome_key, odd_val = parsed
                if outcome_key not in outcomes or float(odd_val) > float(outcomes[outcome_key]):
                    outcomes[outcome_key] = odd_val
        if outcomes:
            markets[name] = outcomes
    return markets


async def get_live_match_odds(fixture_id: int) -> dict:
    live = await _get_live_odds(fixture_id)
    live_status = live["status"]
    odds = live["odds"]

    if odds:
        markets = _parse_live_markets(odds)
        if markets:
            label = "intervalo" if live_status == "intervalo" else "live"
            return {"status": label, "markets": markets}

    prematch = await get_prematch_odds(fixture_id)
    if prematch.get("status") == "ok" and prematch.get("markets"):
        return {"status": "prematch_fallback", "markets": prematch["markets"]}

    return {"status": "sem_cobertura", "markets": {}}
