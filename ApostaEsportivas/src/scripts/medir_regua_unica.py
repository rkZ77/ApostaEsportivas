"""
medir_regua_unica.py · qual regua de selecao o pre-jogo deveria usar?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso (da pasta onde esta' o .env.prod):
  python ApostaEsportivas/src/scripts/medir_regua_unica.py [desde AAAA-MM-DD]

POR QUE (09/11/2026, pedido do usuario). A pergunta era "70% de probabilidade
e odd de 1.35 pra cima e' a regua certa?". Nos picks PUBLICADOS a resposta
parecia sim (>=70% deu ROI +4,9%, <70% deu -6,9%). Mas o publicado ja' e' o
resultado de uma escolha, e medir uma regua so' nos picks que a regua ANTIGA
escolheu mede as duas misturadas. Aqui entra o conjunto inteiro de onde o
motor escolhe: em engine_decisions (VIP_ENGINE), a melhor linha de cada
mercado (`nivel='mercado'`), com a probabilidade final do motor
(`taxa_real`) e a do mercado sem margem
(`avaliacao.probabilidade.mercado_no_vig`). ~11 candidatos por jogo,
publicados ou nao.

O que a primeira passada achou (05/10-07/11, ~6.300 candidatos):
  · o acerto segue a probabilidade do MERCADO, nao a do motor (motor ~59%,
    mercado ~57%, real ~56,5%), e o Brier do motor sozinho e' pior que o do
    mercado sozinho em TODAS as semanas;
  · "piso 70%" no conjunto inteiro: -14% no periodo mais recente;
  · a unica regua positiva nas duas metades foi a ancora de mercado
    (market_anchor.blend com w=0.35) exigindo EV >= 4% na probabilidade
    ancorada -- mas com ~80 candidatos, dentro do ruido.

Cada regua e' liquidada pelo mesmo verificador do site
(AIResultCheckerService.evaluate_pick), com a odd que o candidato tinha.
Cartao so' liquida com a contagem validada; sem ela fica fora (nunca vira
zero). Leitura de cartao NAO passa `market` pro get_fixture_result, entao
nada aqui dispara a validacao (que grava) -- e a sessao e' read-only.

Leitura: uma regua so' merece ir pro motor com 80+ candidatos, ROI - 2 erros-
padrao > 0 e as duas metades do periodo positivas.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import settlement  # noqa: E402
from services.pick_engine import market_anchor  # noqa: E402

MIN_N = 80
ODD_MIN = 1.35
ODD_MAX = 3.0


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def candidato(c: dict) -> dict | None:
    """O candidato reduzido ao que as reguas leem, ou None se falta preco."""
    if c.get("nivel") != "mercado":
        return None
    p, odd = _num(c.get("taxa_real")), _num(c.get("odd"))
    q = _num(((c.get("avaliacao") or {}).get("probabilidade") or {}).get("mercado_no_vig"))
    if p is None or odd is None or q is None or odd <= 1 or not (0 < q < 1):
        return None
    return {"market": c.get("market_name"), "market_type": c.get("market_type"),
            "line": c.get("line"), "p": p, "q": q, "odd": odd,
            "edge": _num(c.get("edge")), "best": bool(c.get("is_best_pick"))}


def ancorada(c: dict, w: float) -> float:
    return market_anchor.blend(c["p"], c["q"], w)


# Cada regua: (nome, funcao candidato -> bool). Todas com a faixa de odd do
# pedido (1.35 pra cima; 3.0 so' como teto de sanidade).
def _faixa(c):
    return ODD_MIN <= c["odd"] <= ODD_MAX


REGUAS = (
    ("todos os candidatos (faixa)", lambda c: _faixa(c)),
    ("escolhido hoje (is_best_pick)", lambda c: c["best"]),
    ("piso 70%", lambda c: _faixa(c) and c["p"] >= 0.70),
    ("piso 70% + edge 8pp", lambda c: _faixa(c) and c["p"] >= 0.70 and (c["edge"] or 0) >= 0.08),
    ("ancora w=0.35 + EV>=4%", lambda c: _faixa(c) and ancorada(c, 0.35) * c["odd"] - 1 >= 0.04),
    ("ancora w=0.20 + EV>=2%", lambda c: _faixa(c) and ancorada(c, 0.20) * c["odd"] - 1 >= 0.02),
)


def resumo(linhas: list) -> dict:
    n = len(linhas)
    if not n:
        return {"n": 0}
    lucros = [x["lucro"] for x in linhas]
    roi = sum(lucros) / n
    ep = math.sqrt(sum((x - roi) ** 2 for x in lucros) / (n - 1) / n) if n > 1 else 0.0
    return {"n": n, "acerto": sum(x["g"] for x in linhas) / n, "roi": roi, "ep": ep,
            "prob": sum(x["p"] for x in linhas) / n,
            "mercado": sum(x["q"] for x in linhas) / n}


def veredito(tudo: dict, a: dict, b: dict) -> str:
    if tudo.get("n", 0) < MIN_N:
        return f"amostra curta ({tudo.get('n', 0)} < {MIN_N})"
    if tudo["roi"] - 2 * tudo["ep"] > 0 and a.get("roi", -1) > 0 and b.get("roi", -1) > 0:
        return "LUCRO FORA DO RUIDO nas duas metades"
    if tudo["roi"] + 2 * tudo["ep"] < 0:
        return "PERDE COM MARGEM"
    return "sem lucro demonstrado"


def ler_decisoes(cur, desde: str) -> list:
    """A ultima decisao do VIP por jogo (a que valia perto do apito)."""
    cur.execute("""
        SELECT DISTINCT ON (fixture_id) fixture_id, match_date, home_team, away_team, candidates
          FROM engine_decisions
         WHERE pipeline = 'VIP_ENGINE' AND match_date >= %s AND match_date < CURRENT_DATE
           AND candidates IS NOT NULL
         ORDER BY fixture_id, created_at DESC
    """, (desde,))
    return cur.fetchall()


def liquidar(checker, stats: dict, c: dict, home: str | None, away: str | None) -> dict | None:
    res, factor = checker.evaluate_pick(c["market"], c["line"], c["odd"], stats,
                                        home, away, c["market_type"])
    if res not in (settlement.GREEN, settlement.RED, settlement.HALF_WIN, settlement.HALF_LOSS):
        return None  # pendente ou PUSH: fora da conta, como no site
    lucro = settlement.profit_units(factor, c["odd"])
    if lucro is None:
        return None
    return {**c, "g": 1 if res in (settlement.GREEN, settlement.HALF_WIN) else 0, "lucro": float(lucro)}


def main():
    from services.ai_result_checker_service import AIResultCheckerService
    from utils.db_utils import get_connection

    desde = sys.argv[1] if len(sys.argv) > 1 else (date.today() - timedelta(days=45)).isoformat()
    checker = AIResultCheckerService("picks_vip")
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
        cur = conn.cursor()
        decisoes = ler_decisoes(cur, desde)
        liquidados = []
        for fixture_id, dia, home, away, cands in decisoes:
            if isinstance(cands, str):
                try:
                    cands = json.loads(cands)
                except ValueError:
                    continue
            reduzidos = [x for x in (candidato(c) for c in (cands or [])) if x]
            if not reduzidos:
                continue
            stats = checker.get_fixture_result(fixture_id, cur)
            if not stats or stats.get("status") not in ("FT", "AET", "PEN"):
                continue
            for c in reduzidos:
                r = liquidar(checker, stats, c, home, away)
                if r:
                    r["dia"] = dia
                    liquidados.append(r)
    finally:
        conn.close()

    if not liquidados:
        print(f"Nenhum candidato liquidado desde {desde}.")
        return
    dias = sorted({x["dia"] for x in liquidados})
    meio = dias[len(dias) // 2]
    print(f"Candidatos do pre-jogo desde {desde}: {len(liquidados)} liquidados, "
          f"{len(dias)} dias (metade 1 < {meio} <= metade 2)\n")
    print(f"  {'regua':32} {'n':>5} {'/dia':>5} {'prom':>6} {'merc':>6} {'real':>6} "
          f"{'ROI':>7} {'±2ep':>6} {'met1':>7} {'met2':>7}  leitura")
    for nome, regra in REGUAS:
        sel = [x for x in liquidados if regra(x)]
        t = resumo(sel)
        a = resumo([x for x in sel if x["dia"] < meio])
        b = resumo([x for x in sel if x["dia"] >= meio])
        if not t["n"]:
            print(f"  {nome:32} {0:>5}")
            continue

        def roi(r):
            return f"{r['roi'] * 100:+6.1f}%" if r.get("n") else "     -"
        print(f"  {nome:32} {t['n']:>5} {t['n'] / len(dias):>5.1f} {t['prob'] * 100:>5.1f}% "
              f"{t['mercado'] * 100:>5.1f}% {t['acerto'] * 100:>5.1f}% {roi(t)} "
              f"{2 * t['ep'] * 100:>5.1f}% {roi(a)} {roi(b)}  {veredito(t, a, b)}")

    tudo = [x for x in liquidados if _faixa(x)]
    if tudo:
        bm = sum((x["p"] - x["g"]) ** 2 for x in tudo) / len(tudo)
        bq = sum((x["q"] - x["g"]) ** 2 for x in tudo) / len(tudo)
        print(f"\nBrier na faixa: motor {bm:.4f} · mercado sem margem {bq:.4f} "
              f"({'motor melhor' if bm < bq else 'MERCADO melhor'})")


if __name__ == "__main__":
    main()
