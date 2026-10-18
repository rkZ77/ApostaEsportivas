"""Pagina publica de um jogo · o basico, aberto ao Google (18/10/2026).

POR QUE EXISTE
--------------
O Pick IA se apresenta como plataforma de analise de futebol, e nao como site
de aposta (decisao do usuario, 18/10/2026). Ate aqui, tudo o que o Google
conseguia ler era pick: home, palpites de hoje, resultados, pick publico. O
Raio-X, que e' a parte "Sofascore" do produto, mora atras do login
(/jogos/<id>) e do plano Pro (12/10/2026). Esta pagina e' a vitrine dele.

O QUE ENTRA, E O QUE NAO
------------------------
Entra so' o basico que o usuario escolheu abrir: horario, liga, posicao e
pontos de cada time, campanha em casa (mandante) ou fora (visitante) e a forma
dos ultimos 5 jogos na competicao. Estatistica, arbitro, jogadores, escalacao e
resumo da IA continuam no Pro · a tela mostra o cadeado e chama pro teste.

SO' BANCO, NUNCA A API
----------------------
`fixtures` (o coletor mantem hoje + 2 dias), `fixtures_arquivo` (o jogo que ja
saiu de `fixtures`), `league_standings` e `match_statistics`. Nenhuma chamada a
API-Football · a cota e' de 7.500/dia e uma pagina aberta a robo nao pode
gastar nada dela.
"""

import logging
import re
import unicodedata

from database import get_connection

logger = logging.getLogger(__name__)


def slug_do_jogo(casa: str | None, fora: str | None) -> str:
    """'Atlético-MG', 'São Paulo' -> 'atletico-mg-x-sao-paulo'.

    A MESMA regra de `slugDoJogo` em frontend/src/lib/jogoPublico.ts · o
    sitemap monta a URL aqui e a tela monta o link la', e as duas tem que
    bater, senao o Google indexa um endereco e o site linka outro.
    """
    def limpo(nome: str | None) -> str:
        sem_acento = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")

    return f"{limpo(casa) or 'casa'}-x-{limpo(fora) or 'fora'}"


def _campanha(linha: dict | None, lado: str) -> dict | None:
    """Posicao e pontos na tabela + a campanha do lado em que o time joga ESTE
    jogo (o mandante em casa, o visitante fora)."""
    if not linha:
        return None
    return {
        "posicao": linha.get("rank"),
        "pontos": linha.get("points"),
        "jogos": linha.get("played"),
        "saldo": linha.get("goals_diff"),
        "lado": {
            "jogos": linha.get(f"{lado}_played"),
            "vitorias": linha.get(f"{lado}_win"),
            "empates": linha.get(f"{lado}_draw"),
            "derrotas": linha.get(f"{lado}_lose"),
            "gols_pro": linha.get(f"{lado}_goals_for"),
            "gols_contra": linha.get(f"{lado}_goals_against"),
        },
    }


