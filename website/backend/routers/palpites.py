"""Paginas publicas de "palpites de futebol" -- as landing pages de busca.

POR QUE ELAS EXISTEM
--------------------
Ate 03/09 o site tinha UMA pagina que alguem podia achar no Google digitando o
que quer: a home. Todo o vocabulario do produto e "pick", e "pick" quase nao e
digitado no Brasil -- quem procura escreve "palpites de futebol hoje",
"palpites brasileirao", "dicas de aposta champions league". Sem uma pagina que
responda essa frase, o site nao aparece.

O conteudo nao e escrito a mao: sai do que o motor ja produziu. Cada liga tem
uma pagina com os jogos do dia, o historico publico de acerto naquela
competicao e os ultimos picks resolvidos dela. E conteudo que muda todo dia
sozinho, que e exatamente o que o Google recompensa em pagina de "hoje".

O QUE ENTRA E O QUE NAO ENTRA
-----------------------------
So pick JA RESOLVIDO, pelo mesmo caminho de /api/public/results (o UNION de
`public.py`, que filtra `result IS NOT NULL`). Nenhum pick pendente vaza aqui:
o mercado do dia continua sendo a recompensa de quem cria conta, e este modulo
nunca le uma tabela de pick direto por isso mesmo -- ele reusa o union que ja
carrega essa regra.

SLUG
----
Vem do NOME da liga, nao do id: `/palpites/brasileirao` e uma URL que alguem
digita e que o Google le, `/palpites/71` nao. Os apelidos em `_APELIDOS`
existem porque o nome oficial ("Brasileirao Serie A", "UEFA Champions League")
nao e o que se busca. Colisao de slug cai no sufixo do id, entao liga nova
nunca derruba a rota de outra.
"""

import logging
import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Query

from data_br import TZ_BR
from database import get_connection

# `_builders` e `_build_union` montam o UNION normalizado das tabelas de pick
# (colunas iguais, so' resolvido, peso de stake ja aplicado). Duplicar isso
# aqui criaria uma segunda definicao de "historico publico" que envelheceria
# sozinha -- foi exatamente o problema que pick_sources.py nasceu pra matar.
from routers.public import _build_union, _builders, _q, _q1

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/palpites", tags=["public"])


# Nome oficial da liga (ja em slug) -> o termo que as pessoas digitam.
_APELIDOS: dict = {
    "brasileirao-serie-a": "brasileirao",
    "serie-a-brasil": "brasileirao",
    "uefa-champions-league": "champions-league",
    "uefa-europa-league": "europa-league",
    "serie-a": "serie-a-italia",
    # Como o nome esta gravado no banco de PROD. Corrigido antes de qualquer
    # indexacao: trocar slug depois que o Google leu custa o ranking da URL.
    "italy-serie-a": "serie-a-italia",
    "bundesliga-1": "bundesliga",
    "copa-libertadores": "libertadores",
    "conmebol-libertadores": "libertadores",
    "conmebol-sudamericana": "sul-americana",
}


def _slug(texto: str) -> str:
    """Slug ASCII, minusculo, com hifen. 'Brasileirao Serie A' -> brasileirao-serie-a."""
    base = unicodedata.normalize("NFKD", texto or "")
    base = base.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "liga"


def _catalogo(cur) -> list:
    """Ligas com slug unico e estavel, na ordem em que devem aparecer.

    Ativa primeiro, igual a /api/public/leagues: competicao encerrada continua
    valendo pagina (o historico dela e conteudo), mas nao abre a lista.
    """
    rows = _q(cur, """
        SELECT league_id, name, season, COALESCE(ativa, TRUE) AS ativa
        FROM leagues
        ORDER BY COALESCE(ativa, TRUE) DESC, name
    """)
    vistos = set()
    ligas = []
    for r in rows:
        bruto = _slug(r["name"])
        slug = _APELIDOS.get(bruto, bruto)
        if slug in vistos:
            # Duas ligas com o mesmo nome (temporadas diferentes, ou paises com
            # "Serie A"): a segunda leva o id. Sem isso uma sobrescreveria a
            # rota da outra e a pagina mostraria a liga errada.
            slug = slug + "-" + str(r["league_id"])
        vistos.add(slug)
        ligas.append({
            "slug": slug,
            "league_id": r["league_id"],
            "name": r["name"],
            "season": r["season"],
            "ativa": bool(r["ativa"]),
            "logo_url": "/api/proxy/league/" + str(r["league_id"]) + ".png",
        })
    return ligas


