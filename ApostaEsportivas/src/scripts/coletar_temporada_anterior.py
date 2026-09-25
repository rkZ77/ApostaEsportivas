"""coletar_temporada_anterior.py · a amostra que falta em comeco de temporada.

SEM `--aplicar` NAO ESCREVE NADA E NAO GASTA COTA: o padrao e' relatorio.

Uso:
  DB_ENV=prod python src/scripts/coletar_temporada_anterior.py
  DB_ENV=prod python src/scripts/coletar_temporada_anterior.py --aplicar --teto 200
  DB_ENV=prod python src/scripts/coletar_temporada_anterior.py --liga 140 --aplicar

POR QUE ISTO EXISTE
-------------------
O motor pre-jogo le historico com `AND ms.season = %s`
(match_stats_service.get_all_matches_full). Em comeco de temporada isso e' um
teto que nenhum limiar contorna: na semana de 14/09/2026, seis ligas europeias
que reiniciaram em agosto tinham 6 ou 7 jogos por time, e delas saiu o bloco de
amostra curta que mediu 53,7% de acerto e -11,57u contra 63,4% e +4,96u de quem
tinha 8 jogos ou mais. A nota inteira esta' no topo de pick_engine/config.py.

O piso de amostra subiu pra 8 e resolveu o PREJUIZO. Ele nao resolve o VOLUME:
liga que reiniciou simplesmente nao produz pick por umas tres rodadas. Quem
resolve o volume e' este coletor, porque `get_all_matches_full` passou a ler a
temporada anterior quando a corrente ainda e' curta -- e em PROD nao havia uma
unica linha de temporada anterior dessas ligas em `match_statistics`, entao
alargar a janela sozinho nao leria nada.

O QUE ELE NAO RESOLVE
---------------------
Time PROMOVIDO. A temporada passada dele esta' sob o `league_id` da divisao de
baixo, e o motor le travado na liga da partida. Ele continua curto ate' acumular,
e esta' certo: 38 jogos da segunda divisao nao descrevem o time na primeira.

CUSTO DE COTA, QUE E' O PONTO
----------------------------
1 requisicao pela lista de jogos da liga, mais 1 POR JOGO pra folha de
estatistica. Temporada inteira de uma liga de 20 times = ~380 folhas. Por isso
duas travas:

  · `--rodadas` (padrao 16) pega so' as rodadas mais recentes da temporada
    passada. O motor precisa de ~16 jogos por time, nao da temporada inteira;
  · `--teto` corta a rodada num numero de requisicoes. A varredura e'
    idempotente (jogo com folha completa nao volta), entao parar no meio e'
    seguro e continuar e' rodar de novo.

Liga de COPA fica fora automaticamente: nelas o motor ja' le' o historico de
todas as competicoes do time (competition_profile.uses_all_competitions_history),
entao amostra curta de copa nao e' este problema e a cota gasta aqui seria
desperdicio.
"""
import argparse
import os
import sys

# O `src/` do motor NUNCA na frente do sys.path (2026-09-04).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.match_statistics_sync_service import MatchStatisticsSyncService  # noqa: E402
from services.match_stats_service import LIMIAR_TEMPORADA_ANTERIOR  # noqa: E402
from services.pick_engine.competition_profile import uses_all_competitions_history  # noqa: E402
from utils.db_utils import get_connection  # noqa: E402

#: Quantas rodadas da temporada passada buscar por liga. 16 porque o motor pede
#: ~16 jogos no historico pra garantir 8 no pool depois do filtro de mando (ver
#: LIMIAR_TEMPORADA_ANTERIOR), e uma rodada rende 1 jogo por time.
RODADAS_PADRAO = 16


