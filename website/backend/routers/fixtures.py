import os
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from database import get_connection
from auth_utils import get_current_user
from arbitro import chave_do_arbitro, sql_chave
import api_quota
import cache_publico

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])

API_URL   = "https://v3.football.api-sports.io/fixtures"
TZ_BRAZIL = "America/Sao_Paulo"
BRT       = timezone(timedelta(hours=-3))

# ── Cache em memória ──────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 600  # 10 minutos


def _api_headers():
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY", "")}


def _brazil_today() -> str:
    """Data de hoje no fuso de Brasília (UTC-3)."""
    return datetime.now(BRT).strftime("%Y-%m-%d")


def _fetch_by_utc_date(league_id: int, season: int, utc_date: str) -> list:
    """
    Busca fixtures para um dia UTC específico.
    Pede ao endpoint com timezone=BRT para já receber os horários convertidos.
    """
    cache_key = f"{league_id}:{utc_date}:{TZ_BRAZIL}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data

    # SEASON NAO ENTRA NO FILTRO (2026-09-07).
    #
    # A tela mostrava DOIS jogos num dia cheio, e nao era filtro do front: a
    # season vinha da coluna `leagues.season`, que so' muda quando alguem roda a
    # coleta. Liga que virou de temporada e ficou com o ano velho na tabela
    # responde ZERO aqui -- a API casa `season` com `date` e nao devolve nada,
    # sem erro nenhum. Uma liga com a season certa sobrava, e a tela dizia que o
    # dia tinha dois jogos.
    #
    # `league` + `date` ja' identificam a rodada sozinhos. A season fica so' como
    # plano B, para o caso de a API passar a exigir o par.
    base = {"league": league_id, "date": utc_date, "timezone": TZ_BRAZIL}
    try:
        resp = requests.get(API_URL, headers=_api_headers(), params=base, timeout=10)
        api_quota.registrar(getattr(resp, "headers", None), "fixtures")
        resp.raise_for_status()
        payload = resp.json()
        result  = payload.get("response", [])

        # `errors` vem como lista vazia no sucesso e como objeto quando a API
        # reclama de parametro -- e ela responde 200 nos dois casos.
        erros = payload.get("errors") or []
        if not result and isinstance(erros, dict) and erros:
            logger.warning("[FIXTURES API] liga %s sem season: %s", league_id, erros)
            resp = requests.get(API_URL, headers=_api_headers(),
                                params={**base, "season": season}, timeout=10)
            api_quota.registrar(getattr(resp, "headers", None), "fixtures")
            resp.raise_for_status()
            result = resp.json().get("response", [])

        _cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logger.error("[FIXTURES API] Erro liga %s / %s: %s", league_id, utc_date, e)
        return []


def _fetch_dia_inteiro(utc_date: str) -> list | None:
    """TODOS os jogos de uma data, de todas as ligas, numa chamada so'.

    POR QUE (2026-10-06). A lista pedia `league` + `date` liga por liga: com 15
    ligas e dois dias UTC eram 30 chamadas a cada 10 minutos, e a tela esperava
    a mais lenta. A API aceita `date` sozinho e devolve o dia inteiro; o filtro
    de liga ativa passa pro nosso lado, onde e' de graca. Sao 2 chamadas por
    janela de cache em vez de 2 x ligas.

    None = a chamada falhou (quem chama cai no caminho por liga). Lista vazia
    = o dia nao tem jogo, o que e' resposta valida.
    """
    cache_key = f"dia:{utc_date}:{TZ_BRAZIL}"
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return data
    try:
        resp = requests.get(API_URL, headers=_api_headers(),
                            params={"date": utc_date, "timezone": TZ_BRAZIL}, timeout=15)
        api_quota.registrar(getattr(resp, "headers", None), "fixtures")
        resp.raise_for_status()
        payload = resp.json()
        erros = payload.get("errors") or []
        if isinstance(erros, dict) and erros:
            logger.warning("[FIXTURES API] dia %s recusado: %s", utc_date, erros)
            return None
        result = payload.get("response", [])
        _guardar(cache_key, result)
        return result
    except Exception as e:
        logger.error("[FIXTURES API] Erro no dia %s: %s", utc_date, e)
        return None


#: Teto de entradas no cache em memoria. A resposta de um dia inteiro tem
#: perto de mil jogos; sem teto, quem navega data a data pela agenda faria o
#: processo crescer pra sempre, porque o TTL so' e' conferido na LEITURA.
_CACHE_MAX = 60


def _guardar(chave: str, valor: list) -> None:
    if len(_cache) >= _CACHE_MAX:
        agora = time.time()
        for k in [k for k, (ts, _) in _cache.items() if agora - ts >= CACHE_TTL]:
            _cache.pop(k, None)
        while len(_cache) >= _CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    _cache[chave] = (time.time(), valor)


