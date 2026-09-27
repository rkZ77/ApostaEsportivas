"""Escalacao de cada time em cada partida encerrada (2026-09-27).

POR QUE UMA TABELA NOVA
-----------------------
Ja' existiam duas fontes de escalacao, e nenhuma responde "o time mudou?":

  fixture_lineups     do pick de jogador: uma linha por PARTIDA, titulares dos
                      dois times misturados, so' das partidas com pick de
                      jogador, sem formacao nem tecnico.
  player_match_stats  titular/reserva por time, mas so' onde a folha de
                      jogador foi coletada (1.665 de 2.494 partidas de 2026
                      em PROD, em 27/09).

`team_lineups` guarda uma linha por (partida, time), com formacao, tecnico,
titulares e reservas. E' o que o dossie da partida le pra medir rodizio e
troca de tecnico -- e o que vai permitir MEDIR se rodizio muda resultado antes
de virar termo de probabilidade.

CUSTO
-----
Uma requisicao por partida (/fixtures/lineups devolve os dois times).
`lineups_checked_at` em match_statistics tira a partida da fila tenha a API
publicado ou nao, entao o backfill e' idempotente e continua de onde parou.
"""
from __future__ import annotations

from utils.api_client import buscar
from utils.db_utils import get_connection

FINALIZADOS = ("FT", "AET", "PEN")

DDL = (
    """CREATE TABLE IF NOT EXISTS team_lineups (
        fixture_id   INTEGER NOT NULL,
        team_id      INTEGER NOT NULL,
        league_id    INTEGER,
        season       INTEGER,
        match_date   TIMESTAMP,
        formation    TEXT,
        coach_id     INTEGER,
        coach_name   TEXT,
        titulares    INTEGER[] NOT NULL DEFAULT '{}',
        reservas     INTEGER[] NOT NULL DEFAULT '{}',
        coletado_em  TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (fixture_id, team_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_team_lineups_time_data ON team_lineups (team_id, match_date DESC)",
    "ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS lineups_checked_at TIMESTAMP",
)


def ler_escalacao(item: dict) -> dict | None:
    """Uma entrada de /fixtures/lineups -> linha de team_lineups (sem ids da partida)."""
    time = item.get("team") or {}
    if not time.get("id"):
        return None
    tecnico = item.get("coach") or {}

    def ids(lista):
        return [p["player"]["id"] for p in (lista or [])
                if (p.get("player") or {}).get("id")]

    return {"team_id": time["id"], "formation": item.get("formation"),
            "coach_id": tecnico.get("id"), "coach_name": tecnico.get("name"),
            "titulares": ids(item.get("startXI")), "reservas": ids(item.get("substitutes"))}


class LineupsCollectorService:

    def __init__(self):
        self.conn = None
        self.cur = None

    def _open(self):
        self.conn = get_connection()
        self.cur = self.conn.cursor()
        for sql in DDL:
            self.cur.execute(sql)
        self.conn.commit()

    def _close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()

    def _gravar(self, fixture_id, league_id, season, match_date, resposta) -> int:
        gravadas = 0
        for item in resposta or []:
            linha = ler_escalacao(item)
            if not linha or not linha["titulares"]:
                continue
            self.cur.execute("""
                INSERT INTO team_lineups (fixture_id, team_id, league_id, season, match_date,
                                          formation, coach_id, coach_name, titulares, reservas)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (fixture_id, team_id) DO UPDATE SET
                    formation = EXCLUDED.formation, coach_id = EXCLUDED.coach_id,
                    coach_name = EXCLUDED.coach_name, titulares = EXCLUDED.titulares,
                    reservas = EXCLUDED.reservas, coletado_em = NOW()
            """, (fixture_id, linha["team_id"], league_id, season, match_date,
                  linha["formation"], linha["coach_id"], linha["coach_name"],
                  linha["titulares"], linha["reservas"]))
            gravadas += 1
        self.cur.execute(
            "UPDATE match_statistics SET lineups_checked_at = NOW() WHERE fixture_id = %s",
            (fixture_id,))
        return gravadas

    def backfill(self, teto_requisicoes: int = 100, temporada_minima: int = 2024) -> dict:
        """Escalacao das partidas encerradas que ainda nao foram pedidas, da
        mais recente pra mais antiga (a que o dossie le primeiro)."""
        self._open()
        com = sem = 0
        try:
            self.cur.execute("""
                SELECT fixture_id, league_id, season, match_date
                  FROM match_statistics
                 WHERE lineups_checked_at IS NULL
                   AND status IN %s AND season >= %s
                 ORDER BY match_date DESC
                 LIMIT %s
            """, (FINALIZADOS, temporada_minima, teto_requisicoes))
            for fixture_id, league_id, season, match_date in self.cur.fetchall():
                try:
                    resposta = buscar("fixtures/lineups", {"fixture": fixture_id},
                                      origem="coletor_escalacao")
                except Exception as e:
                    # Falha de rede nao marca: a partida volta na proxima.
                    print(f"[ESCALACAO] fixture_id={fixture_id}: {e}")
                    continue
                if self._gravar(fixture_id, league_id, season, match_date, resposta):
                    com += 1
                else:
                    sem += 1
                self.conn.commit()
            self.cur.execute("""
                SELECT COUNT(*) FROM match_statistics
                 WHERE lineups_checked_at IS NULL AND status IN %s AND season >= %s
            """, (FINALIZADOS, temporada_minima))
            restantes = self.cur.fetchone()[0]
        finally:
            self._close()
        resumo = {"buscadas": com + sem, "com_escalacao": com, "sem_escalacao": sem,
                  "restantes": restantes}
        print(f"[ESCALACAO] {resumo}")
        return resumo
