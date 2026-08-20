import logging
import traceback
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
from auth_utils import get_current_user_optional
from database import get_connection
from data_br import HOJE_BR, TZ_BR, data_br
from stake_plan import STAKE_PADRAO, stake_de, rotulo_curto

# Peso de cada pipeline em unidades, lido uma vez · os SELECTs sao f-strings
# e interpolar `STAKE_PADRAO['vip']` la dentro exigiria aspas aninhadas.
_P_VIP  = STAKE_PADRAO['vip']
_P_FREE = STAKE_PADRAO['free']
_P_MULT = STAKE_PADRAO['multiplas']
_P_ALAV = STAKE_PADRAO['alavancagem']

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])

LOCAL_LOGOS: dict[int, str] = {
    1: "/logo-copa-mundo.png",
}


@router.get("/leagues")
def public_leagues():
    """Ligas ativas cadastradas no sistema · sem autenticação."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(
            "SELECT league_id, name, season FROM leagues ORDER BY league_id"
        )
        rows = cur.fetchall()
        return [
            {
                "league_id": r["league_id"],
                "name":      r["name"],
                "season":    r["season"],
                "logo_url":  LOCAL_LOGOS.get(
                    r["league_id"],
                    # Proxy do backend (main.py:/api/proxy/league) baixa e cacheia em disco --
                    # hotlink direto pro CDN da API-Sports no browser costuma cair no fallback
                    # genérico (hotlink protection/rate limit do lado deles).
                    f"/api/proxy/league/{r['league_id']}.png"
                ),
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


def _q(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception as e:
        logger.error("[PUBLIC] _q error: %s", e)
        traceback.print_exc()
        cur.connection.rollback()
        return []


def _q1(cur, sql, params=()):
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    except Exception as e:
        logger.error("[PUBLIC] _q1 error: %s", e)
        traceback.print_exc()
        cur.connection.rollback()
        return None


def _qualificar(date_cond: str, alias: str) -> str:
    """Prefixa a coluna do filtro de data com o alias da tabela de picks.

    `date_cond` chega como "AND TO_CHAR(match_date, 'YYYY-MM') = %s", sem
    prefixo. Os builders que dao JOIN em match_statistics (que TAMBEM tem
    match_date) viravam "column reference match_date is ambiguous" -- e o erro
    nao aparecia em lugar nenhum: _collect_results roda cada sub-query isolada
    e engole a falha, entao o tipo de pick sumia do historico filtrado por mes
    em vez de dar erro. No sumario, que usa o UNION inteiro, o mes filtrado
    voltava vazio.
    """
    return date_cond.replace("match_date", f"{alias}.match_date")


def _sub_vip(date_cond: str) -> str:
    # league via match_statistics, nao fixtures -- fixtures e' so fila
    # operacional, o registro ja resolvido/graded quase sempre ja saiu de
    # la; match_statistics e' o registro permanente (sem FK, nunca deletado).
    return f"""
        SELECT pv.match_date,
               pv.home_team_name, pv.away_team_name,
               pv.home_team_id,   pv.away_team_id,
               pv.market, pv.line, pv.odd,
               pv.result, pv.profit * {_P_VIP} AS profit,
               {_P_VIP}::numeric AS stake,
               'vip' AS source,
               ms.league_id AS league_id,
               COALESCE(l.name, 'Liga ' || ms.league_id) AS league_name
        FROM picks_vip pv
        LEFT JOIN match_statistics ms ON ms.fixture_id = pv.fixture_id
        LEFT JOIN leagues l ON l.league_id = ms.league_id
        WHERE pv.result IS NOT NULL {_qualificar(date_cond, "pv")}
    """

def _sub_free(date_cond: str) -> str:
    return f"""
        SELECT pf.match_date,
               pf.home_team AS home_team_name, pf.away_team AS away_team_name,
               COALESCE(pf.home_team_id, f.home_team_id,
                   (SELECT fx.home_team_id FROM fixtures fx
                    WHERE fx.home_team = pf.home_team AND fx.home_team_id IS NOT NULL LIMIT 1)
               ) AS home_team_id,
               COALESCE(pf.away_team_id, f.away_team_id,
                   (SELECT fx.away_team_id FROM fixtures fx
                    WHERE fx.away_team = pf.away_team AND fx.away_team_id IS NOT NULL LIMIT 1)
               ) AS away_team_id,
               pf.market, pf.line, pf.odd,
               pf.result, pf.profit * {_P_FREE} AS profit,
               {_P_FREE} AS stake,
               'free' AS source,
               COALESCE(pf.league_id, ms.league_id) AS league_id,
               COALESCE(pf.league_name, l.name, 'Liga ' || COALESCE(pf.league_id, ms.league_id)) AS league_name
        FROM picks_free pf
        LEFT JOIN fixtures f ON f.fixture_id = pf.fixture_id
        LEFT JOIN match_statistics ms ON ms.fixture_id = pf.fixture_id
        LEFT JOIN leagues l ON l.league_id = COALESCE(pf.league_id, ms.league_id)
        WHERE pf.result IS NOT NULL {_qualificar(date_cond, "pf")}
    """

def _sub_mult(date_cond: str) -> str:
    return f"""
        SELECT match_date,
               CONCAT('Múltipla · ', JSONB_ARRAY_LENGTH(games::jsonb), ' sel.') AS home_team_name,
               NULL AS away_team_name,
               NULL::INTEGER AS home_team_id, NULL::INTEGER AS away_team_id,
               'Múltipla' AS market, NULL AS line, total_odd AS odd,
               result, profit * {_P_MULT} AS profit,
               {_P_MULT}::numeric AS stake,
               'multiplas' AS source,
               NULL::INTEGER AS league_id,
               'Múltiplas' AS league_name
        FROM picks_multiplas
        WHERE result IS NOT NULL {date_cond}
    """

def _sub_alav(date_cond: str) -> str:
    return f"""
        SELECT match_date,
               home_team_1 AS home_team_name, away_team_1 AS away_team_name,
               NULL::INTEGER AS home_team_id, NULL::INTEGER AS away_team_id,
               market_1 AS market, line_1 AS line, odd_combined AS odd,
               result, profit * {_P_ALAV} AS profit,
               {_P_ALAV}::numeric AS stake,
               'alavancagem' AS source,
               NULL::INTEGER AS league_id,
               'Alavancagem' AS league_name
        FROM picks_alavancagem
        WHERE result IS NOT NULL {date_cond}
    """

def _sub_mercado(tabela: str, source: str, rotulo: str):
    """Builder pras tabelas de mercado proprio (picks_faltas, picks_goleiros).

    A forma delas espelha picks_free -- um jogo, um mercado, uma odd -- entao o
    SELECT e' o mesmo, so' muda a tabela. Fabrica em vez de duas funcoes
    copiadas: e' o quarto lugar do projeto onde esse SELECT se repete, e cada
    copia e' mais uma chance de faltas e goleiros divergirem em silencio.

    Entrar aqui e' o que faz os dois mercados contarem no ROI publico, no
    historico e nos filtros por tipo -- e' a fonte unica que todas as
    estatisticas do site consomem.
    """
    peso = stake_de(source)

    def builder(date_cond: str) -> str:
        # Sem JOIN em match_statistics de proposito. Os dois pipelines sempre
        # gravam league_id, entao o fallback nao e' necessario -- e a tabela
        # tambem tem uma coluna match_date, o que deixava o `date_cond` (que
        # chega como "AND TO_CHAR(match_date, ...)", sem prefixo) ambiguo. O
        # erro nao aparecia: _collect_results roda cada sub-query isolada e
        # engole a falha, entao os dois mercados simplesmente sumiam do
        # historico quando alguem filtrava por mes.
        return f"""
        SELECT p.match_date,
               p.home_team AS home_team_name, p.away_team AS away_team_name,
               COALESCE(p.home_team_id, f.home_team_id) AS home_team_id,
               COALESCE(p.away_team_id, f.away_team_id) AS away_team_id,
               p.market, p.line, p.odd,
               p.result, p.profit * {peso} AS profit,
               {peso} AS stake,
               '{source}' AS source,
               p.league_id AS league_id,
               COALESCE(l.name, '{rotulo}') AS league_name
        FROM {tabela} p
        LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
        LEFT JOIN leagues l ON l.league_id = p.league_id
        WHERE p.result IS NOT NULL {_qualificar(date_cond, "p")}
    """
    return builder


_SUB_BUILDERS = {
    "vip":        _sub_vip,
    "free":       _sub_free,
    "multiplas":  _sub_mult,
    "alavancagem":_sub_alav,
    "faltas":     _sub_mercado("picks_faltas",   "faltas",   "Faltas"),
    "goleiros":   _sub_mercado("picks_goleiros", "goleiros", "Defesas"),
}

def _build_union(date_cond: str, source: Optional[str]) -> str:
    """Monta UNION ALL das tabelas de picks (_SUB_BUILDERS) com colunas
    normalizadas."""
    if source and source in _SUB_BUILDERS:
        return _SUB_BUILDERS[source](date_cond)
    return " UNION ALL ".join(fn(date_cond) for fn in _SUB_BUILDERS.values())


def _pagina_de_resultados(cur, date_cond: str, date_params: tuple, source: Optional[str],
                          limit: int = 30, offset: int = 0) -> tuple:
    """(linhas da pagina, total) numa consulta so'.

    ANTES ERAM DOZE IDAS AO BANCO. `_collect_results` rodava uma consulta por
    fonte de pick (6) e `_count_recent` outra por fonte (6), e as duas coisas
    juntas respondiam por mais da metade do tempo de /public/results -- medido
    em 2026-08-13: a rota levava 1893ms enquanto as consultas em si somavam
    menos de 5ms de trabalho no banco. O custo era ida e volta, nao SQL.

    `_build_union` ja normalizava as colunas das 6 fontes e ja era usado pelo
    sumario, entao a peca existia; faltava usa-la aqui. `COUNT(*) OVER ()`
    traz o total junto da pagina, dispensando a segunda varredura.

    O CAMINHO LENTO CONTINUA EXISTINDO, de proposito. A versao por fonte
    isolada nasceu pra uma falha numa tabela nao apagar as outras (coluna que
    faltou numa migracao derruba aquela fonte, nao o historico inteiro). Um
    UNION nao tem essa propriedade: se uma perna quebra, quebra tudo. Entao o
    UNION e' tentado primeiro e, se levantar, cai no laco antigo -- rapido no
    caso normal, resiliente no caso ruim.
    """
    union = _build_union(date_cond, source if source in _SUB_BUILDERS else None)
    p = date_params if source in _SUB_BUILDERS else date_params * len(_SUB_BUILDERS)
    # ORDEM TOTAL, e nao so' "bonita". Paginar sem criterio de desempate deixa
    # o Postgres livre pra devolver empates em ordem diferente a cada consulta,
    # e ai a pagina 2 repete linha da 1 e pula outra. Foi o que a comparacao
    # com o caminho antigo mostrou: mesmo total, mesmas colunas, CONTEUDO
    # diferente na pagina 2.
    #
    # O desempate por fonte reproduz o que o caminho antigo fazia sem querer:
    # ele concatenava as sub-queries na ordem de _SUB_BUILDERS e ordenava com
    # sort estavel, entao empate de data+resultado caia nessa ordem. Deriva da
    # constante, nunca de lista escrita a mao -- registrar um mercado novo nao
    # pode exigir lembrar deste lugar.
    ordem_fontes = list(_SUB_BUILDERS.keys())
    try:
        linhas = _q(cur, f"""
            SELECT *, COUNT(*) OVER () AS _total
            FROM ({union}) t
            ORDER BY match_date DESC, result DESC,
                     array_position(%s::text[], source),
                     market NULLS LAST, line NULLS LAST, home_team_name NULLS LAST
            LIMIT %s OFFSET %s
        """, p + (ordem_fontes, limit, offset))
        total = int(linhas[0]["_total"]) if linhas else 0
        for r in linhas:
            r.pop("_total", None)
        return linhas, total
    except Exception:
        logger.warning("[RESULTS] union falhou, caindo pro caminho por fonte", exc_info=True)
        cur.connection.rollback()
        return (_collect_results(cur, date_cond, date_params, source, limit, offset),
                _count_recent(cur, date_cond, date_params, source))


def _collect_results(cur, date_cond: str, date_params: tuple, source: Optional[str],
                     limit: int = 30, offset: int = 0) -> list:
    """Corre cada sub-query separada, assim uma falha não apaga as outras.
    Paginação: cada sub-query busca até offset+limit linhas (pior caso, se a
    janela [offset, offset+limit) inteira vier de uma unica fonte) -- depois
    do merge+sort global, so' entao aplica o slice [offset:offset+limit].

    Caminho de FALLBACK desde 2026-08-13 (ver _pagina_de_resultados): custa 6
    idas ao banco, entao so' roda quando o UNION falha."""
    builders = [_SUB_BUILDERS[source]] if (source and source in _SUB_BUILDERS) else list(_SUB_BUILDERS.values())
    fetch_n = offset + limit
    rows: list = []
    for fn in builders:
        sub = fn(date_cond)
        try:
            batch = _q(cur, f"SELECT * FROM ({sub}) t ORDER BY match_date DESC, result LIMIT %s", date_params + (fetch_n,))
        except Exception:
            # A propriedade que este caminho existe pra ter: uma fonte quebrada
            # sai do resultado, nao derruba as outras cinco.
            logger.warning("[RESULTS] fonte falhou no fallback", exc_info=True)
            cur.connection.rollback()
            continue
        rows.extend(batch)
    rows.sort(key=lambda r: (str(r["match_date"]), str(r.get("result",""))), reverse=True)
    return rows[offset:offset + limit]


