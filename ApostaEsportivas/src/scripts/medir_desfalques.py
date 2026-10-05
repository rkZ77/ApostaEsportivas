"""
medir_desfalques.py · o sinal de desfalques/tecnico merece entrar na nota?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_desfalques.py

O QUE O SINAL AFIRMA (news_model.news_score): time desfalcado joga diferente
do time que gerou o historico, entao a probabilidade do motor descreve PIOR a
partida -- e a nota deveria cair. Isso e' uma afirmacao testavel: nas pernas
com desfalque, o motor deveria errar mais (acerto real abaixo da probabilidade
prometida, Brier maior) do que nas pernas sem.

COMO MEDE
---------
`engine_decisions.candidates` guarda o `news_score_sombra` de cada candidato
(calculado desde 27/09; em modo shadow desde 02/10). Cruza com `picks_ledger`
por (fixture_id, market_type, line) e compara, por faixa do sinal:

  residuo = acerto - probabilidade prometida   (negativo = motor otimista)

So' vale ligar MOTOR_DESFALQUES=on se a faixa com desfalque tiver residuo
mais negativo que a faixa neutra por mais de 2 erros-padrao da diferenca, e
com pelo menos MIN_POR_FAIXA pernas em cada. Abaixo disso, a resposta honesta
e' "ainda nao sabemos" -- e o sinal fica em shadow.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

MIN_POR_FAIXA = 60


def faixa(news: float | None) -> str | None:
    if news is None:
        return None
    if news >= 0.5:
        return "neutro (sem desfalque)"
    if news >= 0.42:
        return "leve (1 titular ou duvidas)"
    return "pesado (2+ titulares)"


def resumo(pares: list) -> dict:
    """pares = [(probabilidade, acertou 0/1)]."""
    n = len(pares)
    if not n:
        return {"n": 0}
    residuos = [o - p for p, o in pares]
    media = sum(residuos) / n
    dp = math.sqrt(sum((r - media) ** 2 for r in residuos) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "acerto": sum(o for _, o in pares) / n,
            "prob_media": sum(p for p, _ in pares) / n,
            "residuo": media, "ep": dp / math.sqrt(n) if n else None,
            "brier": sum((p - o) ** 2 for p, o in pares) / n}


def veredito(grupos: dict) -> str:
    neutro = grupos.get("neutro (sem desfalque)", {})
    com = [p for k, v in grupos.items() if k != "neutro (sem desfalque)" for p in v]
    a, b = resumo(com), neutro and resumo(neutro)
    if not b or a["n"] < MIN_POR_FAIXA or b["n"] < MIN_POR_FAIXA:
        return (f"AMOSTRA INSUFICIENTE (precisa {MIN_POR_FAIXA} por lado; com desfalque="
                f"{a['n']}, neutro={b['n'] if b else 0}). Manter MOTOR_DESFALQUES=shadow.")
    diff = a["residuo"] - b["residuo"]
    ep = math.sqrt(a["ep"] ** 2 + b["ep"] ** 2)
    if diff < -2 * ep:
        return (f"SINAL CONFIRMADO: com desfalque o motor erra mais ({diff:+.3f}, "
                f"{abs(diff) / ep:.1f} EP). Pode ligar MOTOR_DESFALQUES=on.")
    return (f"SEM EFEITO MEDIVEL ({diff:+.3f}, {abs(diff) / ep if ep else 0:.1f} EP). "
            f"Manter shadow.")


def main():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""
        SELECT fixture_id, candidates FROM engine_decisions
         WHERE fixture_id IS NOT NULL AND created_at >= '2026-09-27'
    """)
    sinal: dict = {}
    for fixture_id, candidatos in cur.fetchall():
        if isinstance(candidatos, str):
            candidatos = json.loads(candidatos)
        for c in candidatos or []:
            news = c.get("news_score_sombra", c.get("news_score"))
            if news is None or c.get("origem") == "rastro":
                continue
            sinal[(fixture_id, c.get("market_type"), c.get("line"))] = float(news)

    cur.execute("""
        SELECT fixture_id, market_type, line, probability, result, pick_type
          FROM picks_ledger
         WHERE result IN ('GREEN', 'RED') AND probability IS NOT NULL
           AND match_date >= '2026-09-27'
    """)
    grupos = defaultdict(list)
    por_produto = defaultdict(lambda: defaultdict(list))
    sem_sinal = 0
    for fixture_id, market_type, line, prob, result, produto in cur.fetchall():
        f = faixa(sinal.get((fixture_id, market_type, line)))
        if f is None:
            sem_sinal += 1
            continue
        par = (float(prob), 1 if result == "GREEN" else 0)
        grupos[f].append(par)
        por_produto[produto][f].append(par)
    cur.close()
    conn.close()

    print(f"{len(sinal)} candidatos com sinal · {sem_sinal} pernas liquidadas sem sinal\n")
    print(f"{'faixa':30} {'n':>5} {'acerto':>7} {'prob':>6} {'residuo':>8} {'ep':>6} {'brier':>6}")
    for nome in ("neutro (sem desfalque)", "leve (1 titular ou duvidas)", "pesado (2+ titulares)"):
        r = resumo(grupos.get(nome, []))
        if r["n"]:
            print(f"{nome:30} {r['n']:5d} {r['acerto']:7.3f} {r['prob_media']:6.3f} "
                  f"{r['residuo']:+8.3f} {r['ep']:6.3f} {r['brier']:6.3f}")
    print("\nPor produto (n por faixa):")
    for produto, fx in sorted(por_produto.items()):
        print(f"  {produto:14} " + "  ".join(f"{k.split(' ')[0]}={len(v)}" for k, v in fx.items()))
    print("\n" + veredito(grupos))


if __name__ == "__main__":
    main()
