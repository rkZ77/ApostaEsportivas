"""Reconstroi o cartao vermelho que o coletor apagou entre 2026-07-25 e 2026-08-26.

O DEFEITO

A API-Football publica ZERO EXPLICITO em todo contador da folha de estatistica
-- escanteio, falta, impedimento, chute, amarelo. O UNICO tipo que ela devolve
como `null` e' "Red Cards", e ela faz isso no caso normal: ninguem foi expulso.
Medido em 2026-08-26 sobre 10 partidas FT sorteadas (20 folhas): 18 nulls em
"Red Cards" contra 0 null em qualquer outro tipo.

O coletor tratava esse `null` como "o provedor nao publicou" e gravava NULL. O
efeito no banco e' visivel a olho nu em DEV:

    mes        jogos FT   com amarelo   com vermelho   vermelho=0   vermelho>0
    2026-06         171           171            171          149           22
    2026-08          95            93             12            0           12

Agosto tem exatamente os jogos em que HOUVE expulsao. Nenhum zero. Junho, ainda
coletado pela regra anterior, tem a distribuicao normal. A taxa de jogos com
expulsao e' a mesma nos dois meses (12,9% e 12,6%) -- o que sumiu foi so' o
registro do zero.


O QUE ESTE SCRIPT FAZ

Preenche 0 no vermelho apenas onde a folha esta' COMPLETA no resto (escanteio,
amarelo, falta e chute presentes) e o vermelho e' o unico buraco. Essa
combinacao so' pode ter sido produzida pelo coletor pos-2026-07-25 lendo uma
folha publicada -- ou seja, a API respondeu e disse que nao houve expulsao.

Jogo com a folha realmente incompleta (a API nao respondeu) NAO e' tocado:
continua NULL, e a coleta volta nele sozinha agora que o vermelho entrou no
predicado de "folha completa" do coletor.

Depois do UPDATE, recalcula `referee_stats.avg_red`, que estava inflado pelo
mesmo motivo: `AVG(total_red_cards)` ignora NULL, entao a media do arbitro saia
tirada SO' dos jogos em que houve expulsao (um arbitro com 1 vermelho em 10
jogos aparecia com media 1,00 em vez de 0,10).

Uso:
    python scripts/backfill_cartao_vermelho.py --env dev              # so' relatorio
    python scripts/backfill_cartao_vermelho.py --env dev --verificar  # confere na API
    python scripts/backfill_cartao_vermelho.py --env dev --apply      # aplica

`--verificar` sorteia N linhas-alvo e pergunta a folha delas pra API AGORA,
antes de escrever nada. E' o que separa "o raciocinio fecha" de "o dado
confirma" -- e num backfill de producao essa diferenca e' a unica que importa.
Custa uma requisicao por linha sorteada.
"""
import argparse
import os
import sys

import requests
from dotenv import load_dotenv, find_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection
from utils.stat_sheet import folha_publicada, ler_valor

load_dotenv(find_dotenv())
STATS_URL = "https://v3.football.api-sports.io/fixtures/statistics"


#: A assinatura do defeito: folha completa em tudo, buraco so' no vermelho.
#: Ler junto com o predicado de "estabilizado" em
#: collectors/match_statistics_sync_service.py::_load_fixtures -- e' o mesmo
#: conjunto de colunas, de proposito.
_ALVO = """
      status IN ('FT', 'AET', 'PEN')
  AND total_corners      IS NOT NULL
  AND total_yellow_cards IS NOT NULL
  AND home_fouls         IS NOT NULL
  AND home_total_shots   IS NOT NULL
  AND (home_red_cards IS NULL OR away_red_cards IS NULL OR total_red_cards IS NULL)
"""