def _count_recent(cur, date_cond: str, date_params: tuple, source: Optional[str]) -> int:
    """Total de linhas pra paginação de 'recent' -- mesma defesa por sub-query
    de _collect_results (uma fonte com erro conta 0 em vez de derrubar o total)."""
    builders = [_SUB_BUILDERS[source]] if (source and source in _SUB_BUILDERS) else list(_SUB_BUILDERS.values())
    total = 0
    for fn in builders:
        sub = fn(date_cond)
        try:
            row = _q1(cur, f"SELECT COUNT(*) AS c FROM ({sub}) t", date_params)
        except Exception:
            logger.warning("[RESULTS] contagem de fonte falhou no fallback", exc_info=True)
            cur.connection.rollback()
            continue
        total += row["c"] if row else 0
    return total


@router.get("/results")
def public_results(
    month:  Optional[str] = Query(None, description="YYYY-MM · filtra por mês"),
    source: Optional[str] = Query(None, description="all | vip | free | multiplas | alavancagem | faltas | goleiros"),
    recent_limit:  int = Query(10, ge=1, le=50, description="Itens por página em 'recent'"),
    recent_offset: int = Query(0, ge=0, description="Offset de paginação em 'recent'"),
    slim: bool = Query(False, description="Pula os blocos que só a página de Resultados usa"),
):
    """Resultados públicos consolidados para a Landing page.

    `slim=1` existe pra Home. Ela le tres coisas -- `summary`, `recent` e o
    TAMANHO de `by_league` -- e recebia sete blocos. Os outros quatro
    (`available_months`, `by_day`, `counts`, `recent_total`) so' a pagina de
    Resultados usa, e cada um custa uma ida ao banco de 154ms (ver
    database.py:71-82) mais o peso no JSON. O `by_day` e' o pior: uma linha por
    dia desde o lancamento, e cresce todo dia.

    Com slim a rota cai de sete consultas pra tres. Sem ele, nada muda: a
    pagina de Resultados continua recebendo a resposta inteira.
    """
    # Mesma varredura em segundo plano de /suggestions/today. Entra aqui
    # também porque esta é a tela que o visitante DESLOGADO abre: sem isso,
    # num dia em que nenhum assinante entrasse no site, o placar público
    # continuaria mostrando "pendente" com os jogos já encerrados.
    try:
        from routers.live import maybe_resolve_pending
        maybe_resolve_pending()
    except Exception:
        logger.warning("[AUTO-RESULT] gatilho em /results falhou", exc_info=True)

    conn = get_connection()
    cur  = conn.cursor()
    try:
        # ── Meses disponíveis (todas as tabelas) ─────────────────────────────
        months_rows = [] if slim else _q(cur, """
            SELECT month, SUM(cnt) AS total FROM (
                SELECT TO_CHAR(match_date, 'YYYY-MM') AS month, COUNT(*) AS cnt
                FROM picks_vip WHERE result IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT TO_CHAR(match_date, 'YYYY-MM'), COUNT(*)
                FROM picks_free WHERE result IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT TO_CHAR(match_date, 'YYYY-MM'), COUNT(*)
                FROM picks_multiplas WHERE result IS NOT NULL GROUP BY 1
                UNION ALL
                SELECT TO_CHAR(match_date, 'YYYY-MM'), COUNT(*)
                FROM picks_alavancagem WHERE result IS NOT NULL GROUP BY 1
            ) t
            GROUP BY month
            HAVING SUM(cnt) > 0
            ORDER BY month DESC
            LIMIT 24
        """)
        available_months = [r["month"] for r in months_rows]

        # ── Filtro de data ────────────────────────────────────────────────────
        if month:
            date_cond   = "AND TO_CHAR(match_date, 'YYYY-MM') = %s"
            date_params = (month,)
        else:
            date_cond   = ""
            date_params = ()

        # Derivado de _SUB_BUILDERS, nunca de lista fixa: com a lista escrita
        # na mao, registrar um mercado novo (faltas/goleiros, 2026-08-01)
        # deixava o numero de placeholders defasado e o filtro por mes
        # quebrava -- erro de contagem de parametro, nao de logica, o tipo que
        # so aparece quando alguem filtra.
        single = source in _SUB_BUILDERS
        union_sql = _build_union(date_cond, source if single else None)
        # cada sub-query tem 1 placeholder; o UNION precisa de um por builder
        p = date_params if single else date_params * len(_SUB_BUILDERS)

        # ── Sumário ───────────────────────────────────────────────────────────
        summary = _q1(cur, f"""
            SELECT
                COUNT(*)                                          AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN')         AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')           AS reds,
                COUNT(*) FILTER (WHERE result = 'PUSH')          AS push,
                COUNT(*) FILTER (WHERE result = 'HALF-WIN')      AS half_wins,
                COUNT(*) FILTER (WHERE result = 'HALF-LOSS')     AS half_losses,
                COALESCE(SUM(profit), 0)                         AS profit,
                COALESCE(SUM(stake),  0)                         AS stake_total,
                ROUND(
                    COALESCE(SUM(profit), 0) /
                    NULLIF(COALESCE(SUM(stake), 0), 0) * 100, 1
                )                                                 AS roi,
                -- A Home so' precisa do NUMERO de ligas cobertas, e lia isso do
                -- tamanho de `by_league`, o que obrigava a montar a quebra por
                -- liga inteira (mais uma varredura do UNION, mais uma consulta
                -- pros nomes). Aqui sai de graca: mesma varredura, mesma linha.
                COUNT(DISTINCT league_id) FILTER (WHERE league_id IS NOT NULL)
                                                                  AS leagues_count,
                -- Quebra de VIP e free pra Home mostrar a MEDIA DE UNIDADES POR
                -- PICK de cada um. Pelo mesmo motivo do `leagues_count` acima:
                -- aqui e' de graca (mesma varredura), e num bloco `by_source`
                -- separado custaria mais uma ida ao banco de 154ms -- que a Home
                -- pagaria em cheio, porque ela chama com slim=1 e um bloco novo
                -- teria que rodar tambem no caminho slim pra servir de algo.
                --
                -- `profit` ja e' unidade (stake fixa de 1 em todo sub-SELECT do
                -- UNION), entao a media e' profit/total direto, sem conversao.
                -- Com `source` filtrado na query, o pipeline de fora vem zerado,
                -- que e' o certo: o recorte pedido manda.
                COALESCE(SUM(profit) FILTER (WHERE source = 'vip'), 0)  AS vip_profit,
                COUNT(*) FILTER (WHERE source = 'vip')                  AS vip_total,
                COALESCE(SUM(profit) FILTER (WHERE source = 'free'), 0) AS free_profit,
                COUNT(*) FILTER (WHERE source = 'free')                 AS free_total
            FROM ({union_sql}) AS t
        """, p)

        # ── Por dia (gráfico) ─────────────────────────────────────────────────
        by_day = [] if slim else _q(cur, f"""
            SELECT
                match_date,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE result = 'GREEN') AS greens,
                COUNT(*) FILTER (WHERE result = 'RED')   AS reds,
                COALESCE(SUM(profit), 0)                 AS profit
            FROM ({union_sql}) AS t
            GROUP BY match_date
            ORDER BY match_date
        """, p)

        # ── Por liga. So' ligas de verdade (league_id IS NOT NULL) -- Múltipla/
        # Alavancagem nao tem league_id real (pernas podem ser de ligas
        # diferentes) e NAO sao ligas, entao ficam de fora desta lista (pedido
        # explicito do usuario: "na liga nao aparece multiplas alavancagem,
        # aparece so ligas mesmo" -- esses tipos continuam cobertos pelo filtro
        # "Fonte" e por `counts` abaixo, so nao entram na quebra POR LIGA).
        # Agrupa por league_id (nao league_name -- o nome denormalizado em
        # picks_free pode estar desatualizado em relacao a leagues.name atual,
        # ex: "Copa do Mundo" vs "Copa do Mundo FIFA" pro mesmo league_id, o
        # que duplicaria a liga em duas linhas).
        #
        # O nome da liga vem por LEFT JOIN, nao por uma segunda consulta a
        # `leagues` montando dicionario em Python. Mesma saida, uma ida a menos.
        by_league = [] if slim else [dict(r) for r in _q(cur, f"""
            SELECT
                t.league_id,
                COUNT(*)                                  AS total,
                COUNT(*) FILTER (WHERE t.result = 'GREEN') AS greens,
                COUNT(*) FILTER (WHERE t.result = 'RED')   AS reds,
                COALESCE(SUM(t.profit), 0)                AS profit,
                COALESCE(SUM(t.stake), 0)                 AS stake_total,
                COALESCE(l.name, 'Liga ' || t.league_id)  AS league_name
            FROM ({union_sql}) AS t
            LEFT JOIN leagues l ON l.league_id = t.league_id
            WHERE t.league_id IS NOT NULL
            GROUP BY t.league_id, l.name
            ORDER BY total DESC
        """, p)]

        # ── Quebra por pipeline, dia a dia ────────────────────────────────────
        #
        # UMA consulta serve as duas coisas que a aba "Por Jogo" mostra: os
        # cards de lucro por produto (VIP, free, múltipla, alavancagem, faltas,
        # defesas) e a curva de cada um no tempo. O agregado por fonte sai da
        # série somando em Python -- não vale uma segunda ida ao banco (154ms,
        # ver database.py:71-82) pra refazer uma soma que já está na mão.
        #
        # Fora do caminho slim: a Home não usa nada disto.
        by_source_day = [] if slim else _q(cur, f"""
            SELECT match_date, source,
                   COUNT(*)                                 AS total,
                   COUNT(*) FILTER (WHERE result = 'GREEN') AS greens,
                   COUNT(*) FILTER (WHERE result = 'RED')   AS reds,
                   COALESCE(SUM(profit), 0)                 AS profit,
                   COALESCE(SUM(stake),  0)                 AS stake_total
            FROM ({union_sql}) AS t
            GROUP BY match_date, source
            ORDER BY match_date
        """, p)

        por_fonte: dict = {}
        for linha in by_source_day:
            acc = por_fonte.setdefault(linha["source"], {
                "source": linha["source"], "total": 0, "greens": 0,
                "reds": 0, "profit": 0.0, "stake_total": 0.0,
            })
            acc["total"]  += int(linha["total"] or 0)
            acc["greens"] += int(linha["greens"] or 0)
            acc["reds"]   += int(linha["reds"] or 0)
            acc["profit"] += float(linha["profit"] or 0)
            acc["stake_total"] += float(linha["stake_total"] or 0)

        by_source = []
        for acc in por_fonte.values():
            acc["profit"] = round(acc["profit"], 2)
            acc["stake_total"] = round(acc["stake_total"], 2)
            acc["win_rate"] = round(acc["greens"] / acc["total"] * 100, 1) if acc["total"] else 0.0
            acc["roi"] = round(acc["profit"] / acc["stake_total"] * 100, 1) if acc["stake_total"] else 0.0
            by_source.append(acc)
        by_source.sort(key=lambda a: a["profit"], reverse=True)

        # ── Recentes (por sub-query para não quebrar tudo se uma coluna faltar) ──
        single_source = source if source in _SUB_BUILDERS else None
        recent, recent_total = _pagina_de_resultados(
            cur, date_cond, date_params, single_source,
            limit=recent_limit, offset=recent_offset)

        # ── Contagem por tipo ─────────────────────────────────────────────────
        counts_row = None if slim else _q1(cur, f"""
            SELECT
                COUNT(*) FILTER (WHERE source = 'vip')        AS vip_total,
                COUNT(*) FILTER (WHERE source = 'free')       AS free_total,
                COUNT(*) FILTER (WHERE source = 'multipla')   AS multipla_total,
                COUNT(*) FILTER (WHERE source = 'alavancagem') AS alavancagem_total,
                COUNT(*) FILTER (WHERE source = 'faltas')     AS faltas_total,
                COUNT(*) FILTER (WHERE source = 'goleiros')   AS goleiros_total
            FROM (
                SELECT 'vip'        AS source FROM picks_vip        WHERE result IS NOT NULL
                UNION ALL
                SELECT 'free'       AS source FROM picks_free       WHERE result IS NOT NULL
                UNION ALL
                SELECT 'multipla'   AS source FROM picks_multiplas  WHERE result IS NOT NULL
                UNION ALL
                SELECT 'alavancagem' AS source FROM picks_alavancagem WHERE result IS NOT NULL
                UNION ALL
                SELECT 'faltas'     AS source FROM picks_faltas     WHERE result IS NOT NULL
                UNION ALL
                SELECT 'goleiros'   AS source FROM picks_goleiros   WHERE result IS NOT NULL
            ) AS t
        """)

        return {
            "available_months": available_months,
            "summary": dict(summary) if summary else {},
            "by_day":  [dict(r) for r in by_day],
            "by_league": by_league,
            "by_source": by_source,
            "by_source_day": [dict(r) for r in by_source_day],
            "recent":  [dict(r) for r in recent],
            "recent_total": recent_total,
            "counts":  dict(counts_row) if counts_row else {},
            # Legenda do plano de stake, montada em stake_plan.py junto com os
            # pesos. Vai na resposta pra que trocar o plano troque o texto da
            # tela no mesmo commit -- legenda velha grudada em numero novo e'
            # pior do que legenda nenhuma.
            "stake_label": rotulo_curto(),
        }
    finally:
        cur.close()
        conn.close()