def montar(fixture_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT j.fixture_id, j.league_id, j.season, j.home_team_id, j.away_team_id,
                   j.home_team, j.away_team, j.match_datetime, j.status, j.round,
                   COALESCE(l.name, 'Liga ' || j.league_id) AS league_name
              FROM (
                    SELECT fixture_id, league_id, season, home_team_id, away_team_id,
                           home_team, away_team, match_datetime, status, round
                      FROM fixtures WHERE fixture_id = %s
                    UNION ALL
                    SELECT fixture_id, league_id, season, home_team_id, away_team_id,
                           home_team, away_team, match_datetime, status, round
                      FROM fixtures_arquivo
                     WHERE fixture_id = %s
                       AND NOT EXISTS (SELECT 1 FROM fixtures WHERE fixture_id = %s)
                   ) j
              LEFT JOIN leagues l ON l.league_id = j.league_id
             LIMIT 1
        """, (fixture_id, fixture_id, fixture_id))
        jogo = cur.fetchone()
        if not jogo:
            return None
        jogo = dict(jogo)

        # Placar so' de jogo encerrado · `match_statistics` e' onde o coletor
        # grava o resultado oficial.
        cur.execute("""
            SELECT home_goals, away_goals FROM match_statistics
             WHERE fixture_id = %s AND status IN ('FT','AET','PEN')
        """, (fixture_id,))
        placar = cur.fetchone()

        # A temporada do jogo, e na falta dela a mais recente da liga · a
        # mesma escolha da aba Tabela do Raio-X.
        cur.execute("""
            SELECT team_id, rank, points, played, goals_diff,
                   home_played, home_win, home_draw, home_lose, home_goals_for, home_goals_against,
                   away_played, away_win, away_draw, away_lose, away_goals_for, away_goals_against
              FROM league_standings
             WHERE league_id = %s
               AND season = COALESCE(
                     (SELECT MAX(season) FROM league_standings WHERE league_id = %s AND season = %s),
                     (SELECT MAX(season) FROM league_standings WHERE league_id = %s))
               AND team_id IN (%s, %s)
        """, (jogo["league_id"], jogo["league_id"], jogo.get("season"), jogo["league_id"],
              jogo["home_team_id"], jogo["away_team_id"]))
        tabela = {r["team_id"]: dict(r) for r in cur.fetchall()}
    finally:
        cur.close()
        conn.close()

    # A forma do Raio-X: ultimos 5 na competicao do jogo, de antes dele.
    from routers.fixtures import _formas_recentes
    quando = jogo.get("match_datetime")
    chave_casa = (jogo["home_team_id"], jogo["league_id"], jogo.get("season"))
    chave_fora = (jogo["away_team_id"], jogo["league_id"], jogo.get("season"))
    formas = _formas_recentes({chave_casa, chave_fora},
                              quando.isoformat() if hasattr(quando, "isoformat") else quando)

    return {
        "fixture_id": jogo["fixture_id"],
        "slug": slug_do_jogo(jogo["home_team"], jogo["away_team"]),
        "league_id": jogo["league_id"],
        "league_name": jogo["league_name"],
        "rodada": jogo.get("round"),
        "match_datetime": quando.isoformat() if hasattr(quando, "isoformat") else quando,
        "status": jogo.get("status"),
        "placar": (
            {"casa": placar["home_goals"], "fora": placar["away_goals"]} if placar else None
        ),
        "casa": {
            "id": jogo["home_team_id"],
            "nome": jogo["home_team"],
            "forma": formas.get(chave_casa, []),
            "tabela": _campanha(tabela.get(jogo["home_team_id"]), "home"),
        },
        "fora": {
            "id": jogo["away_team_id"],
            "nome": jogo["away_team"],
            "forma": formas.get(chave_fora, []),
            "tabela": _campanha(tabela.get(jogo["away_team_id"]), "away"),
        },
    }


def proximos_para_o_sitemap(limite: int = 300) -> list[dict]:
    """Os jogos que ainda vao acontecer (o que `fixtures` tem: hoje + 2 dias).

    So' os futuros: jogo encerrado sai de `fixtures` e a pagina dele envelhece,
    entao nao vale pedir rastreio. Banco fora do ar = lista vazia, e o sitemap
    sai sem eles em vez de nao sair.
    """
    try:
        conn = get_connection()
    except Exception:
        logger.warning("[JOGO_PUBLICO] banco indisponivel pro sitemap", exc_info=True)
        return []
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT fixture_id, home_team, away_team, match_datetime
              FROM fixtures
             WHERE status IN ('NS', 'TBD')
             ORDER BY match_datetime
             LIMIT %s
        """, (limite,))
        return [
            {"fixture_id": r["fixture_id"], "slug": slug_do_jogo(r["home_team"], r["away_team"])}
            for r in cur.fetchall()
        ]
    except Exception:
        logger.warning("[JOGO_PUBLICO] jogos do sitemap indisponiveis", exc_info=True)
        return []
    finally:
        cur.close()
        conn.close()