def _ligas_com_pick(cur) -> list:
    """Catalogo filtrado pelas ligas que TEM historico resolvido.

    E' a lista que vira link em tela e linha no sitemap. Liga cadastrada sem
    pick nenhum rende uma pagina de quatro zeros: mandar visitante e rastreador
    pra la nao ajuda nem um nem outro.
    """
    union = _build_union(_builders(cur), "", None)
    com_pick = set()
    for r in _q(cur, f"SELECT DISTINCT t.league_id FROM ({union}) t WHERE t.league_id IS NOT NULL"):
        if r["league_id"] is not None:
            com_pick.add(int(r["league_id"]))
    return [l for l in _catalogo(cur) if l["league_id"] in com_pick]


def _por_slug(cur, slug: str) -> Optional[dict]:
    alvo = _slug(slug)
    for liga in _catalogo(cur):
        if liga["slug"] == alvo:
            return liga
    return None


def _desempenho(cur, league_id: Optional[int]) -> dict:
    """Placar publico da liga (ou de tudo, com league_id None).

    Sai do mesmo UNION de /api/public/results, entao o numero desta pagina e o
    numero daquela: duas contas diferentes pro mesmo fato seria o site se
    desmentindo em publico.
    """
    union = _build_union(_builders(cur), "", None)
    filtro = "WHERE t.league_id = %s" if league_id is not None else ""
    p = (league_id,) if league_id is not None else ()
    row = _q1(cur, f"""
        SELECT COUNT(*)                                   AS total,
               COUNT(*) FILTER (WHERE t.result = 'GREEN') AS greens,
               COUNT(*) FILTER (WHERE t.result = 'RED')   AS reds,
               COALESCE(SUM(t.profit), 0)                 AS profit,
               COALESCE(SUM(t.stake),  0)                 AS stake_total
        FROM ({union}) t
        {filtro}
    """, p)
    d = dict(row) if row else {}
    total = int(d.get("total") or 0)
    greens = int(d.get("greens") or 0)
    profit = float(d.get("profit") or 0)
    stake = float(d.get("stake_total") or 0)
    return {
        "total": total,
        "greens": greens,
        "reds": int(d.get("reds") or 0),
        "profit": round(profit, 2),
        "win_rate": round(greens / total * 100, 1) if total else 0.0,
        "roi": round(profit / stake * 100, 1) if stake else 0.0,
    }


def _ultimos_picks(cur, league_id: Optional[int], limite: int) -> list:
    union = _build_union(_builders(cur), "", None)
    filtro = "WHERE t.league_id = %s" if league_id is not None else ""
    p = (league_id,) if league_id is not None else ()
    linhas = _q(cur, f"""
        SELECT t.match_date, t.home_team_name, t.away_team_name,
               t.market, t.line, t.odd, t.result, t.source, t.league_name
        FROM ({union}) t
        {filtro}
        ORDER BY t.match_date DESC, t.match_datetime DESC NULLS LAST
        LIMIT %s
    """, p + (limite,))
    saida = []
    for r in linhas:
        d = dict(r)
        if d.get("match_date") is not None and hasattr(d["match_date"], "isoformat"):
            d["match_date"] = d["match_date"].isoformat()
        if d.get("odd") is not None:
            d["odd"] = float(d["odd"])
        saida.append(d)
    return saida


def _jogos(cur, league_id: Optional[int], limite: int) -> list:
    """Jogos de hoje em diante que o motor ja tem na fila.

    Mesma janela e mesmo motivo de /api/public/next-fixtures: `match_datetime`
    esta gravado em horario de Brasilia SEM fuso, entao o corte tem que ser
    contra o relogio de Brasilia e nao contra NOW().
    """
    filtro = "AND f.league_id = %s" if league_id is not None else ""
    p = (league_id,) if league_id is not None else ()
    linhas = _q(cur, f"""
        SELECT f.fixture_id, f.home_team, f.away_team, f.league_id,
               COALESCE(l.name, 'Liga ' || f.league_id) AS league_name,
               f.match_datetime
        FROM fixtures f
        LEFT JOIN leagues l ON l.league_id = f.league_id
        WHERE f.status IN ('NS', 'TBD')
          AND f.match_datetime >= (NOW() AT TIME ZONE '{TZ_BR}') - INTERVAL '10 minutes'
          {filtro}
        ORDER BY f.match_datetime
        LIMIT %s
    """, p + (limite,))
    saida = []
    for r in linhas:
        d = dict(r)
        if d.get("match_datetime") is not None and hasattr(d["match_datetime"], "isoformat"):
            d["match_datetime"] = d["match_datetime"].isoformat()
        saida.append(d)
    return saida


