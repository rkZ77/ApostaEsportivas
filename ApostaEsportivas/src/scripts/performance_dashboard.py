"""Painel interno de desempenho: onde o motor ganha e onde perde.

Le `picks_ledger` (uma linha por PERNA, ver services/picks_ledger_sync_service.py)
e imprime um recorte por dimensao usando services/pick_engine/attribution.py --
a matematica toda vive la', testada sem banco; aqui e' so' consulta e formato.

COMO LER ESTE PAINEL
--------------------
Duas colunas mandam, e nao sao o ROI.

  n     Tamanho da amostra. Recorte com n pequeno nao conclui nada, por mais
        extremo que o ROI pareca.
  sig   O intervalo de confianca de 95% da media exclui o zero? Sem isso, o
        numero ao lado nao distingue vantagem real de sorte.

CLV vem antes de ROI de proposito. O resultado de uma aposta carrega a
variancia inteira do jogo, entao ROI significativo exige da ordem de mil
picks; CLV mede so' o processo (a odd pega contra a de fechamento) e converge
em algumas dezenas. Quando os dois discordam, o CLV descreve melhor o motor e
a diferenca e' variancia.

gap_ev e' a conta que ninguem costuma olhar: quanto o motor PROMETEU de EV
menos quanto ele ENTREGOU de ROI, no mesmo recorte. Positivo grande e'
otimismo sistematico -- e' o sinal de que aquele mercado precisa de
recalibracao, nao de mais volume.

Uso:
    python -m scripts.performance_dashboard [--dias N] [--dimensao market_type]
    python -m scripts.performance_dashboard --listar-dimensoes
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras

from utils.db_utils import get_connection
from services.pick_engine import attribution


# Recortes que nao vem de coluna: derivados na leitura pra nao exigir mais uma
# migracao no ledger (e pra a definicao viver junto da funcao que a calcula).
_DERIVADAS = {
    "hour_bucket": lambda r: attribution.hour_bucket(r.get("kickoff_hour")),
    "selection_role": lambda r: attribution.selection_role(r.get("odd")),
}


def carregar_pernas(dias: int, apenas_motor: bool) -> list:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    filtro_motor = "AND source_system = 'engine'" if apenas_motor else ""
    cur.execute(f"""
        SELECT * FROM picks_ledger
        WHERE match_date >= CURRENT_DATE - INTERVAL '%s days'
        {filtro_motor}
    """ % dias)
    linhas = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    for r in linhas:
        for nome, fn in _DERIVADAS.items():
            r[nome] = fn(r)
    return linhas


def _pct(v, sinal=False) -> str:
    if v is None:
        return "     ·"
    return f"{v * 100:+6.1f}%" if sinal else f"{v * 100:6.1f}%"


def _sig(flag: bool | None, n: int) -> str:
    if not n:
        return "  ·"
    return " sim" if flag else "  --"


def imprimir_geral(resumo: dict) -> None:
    print("=" * 100)
    print("GERAL")
    print("=" * 100)
    print(f"  pernas totais        {resumo['n_total']}")
    print(f"  resolvidas           {resumo['n_resolvidas']}  (binarias: {resumo['n_binarias']})")
    print(f"  taxa de acerto       {_pct(resumo['hit_rate'])}")
    print(f"  ROI                  {_pct(resumo['roi'], sinal=True)}   "
          f"IC95 {resumo['roi_ic95']}   significativo: {'sim' if resumo['roi_significativo'] else 'nao'}")
    print(f"  CLV medio            {_pct(resumo['clv_medio'], sinal=True)}   "
          f"n={resumo['clv_n']}   significativo: {'sim' if resumo['clv_significativo'] else 'nao'}")
    print(f"  Brier                {resumo['brier']}  (n={resumo['brier_n']})")
    print(f"  EV prometido medio   {_pct(resumo['ev_esperado_medio'], sinal=True)}")
    print(f"  gap EV (prometido - entregue)  {_pct(resumo['gap_ev'], sinal=True)}")
    if resumo["clv_n"] == 0:
        print("\n  AVISO: nenhuma perna tem odd de fechamento. Rode "
              "scripts/capture_closing_odds.py perto do horario dos jogos --\n"
              "  sem CLV este painel so' consegue medir resultado, que precisa de "
              "amostra muito maior pra concluir.")


def imprimir_dimensao(nome: str, grupos: dict, min_n: int) -> None:
    elegiveis = {k: v for k, v in grupos.items() if v["n_resolvidas"] >= min_n}
    if not elegiveis:
        return
    print(f"\n{'-' * 100}")
    print(f"POR {nome.upper()}")
    print(f"{'-' * 100}")
    print(f"  {'recorte':<26}{'n':>5}{'acerto':>9}{'ROI':>9}{'sig':>5}"
          f"{'CLV':>9}{'sig':>5}{'Brier':>8}{'gapEV':>9}")
    ordenados = sorted(elegiveis.items(), key=lambda kv: kv[1]["roi"] or -99, reverse=True)
    for chave, r in ordenados:
        print(f"  {chave[:25]:<26}{r['n_resolvidas']:>5}{_pct(r['hit_rate']):>9}"
              f"{_pct(r['roi'], sinal=True):>9}{_sig(r['roi_significativo'], r['n_resolvidas']):>5}"
              f"{_pct(r['clv_medio'], sinal=True):>9}{_sig(r['clv_significativo'], r['clv_n']):>5}"
              f"{str(r['brier'] if r['brier'] is not None else '·'):>8}"
              f"{_pct(r['gap_ev'], sinal=True):>9}")


def imprimir_veredito(relatorio: dict, min_n: int) -> None:
    """A leitura acionavel: onde ha vantagem demonstrada e onde ha prejuizo
    demonstrado. So' entra quem passou no teste de significancia -- o resto
    e' 'ainda nao sei', que e' uma resposta legitima e nao um alerta."""
    print(f"\n{'=' * 100}")
    print("VEREDITO")
    print("=" * 100)
    vantagem, prejuizo, indefinido = [], [], 0
    for chave, r in relatorio["por_dimensao"]["market_type"].items():
        if r["n_resolvidas"] < min_n:
            continue
        if r["clv_significativo"] and (r["clv_medio"] or 0) > 0:
            vantagem.append((chave, r))
        elif r["clv_significativo"] and (r["clv_medio"] or 0) < 0:
            prejuizo.append((chave, r))
        elif r["roi_significativo"] and (r["roi"] or 0) < 0:
            prejuizo.append((chave, r))
        else:
            indefinido += 1

    if vantagem:
        print("\n  Vantagem demonstrada (CLV positivo e significativo):")
        for chave, r in vantagem:
            print(f"    {chave:<24} CLV {_pct(r['clv_medio'], sinal=True)}  n={r['clv_n']}")
    if prejuizo:
        print("\n  Prejuizo demonstrado (candidatos a suspensao):")
        for chave, r in prejuizo:
            print(f"    {chave:<24} CLV {_pct(r['clv_medio'], sinal=True)}  "
                  f"ROI {_pct(r['roi'], sinal=True)}  n={r['n_resolvidas']}")
    if not vantagem and not prejuizo:
        print("\n  Nenhum mercado atingiu significancia ainda. Isso e' esperado com pouco")
        print("  historico e nao e' um problema -- e' o painel se recusando a concluir")
        print("  a partir de ruido.")
    if indefinido:
        print(f"\n  {indefinido} mercado(s) sem conclusao estatistica ainda.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Painel de desempenho do motor de picks")
    ap.add_argument("--dias", type=int, default=180, help="janela de analise (padrao 180)")
    ap.add_argument("--dimensao", help="mostra apenas esta dimensao")
    ap.add_argument("--min-n", type=int, default=5, help="amostra minima por recorte (padrao 5)")
    ap.add_argument("--todos-sistemas", action="store_true",
                    help="inclui picks da IA legada, nao so' do motor")
    ap.add_argument("--listar-dimensoes", action="store_true")
    args = ap.parse_args()

    # As derivadas ja' constam de DIMENSOES_PADRAO; dict.fromkeys preserva a
    # ordem e remove a repeticao.
    dimensoes = tuple(dict.fromkeys(tuple(attribution.DIMENSOES_PADRAO) + tuple(_DERIVADAS)))
    if args.listar_dimensoes:
        print("Dimensoes disponiveis:")
        for d in dimensoes:
            print(f"  {d}")
        return

    pernas = carregar_pernas(args.dias, apenas_motor=not args.todos_sistemas)
    if not pernas:
        print("[PAINEL] Nenhuma perna no periodo. Rode a sincronizacao do ledger primeiro "
              "(services/picks_ledger_sync_service.py, chamada por atualizar_resultados_sugestoes.py).")
        return

    alvo = (args.dimensao,) if args.dimensao else dimensoes
    relatorio = attribution.full_report(pernas, dimensoes=alvo)

    print(f"\n[PAINEL] {len(pernas)} pernas | ultimos {args.dias} dias | "
          f"{'motor + IA' if args.todos_sistemas else 'apenas motor deterministico'}\n")
    imprimir_geral(relatorio["geral"])
    for nome in alvo:
        imprimir_dimensao(nome, relatorio["por_dimensao"][nome], args.min_n)
    if "market_type" in relatorio["por_dimensao"]:
        imprimir_veredito(relatorio, args.min_n)
    print()


if __name__ == "__main__":
    main()
