"""Eventos de cada partida encerrada, com o minuto (2026-09-27).

POR QUE EXISTE
--------------
A folha de estatistica diz QUANTO aconteceu; /fixtures/events diz QUANDO.
Com o minuto, o motor passa a enxergar o que a media esconde:

  gol tardio      time que decide depois dos 75' (e o Under que morre no fim)
  primeiro gol    o que o jogo vira depois que alguem abre o placar
  vermelho        o minuto exato da expulsao -- a leitura do RED sabia que
                  houve, nao quando (aos 20' muda o jogo, aos 88' nao muda)
  substituicao    quando o time mexe, e quanto (base pra "poupou no 2o tempo")

Tambem abastece o motor ao vivo, que hoje so' conhece a expulsao pelo
contador da folha.

CUSTO
-----
Uma requisicao por partida. `events_checked_at` em match_statistics tira a
partida da fila tenha vindo evento ou nao -- idempotente, continua de onde
parou, com teto.
"""
from __future__ import annotations

from utils.api_client import buscar
from utils.db_utils import get_connection

FINALIZADOS = ("FT", "AET", "PEN")

DDL = (
    """CREATE TABLE IF NOT EXISTS match_events (
        fixture_id  INTEGER NOT NULL,
        seq         INTEGER NOT NULL,
        minuto      INTEGER,
        acrescimo   INTEGER,
        team_id     INTEGER,
        player_id   INTEGER,
        tipo        TEXT,
        detalhe     TEXT,
        PRIMARY KEY (fixture_id, seq)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_match_events_time ON match_events (team_id, tipo)",
    "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS events_checked_at TIMESTAMP",
)


def linhas_de_eventos(fixture_id: int, resposta: list) -> list:
    saida = []
    for seq, ev in enumerate(resposta or []):
        tempo = ev.get("time") or {}
        saida.append((fixture_id, seq, tempo.get("elapsed"), tempo.get("extra"),
                      (ev.get("team") or {}).get("id"), (ev.get("player") or {}).get("id"),
                      ev.get("type"), ev.get("detail")))
    return saida


def backfill(teto_requisicoes: int = 100, temporada_minima: int = 2025) -> dict:
    """Eventos das partidas encerradas ainda nao pedidas, da mais recente pra
    mais antiga."""
    conn = get_connection()
    cur = conn.cursor()
    com = sem = 0
    try:
        for sql in DDL:
            cur.execute(sql)
        conn.commit()
        cur.execute("""
            SELECT fixture_id FROM match_statistics
             WHERE events_checked_at IS NULL AND status IN %s AND season >= %s
             ORDER BY match_date DESC LIMIT %s
        """, (FINALIZADOS, temporada_minima, teto_requisicoes))
        from psycopg2.extras import execute_values
        for (fixture_id,) in cur.fetchall():
            try:
                resposta = buscar("fixtures/events", {"fixture": fixture_id}, origem="coletor_eventos")
            except Exception as e:
                print(f"[EVENTOS] fixture_id={fixture_id}: {e}")
                continue
            linhas = linhas_de_eventos(fixture_id, resposta)
            if linhas:
                cur.execute("DELETE FROM match_events WHERE fixture_id = %s", (fixture_id,))
                execute_values(cur, """INSERT INTO match_events
                    (fixture_id, seq, minuto, acrescimo, team_id, player_id, tipo, detalhe)
                    VALUES %s""", linhas)
                com += 1
            else:
                sem += 1
            cur.execute("UPDATE match_statistics SET events_checked_at = NOW() WHERE fixture_id = %s",
                        (fixture_id,))
            conn.commit()
        cur.execute("""SELECT COUNT(*) FROM match_statistics
                        WHERE events_checked_at IS NULL AND status IN %s AND season >= %s""",
                    (FINALIZADOS, temporada_minima))
        restantes = cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()
    resumo = {"com_eventos": com, "sem_eventos": sem, "restantes": restantes}
    print(f"[EVENTOS] {resumo}")
    return resumo


def gols_por_faixa(cur, team_id: int, antes_de, limite: int = 20) -> dict | None:
    """Gols MARCADOS e SOFRIDOS por faixa de 15 minutos nos ultimos jogos do
    time. So' conta jogo que teve evento coletado."""
    cur.execute("""
        SELECT e.minuto, e.team_id = %s AS nosso
          FROM match_events e
          JOIN (SELECT fixture_id FROM match_statistics
                 WHERE (home_team_id = %s OR away_team_id = %s)
                   AND events_checked_at IS NOT NULL AND match_date < %s
                 ORDER BY match_date DESC LIMIT %s) j USING (fixture_id)
         WHERE e.tipo = 'Goal' AND COALESCE(e.detalhe, '') <> 'Missed Penalty'
    """, (team_id, team_id, team_id, antes_de, limite))
    linhas = cur.fetchall()
    if not linhas:
        return None
    faixas = ("0-15", "16-30", "31-45", "46-60", "61-75", "76-90")
    marcados = dict.fromkeys(faixas, 0)
    sofridos = dict.fromkeys(faixas, 0)
    for minuto, nosso in linhas:
        m = min(max(int(minuto or 0), 1), 90)
        faixa = faixas[min((m - 1) // 15, 5)]
        (marcados if nosso else sofridos)[faixa] += 1
    return {"marcados": marcados, "sofridos": sofridos}
