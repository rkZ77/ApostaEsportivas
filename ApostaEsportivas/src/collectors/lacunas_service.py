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
    for rotulo, _, temporada, _ in TIPOS:
        a, d = antes.get(rotulo), depois.get(rotulo)
        if not d:
            continue
        pct = 100 * (d[1] - d[0]) / d[1] if d[1] else 100
        print(f"    {rotulo:<10} desde {temporada}: faltavam {a[0] if a else '?'}, "
              f"faltam {d[0]} de {d[1]} ({pct:.0f}% coberto)")
    return {"antes": antes, "depois": depois}
