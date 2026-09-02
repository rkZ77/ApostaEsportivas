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
from services import api_quota

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


#: (coluna do banco, caminho no bloco `statistics` da API).
#:
#: ERA CODIGO E VIROU DADO (2026-08-28). Os 19 `_num(stats, "grupo", "campo")`
#: viviam soltos dentro de `_linhas_da_fixture`, na ordem exata das colunas do
#: INSERT -- entao "conferir o mapeamento" era ler duas listas em paralelo e
#: torcer. Como tabela, a mesma estrutura serve pra TRES coisas: montar a
#: linha, imprimir o shape, e CONFERIR contra uma resposta real da API.
#:
#: Ordem: a mesma do INSERT, e ha' teste travando isso -- a tupla e' posicional
#: e uma coluna fora de ordem grava chute no campo de falta em silencio.
MAPA_DE_CAMPOS: tuple = (
    ("shots_total",       ("shots", "total")),
    ("shots_on",          ("shots", "on")),
    ("goals_total",       ("goals", "total")),
    ("goals_conceded",    ("goals", "conceded")),
    ("assists",           ("goals", "assists")),
    ("saves",             ("goals", "saves")),
    ("passes_total",      ("passes", "total")),
    ("passes_key",        ("passes", "key")),
    ("tackles_total",     ("tackles", "total")),
    ("blocks",            ("tackles", "blocks")),
    ("interceptions",     ("tackles", "interceptions")),
    ("duels_total",       ("duels", "total")),
    ("duels_won",         ("duels", "won")),
    ("dribbles_attempts", ("dribbles", "attempts")),
    ("dribbles_success",  ("dribbles", "success")),
    ("fouls_drawn",       ("fouls", "drawn")),
    ("fouls_committed",   ("fouls", "committed")),
    ("cards_yellow",      ("cards", "yellow")),
    ("cards_red",         ("cards", "red")),
)


def conferir_mapeamento(stats: dict) -> dict:
    """O mapeamento bate com ESTA resposta da API? Uma fixture responde.

    POR QUE ISTO EXISTE

    O cabecalho deste arquivo avisa em maiusculas desde 01/08 que o mapeamento
    nunca foi conferido contra a API -- os nomes de campo vieram da
    documentacao, porque a cota do dia ja' tinha estourado quando ele foi
    escrito. "Confirmar na primeira execucao antes de confiar nos numeros",
    diz a nota. Meses depois, nada confirmou.

    E a falha e' MUDA: `_num()` devolve None em vez de estourar quando o campo
    nao existe (o que protege a execucao, e por isso fica), entao um grupo
    renomeado pela API vira coluna NULL em silencio. O motor le' aquilo como
    "o provedor nao publicou" e simplesmente nao gera pick -- indistinguivel de
    um dia sem oportunidade.

    Devolve tres listas, e a do meio e' a que importa:

      ok          coluna cujo caminho existe na resposta
      ausentes    caminho que NAO existe · mapeamento errado ou campo removido
      ignorados   grupo/campo que a API manda e o coletor NAO le

    `ausentes` com a lista inteira dentro significa que a resposta veio vazia
    (jogador que nao entrou), e nao que o mapeamento quebrou -- por isso o
    retorno traz `vazia`.
    """
    stats = stats or {}
    ok, ausentes = [], []
    for coluna, caminho in MAPA_DE_CAMPOS:
        atual = stats
        achou = True
        for chave in caminho:
            if not isinstance(atual, dict) or chave not in atual:
                achou = False
                break
            atual = atual[chave]
        (ok if achou else ausentes).append(f"{coluna} <- {'.'.join(caminho)}")

    lidos = {caminho for _c, caminho in MAPA_DE_CAMPOS}
    ignorados = []
    for grupo, conteudo in stats.items():
        if isinstance(conteudo, dict):
            for campo in conteudo:
                if (grupo, campo) not in lidos:
                    ignorados.append(f"{grupo}.{campo}")
        elif (grupo,) not in lidos:
            ignorados.append(str(grupo))

    return {
        "vazia": not stats,
        "ok": ok,
        "ausentes": ausentes,
        "ignorados": sorted(ignorados),
    }