def _parse_fixture(item: dict, league_name: str) -> dict:
    fix         = item["fixture"]
    teams       = item["teams"]
    goals       = item.get("goals", {})
    league_info = item.get("league", {})

    # A API retorna o horário no timezone solicitado (BRT) com offset -03:00.
    # Só formatamos sem o sufixo para o frontend exibir como horário local.
    dt_raw = fix.get("date", "")
    try:
        dt_brt = datetime.fromisoformat(dt_raw)
        dt_iso = dt_brt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        dt_iso = dt_raw

    return {
        "fixture_id":     fix["id"],
        "match_datetime": dt_iso,
        "league_id":      league_info.get("id"),
        "season":         league_info.get("season"),
        "league_name":    league_name,
        "league_logo":    league_info.get("logo"),
        "league_flag":    league_info.get("flag"),
        "league_country": league_info.get("country"),
        "status":         fix["status"]["short"],
        "elapsed":        fix.get("status", {}).get("elapsed"),
        "home_team_id":   teams["home"]["id"],
        "away_team_id":   teams["away"]["id"],
        "home_team":      teams["home"]["name"],
        "away_team":      teams["away"]["name"],
        "home_goals":     goals.get("home"),
        "away_goals":     goals.get("away"),
    }


def _brt_date_of(item: dict) -> str:
    """Retorna a data BRT (YYYY-MM-DD) de um fixture da API."""
    dt_raw = item.get("fixture", {}).get("date", "")
    try:
        dt = datetime.fromisoformat(dt_raw)
        # Se veio com offset, converte para BRT; senão assume BRT
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)
        return dt.astimezone(BRT).strftime("%Y-%m-%d")
    except Exception:
        return ""


