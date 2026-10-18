"""A temporada INTEIRA do arbitro escalado, e nao so' o que a coleta ja' tinha
(18/10/2026, pedido do usuario: "pega todas as partidas da temporada naquela
liga e nao so' um curto tempo").

O PROBLEMA
----------
A API-Football nao tem endpoint de arbitro: o nome dele so' vem dentro de cada
jogo (`fixture.referee`). Entao o que o projeto sabia do arbitro era o que
estava em `match_statistics` -- so' as ligas ATIVAS, e so' os jogos com folha
coletada. O arbitro de Brasileirao que tambem apita Serie B, Copa do Brasil e
estadual aparecia com metade da temporada, e o Raio-X dizia "8 jogos" de quem
apitou 20.

O QUE ESTE COLETOR FAZ
----------------------
So' pros arbitros ESCALADOS nos nossos jogos dos proximos dias (o resto nao
interessa a ninguem hoje):

  1. Descobre as outras ligas do mesmo pais (`/leagues?country=X&current=true`,
     1 requisicao por pais, 1 vez por semana). Fica de fora feminino, base e
     amistoso, e liga que a API nao cobre com evento nem folha.
  2. Lista a temporada de cada uma (`/fixtures?league&season`, 1 requisicao por
     liga, a cada 3 dias). A listagem ja' traz o nome do arbitro e o placar de
     todos os jogos.
  3. Busca a folha (cartao, falta, VAR) so' dos jogos DOS ARBITROS ESCALADOS que
     faltam, por `/fixtures?ids=` · 20 jogos por requisicao, com estatistica e
     eventos na mesma resposta. Jogo de liga ativa sem folha em
     `match_statistics` entra na mesma fila, achado pelo calendario.

Tudo com teto de requisicoes por rodada; idempotente, continua de onde parou.

POR QUE UMA TABELA A PARTE (`arbitro_partidas`)
-----------------------------------------------
Decisao do usuario. `match_statistics` e' o que o motor le pra media de TIME:
gravar Copa do Brasil e estadual la' mudaria o historico do time e, com ele, as
picks -- e sinal novo so' entra no motor depois de medido. Aqui o jogo serve so'
pra o arbitro. O motor continua lendo exatamente o que lia; quem le esta tabela
hoje e' o Raio-X (website/backend/arbitro_do_jogo.py).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from utils import esquema
from utils.api_client import buscar
from utils.arbitro import chave_do_arbitro, chaves_equivalentes, sql_candidatas, sql_chave
from utils.db_utils import get_connection
from utils.stat_sheet import folha_publicada, ler_valor

FINALIZADOS = ("FT", "AET", "PEN")
#: Quantos jogos `/fixtures?ids=` aceita numa requisicao (limite da API).
IDS_POR_REQUISICAO = 20
#: Padrao do comando `arbitros`. A rodada normal gasta bem menos: a descoberta
#: e' semanal e a listagem a cada 3 dias.
TETO_PADRAO = 40
#: Arbitros escalados de hoje ate' N dias a frente. A escala sai 1 ou 2 dias antes.
DIAS_A_FRENTE = 3
REDESCOBRIR_LIGAS = timedelta(days=7)
RELISTAR_LIGA = timedelta(days=3)
#: Pais "World" e' Libertadores/Champions -- ja' vem pelas ligas ativas.
PAISES_FORA = ("World",)

#: Competicao que nao diz nada do arbitro do profissional masculino.
_LIGA_FORA = re.compile(
    r"women|feminin|femenin|u-?\s?1\d|u-?\s?2[0-3]|sub-?\s?\d|youth|junior|juniores|"
    r"reserve|friendl|amistos|beach|futsal|esports?", re.I)

#: O arbitro dos jogos das ligas ATIVAS vem de `calendario_jogos.referee`
#: (calendario_service grava de graca, da mesma listagem da coleta diaria).
DDL = (
    # Quando cada pais teve as ligas descobertas pela ultima vez -- inclusive o
    # pais sem liga extra nenhuma, que senao voltaria todo dia.
    """CREATE TABLE IF NOT EXISTS arbitro_paises (
        pais          TEXT PRIMARY KEY,
        descoberto_em TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS arbitro_ligas_extras (
        league_id    INTEGER NOT NULL,
        season       INTEGER NOT NULL,
        nome         TEXT,
        pais         TEXT,
        descoberta_em TIMESTAMP DEFAULT NOW(),
        listada_em   TIMESTAMP,
        PRIMARY KEY (league_id, season)
    )""",
    """CREATE TABLE IF NOT EXISTS arbitro_partidas (
        fixture_id        INTEGER PRIMARY KEY,
        league_id         INTEGER NOT NULL,
        season            INTEGER,
        liga_nome         TEXT,
        match_date        TIMESTAMP,
        status            TEXT,
        referee           TEXT,
        home_team_id      INTEGER,
        away_team_id      INTEGER,
        home_team         TEXT,
        away_team         TEXT,
        home_goals        INTEGER,
        away_goals        INTEGER,
        home_yellow_cards INTEGER,
        away_yellow_cards INTEGER,
        home_red_cards    INTEGER,
        away_red_cards    INTEGER,
        home_fouls        INTEGER,
        away_fouls        INTEGER,
        var_lances        JSONB,
        penaltis          INTEGER,
        tem_eventos       BOOLEAN DEFAULT FALSE,
        folha_checked_at  TIMESTAMP,
        atualizado_em     TIMESTAMP DEFAULT NOW()
    )""",
    f"CREATE INDEX IF NOT EXISTS idx_arbitro_partidas_chave ON arbitro_partidas (({sql_chave('referee')}))",
)


# ── leitura da resposta da API (pura, testada sem banco) ─────────────────────

def liga_serve(item: dict, ativas: set) -> tuple | None:
    """(league_id, season, nome, pais) de uma liga do `/leagues`, ou None.

    Fica de fora a liga ja' ativa (vem pela coleta normal), feminino/base/
    amistoso, e liga sem cobertura de evento nem de folha -- listar a temporada
    dela custaria requisicao pra nunca ter cartao nenhum."""
    liga, pais = item.get("league") or {}, item.get("country") or {}
    if not liga.get("id") or liga["id"] in ativas or _LIGA_FORA.search(liga.get("name") or ""):
        return None
    atual = next((s for s in item.get("seasons") or [] if s.get("current")), None)
    if not atual or not atual.get("year"):
        return None
    cob = ((atual.get("coverage") or {}).get("fixtures") or {})
    if not (cob.get("events") or cob.get("statistics_fixtures")):
        return None
    return liga["id"], int(atual["year"]), liga.get("name"), pais.get("name")


def linhas_da_listagem(response: list, liga_nome: str | None) -> list:
    """Jogos encerrados COM arbitro da listagem de uma liga extra."""
    saida = {}
    for fx in response or []:
        f, t, g = fx.get("fixture") or {}, fx.get("teams") or {}, fx.get("goals") or {}
        lg = fx.get("league") or {}
        status = (f.get("status") or {}).get("short")
        if not f.get("id") or not f.get("referee") or status not in FINALIZADOS:
            continue
        saida[f["id"]] = (
            f["id"], lg.get("id"), lg.get("season"), liga_nome or lg.get("name"),
            _utc(f.get("date")), status, f["referee"],
            (t.get("home") or {}).get("id"), (t.get("away") or {}).get("id"),
            (t.get("home") or {}).get("name"), (t.get("away") or {}).get("name"),
            g.get("home"), g.get("away"),
        )
    return list(saida.values())


def folha_do_item(item: dict) -> dict:
    """Cartao, falta, VAR e penalti de um jogo do `/fixtures?ids=`.

    Cartao: da folha de estatistica quando publicada; sem ela, dos EVENTOS
    (liga menor costuma ter evento e nao ter folha). Falta so' existe na folha
    -- sem ela fica None, nunca 0 (ver utils/stat_sheet)."""
    times = item.get("teams") or {}
    casa, fora = (times.get("home") or {}).get("id"), (times.get("away") or {}).get("id")
    folhas = {((s.get("team") or {}).get("id")): s.get("statistics") or []
              for s in item.get("statistics") or []}
    fc, ff = folhas.get(casa), folhas.get(fora)
    saida = dict.fromkeys(("home_yellow_cards", "away_yellow_cards", "home_red_cards",
                           "away_red_cards", "home_fouls", "away_fouls"))
    if fc is not None and ff is not None and folha_publicada(fc) and folha_publicada(ff):
        for lado, folha in (("home", fc), ("away", ff)):
            saida[f"{lado}_yellow_cards"] = ler_valor(folha, "Yellow Cards", True)
            saida[f"{lado}_red_cards"] = ler_valor(folha, "Red Cards", True)
            saida[f"{lado}_fouls"] = ler_valor(folha, "Fouls", True)

    eventos = item.get("events") or []
    var, penaltis = [], 0
    cartoes = {casa: [0, 0], fora: [0, 0]}
    for ev in eventos:
        tipo, det = (ev.get("type") or "").lower(), (ev.get("detail") or "")
        tid = (ev.get("team") or {}).get("id")
        if tipo == "var":
            var.append({"minuto": (ev.get("time") or {}).get("elapsed"), "team_id": tid, "detalhe": det})
        elif tipo == "goal" and "penalty" in det.lower():
            penaltis += 1                 # convertido ou perdido: foi marcado
        elif tipo == "card" and tid in cartoes:
            d = det.lower()
            if "second yellow" in d:
                cartoes[tid][1] += 1      # o 2o amarelo vira vermelho (a folha conta assim)
            elif "yellow" in d:
                cartoes[tid][0] += 1
            elif "red" in d:
                cartoes[tid][1] += 1
    if eventos and saida["home_yellow_cards"] is None and casa in cartoes and fora in cartoes:
        saida.update(home_yellow_cards=cartoes[casa][0], away_yellow_cards=cartoes[fora][0],
                     home_red_cards=cartoes[casa][1], away_red_cards=cartoes[fora][1])
    saida.update(var_lances=var if eventos else None, penaltis=penaltis if eventos else None,
                 tem_eventos=bool(eventos))
    return saida


def _utc(iso: str | None):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    # match_statistics.match_date e' UTC sem fuso; a mesma convencao aqui.
    return dt.replace(tzinfo=None) - (dt.utcoffset() or timedelta(0))


# ── coleta ───────────────────────────────────────────────────────────────────

def _alvos(cur) -> tuple[list, list]:
    """(chaves dos arbitros escalados, paises das ligas desses jogos)."""
    cur.execute("""
        SELECT DISTINCT f.referee, c.pais
          FROM fixtures f
          LEFT JOIN LATERAL (SELECT pais FROM calendario_jogos cj
                              WHERE cj.league_id = f.league_id AND cj.pais IS NOT NULL
                              LIMIT 1) c ON TRUE
         WHERE f.referee IS NOT NULL
           AND f.match_datetime >= NOW() - INTERVAL '1 day'
           AND f.match_datetime <  NOW() + make_interval(days => %s)
    """, (DIAS_A_FRENTE,))
    chaves, paises = set(), set()
    for referee, pais in cur.fetchall():
        chave = chave_do_arbitro(referee)
        if chave:
            chaves.add(chave)
        if pais and pais not in PAISES_FORA:
            paises.add(pais)
    return sorted(chaves), sorted(paises)


def _com_as_outras_grafias(cur, chaves: list) -> list:
    """Cada chave mais as grafias da MESMA pessoa no banco ("Ramon Abatti" e
    "Ramon Abatti Abel") · regra em utils/arbitro.chaves_equivalentes."""
    saida = set(chaves)
    for chave in chaves:
        conhecidas = set()
        for tabela in ("match_statistics", "calendario_jogos", "arbitro_partidas"):
            cur.execute(f"SELECT DISTINCT {sql_chave('referee')} FROM {tabela} "
                        f"WHERE {sql_candidatas('referee')}", (chave.split()[0],))
            conhecidas.update(r[0] for r in cur.fetchall() if r[0])
        saida.update(chaves_equivalentes(chave, conhecidas))
    return sorted(saida)


def _descobrir_ligas(cur, paises: list, orcamento: int) -> int:
    gastas = 0
    cur.execute("SELECT league_id FROM leagues WHERE COALESCE(ativa, TRUE)")
    ativas = {r[0] for r in cur.fetchall()}
    for pais in paises:
        if gastas >= orcamento:
            break
        cur.execute("SELECT descoberto_em FROM arbitro_paises WHERE pais = %s", (pais,))
        linha = cur.fetchone()
        ultima = linha[0] if linha else None
        if ultima and datetime.now() - ultima < REDESCOBRIR_LIGAS:
            continue
        try:
            gastas += 1
            resposta = buscar("leagues", {"country": pais, "current": "true"}, origem="coletor_arbitro")
        except Exception as e:
            print(f"[ARBITRO] ligas de {pais}: {e}")
            continue
        novas = [l for l in (liga_serve(i, ativas) for i in resposta) if l]
        for league_id, season, nome, pais_api in novas:
            cur.execute("""
                INSERT INTO arbitro_ligas_extras (league_id, season, nome, pais, descoberta_em)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (league_id, season) DO UPDATE SET nome = EXCLUDED.nome,
                       descoberta_em = NOW()
            """, (league_id, season, nome, pais_api or pais))
        cur.execute("""
            INSERT INTO arbitro_paises (pais, descoberto_em) VALUES (%s, NOW())
            ON CONFLICT (pais) DO UPDATE SET descoberto_em = NOW()
        """, (pais,))
        cur.connection.commit()
        print(f"[ARBITRO] {pais}: {len(novas)} liga(s) extra(s).")
    return gastas


def _listar_ligas(cur, paises: list, orcamento: int) -> int:
    gastas = 0
    if not paises:
        return 0
    cur.execute("""
        SELECT league_id, season, nome FROM arbitro_ligas_extras
         WHERE pais = ANY(%s)
           AND (listada_em IS NULL OR listada_em < NOW() - %s)
         ORDER BY listada_em NULLS FIRST
    """, (paises, RELISTAR_LIGA))
    from psycopg2.extras import execute_values
    for league_id, season, nome in cur.fetchall():
        if gastas >= orcamento:
            break
        try:
            gastas += 1
            resposta = buscar("fixtures", {"league": league_id, "season": season}, origem="coletor_arbitro")
        except Exception as e:
            print(f"[ARBITRO] listagem da liga {league_id}: {e}")
            continue
        linhas = linhas_da_listagem(resposta, nome)
        if linhas:
            # Placar e status podem mudar (W.O., revisao); a folha ja' buscada fica.
            execute_values(cur, """
                INSERT INTO arbitro_partidas (fixture_id, league_id, season, liga_nome, match_date,
                    status, referee, home_team_id, away_team_id, home_team, away_team,
                    home_goals, away_goals)
                VALUES %s
                ON CONFLICT (fixture_id) DO UPDATE SET
                    status = EXCLUDED.status, referee = EXCLUDED.referee,
                    home_goals = EXCLUDED.home_goals, away_goals = EXCLUDED.away_goals,
                    atualizado_em = NOW()
            """, linhas)
        cur.execute("UPDATE arbitro_ligas_extras SET listada_em = NOW() WHERE league_id = %s AND season = %s",
                    (league_id, season))
        cur.connection.commit()
    return gastas


def _trazer_buracos_das_ativas(cur, chaves: list) -> int:
    """Jogo de liga ATIVA dos arbitros escalados que esta' no calendario e nao
    tem folha de cartao em `match_statistics` entra na fila daqui. Zero API."""
    cur.execute(f"""
        INSERT INTO arbitro_partidas (fixture_id, league_id, season, match_date, status, referee,
                                      home_team_id, away_team_id)
        SELECT cj.fixture_id, cj.league_id, cj.season, cj.match_datetime, cj.status, cj.referee,
               cj.home_team_id, cj.away_team_id
          FROM calendario_jogos cj
          JOIN leagues l ON l.league_id = cj.league_id AND l.season = cj.season
         WHERE cj.status IN %s
           AND {sql_chave('cj.referee')} = ANY(%s)
           AND NOT EXISTS (SELECT 1 FROM match_statistics ms
                            WHERE ms.fixture_id = cj.fixture_id
                              AND ms.total_yellow_cards IS NOT NULL)
        ON CONFLICT (fixture_id) DO NOTHING
    """, (FINALIZADOS, chaves))
    novos = cur.rowcount or 0
    cur.connection.commit()
    return novos


def _buscar_folhas(cur, chaves: list, orcamento: int) -> tuple[int, int]:
    cur.execute(f"""
        SELECT fixture_id FROM arbitro_partidas
         WHERE folha_checked_at IS NULL AND status IN %s
           AND {sql_chave('referee')} = ANY(%s)
         ORDER BY match_date DESC NULLS LAST
         LIMIT %s
    """, (FINALIZADOS, chaves, orcamento * IDS_POR_REQUISICAO))
    fila = [r[0] for r in cur.fetchall()]
    gastas = gravadas = 0
    for i in range(0, len(fila), IDS_POR_REQUISICAO):
        lote = fila[i:i + IDS_POR_REQUISICAO]
        try:
            gastas += 1
            resposta = buscar("fixtures", {"ids": "-".join(map(str, lote))}, origem="coletor_arbitro")
        except Exception as e:
            # Falha de rede nao marca: o lote volta na proxima rodada.
            print(f"[ARBITRO] folhas, lote {lote[0]}..: {e}")
            continue
        for item in resposta or []:
            f, t, g = item.get("fixture") or {}, item.get("teams") or {}, item.get("goals") or {}
            if not f.get("id"):
                continue
            d = folha_do_item(item)
            cur.execute("""
                UPDATE arbitro_partidas SET
                    liga_nome = COALESCE(liga_nome, %s),
                    -- O calendario guarda Brasilia; aqui fica UTC, como match_statistics.
                    match_date = COALESCE(%s, match_date),
                    home_team = COALESCE(home_team, %s), away_team = COALESCE(away_team, %s),
                    home_goals = COALESCE(%s, home_goals), away_goals = COALESCE(%s, away_goals),
                    home_yellow_cards = %s, away_yellow_cards = %s,
                    home_red_cards = %s, away_red_cards = %s,
                    home_fouls = %s, away_fouls = %s,
                    var_lances = %s, penaltis = %s, tem_eventos = %s,
                    folha_checked_at = NOW(), atualizado_em = NOW()
                 WHERE fixture_id = %s
            """, ((item.get("league") or {}).get("name"), _utc(f.get("date")),
                  (t.get("home") or {}).get("name"), (t.get("away") or {}).get("name"),
                  g.get("home"), g.get("away"),
                  d["home_yellow_cards"], d["away_yellow_cards"], d["home_red_cards"], d["away_red_cards"],
                  d["home_fouls"], d["away_fouls"],
                  json.dumps(d["var_lances"]) if d["var_lances"] is not None else None,
                  d["penaltis"], d["tem_eventos"], f["id"]))
            gravadas += 1
        cur.connection.commit()
    return gastas, gravadas


def coletar(teto_requisicoes: int = TETO_PADRAO) -> dict:
    """Uma rodada: descobre, lista e busca folha, nessa ordem, ate' o teto."""
    conn = get_connection()
    cur = conn.cursor()
    resumo = {"arbitros": 0, "requisicoes": 0, "buracos_das_ativas": 0, "folhas": 0}
    try:
        # O DDL do calendario junto: a coluna `referee` dele e' lida aqui, e o
        # comando pode rodar avulso antes de a coleta diaria passar.
        from collectors.calendario_service import DDL as DDL_CALENDARIO
        esquema.garantir(cur, (*DDL_CALENDARIO, *DDL))
        conn.commit()
        chaves, paises = _alvos(cur)
        resumo["arbitros"] = len(chaves)
        if not chaves:
            print("[ARBITRO] nenhum arbitro escalado nos proximos dias.")
            return resumo
        chaves = _com_as_outras_grafias(cur, chaves)
        # Metade do teto no maximo pra descobrir/listar: a folha e' o que importa.
        gastas = _descobrir_ligas(cur, paises, teto_requisicoes // 4)
        gastas += _listar_ligas(cur, paises, teto_requisicoes // 2 - gastas)
        resumo["buracos_das_ativas"] = _trazer_buracos_das_ativas(cur, chaves)
        g, n = _buscar_folhas(cur, chaves, teto_requisicoes - gastas)
        resumo.update(requisicoes=gastas + g, folhas=n)
    finally:
        cur.close()
        conn.close()
    print(f"[ARBITRO] {resumo}")
    return resumo
