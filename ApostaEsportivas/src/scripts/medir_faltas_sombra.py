"""
medir_faltas_sombra.py · as escolhas do motor de faltas dao lucro?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso (da pasta onde esta' o .env.prod):
  python ApostaEsportivas/src/scripts/medir_faltas_sombra.py [desde AAAA-MM-DD]

POR QUE (18/10/2026). Faltas pode ir pra sombra (engine_pipelines/faltas_pipeline
.modo_faltas): 21 pernas publicadas com acerto de 43% contra 57% do preco. Em
sombra o motor continua escolhendo, mas nao publica, entao nao ha' ledger.
Aqui cada escolha (engine_decisions, FALTAS_ENGINE, status selecionado) e'
liquidada pelas faltas do jogo em match_statistics.

Conta TODAS as escolhas desde `desde`, publicadas ou nao: e' o mesmo motor, e
juntar as publicadas antes de 18/10 encurta a espera. A linha das faltas e'
sempre Over (o motor so' gera Over), sem empate possivel nas linhas .5.

Leitura: `on` so' com 50+ escolhas e ROI - 2 erros-padrao > 0.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

MIN_ESCOLHAS = 50


def _linha(texto) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", str(texto or ""))
    return float(m.group(1)) if m else None


def liquidar(escolha: dict, faltas: int | None) -> dict | None:
    """{'g': 0|1, 'lucro', 'p', 'preco'} ou None (sem resultado ou sem odd)."""
    linha, odd = _linha(escolha.get("line")), escolha.get("odd")
    if faltas is None or linha is None or not odd or float(odd) <= 1:
        return None
    odd = float(odd)
    g = 1 if faltas > linha else 0
    p = escolha.get("taxa_real")
    return {"g": g, "lucro": (odd - 1) if g else -1.0,
            "p": float(p) if p is not None else None, "preco": 1 / odd}


def resumo(linhas: list) -> dict:
    n = len(linhas)
    if not n:
        return {"n": 0}
    lucros = [x["lucro"] for x in linhas]
    roi = sum(lucros) / n
    ep = math.sqrt(sum((x - roi) ** 2 for x in lucros) / (n - 1) / n) if n > 1 else 0.0
    ps = [x["p"] for x in linhas if x["p"] is not None]
    return {"n": n, "acerto": sum(x["g"] for x in linhas) / n, "roi": roi, "ep": ep,
            "prob": sum(ps) / len(ps) if ps else None,
            "preco": sum(x["preco"] for x in linhas) / n}


def veredito(r: dict) -> str:
    if r.get("n", 0) < MIN_ESCOLHAS:
        return (f"AMOSTRA INSUFICIENTE ({r.get('n', 0)} escolhas liquidadas; precisa {MIN_ESCOLHAS}). "
                f"Manter MOTOR_FALTAS=sombra.")
    if r["roi"] - 2 * r["ep"] > 0:
        return "FALTAS DA' LUCRO FORA DO RUIDO. Pode voltar MOTOR_FALTAS=on."
    if r["roi"] + 2 * r["ep"] < 0:
        return "FALTAS PERDE DINHEIRO COM MARGEM. Manter em sombra e rever o modelo."
    return "SEM LUCRO DEMONSTRADO. Manter MOTOR_FALTAS=sombra."


def main():
    desde = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (d.fixture_id) d.fixture_id, d.match_date, d.candidates,
               m.home_fouls, m.away_fouls
          FROM engine_decisions d
          LEFT JOIN match_statistics m ON m.fixture_id = d.fixture_id
                                      AND m.status IN ('FT', 'AET', 'PEN')
         WHERE d.pipeline = 'FALTAS_ENGINE' AND d.status = 'selecionado'
           AND d.match_date >= %s
         ORDER BY d.fixture_id, d.created_at DESC
    """, (desde,))
    linhas = cur.fetchall()
    cur.close()
    conn.close()

    antes, depois, pendentes = [], [], 0
    for fid, dia, cands, hf, af in linhas:
        if isinstance(cands, str):
            cands = json.loads(cands)
        escolha = next((c for c in cands or [] if c.get("odd")), None)
        faltas = (hf + af) if hf is not None and af is not None else None
        r = liquidar(escolha or {}, faltas)
        if r is None:
            pendentes += 1
            continue
        (antes if str(dia) < "2026-10-18" else depois).append(r)

    print(f"Escolhas do motor de faltas desde {desde}: {len(linhas)} "
          f"({pendentes} sem resultado ou sem odd)\n")
    print(f"  {'':28} {'n':>4} {'prob':>6} {'preco':>6} {'acerto':>7} {'ROI':>7} {'±2ep':>6}")
    for nome, grupo in (("publicadas (ate 17/10)", antes), ("em sombra (desde 18/10)", depois),
                        ("TODAS", antes + depois)):
        r = resumo(grupo)
        if not r["n"]:
            print(f"  {nome:28} {0:>4}")
            continue
        prob = "-" if r["prob"] is None else f"{r['prob']:.3f}"
        print(f"  {nome:28} {r['n']:>4} {prob:>6} {r['preco']:>6.3f} {r['acerto']:>7.3f} "
              f"{r['roi']:>+7.3f} {2 * r['ep']:>6.3f}")

    print("\n=== Leitura ===")
    print(veredito(resumo(antes + depois)))


if __name__ == "__main__":
    main()