def _diagnostico(cur) -> list:
    """Por liga ativa: a MEDIANA de jogos por time na temporada corrente e na
    anterior. E' a mesma consulta que respondeu "quais ligas estao curtas" em
    24/09, virada em funcao.

    MEDIANA, E NAO "EXISTE LINHA DA ANTERIOR?". A primeira versao deste script
    perguntava se havia qualquer jogo da temporada passada e marcou quatro ligas
    como resolvidas -- Premier League, Bundesliga, Serie A e Ligue 1 tinham 34 a
    47 jogos gravados de uma temporada de 380, ou seja DOIS por time. Presenca
    nao e' profundidade: o que decide e' se corrente + anterior alcanca o limiar
    que o motor pede.
    """
    cur.execute("""
        WITH jogos AS (
          SELECT ms.league_id, ms.season, t.team_id, COUNT(*) AS n
            FROM match_statistics ms
            JOIN (SELECT home_team_id AS team_id, league_id, season, match_date
                    FROM match_statistics
                  UNION ALL
                  SELECT away_team_id AS team_id, league_id, season, match_date
                    FROM match_statistics) t
              ON t.league_id = ms.league_id AND t.season = ms.season
             AND t.match_date = ms.match_date
             AND (ms.home_team_id = t.team_id OR ms.away_team_id = t.team_id)
           WHERE ms.status IN ('FT','AET','PEN')
           GROUP BY 1,2,3)
        SELECT l.league_id, l.name, l.season,
               COALESCE(PERCENTILE_DISC(0.5) WITHIN GROUP (
                   ORDER BY CASE WHEN j.season = l.season THEN j.n END), 0) AS mediana_atual,
               COALESCE(PERCENTILE_DISC(0.5) WITHIN GROUP (
                   ORDER BY CASE WHEN j.season = l.season - 1 THEN j.n END), 0) AS mediana_anterior
          FROM leagues l
          LEFT JOIN jogos j ON j.league_id = l.league_id
         WHERE l.ativa IS TRUE
         GROUP BY 1,2,3
         ORDER BY mediana_atual
    """)
    colunas = [d[0] for d in cur.description]
    return [dict(zip(colunas, r)) for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true",
                    help="coleta de verdade (gasta cota). Sem isto, so' relatorio.")
    ap.add_argument("--liga", type=int, help="so' esta liga")
    ap.add_argument("--rodadas", type=int, default=RODADAS_PADRAO,
                    help=f"rodadas mais recentes da temporada passada (padrao {RODADAS_PADRAO})")
    ap.add_argument("--teto", type=int, default=200,
                    help="teto de requisicoes de folha por liga (padrao 200)")
    args = ap.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        ligas = _diagnostico(cur)
    finally:
        conn.close()

    if args.liga:
        ligas = [l for l in ligas if l["league_id"] == args.liga]

    print(f"Limiar do motor: {LIMIAR_TEMPORADA_ANTERIOR} jogos na temporada corrente.")
    print("Abaixo dele a temporada anterior passa a ser lida -- se existir no banco.\n")
    print(f"{'liga':>5} {'nome':<24} {'temp':>5} {'atual':>6} {'anter.':>7} "
          f"{'janela':>7} {'acao':<30}")

    alvos = []
    for l in ligas:
        atual = int(l["mediana_atual"] or 0)
        anterior = int(l["mediana_anterior"] or 0)
        janela = atual + anterior
        e_copa = uses_all_competitions_history(l["league_id"])
        if e_copa:
            acao = "copa: le' todas as competicoes"
        elif atual >= LIMIAR_TEMPORADA_ANTERIOR:
            acao = "temporada cheia, nada a fazer"
        elif janela >= LIMIAR_TEMPORADA_ANTERIOR:
            acao = "janela ja' alcanca o limiar"
        else:
            acao = f"COLETAR (faltam ~{LIMIAR_TEMPORADA_ANTERIOR - janela}/time)"
            alvos.append(l)
        print(f"{l['league_id']:>5} {(l['name'] or '?')[:24]:<24} {l['season']:>5} "
              f"{atual:>6} {anterior:>7} {janela:>7} {acao:<30}")

    if not alvos:
        print("\nNenhuma liga precisa de backfill agora.")
        return

    custo = len(alvos) * (1 + args.teto)
    print(f"\n{len(alvos)} liga(s) a coletar. Custo maximo estimado: {custo} requisicoes "
          f"({args.teto} folhas + 1 listagem por liga).")
    print(f"Recorte: as {args.rodadas} rodadas mais recentes da temporada anterior.")

    if not args.aplicar:
        print("\nRelatorio apenas. Rode com --aplicar pra coletar.")
        return

    servico = MatchStatisticsSyncService()
    for l in alvos:
        anterior = l["season"] - 1
        print(f"\n===== {l['name']} ({l['league_id']}) · temporada {anterior} =====")
        servico.sync_all_finished_fixtures(
            use_date_filter=False,
            apenas_liga=l["league_id"],
            temporada=anterior,
            # Na temporada passada metade dos adversarios era time rebaixado,
            # que nao esta mais em `teams` com este league_id.
            exigir_os_dois_times=False,
            ultimas_rodadas=args.rodadas,
            teto_requisicoes=args.teto,
        )

    print("\nFeito. Rode de novo pra ver o que sobrou (a varredura e' idempotente)")
    print("e depois `medir_red_por_amostra.py` pra acompanhar o efeito na amostra.")


if __name__ == "__main__":
    main()