def _mask_first(full_name: str) -> str:
    """'João da Silva' → 'João S.'"""
    parts = (full_name or "").strip().split()
    if not parts:
        return "Usuário"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0]}."



@router.get("/pick/{pick_type}/{pick_id}")
def public_pick(pick_type: str, pick_id: int):
    """Teaser público de pick para compartilhamento. Nao expoe market/reasoning."""
    valid = {"vip", "free", "multipla", "alavancagem", "faltas", "goleiros"}
    if pick_type not in valid:
        raise HTTPException(400, "Tipo inválido")

    conn = get_connection()
    cur  = conn.cursor()
    try:
        if pick_type == "vip":
            cur.execute("""
                SELECT pv.id, pv.match_date,
                       pv.home_team_name, pv.away_team_name,
                       pv.home_team_id,  pv.away_team_id,
                       COALESCE(l.name, '') AS league_name,
                       f.league_id,
                       pv.odd, pv.result, pv.profit
                FROM picks_vip pv
                LEFT JOIN fixtures f ON f.fixture_id = pv.fixture_id
                LEFT JOIN leagues  l ON l.league_id  = f.league_id
                WHERE pv.id = %s
            """, (pick_id,))
        elif pick_type == "free":
            cur.execute("""
                SELECT pf.id, pf.match_date,
                       pf.home_team AS home_team_name, pf.away_team AS away_team_name,
                       COALESCE(pf.home_team_id, fx.home_team_id) AS home_team_id,
                       COALESCE(pf.away_team_id, fx.away_team_id) AS away_team_id,
                       COALESCE(l.name, '') AS league_name,
                       fx.league_id,
                       pf.odd, pf.result, pf.profit
                FROM picks_free pf
                LEFT JOIN fixtures fx ON fx.fixture_id = pf.fixture_id
                LEFT JOIN leagues   l ON l.league_id   = fx.league_id
                WHERE pf.id = %s
            """, (pick_id,))
        elif pick_type == "multipla":
            cur.execute("""
                SELECT id, match_date, games, total_odd AS odd, result, profit
                FROM picks_multiplas WHERE id = %s
            """, (pick_id,))
        elif pick_type in ("faltas", "goleiros"):
            # Mesmo contrato dos outros: teaser sem market nem reasoning, que
            # e o que o link compartilhado pode mostrar sem entregar a analise.
            tabela = "picks_faltas" if pick_type == "faltas" else "picks_goleiros"
            cur.execute(f"""
                SELECT id, match_date,
                       home_team AS home_team_name, away_team AS away_team_name,
                       odd, result, profit
                FROM {tabela} WHERE id = %s
            """, (pick_id,))
        else:  # alavancagem
            cur.execute("""
                SELECT id, match_date,
                       home_team_1 AS home_team_name, away_team_1 AS away_team_name,
                       odd_combined AS odd, result, profit
                FROM picks_alavancagem WHERE id = %s
            """, (pick_id,))

        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Pick não encontrado")

        d = dict(row)
        if d.get("match_date") and hasattr(d["match_date"], "isoformat"):
            d["match_date"] = d["match_date"].isoformat()

        # Para múltipla: extrai preview dos times sem expor markets
        if pick_type == "multipla" and d.get("games"):
            import json as _json
            games = d["games"] if isinstance(d["games"], list) else _json.loads(d["games"])
            d["teams_preview"] = [
                f"{g.get('home_team', '?')} x {g.get('away_team', '?')}"
                for g in games[:4]
            ]
            d.pop("games", None)

        d["pick_type"] = pick_type
        return d
    finally:
        cur.close()
        conn.close()


