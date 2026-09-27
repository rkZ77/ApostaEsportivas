"""Calendario de todas as partidas das ligas acompanhadas (2026-09-27).

POR QUE EXISTE
--------------
Pedido do usuario: o motor precisa saber o calendario de cada time, em TODAS
as competicoes -- quanto descansou, quando joga de novo, quantos jogos fez nas
ultimas duas semanas. Time que joga Libertadores em 3 dias poupa titular hoje;
time com 4 jogos em 12 dias corre menos. Nada disso aparece na media.

`fixtures` nao serve: e' a fila operacional do dia e apaga a partida depois
que ela acaba. `match_statistics` so' tem jogo encerrado. Faltava a TEMPORADA
INTEIRA, passado e futuro.

CUSTO ZERO
----------
A coleta diaria da folha (match_statistics_sync_service._load_fixtures) ja'
pede `/fixtures?league=X&season=Y` pra cada liga, e a resposta traz a
temporada inteira -- inclusive os jogos que ainda nao aconteceram. Ate' aqui
tudo que nao era FT era descartado. `gravar_temporada` aproveita a MESMA
resposta: nenhuma requisicao a mais.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_TZ_BR = ZoneInfo("America/Sao_Paulo")

DDL = (
    """CREATE TABLE IF NOT EXISTS calendario_jogos (
        fixture_id      INTEGER PRIMARY KEY,
        league_id       INTEGER NOT NULL,
        season          INTEGER,
        round           TEXT,
        match_datetime  TIMESTAMP,
        home_team_id    INTEGER,
        away_team_id    INTEGER,
        status          TEXT,
        venue_city      TEXT,
        pais            TEXT,
        atualizado_em   TIMESTAMP DEFAULT NOW()
    )""",
    # Pais da liga: desambigua a cidade no geocoding do clima (clima_service).
    "ALTER TABLE calendario_jogos ADD COLUMN IF NOT EXISTS pais TEXT",
    "CREATE INDEX IF NOT EXISTS idx_calendario_casa ON calendario_jogos (home_team_id, match_datetime)",
    "CREATE INDEX IF NOT EXISTS idx_calendario_fora ON calendario_jogos (away_team_id, match_datetime)",
)


def _br(data_iso: str | None):
    """Horario da API em Brasilia sem fuso -- a convencao de fixtures.match_datetime."""
    if not data_iso:
        return None
    try:
        dt = datetime.fromisoformat(data_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(_TZ_BR).replace(tzinfo=None) if dt.tzinfo else dt


def coletar_todas_as_ligas() -> dict:
    """Uma requisicao por liga ativa: a temporada inteira de cada uma. E' o
    comando `calendario`; a coleta diaria ja' faz o mesmo de graca, isto so'
    serve pra encher (ou atualizar) sem rodar a folha."""
    from utils.api_client import buscar
    from utils.db_utils import get_connection
    conn = get_connection()
    cur = conn.cursor()
    total = ligas = 0
    try:
        cur.execute("SELECT league_id, season FROM leagues WHERE COALESCE(ativa, TRUE)")
        for league_id, season in cur.fetchall():
            try:
                resposta = buscar("fixtures", {"league": league_id, "season": season},
                                  origem="coletor_calendario")
            except Exception as e:
                print(f"[CALENDARIO] liga {league_id}: {e}")
                continue
            total += gravar_temporada(cur, resposta, league_id, season)
            ligas += 1
            conn.commit()
    finally:
        cur.close()
        conn.close()
    print(f"[CALENDARIO] {total} partidas de {ligas} ligas")
    return {"partidas": total, "ligas": ligas}


def linhas_da_temporada(response: list, league_id: int, season) -> list:
    saida = []
    for fx in response or []:
        f, t = fx.get("fixture") or {}, fx.get("teams") or {}
        if not f.get("id"):
            continue
        saida.append((
            f["id"], league_id, season, (fx.get("league") or {}).get("round"),
            _br(f.get("date")), (t.get("home") or {}).get("id"), (t.get("away") or {}).get("id"),
            (f.get("status") or {}).get("short"), (f.get("venue") or {}).get("city"),
            (fx.get("league") or {}).get("country"),
        ))
    return saida


def gravar_temporada(cur, response: list, league_id: int, season) -> int:
    """Upsert da temporada inteira de uma liga. Devolve quantas linhas vieram."""
    linhas = linhas_da_temporada(response, league_id, season)
    if not linhas:
        return 0
    for sql in DDL:
        cur.execute(sql)
    from psycopg2.extras import execute_values
    execute_values(cur, """
        INSERT INTO calendario_jogos (fixture_id, league_id, season, round, match_datetime,
                                      home_team_id, away_team_id, status, venue_city, pais)
        VALUES %s
        ON CONFLICT (fixture_id) DO UPDATE SET
            round = EXCLUDED.round, match_datetime = EXCLUDED.match_datetime,
            status = EXCLUDED.status, venue_city = COALESCE(EXCLUDED.venue_city, calendario_jogos.venue_city),
            pais = COALESCE(EXCLUDED.pais, calendario_jogos.pais),
            atualizado_em = NOW()
    """, linhas)
    return len(linhas)


#: Status de partida que nao aconteceu e nao vai acontecer na data.
_NAO_JOGADA = ("PST", "CANC", "ABD", "AWD", "WO")


def carga_do_time(cur, team_id: int, quando: datetime) -> dict | None:
    """O calendario de um time em torno de uma partida.

    dias_desde_o_ultimo   descanso, contando qualquer competicao acompanhada
    dias_ate_o_proximo    a proxima partida depois desta (poupar hoje?)
    proximo_liga_id       de que competicao e' a proxima (copa x liga)
    jogos_ultimos_14_dias desgaste acumulado
    """
    if not team_id or not quando:
        return None
    cur.execute("""
        SELECT match_datetime, league_id FROM calendario_jogos
         WHERE (home_team_id = %s OR away_team_id = %s)
           AND match_datetime IS NOT NULL
           AND COALESCE(status, '') NOT IN %s
           AND match_datetime BETWEEN %s AND %s
         ORDER BY match_datetime
    """, (team_id, team_id, _NAO_JOGADA, quando - timedelta(days=30), quando + timedelta(days=21)))
    jogos = cur.fetchall()
    antes = [j for j in jogos if j[0] < quando - timedelta(hours=3)]
    depois = [j for j in jogos if j[0] > quando + timedelta(hours=3)]
    if not antes and not depois:
        return None
    saida = {
        "jogos_ultimos_14_dias": sum(1 for j in antes if j[0] >= quando - timedelta(days=14)),
    }
    if antes:
        saida["dias_desde_o_ultimo"] = round((quando - antes[-1][0]).total_seconds() / 86400, 1)
    if depois:
        saida["dias_ate_o_proximo"] = round((depois[0][0] - quando).total_seconds() / 86400, 1)
        saida["proximo_liga_id"] = depois[0][1]
    return saida