def _relatorio(cur):
    cur.execute(f"SELECT COUNT(*) FROM match_statistics WHERE {_ALVO};")
    alvo = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM match_statistics
         WHERE status IN ('FT','AET','PEN')
           AND (home_red_cards IS NULL OR away_red_cards IS NULL
                OR total_red_cards IS NULL);
    """)
    sem_vermelho = cur.fetchone()[0]

    print(f"  jogos FT sem vermelho no banco ......... {sem_vermelho}")
    print(f"  destes, com folha completa no resto .... {alvo}   <- alvo")
    print(f"  folha de fato incompleta (fica NULL) ... {sem_vermelho - alvo}")

    cur.execute("""
        SELECT date_trunc('month', match_date)::date AS mes,
               COUNT(*) AS ft,
               COUNT(total_red_cards) AS com_vermelho,
               COUNT(*) FILTER (WHERE total_red_cards = 0) AS zero,
               COUNT(*) FILTER (WHERE total_red_cards > 0) AS positivo
          FROM match_statistics
         WHERE status IN ('FT','AET','PEN') AND match_date >= NOW() - INTERVAL '8 months'
         GROUP BY 1 ORDER BY 1;
    """)
    print(f"\n  {'mes':>12} {'FT':>6} {'c/ vermelho':>12} {'=0':>6} {'>0':>6}")
    for mes, ft, com, zero, pos in cur.fetchall():
        print(f"  {str(mes):>12} {ft:>6} {com:>12} {zero:>6} {pos:>6}")
    return alvo


def _aplicar(cur):
    cur.execute(f"""
        UPDATE match_statistics
           SET home_red_cards  = COALESCE(home_red_cards, 0),
               away_red_cards  = COALESCE(away_red_cards, 0),
               total_red_cards = COALESCE(home_red_cards, 0) + COALESCE(away_red_cards, 0)
         WHERE {_ALVO};
    """)
    return cur.rowcount


def _recalcular_arbitros(cur):
    """Refaz avg_red/avg_yellow/avg_fouls a partir da estatistica ja' corrigida.

    So' toca arbitro que tem jogo com folha -- COUNT/AVG aqui saem do MESMO
    conjunto de linhas, que e' o que a versao no coletor nao garante.
    """
    cur.execute("""
        UPDATE referee_stats rs
           SET avg_red      = m.avg_red,
               avg_yellow   = m.avg_yellow,
               avg_fouls    = m.avg_fouls,
               avg_corners  = m.avg_corners,
               avg_goals    = m.avg_goals,
               games        = m.games,
               last_updated = NOW()
          FROM (
            SELECT r.referee_id,
                   ms.season,
                   COUNT(*)                                              AS games,
                   ROUND(AVG(ms.total_red_cards)::numeric, 2)            AS avg_red,
                   ROUND(AVG(ms.total_yellow_cards)::numeric, 2)         AS avg_yellow,
                   ROUND(AVG(ms.home_fouls + ms.away_fouls)::numeric, 2) AS avg_fouls,
                   ROUND(AVG(ms.total_corners)::numeric, 2)              AS avg_corners,
                   ROUND(AVG(ms.total_goals)::numeric, 2)                AS avg_goals
              FROM match_statistics ms
              JOIN referees r ON r.name = ms.referee
             WHERE ms.status IN ('FT','AET','PEN')
             GROUP BY r.referee_id, ms.season
          ) m
         WHERE rs.referee_id = m.referee_id
           AND rs.season = m.season;
    """)
    return cur.rowcount


def _verificar_na_api(cur, quantas: int) -> bool:
    """Sorteia linhas-alvo e confere a folha na API. True se todas derem zero.

    Nao escreve nada e nao decide nada sozinho: quem le o resultado decide.
    """
    chave = os.getenv("API_FOOTBALL_KEY")
    if not chave:
        print("\n[VERIFICAR] API_FOOTBALL_KEY nao definida · pulando.")
        return False

    cur.execute(f"""
        SELECT fixture_id, match_date, home_team_id, away_team_id
          FROM match_statistics
         WHERE {_ALVO}
         ORDER BY random() LIMIT %s;
    """, (quantas,))
    linhas = cur.fetchall()
    if not linhas:
        print("\n[VERIFICAR] Nenhuma linha-alvo pra conferir.")
        return False

    print(f"\n=== CONFERINDO {len(linhas)} LINHA(S) NA API ===")
    confirmam = 0
    for fixture_id, data, home_id, away_id in linhas:
        try:
            resp = requests.get(STATS_URL, headers={"x-apisports-key": chave},
                                params={"fixture": fixture_id},
                                timeout=20).json().get("response", [])
        except Exception as e:
            print(f"  {fixture_id} {data}: erro na API ({e})")
            continue

        if len(resp) < 2:
            print(f"  {fixture_id} {data}: folha AUSENTE na API  << NAO CONFIRMA")
            continue

        por_id = {t["team"]["id"]: t["statistics"] for t in resp}
        casa, fora = por_id.get(home_id, []), por_id.get(away_id, [])
        r_casa, r_fora = ler_valor(casa, "Red Cards"), ler_valor(fora, "Red Cards")
        cru = ([s["value"] for s in casa if s["type"] == "Red Cards"]
               + [s["value"] for s in fora if s["type"] == "Red Cards"])
        ok = (r_casa == 0 and r_fora == 0)
        confirmam += 1 if ok else 0
        print(f"  {fixture_id} {data}: cru={cru} -> {r_casa}/{r_fora} | publicada "
              f"{folha_publicada(casa)}/{folha_publicada(fora)}  "
              f"{'OK' if ok else '<< NAO E ZERO'}")

    print(f"\n  {confirmam}/{len(linhas)} confirmam zero")
    return confirmam == len(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=("dev", "prod"), required=True)
    ap.add_argument("--apply", action="store_true",
                    help="sem esta flag o script so' relata, nao escreve")
    ap.add_argument("--verificar", type=int, nargs="?", const=10, default=0,
                    metavar="N",
                    help="confere N linhas-alvo na API antes de escrever (padrao 10)")
    args = ap.parse_args()

    conn = get_connection(args.env)
    cur = conn.cursor()

    print(f"\n=== ANTES ({args.env.upper()}) ===")
    alvo = _relatorio(cur)

    if args.verificar:
        _verificar_na_api(cur, args.verificar)

    if not args.apply:
        print(f"\n[DRY-RUN] {alvo} linha(s) seriam corrigidas. Rode com --apply.")
        cur.close(); conn.close()
        return

    if not alvo:
        print("\nNada a corrigir.")
        cur.close(); conn.close()
        return

    corrigidas = _aplicar(cur)
    arbitros = _recalcular_arbitros(cur)
    conn.commit()

    print(f"\n[APPLY] {corrigidas} jogo(s) com vermelho = 0 gravado.")
    print(f"[APPLY] {arbitros} linha(s) de referee_stats recalculada(s).")
    print(f"\n=== DEPOIS ({args.env.upper()}) ===")
    _relatorio(cur)

    cur.close(); conn.close()


if __name__ == "__main__":
    main()
