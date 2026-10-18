"""Lacunas: acha o dado que falta e preenche sozinho, todo dia (18/10/2026).

PEDIDO DO USUARIO
-----------------
"Voce tem que conseguir pegar esses gaps sem minha ajuda e resolver, precisa
ter dados." O caso: Raio-X de escanteio do 1o tempo do Bragantino com 7 jogos
de 30. A coleta diaria so' pede a folha por tempo desde 27/09/2026, e o
historico dependia de um botao no /admin (100 partidas por clique) que quase
nunca foi apertado. Medido em PROD no mesmo dia: 1.793 partidas de 2026 e
todas as 1.034 de 2025 sem o 1o tempo NUNCA pedido. O motor so' conta o jogo
com o numero dos dois lados (stats_model.FAMILIAS_1T), entao a taxa de 1o
tempo saia de amostra curta e so' de jogo recente.

O QUE FAZ
---------
Etapa LACUNAS do `tudo`. Pra cada tipo de dado de historico, conta quanto
falta, preenche dentro de um teto de requisicoes e imprime a cobertura antes e
depois -- o log do Rodar Tudo diz sozinho se o buraco esta' fechando.

  1o tempo     folha por tempo + placar do intervalo · 1 requisicao por
               partida (a folha por tempo so' vem em /fixtures/statistics)
  eventos      minuto de gol, cartao, VAR · 20 partidas por requisicao
  escalacao    titulares, formacao, tecnico · 20 partidas por requisicao

Os tetos somam ~360 requisicoes por dia (o plano e' 7.500). Todos os backfills
sao idempotentes: o que foi pedido sai da fila venha o dado ou nao, e a ordem
e' da partida mais recente pra mais antiga, que e' a que o motor le' primeiro.
"""
from __future__ import annotations

from utils.db_utils import get_connection

FINALIZADOS = ("FT", "AET", "PEN")

#: (rotulo, coluna de "ja' pedido" em match_statistics, temporada minima,
#:  teto de requisicoes por dia). A temporada minima e' a dos proprios
#:  backfills: a API so' publica folha por tempo desde 2024.
TIPOS = (
    ("1o tempo", "stats_1h_checked_at", 2024, 300),
    ("eventos", "events_checked_at", 2025, 30),
    ("escalacao", "lineups_checked_at", 2024, 30),
)


#: So' MEDIDOS aqui: quem preenche e' outra etapa do `tudo`, e o log diz se
#: ela esta' dando conta. (rotulo, SQL que devolve (faltam, total), quem enche)
SO_MEDIR = (
    ("jogos fora do banco", """
        SELECT COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM match_statistics ms
                                                   WHERE ms.fixture_id = cj.fixture_id)), COUNT(*)
          FROM calendario_jogos cj
          JOIN leagues l ON l.league_id = cj.league_id AND l.season = cj.season AND COALESCE(l.ativa, TRUE)
         WHERE cj.status IN ('FT','AET','PEN') AND cj.match_datetime < NOW() - INTERVAL '6 hours'
    """, "DADOS (ate' 200 por dia)"),
    ("jogadores", """
        SELECT COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM player_match_stats p
                                                   WHERE p.fixture_id = ms.fixture_id)), COUNT(*)
          FROM match_statistics ms
          JOIN leagues l ON l.league_id = ms.league_id AND l.season = ms.season AND COALESCE(l.ativa, TRUE)
         WHERE ms.status IN ('FT','AET','PEN')
    """, "ESTATISTICA DE JOGADOR (200 por dia)"),
)


