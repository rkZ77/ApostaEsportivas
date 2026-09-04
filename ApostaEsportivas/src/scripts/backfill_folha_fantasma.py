"""Apaga a folha FANTASMA que o coletor antigo gravou como zero.

O DEFEITO

Ate' 2026-07-25 o coletor transformava folha AUSENTE em zero: a API respondia
com lista vazia (jogo sem estatistica publicada) e o banco guardava a partida
com escanteio 0, falta 0, chute 0 e posse 0,00. Aquele bug foi corrigido na
origem -- hoje `utils/stat_sheet.folha_publicada` devolve None em tudo -- mas a
correcao nunca voltou pras linhas ja gravadas.

E ELAS SAO INVISIVEIS PRA TODO GUARD DO PROJETO. `stats_model.
_tem_folha_da_familia` derruba do pool o jogo de folha PARCIAL, e ele decide
isso olhando `is None`. Uma folha fantasma nao tem None em lugar nenhum: tem
zero. Passa pelo filtro como se fosse um jogo de verdade em que ninguem bateu
escanteio.

Medido em PROD em 2026-08-28: 90 dos 1.790 jogos FT, 86 deles COM GOL marcado
-- ou seja, partidas que aconteceram de verdade.


O MARCADOR

Posse de bola ZERO nos DOIS lados. Posse e' o unico campo da folha em que zero
e' fisicamente impossivel num jogo que aconteceu (por isso ele esta' em
`stat_sheet._NUNCA_ZERO`, junto com precisao de passe). Escanteio 0, falta 0 e
ate' chute 0 sao valores legitimos e raros; posse 0,00 nos dois times, nunca.

Nao se usa "tudo zerado" como criterio porque isso deixaria de fora a folha
fantasma de um jogo que teve gol -- e' o caso mais comum, 86 dos 90.


O QUE ELE FAZ

Apaga (NULL) as colunas de folha dessas linhas. NAO apaga placar, data, status,
arbitro nem rodada: essas vem da listagem de fixtures, nao da folha, e sao
verdadeiras. A linha continua existindo, entao a partida NAO volta pra fila de
"jogo encerrado sem linha" -- ela fica como jogo cujo provedor nao publicou
estatistica, que e' a verdade.

Depois disso e' obrigatorio refazer `team_statistics`: corrigir o jogo e deixar
a media velha troca um numero errado por outro, com a agravante de parecer
atualizado (mesma regra do backfill de vermelho). O script faz isso sozinho.

Uso:
    python scripts/backfill_folha_fantasma.py --env dev
    python scripts/backfill_folha_fantasma.py --env prod --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

#: Colunas que vem da FOLHA de estatistica, e so' elas. Placar, placar de 90',
#: intervalo, arbitro, rodada, data e status vem da listagem de fixtures e
#: continuam validos numa partida sem folha.
_COLUNAS_DA_FOLHA = [
    "home_corners", "away_corners", "total_corners",
    "home_yellow_cards", "away_yellow_cards", "total_yellow_cards",
    "home_red_cards", "away_red_cards", "total_red_cards",
    "home_shots_on", "away_shots_on",
    "home_shots_off", "away_shots_off",
    "home_total_shots", "away_total_shots",
    "home_blocked_shots", "away_blocked_shots",
    "home_goalkeeper_saves", "away_goalkeeper_saves",
    "home_fouls", "away_fouls",
    "home_offsides", "away_offsides",
    "home_possession", "away_possession",
    "home_passes", "away_passes",
    "home_passes_accuracy", "away_passes_accuracy",
]

#: A folha fantasma. Ver o cabecalho pro porque o marcador e' a posse.
_SQL_FANTASMA = """
    status = 'FT'
    AND home_possession = 0
    AND away_possession = 0
"""


def _relatorio(cur):
    cur.execute(f"""
        SELECT COUNT(*) FILTER (WHERE {_SQL_FANTASMA})                    AS fantasmas,
               COUNT(*) FILTER (WHERE {_SQL_FANTASMA}
                                  AND (home_goals > 0 OR away_goals > 0)) AS com_gol,
               COUNT(*) FILTER (WHERE status = 'FT')                      AS ft
          FROM match_statistics
    """)
    fantasmas, com_gol, ft = cur.fetchone()
    pct = (100.0 * fantasmas / ft) if ft else 0
    print(f"  folhas fantasma : {fantasmas} de {ft} jogos FT ({pct:.1f}%)")
    print(f"  delas, com gol  : {com_gol}")

    cur.execute(f"""
        SELECT ms.league_id, COALESCE(l.name, '(liga nao cadastrada)'), ms.season,
               COUNT(*)
          FROM match_statistics ms
     LEFT JOIN leagues l ON l.league_id = ms.league_id
         WHERE {_SQL_FANTASMA}
      GROUP BY 1, 2, 3
      ORDER BY 4 DESC
    """)
    linhas = cur.fetchall()
    if linhas:
        print("\n  por liga/temporada:")
        for liga, nome, season, n in linhas:
            print(f"    {liga:>5} {nome[:32]:32} {season}  {n}")
    return fantasmas


def _times_afetados(cur):
    """(time, liga, temporada) que tem media contaminada por folha fantasma."""
    cur.execute(f"""
        SELECT DISTINCT lado.team_id, ms.league_id, ms.season
          FROM match_statistics ms
          CROSS JOIN LATERAL (VALUES (ms.home_team_id), (ms.away_team_id))
               AS lado(team_id)
         WHERE {_SQL_FANTASMA}
           AND lado.team_id IS NOT NULL
    """)
    return [{"team_id": r[0], "league_id": r[1], "season": r[2]} for r in cur.fetchall()]


def _aplicar(cur):
    sets = ", ".join(f"{c} = NULL" for c in _COLUNAS_DA_FOLHA)
    cur.execute(f"""
        UPDATE match_statistics
           SET {sets}, last_updated = NOW()
         WHERE {_SQL_FANTASMA}
    """)
    return cur.rowcount or 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=("dev", "prod"), required=True)
    ap.add_argument("--apply", action="store_true",
                    help="sem isto e' dry-run: so' mostra o que faria")
    args = ap.parse_args()

    os.environ["DB_ENV"] = args.env
    conn = get_connection(args.env)
    cur = conn.cursor()

    print(f"\n=== ANTES ({args.env.upper()}) ===")
    alvo = _relatorio(cur)
    afetados = _times_afetados(cur)
    print(f"\n  medias a refazer depois: {len(afetados)} (time, liga, temporada)")

    if not args.apply:
        print(f"\n[DRY-RUN] {alvo} linha(s) seriam limpas. Rode com --apply.")
        cur.close(); conn.close()
        return

    if not alvo:
        print("\nNada a limpar.")
        cur.close(); conn.close()
        return

    limpas = _aplicar(cur)
    conn.commit()
    print(f"\n[APPLY] {limpas} folha(s) fantasma apagada(s).")

    # A media DEPOIS, e nao antes: o agregador le' `match_statistics`.
    from services.team_stats_aggregator_service import TeamStatsAggregatorService
    agg = TeamStatsAggregatorService()
    for t in afetados:
        try:
            agg.process_single_team(t["team_id"], t["league_id"], t["season"])
        except Exception as e:
            print(f"   x falha no time {t['team_id']}: {e}")
    print(f"[APPLY] {len(afetados)} media(s) refeita(s).")

    print(f"\n=== DEPOIS ({args.env.upper()}) ===")
    _relatorio(cur)
    cur.close(); conn.close()


if __name__ == "__main__":
    main()