@router.get("/today")
def get_today_fixtures(
    current_user: dict = Depends(get_current_user),
    date: Optional[str] = Query(None, description="YYYY-MM-DD no fuso de Brasília"),
):
    """
    Jogos do dia das ligas monitoradas · horários em BRT, cache 10 min.

    Busca o dia solicitado E o dia UTC seguinte, pois jogos após 21h BRT
    caem no próximo dia UTC (BRT = UTC-3, então 21h BRT = 00h UTC+1).
    Filtra pelo horário BRT para mostrar apenas os jogos do dia correto.
    """
    target_brt = date or _brazil_today()

    # Valida formato antes de usar
    try:
        local_dt = datetime.strptime(target_brt, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Formato de data inválido. Use YYYY-MM-DD.")
    next_utc_date = (local_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    utc_dates_to_query = [target_brt, next_utc_date]

    # A CONEXAO NAO ATRAVESSA AS CHAMADAS EXTERNAS.
    #
    # Antes era uma so', aberta aqui e fechada no fim, com `nº de ligas x 2`
    # chamadas HTTP a API-Football no meio. Com 15 ligas sao 30 chamadas de ate'
    # 10s de timeout cada, e o slot do pool (que tem 10 no total, ver
    # database.py:87-91) ficava presso o tempo todo. Um usuario nessa tela com o
    # cache frio tirava capacidade do site inteiro.
    #
    # Agora sao duas conexoes curtas, uma antes e outra depois. Com o pool, pegar
    # de volta custa perto de nada; segurar por dez segundos custava caro.
    conn = get_connection()
    cur  = conn.cursor()
    try:
        # SO' LIGA ATIVA (2026-10-06, pedido do usuario): a aba Jogos e' das
        # ligas cadastradas no site. Liga desativada no /admin sumia da coleta,
        # do motor e do calendario (todos filtram `ativa`), mas continuava aqui
        # -- e gastando duas chamadas da API-Football por visita.
        cur.execute("SELECT league_id, name, season FROM leagues "
                    "WHERE COALESCE(ativa, TRUE) ORDER BY league_id")
        leagues = [dict(r) for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()

    if not leagues:
        return []

    # O DIA INTEIRO EM DUAS CHAMADAS (ver _fetch_dia_inteiro), as duas em
    # paralelo, e o recorte pelas ligas ativas aqui. Mesmo formato de
    # `respostas` do caminho antigo, pra o laco de baixo nao mudar.
    with ThreadPoolExecutor(max_workers=2) as pool:
        dias = list(pool.map(_fetch_dia_inteiro, utc_dates_to_query))

    if all(d is not None for d in dias):
        por_liga = {row["league_id"]: row for row in leagues}
        ordem = {row["league_id"]: i for i, row in enumerate(leagues)}
        itens = [it for dia in dias for it in dia
                 if (it.get("league") or {}).get("id") in por_liga]
        # A ordem de desempate do caminho antigo era a de `leagues`.
        itens.sort(key=lambda it: ordem[it["league"]["id"]])
        respostas = [(por_liga[it["league"]["id"]], [it]) for it in itens]
    else:
        # RESERVA: a chamada do dia falhou (rede, limite). O caminho por liga
        # continua funcionando, so' mais caro. EM PARALELO, com teto de 8 pra
        # nao levar rate limit da API-Football num pico.
        tarefas = [(row, utc_date) for row in leagues for utc_date in utc_dates_to_query]
        with ThreadPoolExecutor(max_workers=min(8, len(tarefas))) as pool:
            respostas = list(pool.map(
                lambda t: (t[0], _fetch_by_utc_date(t[0]["league_id"], t[0]["season"], t[1])),
                tarefas,
            ))

    seen_ids: set[int] = set()
    all_fixtures: list[dict] = []

    # A ordem de `tarefas` e' a de `leagues`, e `pool.map` preserva ordem, entao
    # o desempate de fixture repetida em duas ligas continua sendo o de antes.
    for row, items in respostas:
        for item in items:
            fid = item["fixture"]["id"]
            if fid in seen_ids:
                continue
            if _brt_date_of(item) != target_brt:
                continue
            seen_ids.add(fid)
            all_fixtures.append(_parse_fixture(item, row["name"]))

    # Marca quais fixtures têm pick cadastrado para o dia
    if all_fixtures:
        conn = get_connection()
        cur  = conn.cursor()
        try:
            fixture_ids = [f["fixture_id"] for f in all_fixtures]
            placeholders = ",".join(["%s"] * len(fixture_ids))
            cur.execute(f"""
                SELECT fixture_id, market, 'free' AS pick_type FROM picks_free
                WHERE fixture_id IN ({placeholders}) AND match_date = %s
                UNION ALL
                SELECT fixture_id, market, 'vip' AS pick_type FROM picks_vip
                WHERE fixture_id IN ({placeholders}) AND match_date = %s
            """, fixture_ids + [target_brt] + fixture_ids + [target_brt])
            picks_map: dict[int, dict] = {}
            for r in cur.fetchall():
                fid = r["fixture_id"]
                # prefere vip se houver os dois
                if fid not in picks_map or picks_map[fid]["pick_type"] == "free":
                    picks_map[fid] = {"market": r["market"], "pick_type": r["pick_type"]}
        finally:
            # try/finally novo: sem ele, um erro aqui devolvia a conexao pro pool
            # so' quando o coletor de lixo passasse -- e o pool tem 10 slots.
            cur.close(); conn.close()

        for f in all_fixtures:
            pick = picks_map.get(f["fixture_id"])
            f["has_pick"]    = pick is not None
            f["pick_market"] = pick["market"] if pick else None
            f["pick_type_flag"] = pick["pick_type"] if pick else None

        formas = _formas_recentes(
            {f["home_team_id"] for f in all_fixtures} | {f["away_team_id"] for f in all_fixtures},
            antes_de=target_brt,
        )
        for f in all_fixtures:
            f["forma_home"] = formas.get(f["home_team_id"], [])
            f["forma_away"] = formas.get(f["away_team_id"], [])

    all_fixtures.sort(key=lambda x: x["match_datetime"] or "")
    return all_fixtures


def _resultado_do_time(row: dict, team_id: int) -> str | None:
    """'V', 'E' ou 'D' do ponto de vista de `team_id`."""
    hg, ag = row.get("home_goals"), row.get("away_goals")
    if hg is None or ag is None:
        return None
    pro, contra = (hg, ag) if row["home_team_id"] == team_id else (ag, hg)
    return "V" if pro > contra else "E" if pro == contra else "D"


_COLUNAS_DO_JOGO = """fixture_id, match_date, league_id, home_team_id, away_team_id,
               home_goals, away_goals, home_corners, away_corners,
               home_yellow_cards, away_yellow_cards, home_red_cards, away_red_cards,
               home_shots_on, away_shots_on, home_fouls, away_fouls,
               home_possession, away_possession,
               home_goals_ht, away_goals_ht, home_corners_1h, away_corners_1h,
               home_yellow_cards_1h, away_yellow_cards_1h,
               home_shots_on_1h, away_shots_on_1h"""


def _ultimos_jogos(cur, team_ids: list, antes_de, n: int) -> list:
    """Os ultimos `n` jogos encerrados de CADA time, numa consulta so'.

    COMO, E POR QUE ASSIM. Um time aparece em `home_team_id` OU em
    `away_team_id`, e um `OR` entre duas colunas faz o Postgres desistir dos
    indices e varrer a tabela. Aqui cada metade e' uma consulta propria, com
    `ORDER BY match_date DESC LIMIT n` em cima do seu indice
    (idx_match_stats_home_date / _away_date, ver migrations.py): o banco le'
    no maximo `n` entradas de cada lado e para. O `LATERAL` repete isso por
    time sem ida e volta, e o LIMIT de fora junta as duas metades.

    Volta linhas com `team_id` (o time de quem a serie e'), ordenadas por time
    e do jogo mais recente pro mais antigo. `antes_de` None = sem corte.
    """
    if not team_ids:
        return []
    cur.execute(f"""
        SELECT t.team_id, j.*
        FROM unnest(%s::int[]) AS t(team_id)
        CROSS JOIN LATERAL (
            SELECT * FROM (
                (SELECT {_COLUNAS_DO_JOGO} FROM match_statistics
                  WHERE home_team_id = t.team_id
                    AND status IN ('FT','AET','PEN')
                    AND (%s::timestamp IS NULL OR match_date < %s::timestamp)
                  ORDER BY match_date DESC LIMIT %s)
                UNION ALL
                (SELECT {_COLUNAS_DO_JOGO} FROM match_statistics
                  WHERE away_team_id = t.team_id
                    AND status IN ('FT','AET','PEN')
                    AND (%s::timestamp IS NULL OR match_date < %s::timestamp)
                  ORDER BY match_date DESC LIMIT %s)
            ) dois_lados
            ORDER BY match_date DESC
            LIMIT %s
        ) j
        ORDER BY t.team_id, j.match_date DESC
    """, (list(team_ids), antes_de, antes_de, n, antes_de, antes_de, n, n))
    return [dict(r) for r in cur.fetchall()]


def _formas_recentes(team_ids: set, antes_de: str, n: int = 5) -> dict:
    """Ultimos `n` resultados de cada time, do mais recente pro mais antigo.

    UMA consulta pra lista inteira, com ROW_NUMBER por time · uma por jogo
    seriam 40 idas ao banco num sabado de rodada cheia. `antes_de` existe pra
    que olhar a rodada de ontem mostre a forma de ANTES daquele jogo, e nao um
    resultado que o proprio jogo ja' produziu.
    """
    ids = [t for t in team_ids if t]
    if not ids:
        return {}
    conn = get_connection()
    cur = conn.cursor()
    try:
        saida: dict[int, list] = {}
        for r in _ultimos_jogos(cur, ids, antes_de, n):
            res = _resultado_do_time(r, r["team_id"])
            if res:
                saida.setdefault(r["team_id"], []).append(res)
        return saida
    except Exception:
        # Forma e' enfeite da lista: falhar aqui nao pode derrubar a agenda.
        logger.warning("[FIXTURES] forma recente indisponivel", exc_info=True)
        return {}
    finally:
        cur.close(); conn.close()


@router.get("/{fixture_id}/stats")
def get_fixture_stats(fixture_id: int, current_user: dict = Depends(get_current_user)):
    """Estatísticas do fixture: médias por time + últimas 5 partidas de cada time."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM fixtures WHERE fixture_id = %s", (fixture_id,))
    fix = cur.fetchone()
    if not fix:
        cur.close(); conn.close()
        raise HTTPException(404, "Fixture não encontrado")

    home_id  = fix["home_team_id"]
    away_id  = fix["away_team_id"]
    league   = fix["league_id"]

    def get_team_stats(team_id, context):
        cur.execute("""
            SELECT games_count,
                   avg_goals_for, avg_goals_against, avg_total_goals,
                   avg_corners_for, avg_corners_against,
                   avg_shots_on_for, avg_shots_on_against,
                   avg_possession_for,
                   avg_yellow_for, avg_red_for
            FROM team_statistics
            WHERE team_id = %s AND league_id = %s AND context_type = %s
            ORDER BY season DESC LIMIT 1
        """, (team_id, league, context))
        row = cur.fetchone()
        return dict(row) if row else {}

    def get_recent(team_id):
        cur.execute("""
            SELECT ms.fixture_id, ms.match_date, ms.league_id,
                   ms.home_team_id, ms.away_team_id,
                   ms.home_goals, ms.away_goals, ms.total_goals,
                   ms.home_corners, ms.away_corners, ms.total_corners,
                   ms.home_yellow_cards, ms.away_yellow_cards, ms.total_yellow_cards,
                   ms.home_red_cards, ms.away_red_cards, ms.total_red_cards,
                   ms.home_fouls, ms.away_fouls,
                   ms.home_shots_on, ms.away_shots_on,
                   ms.home_possession, ms.away_possession,
                   ms.status
            FROM match_statistics ms
            WHERE (ms.home_team_id = %s OR ms.away_team_id = %s)
              AND ms.status IN ('FT','AET','PEN')
              AND ms.fixture_id != %s
            ORDER BY ms.match_date DESC
            -- 40, e nao 15, POR CAUSA do filtro Casa/Fora da tela.
            --
            -- O painel do jogo corta por mando DEPOIS de receber esta lista.
            -- Com 15 jogos, escolher "Casa" e "15J" devolvia os sete ou oito
            -- que por acaso foram em casa, e o rotulo "15J" mentia sem nenhum
            -- sintoma: a media aparecia normal, calculada sobre metade da
            -- amostra pedida. 40 jogos garantem 15 de cada lado com folga.
            LIMIT 40
        """, (team_id, team_id, fixture_id))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["is_home"] = (r["home_team_id"] == team_id)

        # Enrich with team names
        all_ids = set()
        for r in rows:
            all_ids.add(r["home_team_id"])
            all_ids.add(r["away_team_id"])
        if all_ids:
            cur.execute("""
                SELECT DISTINCT ON (team_id) team_id, name
                FROM teams WHERE team_id = ANY(%s)
                ORDER BY team_id, season DESC
            """, (list(all_ids),))
            names = {r["team_id"]: r["name"] for r in cur.fetchall()}
            for r in rows:
                r["home_team_name"] = names.get(r["home_team_id"], "")
                r["away_team_name"] = names.get(r["away_team_id"], "")
        return rows

    home_stats   = get_team_stats(home_id, "HOME")
    away_stats   = get_team_stats(away_id, "AWAY")
    home_recent  = get_recent(home_id)
    away_recent  = get_recent(away_id)

    cur.close(); conn.close()
    return {
        "fixture": dict(fix),
        "home_stats":  home_stats,
        "away_stats":  away_stats,
        "home_recent": home_recent,
        "away_recent": away_recent,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RAIO-X DO JOGO (2026-10-06)
#
# A aba Jogos virou o lugar de pesquisar antes de montar um bilhete: o que cada
# time faz, o que cada JOGADOR faz, o confronto e o arbitro. A rota devolve as
# SERIES jogo a jogo, e nao medias prontas, de proposito: a tela deixa a pessoa
# escolher a linha (1+ chute no alvo, 9.5 escanteios...) e conta quantas vezes
# ela bateu nos ultimos N. Media pronta respondia uma pergunta so'; a serie
# responde todas as linhas sem voltar ao servidor.
#
# So' banco, nenhuma chamada a API-Football: abrir o Raio-X de vinte jogos nao
# pode custar cota.
# ─────────────────────────────────────────────────────────────────────────────

_JOGOS_RAIO_X = 10
_H2H_MAX = 8


def _serie_do_time(linhas: list, team_id: int) -> list:
    """Linhas de `_ultimos_jogos` de um time -> jogos do ponto de vista dele."""
    jogos = []
    for r in linhas:
        if r["team_id"] != team_id:
            continue
        casa = r["home_team_id"] == team_id
        lado, outro = ("home", "away") if casa else ("away", "home")
        jogos.append({
            "fixture_id": r["fixture_id"],
            "data": r["match_date"].isoformat() if r["match_date"] else None,
            "em_casa": casa,
            "adversario_id": r[f"{outro}_team_id"],
            "gols_pro": r[f"{lado}_goals"], "gols_contra": r[f"{outro}_goals"],
            "escanteios_pro": r[f"{lado}_corners"], "escanteios_contra": r[f"{outro}_corners"],
            "amarelos_pro": r[f"{lado}_yellow_cards"], "amarelos_contra": r[f"{outro}_yellow_cards"],
            "vermelhos_pro": r[f"{lado}_red_cards"], "vermelhos_contra": r[f"{outro}_red_cards"],
            "chutes_alvo_pro": r[f"{lado}_shots_on"], "chutes_alvo_contra": r[f"{outro}_shots_on"],
            "faltas_pro": r[f"{lado}_fouls"], "faltas_contra": r[f"{outro}_fouls"],
            "posse": r[f"{lado}_possession"],
            # 1o TEMPO (folha do 1o tempo, coletada desde 27/09). O 2o tempo a
            # tela tira por conta (total - 1o). Null = jogo antigo, sem folha.
            "gols_pro_1t": r.get(f"{lado}_goals_ht"), "gols_contra_1t": r.get(f"{outro}_goals_ht"),
            "escanteios_pro_1t": r.get(f"{lado}_corners_1h"),
            "escanteios_contra_1t": r.get(f"{outro}_corners_1h"),
            "amarelos_pro_1t": r.get(f"{lado}_yellow_cards_1h"),
            "amarelos_contra_1t": r.get(f"{outro}_yellow_cards_1h"),
            "chutes_alvo_pro_1t": r.get(f"{lado}_shots_on_1h"),
            "chutes_alvo_contra_1t": r.get(f"{outro}_shots_on_1h"),
        })
    return jogos


def _nomes_dos_times(cur, ids: set) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    cur.execute("""
        SELECT DISTINCT ON (team_id) team_id, name
        FROM teams WHERE team_id = ANY(%s)
        ORDER BY team_id, season DESC
    """, (ids,))
    return {r["team_id"]: r["name"] for r in cur.fetchall()}


def _titulares_provaveis(cur, fixture_id: int, team_ids: list) -> dict:
    """Quem deve comecar jogando, por time, e de onde veio a informacao.

    Ordem de confianca: a escalacao do PROPRIO jogo (`fixture_lineups`, oficial
    ou provavel; os dois times na mesma lista, e quem separa e' a intersecao
    com os jogadores de cada time, feita em _jogadores_dos_times); a do proprio
    jogo ja' disputado (`team_lineups`); senao a ultima que o time usou.

    Volta {team_id: (ids, fonte)}. Uma leitura de `fixture_lineups` pros dois
    times, e `team_lineups` so' pra quem ficou sem.
    """
    saida = {t: (set(), "") for t in team_ids}
    try:
        cur.execute("SELECT oficial, titulares FROM fixture_lineups WHERE fixture_id = %s",
                    (fixture_id,))
        r = cur.fetchone()
        if r and r["titulares"]:
            fonte = "escalacao oficial" if r["oficial"] else "escalacao provavel"
            return {t: (set(r["titulares"]), fonte) for t in team_ids}

        # A do jogo, ou a mais recente de cada time · DISTINCT ON pega uma
        # linha por time no indice (team_id, match_date DESC).
        cur.execute("""
            SELECT DISTINCT ON (team_id) team_id, titulares, fixture_id
            FROM team_lineups
            WHERE team_id = ANY(%s) AND cardinality(titulares) > 0
            ORDER BY team_id, (fixture_id = %s) DESC, match_date DESC
        """, (list(team_ids), fixture_id))
        for r in cur.fetchall():
            fonte = "escalacao do jogo" if r["fixture_id"] == fixture_id else "ultima escalacao"
            saida[r["team_id"]] = (set(r["titulares"]), fonte)
    except Exception:
        logger.warning("[RAIO-X] escalacao indisponivel", exc_info=True)
        # Sem o rollback, a transacao abortada derrubaria as consultas
        # seguintes do Raio-X (jogadores, arbitro) por causa de um enfeite.
        try:
            cur.connection.rollback()
        except Exception:
            pass
    return saida


_CAMPOS_JOGADOR = {
    "chutes": "shots_total", "chutes_alvo": "shots_on", "gols": "goals_total",
    "assistencias": "assists", "faltas": "fouls_committed", "faltas_sofridas": "fouls_drawn",
    "desarmes": "tackles_total", "defesas": "saves", "amarelos": "cards_yellow",
    "passes": "passes_total", "dribles": "dribbles_success",
}


def _jogadores_dos_times(cur, jogos_por_time: dict, titulares: dict) -> dict:
    """Jogadores de cada time nos jogos da serie dele, numa consulta so'.

    `fixture_id = ANY(...)` cai no idx_pms_fixture: sao no maximo 2 x 20 jogos,
    o banco busca as fichas desses jogos e o filtro de time separa os lados.
    """
    todos = sorted({f for ids in jogos_por_time.values() for f in ids})
    saida = {t: [] for t in jogos_por_time}
    if not todos:
        return saida
    colunas = ", ".join(sorted(set(_CAMPOS_JOGADOR.values())))
    cur.execute(f"""
        SELECT team_id, fixture_id, match_date, player_id, player_name, position,
               minutes, rating, is_substitute, {colunas}
        FROM player_match_stats
        WHERE fixture_id = ANY(%s) AND team_id = ANY(%s) AND minutes > 0
        ORDER BY match_date DESC
    """, (todos, list(jogos_por_time)))

    por_jogador: dict[tuple, dict] = {}
    for r in cur.fetchall():
        team_id = r["team_id"]
        # Jogo da serie DO OUTRO time (um confronto entre os dois aparece nas
        # duas): a ficha so' conta pro time de quem e' a serie.
        if team_id not in jogos_por_time or r["fixture_id"] not in jogos_por_time[team_id]:
            continue
        if not r["minutes"]:
            continue   # banco sem entrar nao e' amostra de nada
        j = por_jogador.setdefault((team_id, r["player_id"]), {
            "player_id": r["player_id"], "nome": r["player_name"],
            "posicao": r["position"], "jogos": [], "_time": team_id,
        })
        j["jogos"].append({
            "fixture_id": r["fixture_id"],
            "minutos": r["minutes"],
            "titular": not r["is_substitute"],
            "nota": float(r["rating"]) if r["rating"] is not None else None,
            **{k: r[col] for k, col in _CAMPOS_JOGADOR.items()},
        })

    for j in por_jogador.values():
        team_id = j.pop("_time")
        j["titular_provavel"] = j["player_id"] in titulares.get(team_id, (set(), ""))[0]
        j["minutos_total"] = sum(g["minutos"] for g in j["jogos"])
        saida[team_id].append(j)
    # Titular provavel primeiro, depois quem mais jogou: e' a ordem em que a
    # pessoa procura o jogador pra montar o bilhete.
    for lista in saida.values():
        lista.sort(key=lambda j: (not j["titular_provavel"], -j["minutos_total"]))
    return saida


def _arbitro(cur, nome: str | None, n: int) -> dict | None:
    # Pela chave do nome, nao pelo texto exato (2026-10-07): a API escreve o
    # mesmo arbitro como "Raphael Claus" e "Raphael Claus, Brazil", e o Raio-X
    # mostrava so' os jogos da grafia de hoje. Ver arbitro.py.
    chave = chave_do_arbitro(nome)
    if not chave:
        return None
    cur.execute(f"""
        SELECT match_date, home_yellow_cards, away_yellow_cards,
               home_red_cards, away_red_cards, home_fouls, away_fouls
        FROM match_statistics
        WHERE {sql_chave('referee')} = %s AND status IN ('FT','AET','PEN')
        ORDER BY match_date DESC LIMIT %s
    """, (chave, n))
    jogos = [{
        "amarelos": (r["home_yellow_cards"] or 0) + (r["away_yellow_cards"] or 0),
        "vermelhos": (r["home_red_cards"] or 0) + (r["away_red_cards"] or 0),
        "faltas": ((r["home_fouls"] or 0) + (r["away_fouls"] or 0))
                  if r["home_fouls"] is not None and r["away_fouls"] is not None else None,
    } for r in cur.fetchall()]
    return {"nome": nome, "jogos": jogos}


#: Quanto tempo o Raio-X de um jogo serve sem voltar ao banco. Tudo nele e'
#: historico (jogos encerrados) mais a escalacao, que muda poucas vezes por
#: dia: tres minutos nao escondem nada que importe, e um jogo grande aberto
#: por cem pessoas na mesma hora vira UMA montagem (o cache_publico e'
#: single-flight: quem chega durante o calculo espera o resultado dele).
_RAIO_X_TTL = 180


@router.get("/{fixture_id}/raio-x")
def get_raio_x(
    fixture_id: int,
    current_user: dict = Depends(get_current_user),
    home: Optional[int] = Query(None, description="time da casa, se o jogo ainda nao estiver em `fixtures`"),
    away: Optional[int] = Query(None),
    league: Optional[int] = Query(None),
    n: int = Query(_JOGOS_RAIO_X, ge=5, le=20),
):
    """Tudo pra montar bilhete sobre um jogo · ver o bloco acima.

    O dado nao depende de quem pede, entao a chave do cache e' so' o jogo.
    """
    return cache_publico.obter(
        f"raio-x:{fixture_id}:{home}:{away}:{n}", _RAIO_X_TTL,
        lambda: _montar_raio_x(fixture_id, home, away, league, n),
    )


@router.get("/{fixture_id}/escalacao")
def get_escalacao(
    fixture_id: int,
    current_user: dict = Depends(get_current_user),
    home: Optional[int] = Query(None),
    away: Optional[int] = Query(None),
):
    """Campinho do Raio-X: escalação oficial ou provável e os desfalques.

    Rota separada do Raio-X de propósito: ela fala com a API-Football (o
    Raio-X é só banco) e muda perto do apito, enquanto o resto é histórico.
    Ver escalacao.py.
    """
    import escalacao
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT home_team_id, away_team_id FROM fixtures WHERE fixture_id = %s",
                    (fixture_id,))
        fix = cur.fetchone()
        home_id = (fix or {}).get("home_team_id") or home
        away_id = (fix or {}).get("away_team_id") or away
        if not home_id or not away_id:
            raise HTTPException(404, "Jogo nao encontrado")
        return escalacao.escalacao_do_jogo(cur, fixture_id, home_id, away_id)
    finally:
        cur.close(); conn.close()


@router.get("/{fixture_id}/classificacao")
def get_classificacao(
    fixture_id: int,
    current_user: dict = Depends(get_current_user),
    league: Optional[int] = Query(None),
):
    """A tabela da liga do jogo (2026-10-07, pedido do usuario).

    Le' `league_standings`, que a coleta de classificacao refaz inteira a cada
    passada (geral, casa e fora). So' banco · e muda uma vez por rodada, entao
    10 minutos de cache nao escondem nada. Liga de grupos volta separada por
    `grupo`, na ordem da posicao.
    """
    def montar():
        conn = get_connection()
        cur = conn.cursor()
        try:
            liga = league
            if not liga:
                cur.execute("SELECT league_id FROM fixtures WHERE fixture_id = %s", (fixture_id,))
                linha = cur.fetchone()
                liga = linha["league_id"] if linha else None
            if not liga:
                raise HTTPException(404, "Liga do jogo nao encontrada")
            cur.execute("""
                SELECT group_name, team_id, team_name, rank, points, goals_diff, form,
                       description, played, win, draw, lose, goals_for, goals_against,
                       home_played, home_win, home_draw, home_lose, home_goals_for, home_goals_against,
                       away_played, away_win, away_draw, away_lose, away_goals_for, away_goals_against
                  FROM league_standings
                 WHERE league_id = %s
                   AND season = (SELECT MAX(season) FROM league_standings WHERE league_id = %s)
                 ORDER BY group_name NULLS FIRST, rank
            """, (liga, liga))
            return {"league_id": liga, "linhas": [dict(r) for r in cur.fetchall()]}
        finally:
            cur.close(); conn.close()

    return cache_publico.obter(f"classificacao:{fixture_id}:{league}", 600, montar)


def _montar_raio_x(fixture_id: int, home, away, league, n: int) -> dict:
    """Sete consultas numa conexao so', todas em indice · ver cada helper."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT fixture_id, league_id, season, home_team_id, away_team_id,
                   home_team, away_team, match_datetime, status, referee, round
            FROM fixtures WHERE fixture_id = %s
        """, (fixture_id,))
        fix = cur.fetchone()
        fix = dict(fix) if fix else {}
        # Jogo de data que a coleta ainda nao trouxe pro banco: a lista veio da
        # API, entao os ids dos times chegam por parametro.
        home_id = fix.get("home_team_id") or home
        away_id = fix.get("away_team_id") or away
        if not home_id or not away_id:
            raise HTTPException(404, "Jogo nao encontrado")

        antes_de = fix.get("match_datetime")
        ultimos = _ultimos_jogos(cur, [home_id, away_id], antes_de, n)
        serie_home = _serie_do_time(ultimos, home_id)
        serie_away = _serie_do_time(ultimos, away_id)

        # Confronto: as duas ordens de mando como metades separadas, cada uma
        # no indice do mandante · mesmo motivo do UNION ALL em _ultimos_jogos.
        cur.execute("""
            SELECT * FROM (
                (SELECT match_date, home_team_id, away_team_id, home_goals, away_goals,
                        home_corners, away_corners, home_yellow_cards, away_yellow_cards
                   FROM match_statistics
                  WHERE home_team_id = %s AND away_team_id = %s
                    AND status IN ('FT','AET','PEN')
                  ORDER BY match_date DESC LIMIT %s)
                UNION ALL
                (SELECT match_date, home_team_id, away_team_id, home_goals, away_goals,
                        home_corners, away_corners, home_yellow_cards, away_yellow_cards
                   FROM match_statistics
                  WHERE home_team_id = %s AND away_team_id = %s
                    AND status IN ('FT','AET','PEN')
                  ORDER BY match_date DESC LIMIT %s)
            ) h2h
            ORDER BY match_date DESC LIMIT %s
        """, (home_id, away_id, _H2H_MAX, away_id, home_id, _H2H_MAX, _H2H_MAX))
        h2h = [{
            "data": r["match_date"].isoformat() if r["match_date"] else None,
            "home_team_id": r["home_team_id"], "away_team_id": r["away_team_id"],
            "home_goals": r["home_goals"], "away_goals": r["away_goals"],
            "escanteios": (r["home_corners"] or 0) + (r["away_corners"] or 0)
                          if r["home_corners"] is not None and r["away_corners"] is not None else None,
            "amarelos": (r["home_yellow_cards"] or 0) + (r["away_yellow_cards"] or 0),
        } for r in cur.fetchall()]

        titulares = _titulares_provaveis(cur, fixture_id, [home_id, away_id])
        jogadores = _jogadores_dos_times(cur, {
            home_id: {j["fixture_id"] for j in serie_home},
            away_id: {j["fixture_id"] for j in serie_away},
        }, titulares)

        nomes = _nomes_dos_times(
            cur, {home_id, away_id}
                 | {j["adversario_id"] for j in serie_home + serie_away})
        for j in serie_home + serie_away:
            j["adversario"] = nomes.get(j["adversario_id"], "")

        arbitro = _arbitro(cur, fix.get("referee"), 15)
    finally:
        cur.close(); conn.close()

    return {
        "fixture": {
            "fixture_id": fixture_id,
            "league_id": fix.get("league_id") or league,
            "home_team_id": home_id, "away_team_id": away_id,
            "home_team": fix.get("home_team") or nomes.get(home_id, ""),
            "away_team": fix.get("away_team") or nomes.get(away_id, ""),
            "match_datetime": antes_de.isoformat() if antes_de else None,
            "status": fix.get("status"),
            "round": fix.get("round"),
        },
        "times": {
            "home": {"team_id": home_id, "jogos": serie_home},
            "away": {"team_id": away_id, "jogos": serie_away},
        },
        "h2h": h2h,
        "arbitro": arbitro,
        "jogadores": {
            "home": {"fonte_titulares": titulares[home_id][1], "lista": jogadores[home_id]},
            "away": {"fonte_titulares": titulares[away_id][1], "lista": jogadores[away_id]},
        },
    }