def cobertura() -> dict:
    """{rotulo: (faltam, total)} por tipo, sem API."""
    conn = get_connection()
    cur = conn.cursor()
    saida = {}
    try:
        for rotulo, coluna, temporada, _ in TIPOS:
            try:
                cur.execute(f"""
                    SELECT COUNT(*) FILTER (WHERE {coluna} IS NULL), COUNT(*)
                      FROM match_statistics
                     WHERE status IN %s AND season >= %s
                """, (FINALIZADOS, temporada))
                saida[rotulo] = tuple(cur.fetchone())
            except Exception as e:
                # Coluna que o coletor ainda nao criou neste ambiente.
                conn.rollback()
                print(f"[LACUNAS] {rotulo}: sem como medir ({e})")
        for rotulo, sql, _ in SO_MEDIR:
            try:
                cur.execute(sql)
                saida[rotulo] = tuple(cur.fetchone())
            except Exception as e:
                conn.rollback()
                print(f"[LACUNAS] {rotulo}: sem como medir ({e})")
    finally:
        cur.close()
        conn.close()
    return saida


#: Colunas que `calendario_jogos` ja' tem e `match_statistics` perdeu, copiadas
#: sem API. Medido em PROD (18/10/2026): 810 partidas sem rodada (a ida/volta
#: do mata-mata sai dela) e 91 sem arbitro, as duas com o dado no calendario.
#: COALESCE do lado de quem recebe: so' preenche onde esta' NULL.
DE_GRACA = (
    ("rodada", "round", "round"),
    ("arbitro", "referee", "referee"),
)


def de_graca() -> dict:
    """{rotulo: linhas preenchidas} copiando do calendario. Zero requisicao."""
    conn = get_connection()
    cur = conn.cursor()
    saida = {}
    try:
        for rotulo, destino, origem in DE_GRACA:
            try:
                cur.execute(f"""
                    UPDATE match_statistics ms SET {destino} = cj.{origem}
                      FROM calendario_jogos cj
                     WHERE cj.fixture_id = ms.fixture_id
                       AND ms.{destino} IS NULL AND cj.{origem} IS NOT NULL
                """)
                saida[rotulo] = cur.rowcount
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"[LACUNAS] {rotulo} do calendario: {e}")
    finally:
        cur.close()
        conn.close()
    return saida


def _preencher(rotulo: str, teto: int) -> None:
    if rotulo == "1o tempo":
        from collectors.match_statistics_sync_service import MatchStatisticsSyncService
        MatchStatisticsSyncService().backfill_primeiro_tempo(teto_requisicoes=teto)
    elif rotulo == "eventos":
        from collectors.eventos_collector_service import backfill
        backfill(teto_requisicoes=teto)
    elif rotulo == "escalacao":
        from collectors.lineups_collector_service import LineupsCollectorService
        LineupsCollectorService().backfill(teto_requisicoes=teto)


def preencher(escala: float = 1.0) -> dict:
    """Uma rodada. `escala` multiplica os tetos (2 = o dobro, num dia de folga
    de cota). Um tipo que quebra nao leva os outros."""
    copiados = de_graca()
    if any(copiados.values()):
        print(f"[LACUNAS] copiado do calendario (sem API): {copiados}")
    antes = cobertura()
    for rotulo, _, _, teto in TIPOS:
        faltam = (antes.get(rotulo) or (0, 0))[0]
        if not faltam:
            continue
        try:
            _preencher(rotulo, max(1, int(teto * escala)))
        except Exception as e:
            print(f"[LACUNAS] {rotulo} falhou: {e}")
    depois = cobertura()
    print("[LACUNAS] cobertura (faltam / total de partidas encerradas):")
    linhas = [(r, f"desde {t}") for r, _, t, _ in TIPOS] + [(r, f"enche: {q}") for r, _, q in SO_MEDIR]
    for rotulo, nota in linhas:
        a, d = antes.get(rotulo), depois.get(rotulo)
        if not d:
            continue
        pct = 100 * (d[1] - d[0]) / d[1] if d[1] else 100
        print(f"    {rotulo:<20} faltavam {a[0] if a else '?'}, faltam {d[0]} de {d[1]} "
              f"({pct:.0f}% coberto) · {nota}")
    return {"antes": antes, "depois": depois}
