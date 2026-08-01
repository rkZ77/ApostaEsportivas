"""Coletor de estatistica POR JOGADOR por jogo (/fixtures/players).

Ate 2026-08-01 o projeto nao tinha nenhuma entidade de jogador no banco --
so' numero agregado por time em match_statistics. Este coletor preenche
player_match_stats, que destrava:

- mercados de falta por jogador (fouls_committed / fouls_drawn);
- defesas POR GOLEIRO (saves). match_statistics.home_goalkeeper_saves e' a
  soma do time: se houve substituicao do goleiro, o numero nao pertence a
  ninguem. Pro modelo de defesas isso importa, porque o mercado e' apostado
  no goleiro, nao no time.

ATENCAO -- MAPEAMENTO NAO VERIFICADO CONTRA A API AINDA. Escrito em
2026-08-01 com a cota diaria da API-Football ja esgotada, entao os nomes de
campo vieram da documentacao, nao de uma resposta real. Por isso:

- toda leitura passa por _num()/_get, que devolvem None em vez de estourar
  se o campo mudar de nome ou vier ausente;
- a coluna `raw` guarda o bloco `statistics` original, entao da' pra
  reprocessar sem recoletar se algum mapeamento estiver errado;
- a primeira fixture de cada execucao imprime as chaves cruas recebidas
  (DEBUG_SHAPE), que e' o jeito de confirmar o mapeamento na primeira
  rodada real.

Confirmar na primeira execucao antes de confiar nos numeros.
"""
from __future__ import annotations

import json
import os
import time

import requests
from dotenv import find_dotenv, load_dotenv

from utils.db_utils import get_connection

load_dotenv(find_dotenv())

BASE = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": os.getenv("API_FOOTBALL_KEY")}

# A API limita requisicoes por minuto; o resto do projeto usa a mesma pausa.
PAUSA_ENTRE_CHAMADAS = 0.4


def _get(dado, *caminho):
    """Navega dicts aninhados sem estourar se faltar chave no meio."""
    atual = dado
    for chave in caminho:
        if not isinstance(atual, dict):
            return None
        atual = atual.get(chave)
    return atual


def _num(dado, *caminho):
    """Igual a _get, mas devolve int/float ou None -- a API manda null,
    string e ate '80%' (posse) dependendo do campo."""
    valor = _get(dado, *caminho)
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return valor
    texto = str(valor).strip().replace("%", "")
    if not texto:
        return None
    try:
        return float(texto) if "." in texto else int(texto)
    except ValueError:
        return None