class PlayerStatsCollectorService:

    def __init__(self, debug_shape: bool = True):
        self.debug_shape = debug_shape
        self._ja_mostrou_shape = False

    def _buscar(self, fixture_id: int) -> list:
        r = requests.get(f"{BASE}/fixtures/players", headers=HEADERS,
                         params={"fixture": fixture_id}, timeout=20)
        api_quota.registrar(getattr(r, "headers", None), "coletor_jogadores")
        r.raise_for_status()
        corpo = r.json()
        erros = corpo.get("errors")
        # A API devolve 200 com errors preenchido quando estoura cota ou plano.
        if erros:
            raise RuntimeError(f"API recusou: {erros}")
        return corpo.get("response", []) or []

    def _mostrar_shape(self, bloco_stats: dict) -> None:
        """Confere o mapeamento contra a resposta real, uma vez por execucao.

        Antes so' IMPRIMIA os grupos recebidos e deixava a conferencia pra quem
        estivesse olhando o stdout na hora -- que e' o mesmo que nao conferir.
        Agora ele compara com MAPA_DE_CAMPOS e diz o que nao bate.
        """
        if self._ja_mostrou_shape or not self.debug_shape:
            return
        # Jogador que nao entrou vem com o bloco vazio · conferir contra ele
        # daria "19 campos ausentes" e o alarme seria falso. Espera o proximo.
        if not bloco_stats:
            return
        self._ja_mostrou_shape = True

        laudo = conferir_mapeamento(bloco_stats)
        print("[PLAYER_STATS][DEBUG_SHAPE] grupos recebidos:")
        for grupo, conteudo in bloco_stats.items():
            if isinstance(conteudo, dict):
                print(f"    {grupo}: {list(conteudo.keys())}")
            else:
                print(f"    {grupo}: {type(conteudo).__name__}")

        if laudo["ausentes"]:
            print(f"[PLAYER_STATS][DEBUG_SHAPE] *** {len(laudo['ausentes'])} CAMPO(S) "
                  f"NAO ENCONTRADO(S) NA RESPOSTA ***")
            for linha in laudo["ausentes"]:
                print(f"    FALTA  {linha}")
            print("    Esses viram NULL em silencio: _num() devolve None em vez "
                  "de estourar, e o motor le' como 'provedor nao publicou'.")
        else:
            print(f"[PLAYER_STATS][DEBUG_SHAPE] mapeamento OK · "
                  f"{len(laudo['ok'])} campo(s) conferido(s) contra a resposta real.")

        if laudo["ignorados"]:
            print(f"[PLAYER_STATS][DEBUG_SHAPE] a API manda e o coletor ignora: "
                  f"{', '.join(laudo['ignorados'])}")

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
                    # Montada a partir de MAPA_DE_CAMPOS, na ordem dele · era
                    # uma lista de 19 chamadas escritas na mao, paralela a lista
                    # de colunas do INSERT. Duas listas posicionais que
                    # precisavam concordar e nada garantia que concordassem.
                    *[_num(stats, *caminho) for _coluna, caminho in MAPA_DE_CAMPOS],
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

    def coletar_pendentes(self, limite: int = 50, por_liga: int | None = None) -> int:
        """Fixtures ja finalizadas que ainda nao tem estatistica de jogador.

        Usa match_statistics como fonte de jogos encerrados -- e' a mesma
        tabela que o resto do projeto trata como registro permanente.

        RODIZIO POR LIGA (2026-08-27)
        -----------------------------
        Ate' aqui era `ORDER BY match_date DESC LIMIT 50`, e com backlog isso
        NAO e' um limite, e' um filtro: as 50 partidas mais recentes do banco
        inteiro caem quase todas nas ligas que jogaram ontem. Liga que joga em
        outro dia da semana nunca era alcancada enquanto a fila fosse maior que
        o limite -- e ela sempre e', porque cada rodada acrescenta jogo novo no
        topo enquanto o antigo espera embaixo.

        O sintoma nao e' erro: e' o banco de jogador ficar com "muita liga
        faltando" pra sempre, e o Player Stats so' publicar prop das duas ou
        tres ligas de calendario mais denso.

        O rodizio corta por LIGA: cada uma avanca `por_liga` partidas por
        execucao, e a ordem dentro dela continua sendo a mais recente primeiro
        (a API publica folha de jogo velho cada vez menos, mesma razao da
        recoleta em lote do /admin). Assim toda liga da aba Ligas anda, mesmo
        que devagar, em vez de umas andarem e outras nunca comecarem.

        `por_liga=None` reparte o limite entre as ligas que TEM fila, com o
        piso de 1: com 12 ligas pendentes e limite 50, sao 4 por liga.
        """
        conn = get_connection()
        cur = conn.cursor()

        # Quantas ligas tem fila AGORA · e' o divisor do rodizio, e ele muda a
        # cada execucao (liga que zerou sai, liga que jogou ontem entra).
        # SO' LIGA LIGADA (29/08, decisao do usuario).
        #
        # Este era o ultimo coletor que ainda varria `match_statistics` sem
        # olhar `leagues.ativa`. A tabela guarda tudo que ja' foi coletado,
        # entao liga desativada continuava na fila e gastava requisicao pra
        # preencher jogador de partida que o motor nao le mais.
        #
        # O rodizio por liga piorava: a liga morta entrava no divisor e tirava
        # vaga das vivas na mesma passada.
        cur.execute("""
            SELECT COUNT(DISTINCT ms.league_id)
            FROM match_statistics ms
            LEFT JOIN player_match_stats p ON p.fixture_id = ms.fixture_id
            JOIN leagues l ON l.league_id = ms.league_id
                          AND l.season = ms.season
                          AND COALESCE(l.ativa, TRUE)
            WHERE p.fixture_id IS NULL AND ms.league_id IS NOT NULL
        """)
        ligas_com_fila = (cur.fetchone() or [0])[0] or 0

        if por_liga is None:
            por_liga = max(1, limite // ligas_com_fila) if ligas_com_fila else limite

        cur.execute("""
            SELECT fixture_id, league_id, season, match_date FROM (
                SELECT ms.fixture_id, ms.league_id, ms.season, ms.match_date,
                       ROW_NUMBER() OVER (PARTITION BY ms.league_id
                                          ORDER BY ms.match_date DESC) AS ordem
                  FROM match_statistics ms
             LEFT JOIN player_match_stats p ON p.fixture_id = ms.fixture_id
                  -- Mesmo recorte do contador acima. Os dois precisam andar
                  -- juntos: divisor de um universo e fila de outro dariam um
                  -- `por_liga` calculado sobre ligas que nao entram na fila.
                  JOIN leagues l ON l.league_id = ms.league_id
                                AND l.season = ms.season
                                AND COALESCE(l.ativa, TRUE)
                 WHERE p.fixture_id IS NULL
            ) t
            WHERE t.ordem <= %s
            -- Entre as ligas, a mais recente primeiro · quando o limite geral
            -- corta antes do fim, ele corta o jogo mais velho, nao a liga mais
            -- azarada da ordenacao.
            ORDER BY t.match_date DESC
            LIMIT %s
        """, (por_liga, limite))
        fixtures = [{"fixture_id": r[0], "league_id": r[1], "season": r[2], "match_date": r[3]}
                    for r in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"[PLAYER_STATS] {len(fixtures)} fixtures pendentes "
              f"({ligas_com_fila} liga(s) com fila · ate' {por_liga} por liga · teto {limite}).")
        return self.coletar(fixtures)


if __name__ == "__main__":
    # Executavel direto pra o painel Admin poder disparar (ele roda scripts
    # por caminho, nao importa modulo). Limite pelo argv ou PLAYER_STATS_LIMIT.
    import sys

    limite_arg = sys.argv[1] if len(sys.argv) > 1 else os.getenv("PLAYER_STATS_LIMIT", "50")
    PlayerStatsCollectorService().coletar_pendentes(limite=int(limite_arg))
