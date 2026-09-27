"""
medir_mudancas_por_fase.py · a mudanca de motor melhorou ou piorou?

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_mudancas_por_fase.py
  DB_ENV=prod python src/scripts/medir_mudancas_por_fase.py 2026-09-01 2026-09-10 2026-09-15 2026-09-25

As datas sao os CORTES entre fases (cada uma comeca numa data de mudanca do
motor). Sem argumento, usa os cortes medidos em 27/09/2026.

POR QUE EXISTE
--------------
Regra do usuario (27/09/2026): nao mexer no que esta' dando certo, e so'
mudar quando a medicao mostrar melhora. Isso pede a pergunta inversa sempre a
mao: depois da ultima mudanca, o produto ficou melhor ou pior? Varias mudancas
de setembro subiram no mesmo dia, entao a medicao e' por FASE, nao por commit.

O QUE IMPRIME
-------------
1. Por produto e fase: apostas, acerto, acerto implicito do mercado (1/odd),
   lucro total e por aposta. Nivel de APOSTA (tabela de origem): e' o que o
   assinante ganhou.
2. Premium e Dica por fase separados por AMOSTRA (menor `jogos_lidos` dos dois
   times, gravado no engine_debug): foi assim que se viu, em 27/09, que 2/3 do
   prejuizo de 15-24/09 vinham do bloco de amostra curta ja' corrigido pelo
   piso de 8.
3. Pernas por familia e direcao: probabilidade anunciada, mercado e acerto --
   se o motor anuncia acima do mercado e acerta abaixo dele, a "vantagem" e'
   excesso de confianca.
4. IA: acerto das pernas que ela aprovou contra as que vetaria. Antes de ligar
   o modo `enforce`, o vetado tem que acertar MENOS que o aprovado.

COMO LER
--------
Amostra curta nao decide nada nas duas direcoes (mesma regra do piso e do veto
de cartao). Uma fase com menos de ~25 apostas e' sinal pra acompanhar, nao
motivo pra reverter.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

CORTES_PADRAO = ("2026-09-01", "2026-09-10", "2026-09-15", "2026-09-25")

PRODUTOS = (
    ("Premium", "picks_vip", "odd"), ("Dica", "picks_free", "odd"),
    ("Multipla", "picks_multiplas", "total_odd"), ("Bingo", "picks_bingo", "total_odd"),
    ("Alavancagem", "picks_alavancagem", "odd_combined"), ("Boost", "picks_boost", "odd"),
    ("Faltas", "picks_faltas", "odd"), ("Jogador", "picks_player_stats", "odd"),
    ("Ao vivo", "picks_live", "odd"),
)
DECIDIDOS = ("GREEN", "RED", "HALF-WIN", "HALF-LOSS")


def _fase(dia, cortes) -> str | None:
    dia = str(dia)[:10]
    fase = None
    for i, corte in enumerate(cortes):
        if dia >= corte:
            fase = f"{chr(65 + i)} desde {corte[8:10]}/{corte[5:7]}"
    return fase


def _acerto(res) -> float:
    return 1.0 if res == "GREEN" else 0.5 if res == "HALF-WIN" else 0.0


def por_produto(cur, cortes):
    print("\n1. POR PRODUTO E FASE")
    print(f"{'produto':12} {'fase':15} {'n':>4} {'acerto':>7} {'mercado':>8} {'lucro':>8} {'u/aposta':>9}")
    for nome, tabela, col_odd in PRODUTOS:
        try:
            cur.execute(f"""SELECT match_date, result, {col_odd}, profit FROM {tabela}
                             WHERE match_date >= %s AND result IN %s""", (cortes[0], DECIDIDOS))
            linhas = cur.fetchall()
        except Exception as e:
            cur.connection.rollback()
            print(f"{nome:12} indisponivel ({str(e)[:50]})")
            continue
        g = defaultdict(lambda: [0, 0.0, 0.0, 0, 0.0])
        for dia, res, odd, lucro in linhas:
            f = _fase(dia, cortes)
            if not f:
                continue
            x = g[f]
            x[0] += 1; x[1] += _acerto(res); x[4] += float(lucro or 0)
            if odd and float(odd) > 1:
                x[2] += 1 / float(odd); x[3] += 1
        for f in sorted(g):
            n, h, imp, n_imp, u = g[f]
            mercado = f"{imp / n_imp:8.1%}" if n_imp else "       -"
            print(f"{nome:12} {f:15} {n:4d} {h / n:7.1%} {mercado} {u:+8.2f} {u / n:+9.3f}")


def por_amostra(cur, cortes):
    print("\n2. PREMIUM E DICA POR AMOSTRA (menor jogos_lidos dos dois times)")
    g = defaultdict(lambda: [0, 0.0, 0.0])
    for nome, tabela in (("Premium", "picks_vip"), ("Dica", "picks_free")):
        cur.execute(f"""SELECT match_date, result, profit, engine_debug FROM {tabela}
                         WHERE match_date >= %s AND result IN %s""", (cortes[0], DECIDIDOS))
        for dia, res, lucro, dbg in cur.fetchall():
            f = _fase(dia, cortes)
            if not f:
                continue
            d = dbg if isinstance(dbg, dict) else (json.loads(dbg) if dbg else {})
            am = d.get("amostra") or {}
            lidos = [(am.get(l) or {}).get("jogos_lidos") for l in ("mandante", "visitante")]
            lidos = [x for x in lidos if isinstance(x, (int, float))]
            faixa = "sem registro" if not lidos else ("< 8 jogos" if min(lidos) < 8 else ">= 8 jogos")
            x = g[(nome, f, faixa)]
            x[0] += 1; x[1] += _acerto(res); x[2] += float(lucro or 0)
    for k in sorted(g):
        n, h, u = g[k]
        print(f"{k[0]:8} {k[1]:15} {k[2]:13} n={n:3d} acerto={h / n:6.1%} "
              f"lucro={u:+7.2f} ({u / n:+.3f}/aposta)")


def _direcao(line, side) -> str:
    t = (line or "").lower()
    if "over" in t or "mais" in t:
        return "over"
    if "under" in t or "menos" in t:
        return "under"
    return (side or "-").lower()


def por_familia_e_ia(cur, cortes):
    cur.execute("""SELECT match_date, market_type, pick_side, line, odd, probability,
                          result, profit, ai_decision, ai_status
                     FROM picks_ledger
                    WHERE match_date >= %s AND result IN %s""", (cortes[0], DECIDIDOS))
    linhas = cur.fetchall()
    print("\n3. PERNAS POR FAMILIA E DIRECAO (todos os produtos)")
    print(f"{'fase':15} {'familia':16} {'dir':7} {'n':>4} {'anunc':>6} {'mercado':>8} {'acerto':>7} {'lucro':>7}")
    g = defaultdict(lambda: [0, 0.0, 0, 0.0, 0, 0.0, 0.0])
    ia = defaultdict(lambda: [0, 0.0, 0.0])
    for dia, mt, side, line, odd, prob, res, lucro, aid, ast in linhas:
        f = _fase(dia, cortes)
        if not f:
            continue
        x = g[(f, mt, _direcao(line, side))]
        x[0] += 1; x[5] += _acerto(res); x[6] += float(lucro or 0)
        if prob is not None:
            p = float(prob)
            x[1] += p / 100 if p > 1 else p; x[2] += 1
        if odd and float(odd) > 1:
            x[3] += 1 / float(odd); x[4] += 1
        if ast == "ok" and aid in ("approve", "reject"):
            y = ia[(f, aid)]
            y[0] += 1; y[1] += _acerto(res); y[2] += float(lucro or 0)
    for k in sorted(g):
        n, sp, np_, sm, nm, h, u = g[k]
        if n < 8:
            continue
        anunc = f"{sp / np_:6.1%}" if np_ else "     -"
        merc = f"{sm / nm:8.1%}" if nm else "       -"
        print(f"{k[0]:15} {str(k[1]):16} {k[2]:7} {n:4d} {anunc} {merc} {h / n:7.1%} {u:+7.2f}")

    print("\n4. IA: APROVADO x VETARIA (so' pernas com parecer ok)")
    for k in sorted(ia):
        n, h, u = ia[k]
        print(f"{k[0]:15} {k[1]:8} n={n:4d} acerto={h / n:6.1%} lucro={u:+7.2f}")


def main():
    cortes = tuple(sys.argv[1:]) or CORTES_PADRAO
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    try:
        por_produto(cur, cortes)
        por_amostra(cur, cortes)
        por_familia_e_ia(cur, cortes)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