class PlayerStatsCollectorService:

    def __init__(self, debug_shape: bool = True):
        self.debug_shape = debug_shape
        self._ja_mostrou_shape = False

    def _buscar(self, fixture_id: int) -> list:
        r = requests.get(f"{BASE}/fixtures/players", headers=HEADERS,
                         params={"fixture": fixture_id}, timeout=20)
        r.raise_for_status()
        corpo = r.json()
        erros = corpo.get("errors")
        # A API devolve 200 com errors preenchido quando estoura cota ou plano.
        if erros:
            raise RuntimeError(f"API recusou: {erros}")
        return corpo.get("response", []) or []

    def _mostrar_shape(self, bloco_stats: dict) -> None:
        """Imprime a estrutura crua uma vez, pra conferir o mapeamento."""
        if self._ja_mostrou_shape or not self.debug_shape:
            return
        self._ja_mostrou_shape = True
        print("[PLAYER_STATS][DEBUG_SHAPE] grupos recebidos:")
        for grupo, conteudo in (bloco_stats or {}).items():
            if isinstance(conteudo, dict):
                print(f"    {grupo}: {list(conteudo.keys())}")
            else:
                print(f"    {grupo}: {type(conteudo).__name__}")

    def _linhas_da_fixture(self, fixture: dict, resposta: list) -> list[tuple]:
        linhas = []
        for bloco_time in resposta:
            team_id = _get(bloco_time, "team", "id")
            team_name = _get(bloco_time, "team", "name")
            for jogador in bloco_time.get("players", []) or []:
                stats = (jogador.get("statistics") or [{}])[0]
                self._mostrar_shape(stats)
                linhas.append((
                    fixture["fixture_id"], _get(jogador, "player", "id"),
                    _get(jogador, "player", "name"), team_id, team_name,
                    fixture.get("league_id"), fixture.get("season"), fixture.get("match_date"),
                    _get(stats, "games", "position"),
                    _num(stats, "games", "minutes"),
                    _num(stats, "games", "rating"),
                    bool(_get(stats, "games", "substitute")),
                    _num(stats, "shots", "total"), _num(stats, "shots", "on"),
                    _num(stats, "goals", "total"), _num(stats, "goals", "conceded"),
                    _num(stats, "goals", "assists"), _num(stats, "goals", "saves"),
                    _num(stats, "passes", "total"), _num(stats, "passes", "key"),
                    _num(stats, "tackles", "total"), _num(stats, "tackles", "blocks"),
                    _num(stats, "tackles", "interceptions"),
                    _num(stats, "duels", "total"), _num(stats, "duels", "won"),
                    _num(stats, "dribbles", "attempts"), _num(stats, "dribbles", "success"),
                    _num(stats, "fouls", "drawn"), _num(stats, "fouls", "committed"),
                    _num(stats, "cards", "yellow"), _num(stats, "cards", "red"),
                    json.dumps(stats, ensure_ascii=False),
                ))
        return linhas

    def coletar(self, fixtures: list[dict]) -> int:
        """fixtures: dicts com fixture_id e, opcionalmente, league_id/season/
        match_date. Devolve quantas linhas de jogador foram gravadas."""
        if not fixtures:
            print("[PLAYER_STATS] Nenhuma fixture recebida.")
            return 0

        conn = get_connection()
        cur = conn.cursor()
        total = 0

        for fixture in fixtures:
            fid = fixture["fixture_id"]
            try:
                linhas = self._linhas_da_fixture(fixture, self._buscar(fid))
                if not linhas:
                    print(f"[PLAYER_STATS] Fixture {fid}: sem dado de jogador (jogo nao comecou?).")
                    continue
                cur.executemany("""
                    INSERT INTO player_match_stats (
                        fixture_id, player_id, player_name, team_id, team_name,
                        league_id, season, match_date, position, minutes, rating, is_substitute,
                        shots_total, shots_on, goals_total, goals_conceded, assists, saves,
                        passes_total, passes_key, tackles_total, blocks, interceptions,
                        duels_total, duels_won, dribbles_attempts, dribbles_success,
                        fouls_drawn, fouls_committed, cards_yellow, cards_red, raw
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (fixture_id, player_id) DO UPDATE SET
                        minutes = EXCLUDED.minutes, rating = EXCLUDED.rating,
                        saves = EXCLUDED.saves, fouls_committed = EXCLUDED.fouls_committed,
                        fouls_drawn = EXCLUDED.fouls_drawn, raw = EXCLUDED.raw
                """, linhas)
                conn.commit()
                total += len(linhas)
                print(f"[PLAYER_STATS] Fixture {fid}: {len(linhas)} jogadores.")
            except Exception as e:
                conn.rollback()
                print(f"[PLAYER_STATS] Erro na fixture {fid}, pulando: {e}")
            time.sleep(PAUSA_ENTRE_CHAMADAS)

        cur.close()
        conn.close()
        print(f"[PLAYER_STATS] {total} linhas de jogador gravadas.")
        return total

    def coletar_pendentes(self, limite: int = 50) -> int:
        """Fixtures ja finalizadas que ainda nao tem estatistica de jogador.

        Usa match_statistics como fonte de jogos encerrados -- e' a mesma
        tabela que o resto do projeto trata como registro permanente.
        """
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT ms.fixture_id, ms.league_id, ms.season, ms.match_date
            FROM match_statistics ms
            LEFT JOIN player_match_stats p ON p.fixture_id = ms.fixture_id
            WHERE p.fixture_id IS NULL
            ORDER BY ms.match_date DESC
            LIMIT %s
        """, (limite,))
        fixtures = [{"fixture_id": r[0], "league_id": r[1], "season": r[2], "match_date": r[3]}
                    for r in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"[PLAYER_STATS] {len(fixtures)} fixtures pendentes (limite {limite}).")
        return self.coletar(fixtures)