@router.get("")
def hub(limite_jogos: int = Query(12, ge=1, le=40)):
    """Pagina /palpites-de-futebol-hoje: os jogos do dia e as ligas cobertas."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        ligas = _catalogo(cur)
        # Quantos picks resolvidos cada liga ja tem: a lista ordena por isso, e
        # liga sem historico nenhum nem jogo na fila nao vira link (pagina vazia
        # no indice do Google e pior do que pagina que nao existe).
        union = _build_union(_builders(cur), "", None)
        agregado = {}
        for r in _q(cur, f"""
            SELECT t.league_id,
                   COUNT(*)                                   AS total,
                   COUNT(*) FILTER (WHERE t.result = 'GREEN') AS greens
            FROM ({union}) t
            WHERE t.league_id IS NOT NULL
            GROUP BY t.league_id
        """):
            if r["league_id"] is not None:
                agregado[int(r["league_id"])] = dict(r)

        jogos = _jogos(cur, None, limite_jogos)
        com_jogo = set(j["league_id"] for j in jogos)

        saida = []
        for liga in ligas:
            ag = agregado.get(liga["league_id"], {})
            total = int(ag.get("total") or 0)
            greens = int(ag.get("greens") or 0)
            if not total and liga["league_id"] not in com_jogo:
                continue
            item = dict(liga)
            item["picks_resolvidos"] = total
            item["win_rate"] = round(greens / total * 100, 1) if total else None
            item["tem_jogo_hoje"] = liga["league_id"] in com_jogo
            saida.append(item)
        saida.sort(key=lambda l: (not l["tem_jogo_hoje"], -l["picks_resolvidos"]))

        return {
            "ligas": saida,
            "jogos": jogos,
            "desempenho": _desempenho(cur, None),
            "ultimos_picks": _ultimos_picks(cur, None, 12),
        }
    finally:
        cur.close()
        conn.close()


@router.get("/{slug}")
def por_liga(slug: str, limite_jogos: int = Query(10, ge=1, le=30)):
    """Pagina /palpites/<liga>.

    Slug desconhecido volta `encontrada: false` com a lista de slugs validos, e
    nao 404: a tela precisa oferecer as ligas que existem pra quem chegou de uma
    busca com o nome errado, e um erro HTTP so daria a tela de nada.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        liga = _por_slug(cur, slug)
        if not liga:
            return {"encontrada": False, "ligas": _ligas_com_pick(cur)}
        return {
            "encontrada": True,
            "liga": liga,
            "desempenho": _desempenho(cur, liga["league_id"]),
            "jogos": _jogos(cur, liga["league_id"], limite_jogos),
            "ultimos_picks": _ultimos_picks(cur, liga["league_id"], 15),
            # O catalogo vai junto pro rodape de links entre as ligas. Nao e
            # enfeite: sem um link apontando pra ela, uma pagina de liga so
            # existe pro Google enquanto estiver no sitemap.
            "ligas": _ligas_com_pick(cur),
        }
    finally:
        cur.close()
        conn.close()


def slugs_publicos() -> list:
    """Ligas que entram no sitemap, usado por agent_web.sitemap_xml.

    So entra liga que TEM pick resolvido. Uma liga cadastrada sem historico
    nenhum rende uma pagina com quatro zeros e uma tabela vazia -- pagina assim
    no indice do Google e pior do que pagina que nao existe, porque ela e' a
    amostra pela qual o site inteiro passa a ser julgado.

    Falha em silencio com lista vazia: sitemap e conteudo secundario, e um banco
    fora do ar nao pode derrubar a rota inteira.
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        try:
            return [
                {"slug": l["slug"], "name": l["name"], "ativa": l["ativa"]}
                for l in _ligas_com_pick(cur)
            ]
        finally:
            cur.close()
            conn.close()
    except Exception:
        logger.warning("[PALPITES] catalogo indisponivel pro sitemap", exc_info=True)
        return []
