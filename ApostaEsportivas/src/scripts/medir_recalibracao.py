"""
medir_recalibracao.py · a probabilidade recalibrada acerta melhor que a do motor?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso (da pasta onde esta' o .env.prod):
  python ApostaEsportivas/src/scripts/medir_recalibracao.py [corte AAAA-MM-DD] [desde AAAA-MM-DD]

DESCOBERTA x CONFIRMACAO POR DATA. A curva (pick_engine/recalibracao.py) e'
ajustada so' com as pernas ANTES do corte e testada nas pernas DO CORTE EM
DIANTE, que ela nunca viu. Sem corte, usa a data do meio da amostra. Ajustar e
testar no mesmo periodo mostraria melhora por construcao.

TRES PERGUNTAS, na ordem em que decidem:
  1. Brier e log-loss: a corrigida erra menos que a do motor? (menor = melhor)
  2. Por faixa: a corrigida fica perto do acerto onde a do motor nao ficava?
  3. Dinheiro: as pernas que a corrigida TIRARIA (valor some: p*odd <= 1)
     rendem pior que as que ela mantem? Se render igual, a correcao so' corta
     volume sem melhorar nada -- e o produto vende pick de valor, entao esta e'
     a que decide.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402
from services.pick_engine import recalibracao  # noqa: E402


def brier(pares):
    return sum((p - (1 if a else 0)) ** 2 for p, a in pares) / len(pares)


def logloss(pares):
    eps = 1e-6
    return -sum(math.log(max(p, eps)) if a else math.log(max(1 - p, eps)) for p, a in pares) / len(pares)


def roi(linhas):
    if not linhas:
        return None
    return sum((o - 1) if a else -1 for _, _, a, o in linhas) / len(linhas)


def ep_roi(linhas):
    """Erro padrao do ROI por perna (a unidade)."""
    if len(linhas) < 2:
        return None
    r = [(o - 1) if a else -1 for _, _, a, o in linhas]
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1) / len(r))


def main():
    corte = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    desde = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 7, 25)

    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    todos = [t for t in recalibracao.pares_do_ledger(cur, desde=desde) if t[0] is not None]
    cur.close()
    conn.close()
    if not todos:
        print("Sem pernas pre-jogo decididas no periodo.")
        return

    if corte is None:
        datas = sorted(t[3] for t in todos)
        corte = datas[len(datas) // 2]
    descoberta = [t for t in todos if t[3] < corte]
    confirmacao = [t for t in todos if t[3] >= corte]
    print(f"Pernas pre-jogo (sem Ao Vivo/Boost) desde {desde}: {len(todos)}")
    print(f"Descoberta: {len(descoberta)} antes de {corte}  |  Confirmacao: {len(confirmacao)} a partir de {corte}")

    curva = recalibracao.ajustar_curva([(p, a) for p, a, _, _ in descoberta])
    if not curva:
        print("Descoberta sem amostra pra curva (minimo de "
              f"{recalibracao.MIN_POR_FAIXA} pernas por faixa).")
        return
    print("\nCurva ajustada na descoberta (prometido -> corrigido, n):")
    for x, y, n in curva:
        print(f"  {x:.3f} -> {y:.3f}   ({n})")

    pares_motor = [(p, a) for p, a, _, _ in confirmacao]
    pares_recal = [(recalibracao.aplicar(p, curva), a) for p, a, _, _ in confirmacao]
    print("\n=== 1. Erro na confirmacao (menor = melhor) ===")
    bm, br = brier(pares_motor), brier(pares_recal)
    lm, lr = logloss(pares_motor), logloss(pares_recal)
    print(f"  Brier     motor {bm:.4f}   corrigida {br:.4f}   ({'melhor' if br < bm else 'pior'})")
    print(f"  Log-loss  motor {lm:.4f}   corrigida {lr:.4f}   ({'melhor' if lr < lm else 'pior'})")

    print("\n=== 2. Por faixa na confirmacao ===")
    print(f"  {'faixa':11} {'n':>5} {'motor':>6} {'corrig':>7} {'acerto':>7} {'±2ep':>6}")
    for lo, hi in zip(recalibracao.FAIXAS, recalibracao.FAIXAS[1:]):
        f = [(p, recalibracao.aplicar(p, curva), a) for p, a, _, _ in confirmacao if lo <= p < hi]
        if len(f) < 10:
            continue
        n = len(f)
        ac = sum(1 for *_, a in f if a) / n
        print(f"  {lo:.2f}-{min(hi, 1):.2f} {n:>5} {sum(x for x, _, _ in f) / n:>6.3f} "
              f"{sum(y for _, y, _ in f) / n:>7.3f} {ac:>7.3f} {2 * math.sqrt(ac * (1 - ac) / n):>6.3f}")

    print("\n=== 3. Dinheiro: o que a corrigida tiraria x o que manteria ===")
    com_odd = [(p, recalibracao.aplicar(p, curva), a, o) for p, a, o, _ in confirmacao if o and o > 1]
    sairiam = [t for t in com_odd if t[0] * t[3] > 1 and t[1] * t[3] <= 1]
    ficam = [t for t in com_odd if t[1] * t[3] > 1]
    for rotulo, grupo in (("ficam (valor confirmado)", ficam), ("sairiam (valor some)", sairiam)):
        r, e = roi(grupo), ep_roi(grupo)
        ac = sum(1 for _, _, a, _ in grupo if a) / len(grupo) if grupo else None
        print(f"  {rotulo:26} n={len(grupo):>4}  acerto={'-' if ac is None else f'{ac:.3f}'}  "
              f"ROI={'-' if r is None else f'{r:+.3f}'}  ±2ep={'-' if e is None else f'{2 * e:.3f}'}")

    print("\n=== Leitura ===")
    r_f, r_s = roi(ficam), roi(sairiam)
    e_s = ep_roi(sairiam)
    if br >= bm:
        print("  A corrigida NAO erra menos fora da amostra: nao ligar.")
    elif r_s is None or len(sairiam) < 30:
        print("  Erra menos, mas poucas pernas mudariam de lado pra medir dinheiro: "
              "manter em sombra e rodar de novo com mais dado.")
    elif r_f is not None and e_s is not None and r_s < r_f - 2 * e_s:
        print("  Erra menos E o que ela tiraria rende pior: vale ligar.")
    else:
        print("  Erra menos, mas o que ela tiraria rende parecido: ligar so' pra "
              "stake/valor exibido, sem usar pra cortar pick.")


if __name__ == "__main__":
    main()