@router.get("/today-summary")
def public_today_summary():
    """Contagem de picks publicados hoje (qualquer status, inclusive ainda
    sem resultado -- jogo pode estar rolando) -- sem isso a home so mostrava
    estatisticas agregadas historicas, sem nenhum sinal de atividade do dia
    atual (achado real: usuario relatou 'nao aparece nada do dia' na home)."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        row = _q1(cur, f"""
            SELECT
                COUNT(*) FILTER (WHERE t.source = 'vip')         AS vip,
                COUNT(*) FILTER (WHERE t.source = 'free')        AS free,
                COUNT(*) FILTER (WHERE t.source = 'multiplas')   AS multiplas,
                COUNT(*) FILTER (WHERE t.source = 'alavancagem') AS alavancagem,
                COUNT(*) FILTER (WHERE t.source = 'faltas')      AS faltas,
                COUNT(*) FILTER (WHERE t.source = 'goleiros')    AS goleiros,
                COUNT(*)                                         AS total
            FROM (
                SELECT 'vip'         AS source FROM picks_vip         WHERE match_date = {HOJE_BR}
                UNION ALL
                SELECT 'free'        AS source FROM picks_free        WHERE match_date = {HOJE_BR}
                UNION ALL
                SELECT 'multiplas'   AS source FROM picks_multiplas   WHERE match_date = {HOJE_BR}
                UNION ALL
                SELECT 'alavancagem' AS source FROM picks_alavancagem WHERE match_date = {HOJE_BR}
                UNION ALL
                SELECT 'faltas'      AS source FROM picks_faltas      WHERE match_date = {HOJE_BR}
                UNION ALL
                SELECT 'goleiros'    AS source FROM picks_goleiros    WHERE match_date = {HOJE_BR}
            ) t
        """)
        return dict(row) if row else {"vip": 0, "free": 0, "multiplas": 0,
                                      "alavancagem": 0, "faltas": 0, "goleiros": 0, "total": 0}
    finally:
        cur.close()
        conn.close()


@router.get("/fixtures-today")
def public_fixtures_today(days_ahead: int = Query(0, ge=0, le=7)):
    """Jogos de hoje (ou dias_a_frente adiante) das ligas cobertas, sem
    autenticacao -- so calendario (times, liga, horario), sem odds/picks.
    Usado pro card de compartilhamento 'jogos de hoje/amanha'."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT f.fixture_id, f.home_team, f.away_team,
                   f.home_team_id, f.away_team_id,
                   f.league_id, COALESCE(l.name, 'Liga ' || f.league_id) AS league_name,
                   f.match_datetime
            FROM fixtures f
            LEFT JOIN leagues l ON l.league_id = f.league_id
            WHERE f.match_datetime::date = CURRENT_DATE + (%s * INTERVAL '1 day')
              AND f.status = 'NS'
            ORDER BY f.match_datetime
            LIMIT 8
        """, (days_ahead,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("match_datetime") and hasattr(d["match_datetime"], "isoformat"):
                d["match_datetime"] = d["match_datetime"].isoformat()
            result.append(d)
        return result
    finally:
        cur.close()
        conn.close()


@router.get("/profit-curve")
def public_profit_curve(days: int = Query(180, ge=7, le=1095)):
    """Lucro em unidades por dia e por produto · série crua, sem agregado.

    Existe para a HOME. A página de Resultados já recebe isto dentro de
    /public/results, mas a Home chama aquela rota com `slim=1` justamente para
    cair de sete consultas para três, e pendurar a série lá dentro devolveria o
    custo que o slim tirou -- na chamada que desenha o topo da página, ainda por
    cima.

    Aqui é uma consulta só, chamada à parte e depois do topo: se ela demorar ou
    falhar, o que atrasa é um gráfico abaixo da dobra, não a primeira tela.

    O peso do plano de stake já vem embutido (ver stake_plan.py), então a curva
    fala a mesma unidade do resto do site.
    """
    conn = get_connection()
    cur  = conn.cursor()
    try:
        union_sql = _build_union("AND match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')", None)
        p = (days,) * len(_SUB_BUILDERS)
        rows = _q(cur, f"""
            SELECT match_date, source, COALESCE(SUM(profit), 0) AS profit
            FROM ({union_sql}) AS t
            GROUP BY match_date, source
            ORDER BY match_date
        """, p)
        return [dict(r) for r in rows]
    finally:
        cur.close()
        conn.close()


@router.get("/next-fixtures")
def public_next_fixtures(limit: int = Query(6, ge=1, le=30),
                         date: Optional[str] = Query(None, description="YYYY-MM-DD · dia inteiro em vez de 'daqui pra frente'")):
    """Proximos jogos que a IA ainda vai analisar · sem login.

    Substitui, na Home, a chamada a GET /api/fixtures/today, que era o caminho
    errado por tres motivos ao mesmo tempo:

      1. exige sessao (Depends(get_current_user)), entao pro visitante anonimo
         -- que e' o publico da Home -- ela sempre devolvia 401 e a faixa
         "Na fila da IA" simplesmente nao existia;
      2. cada 401 acionava o interceptor do axios, que tentava /auth/refresh e
         reenviava a requisicao: tres viagens por dia consultado, e a Home
         consultava ate' quatro dias em serie;
      3. quem estava logado pagava pior ainda -- aquela rota bate na
         API-Football liga por liga, dois dias UTC cada, com timeout de 10s.

    Aqui e' uma consulta so' na tabela `fixtures`, que o coletor ja mantem com
    hoje + 2 dias a frente (fixture_collector_service.DIAS_BR = 3).

    A janela nao e' "hoje": e' "daqui pra frente". Quando os jogos do dia ja
    comecaram, a lista anda sozinha pros de amanha em vez de mostrar partida
    que ja rolou -- que era a queixa real ("na fila da IA mostrar os proximos
    jogos do outro dia").

    `match_datetime` esta gravado em horario de Brasilia SEM fuso (o coletor
    converte antes de salvar, ver convert_utc_to_br_naive), entao o corte tem
    que ser contra o relogio de Brasilia, nao contra NOW() -- o banco roda em
    UTC e o filtro adiantaria 3 horas, escondendo os jogos da tarde.

    `date` (YYYY-MM-DD) troca a janela por UM DIA INTEIRO. Existe pro card
    "jogos sendo analisados hoje" da tela de Picks, que antes montava a lista
    varrendo a API-Football liga por liga (GET /api/fixtures/today) e perdia a
    maior parte dos jogos pro teto de requisicoes: com 10 ligas cadastradas sao
    20 chamadas em rajada, e as que estouram o limite voltam vazias em silencio
    -- na pratica so' as primeiras ligas do `ORDER BY league_id` apareciam na
    tela, mesmo com as outras tendo jogo no mesmo dia.

    A tabela local e' a resposta certa pra essa pergunta de qualquer forma: o
    motor analisa o que esta em `fixtures`, entao "o que vai ser analisado" e'
    exatamente esta consulta, sem ida a API nenhuma.
    """
    if date:
        janela = "AND f.match_datetime::date = %s::date"
        param_janela: tuple = (date,)
    else:
        janela = f"AND f.match_datetime >= (NOW() AT TIME ZONE '{TZ_BR}') - INTERVAL '10 minutes'"
        param_janela = ()

    conn = get_connection()
    cur  = conn.cursor()
    try:
        rows = _q(cur, f"""
            SELECT f.fixture_id, f.home_team, f.away_team,
                   f.home_team_id, f.away_team_id,
                   f.league_id, COALESCE(l.name, 'Liga ' || f.league_id) AS league_name,
                   f.match_datetime,
                   EXISTS (SELECT 1 FROM picks_vip  pv WHERE pv.fixture_id = f.fixture_id) AS tem_vip,
                   EXISTS (SELECT 1 FROM picks_free pf WHERE pf.fixture_id = f.fixture_id) AS tem_free
            FROM fixtures f
            LEFT JOIN leagues l ON l.league_id = f.league_id
            WHERE f.status IN ('NS', 'TBD')
              {janela}
            ORDER BY f.match_datetime
            LIMIT %s
        """, param_janela + (limit,))
        result = []
        for r in rows:
            d = dict(r)
            if d.get("match_datetime") and hasattr(d["match_datetime"], "isoformat"):
                d["match_datetime"] = d["match_datetime"].isoformat()

            # So' a EXISTENCIA do pick, nunca o mercado.
            #
            # A rota e' publica: mandar market/line aqui daria de graca o que a
            # Dica do Dia esconde atras de cadastro tres blocos acima na mesma
            # pagina -- bastaria trocar de endpoint no DevTools. "Ja tem pick"
            # e' chamariz; "qual e' o pick" e' o produto.
            tem_vip  = bool(d.pop("tem_vip", False))
            tem_free = bool(d.pop("tem_free", False))
            d["has_pick"]  = tem_vip or tem_free
            d["pick_type"] = "vip" if tem_vip else ("free" if tem_free else None)
            result.append(d)
        return result
    finally:
        cur.close()
        conn.close()


# Colunas da Dica do Dia, uma vez so'. As duas consultas de
# public_free_pick_today (a de hoje e a de reserva) precisam devolver
# exatamente o mesmo formato -- escrever o SELECT duas vezes e' como as duas
# passam a divergir sem ninguem notar.
_FREE_PICK_SELECT = """
    SELECT pf.id, pf.match_date,
           pf.home_team AS home_team_name, pf.away_team AS away_team_name,
           COALESCE(pf.home_team_id, fx.home_team_id) AS home_team_id,
           COALESCE(pf.away_team_id, fx.away_team_id) AS away_team_id,
           pf.odd, pf.result, pf.market, pf.line,
           fx.match_datetime, l.name AS league_name
    FROM picks_free pf
    LEFT JOIN fixtures fx ON fx.fixture_id = pf.fixture_id
    LEFT JOIN leagues  l  ON l.league_id = fx.league_id
"""


@router.get("/free-pick-today")
def public_free_pick_today(request: Request):
    """Dica do Dia (free): a de hoje, ou a ultima publicada.

    Publico, mas mostra MAIS pra quem tem conta: visitante anonimo ve o jogo e
    a odd, e o mercado volta como `locked: true` sem o valor. Quem esta logado
    recebe market e line de verdade.

    O corte e aqui e nao no CSS de proposito. Mandar o mercado e desfocar na
    tela nao esconde nada: o texto continua no JSON e aparece no DevTools. Se
    o campo e a recompensa por criar conta, ele nao pode sair daqui antes.

    Duas correcoes de data, ambas visiveis na Home:

    - o filtro era `CURRENT_DATE`, que e' a data UTC. Entre 21:00 e 00:00 de
      Brasilia o banco ja virou o dia e o Brasil nao, entao a dica do dia
      sumia da Home justamente no horario de pico. Agora usa HOJE_BR.
    - sem pick publicado ainda, devolvia None e a Home ficava com um buraco no
      lugar do card. Desde 01/08 nao existe horario fixo de publicacao, entao
      esse buraco podia durar o dia inteiro. Agora cai na ultima dica
      publicada, marcada com `is_previous: true` -- a tela mostra a data e o
      resultado dela, que e' prova, nao enfeite.
    """
    user = get_current_user_optional(request)
    conn = get_connection()
    cur  = conn.cursor()
    try:
        row = _q1(cur, f"""
            {_FREE_PICK_SELECT}
            WHERE pf.match_date = {HOJE_BR}
            ORDER BY pf.created_at DESC
            LIMIT 1
        """)
        is_previous = False
        if not row:
            row = _q1(cur, f"""
                {_FREE_PICK_SELECT}
                WHERE pf.match_date < {HOJE_BR}
                ORDER BY pf.match_date DESC, pf.created_at DESC
                LIMIT 1
            """)
            is_previous = True
        if not row:
            return None
        d = dict(row)
        d["is_previous"] = is_previous
        if d.get("match_date") and hasattr(d["match_date"], "isoformat"):
            d["match_date"] = d["match_date"].isoformat()
        if d.get("match_datetime") and hasattr(d["match_datetime"], "isoformat"):
            d["match_datetime"] = d["match_datetime"].isoformat()

        if user:
            d["locked"] = False
        else:
            # Anonimo: o mercado nem entra na resposta.
            d.pop("market", None)
            d.pop("line", None)
            d["locked"] = True
        return d
    finally:
        cur.close()
        conn.close()


@router.get("/leaderboard")
def public_leaderboard():
    """Top 5 usuarios por yield ROI · anonimizados para landing page (min 5 picks resolvidos)."""
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("""
            WITH resolved AS (
                SELECT
                    uf.user_id,
                    uf.stake_units,
                    CASE uf.pick_type
                        WHEN 'vip'         THEN pv.result
                        WHEN 'free'        THEN pf.result
                        WHEN 'multipla'    THEN pm.result
                        WHEN 'alavancagem' THEN pa.result
                        WHEN 'faltas'      THEN pfa.result
                        WHEN 'goleiros'    THEN pg.result
                    END AS result,
                    CASE uf.pick_type
                        WHEN 'vip'         THEN COALESCE(pv.profit, 0)
                        WHEN 'free'        THEN COALESCE(pf.profit, 0)
                        WHEN 'multipla'    THEN COALESCE(pm.profit, 0)
                        WHEN 'alavancagem' THEN COALESCE(pa.profit, 0)
                        WHEN 'faltas'      THEN COALESCE(pfa.profit, 0)
                        WHEN 'goleiros'    THEN COALESCE(pg.profit, 0)
                        ELSE 0
                    END AS profit
                FROM user_followed_picks uf
                LEFT JOIN picks_vip pv         ON pv.id = uf.pick_id AND uf.pick_type = 'vip'
                LEFT JOIN picks_free pf        ON pf.id = uf.pick_id AND uf.pick_type = 'free'
                LEFT JOIN picks_multiplas pm   ON pm.id = uf.pick_id AND uf.pick_type = 'multipla'
                LEFT JOIN picks_alavancagem pa ON pa.id = uf.pick_id AND uf.pick_type = 'alavancagem'
                -- Faltas e defesas entravam no CASE como NULL, entao a aposta
                -- do usuario nesses dois mercados era descartada pelo
                -- FILTER (WHERE result IS NOT NULL) logo abaixo: ela contava
                -- na banca dele e sumia do ranking. Quem apostasse so' nesses
                -- dois nem aparecia na lista.
                LEFT JOIN picks_faltas pfa     ON pfa.id = uf.pick_id AND uf.pick_type = 'faltas'
                LEFT JOIN picks_goleiros pg    ON pg.id = uf.pick_id AND uf.pick_type = 'goleiros'
            ),
            user_stats AS (
                SELECT
                    user_id,
                    COUNT(*) FILTER (WHERE result IS NOT NULL)  AS total,
                    COUNT(*) FILTER (WHERE result = 'GREEN')    AS greens,
                    ROUND(
                        COUNT(*) FILTER (WHERE result = 'GREEN')::numeric /
                        NULLIF(COUNT(*) FILTER (WHERE result IS NOT NULL), 0) * 100
                    ) AS win_rate,
                    ROUND(
                        COALESCE(SUM(profit) FILTER (WHERE result IS NOT NULL), 0) /
                        NULLIF(COALESCE(SUM(stake_units) FILTER (WHERE result IS NOT NULL), 0), 0) * 100,
                        1
                    ) AS yield_roi
                FROM resolved
                GROUP BY user_id
                HAVING COUNT(*) FILTER (WHERE result IS NOT NULL) >= 5
            )
            SELECT u.name, u.avatar_url, us.total, us.greens, us.win_rate, us.yield_roi
            FROM user_stats us
            JOIN users u ON u.id = us.user_id
            ORDER BY us.yield_roi DESC
            LIMIT 5
        """)
        rows = cur.fetchall()
        return [
            {
                "name":      _mask_first(r["name"]),
                "avatar_url": r["avatar_url"],
                "total":     int(r["total"]),
                "greens":    int(r["greens"]),
                "win_rate":  int(r["win_rate"]),
                "yield_roi": float(r["yield_roi"]),
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


# ─────────────────────── Movimento de mercado (CLV) ───────────────────────
#
# Isto é a versão viável de "mercado em movimento".
#
# Não existe série temporal de odds no banco: `odds_values` é upsert e só
# guarda a odd corrente, e `closing_odds` grava UMA linha por (fixture,
# market) perto do apito. Então não dá pra desenhar a odd variando ao longo
# do dia sem antes criar um coletor que grave histórico.
#
# O que dá, e vale mais: Closing Line Value. Compara a odd em que o pick foi
# publicado com a odd de fechamento do mesmo mercado. Se o mercado fechou
# MAIS BAIXO que a nossa entrada, o preço andou a nosso favor: pegamos valor
# antes do mercado corrigir. CLV positivo consistente é o indicador que
# sobrevive à variância de resultado, porque não depende do jogo ter dado
# certo, só de termos entrado num preço melhor que o de fechamento.

# Tabelas de pick que têm odd + market_id e podem casar com closing_odds.
#
# Cada uma traz seu par de colunas de time porque o nome diverge entre elas:
# picks_vip tem home_team_name/away_team_name e picks_free tem home_team/
# away_team. Um UNION com nome fixo quebrava em uma das duas.
_CLV_SOURCES = [
    ("picks_vip",  "vip",  "home_team_name", "away_team_name"),
    ("picks_free", "free", "home_team",      "away_team"),
]


@router.get("/market-movement")
def public_market_movement(days: int = Query(30, ge=1, le=365)):
    """CLV dos picks resolvidos na janela · sem autenticação."""
    union_sql = " UNION ALL ".join(
        f"""SELECT id, fixture_id, market_id, market_type, line, odd, result,
                   match_date,
                   {home_col} AS home_team_name,
                   {away_col} AS away_team_name,
                   '{label}' AS pick_type
              FROM {table}
             WHERE market_id IS NOT NULL AND odd IS NOT NULL"""
        for table, label, home_col, away_col in _CLV_SOURCES
    )

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            WITH picks AS ({union_sql}),
            joined AS (
                SELECT p.*, co.closing_odd,
                       -- Movimento em pontos percentuais. Negativo = mercado
                       -- fechou MAIS BAIXO que a nossa entrada, ou seja, o
                       -- preco andou a nosso favor.
                       --
                       -- Sem sinal de porcentagem neste comentario de
                       -- proposito: o psycopg2 varre a query inteira atras de
                       -- placeholder e nao distingue comentario, entao um
                       -- por-cento solto aqui quebrava o execute com
                       -- "tuple index out of range" e o endpoint devolvia
                       -- available:false pra sempre.
                       ROUND(((co.closing_odd - p.odd) / p.odd * 100)::numeric, 2) AS move_pct
                  FROM picks p
                  JOIN closing_odds co
                    ON co.fixture_id = p.fixture_id
                   AND co.market_id  = p.market_id
                   -- A linha entra no casamento, nao so' o mercado: um "Over
                   -- 4.5" e um "Under 4.5" do MESMO mercado sao precos
                   -- opostos, e casar so' por (fixture, market_id) mostraria
                   -- um movimento invertido. Mesmo defeito que corrompeu o
                   -- CLV do ledger ate' 2026-08-20, um nivel abaixo.
                   AND co.line       = p.line
                 WHERE p.match_date >= CURRENT_DATE - %s::int
                   AND co.closing_odd IS NOT NULL
                   AND co.closing_odd > 0
            )
            SELECT * FROM joined ORDER BY match_date DESC, id DESC LIMIT 200
        """, (days,))
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("[MARKET_MOVEMENT] %s", e)
        return {"available": False, "reason": "sem dados de fechamento", "summary": None, "recent": []}
    finally:
        cur.close()
        conn.close()

    if not rows:
        # Sem linha nenhuma não é erro: o capture roda perto do jogo e um
        # ambiente novo simplesmente ainda não tem fechamento gravado.
        return {"available": False, "reason": "sem odds de fechamento na janela", "summary": None, "recent": []}

    # CLV positivo = entramos numa odd MAIOR que a de fechamento (move_pct < 0)
    beat = [r for r in rows if r["move_pct"] is not None and r["move_pct"] < 0]
    moves = [float(r["move_pct"]) for r in rows if r["move_pct"] is not None]
    avg_move = round(sum(moves) / len(moves), 2) if moves else 0.0

    return {
        "available": True,
        "summary": {
            "total": len(rows),
            "beat_closing": len(beat),
            "beat_pct": round(len(beat) / len(rows) * 100) if rows else 0,
            # sinal invertido pra leitura: positivo = valor capturado
            "avg_clv": round(-avg_move, 2),
            "days": days,
        },
        "recent": [
            {
                "pick_type":  r["pick_type"],
                "match_date": r["match_date"].isoformat() if hasattr(r["match_date"], "isoformat") else r["match_date"],
                "home_team":  r["home_team_name"],
                "away_team":  r["away_team_name"],
                "market":     r["market_type"],
                "line":       r["line"],
                "odd":        float(r["odd"]),
                "closing_odd": float(r["closing_odd"]),
                "clv":        round(-float(r["move_pct"]), 2) if r["move_pct"] is not None else None,
                "result":     r["result"],
            }
            for r in rows[:40]
        ],
    }
