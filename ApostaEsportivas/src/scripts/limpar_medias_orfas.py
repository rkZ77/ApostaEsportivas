"""Apaga de `team_statistics` a media que o motor nunca vai ler.

O QUE E' UMA MEDIA ORFA

`team_statistics` era alimentada a partir da tabela `teams`, que guarda toda
liga que ja' passou pelo coletor -- inclusive a que foi desativada e a de
temporada encerrada. O motor, do outro lado, so' consulta liga cadastrada,
`ativa` e na temporada corrente (services/team_stats_reader._SQL_ALVOS_DA_MEDIA
depois de 2026-08-28). Tudo que fica fora desse recorte e' numero calculado,
gravado e reescrito sem nenhum leitor.

Medido em PROD em 2026-08-28: 141 das 1.490 linhas, 9,5% da tabela.

    liga INATIVA            96 linhas   (Copa do Mundo)
    liga NAO cadastrada     45 linhas   (6 competicoes do backfill de selecoes)

NAO E' PERDA DE HISTORICO. `team_statistics` e' DERIVADA de `match_statistics`,
que este script nao toca: as partidas continuam todas la', e refazer qualquer
uma destas medias e' reativar a liga e rodar o agregador, a custo zero de
requisicao de API. O que se apaga aqui e' cache, nao fonte.

Por isso a liga fica em `leagues` mesmo depois da limpeza -- desativar uma
competicao nunca significou apagar o que ela jogou.

Uso:
    python scripts/limpar_medias_orfas.py --env dev
    python scripts/limpar_medias_orfas.py --env prod --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

#: Espelha _SQL_ALVOS_DA_MEDIA do lado da media: a linha e' orfa quando a liga
#: dela nao esta' cadastrada, esta' inativa, ou a temporada nao e' mais a
#: corrente daquela liga.
_SQL_ORFA = """
    NOT EXISTS (
        SELECT 1 FROM leagues l
         WHERE l.league_id = ts.league_id
           AND l.season = ts.season
           AND COALESCE(l.ativa, TRUE)
    )
"""


def _relatorio(cur):
    cur.execute(f"""
        SELECT CASE WHEN l.league_id IS NULL          THEN 'liga nao cadastrada'
                    WHEN NOT COALESCE(l.ativa, TRUE)  THEN 'liga inativa'
                    ELSE 'temporada encerrada' END           AS motivo,
               ts.league_id,
               COALESCE(l.name, '(sem cadastro)')            AS liga,
               ts.season,
               COUNT(*)                                      AS linhas
          FROM team_statistics ts
     LEFT JOIN leagues l ON l.league_id = ts.league_id
         WHERE {_SQL_ORFA}
      GROUP BY 1, 2, 3, 4
      ORDER BY 5 DESC
    """)
    linhas = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM team_statistics")
    total = cur.fetchone()[0]
    orfas = sum(r[4] for r in linhas)
    pct = (100.0 * orfas / total) if total else 0
    print(f"  medias orfas: {orfas} de {total} linhas ({pct:.1f}%)")
    for motivo, liga_id, nome, season, n in linhas:
        print(f"    {liga_id:>5} {nome[:30]:30} {season}  {n:>4}  {motivo}")
    return orfas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=("dev", "prod"), required=True)
    ap.add_argument("--apply", action="store_true",
                    help="sem isto e' dry-run: so' mostra o que faria")
    args = ap.parse_args()

    conn = get_connection(args.env)
    cur = conn.cursor()

    print(f"\n=== {args.env.upper()} ===")
    alvo = _relatorio(cur)

    if not args.apply:
        print(f"\n[DRY-RUN] {alvo} linha(s) seriam apagadas. Rode com --apply.")
    elif not alvo:
        print("\nNada a limpar.")
    else:
        cur.execute(f"DELETE FROM team_statistics ts WHERE {_SQL_ORFA}")
        apagadas = cur.rowcount or 0
        conn.commit()
        print(f"\n[APPLY] {apagadas} media(s) orfa(s) apagada(s).")
        print("        `match_statistics` intacta · reativar a liga e rodar o "
              "agregador refaz tudo sem gastar API.")

    cur.close(); conn.close()


if __name__ == "__main__":
    main()
