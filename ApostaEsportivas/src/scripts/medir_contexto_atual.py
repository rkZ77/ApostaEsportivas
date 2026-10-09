"""
medir_contexto_atual.py · o contexto atual merece entrar na conta do motor?

SOMENTE LEITURA. Pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_contexto_atual.py

O QUE O CONTEXTO AFIRMA (services/pick_engine/contexto_atual.py): quando o
tecnico mudou, a forma destoou ou quem esta' fora produzia parte do
historico, a probabilidade com a amostra efetiva descreve MELHOR a partida
do que a do historico inteiro. Afirmacao testavel nas pernas liquidadas.

O QUE MEDE
----------
`engine_decisions.candidates` grava, por candidato, `contexto_sombra` =
{taxa (com contexto), taxa_sem_contexto, amostra_efetiva, fatores, ev}.
Cruza com `picks_ledger` por (fixture_id, market_type, line) e responde:

  1. CALIBRACAO PAREADA  Brier e log-loss das duas probabilidades nas MESMAS
                         pernas. Diferenca por perna, media e erro-padrao.
                         Metade antiga = descoberta, metade nova =
                         confirmacao: so' conta se melhorar NAS DUAS.
  2. CORTE               pernas que o contexto teria barrado (EV <= 0 com a
                         probabilidade nova, ou amostra efetiva < 8) contra as
                         que ele manteria: acerto, ROI e CLV de cada grupo. Se
                         as barradas renderam MENOS, o corte tira prejuizo.
  3. POR FATOR           residuo (acerto - probabilidade publicada) das pernas
                         com cada fator (tecnico, forma, desfalques) e de cada
                         fator de incerteza da partida (pausa longa, sequencia
                         apertada, viagem...) -- e' daqui que um fator que hoje
                         so' e' rotulo pode virar conta, ou um fator ligado
                         pode ser desligado (MOTOR_CONTEXTO_FATORES).

Sem vazamento: a probabilidade comparada e' a que o motor gravou ANTES do
jogo (created_at do log < apito); o resultado vem depois, do ledger.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db_utils import get_connection  # noqa: E402

MIN_PERNAS = 40           # por metade
MIN_POR_GRUPO = 30
DESDE = "2026-10-08"
AMOSTRA_MINIMA = 8        # config.AMOSTRA_RICA


def _ll(p: float, o: int) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(o * math.log(p) + (1 - o) * math.log(1 - p))


def pareado(pernas: list) -> dict:
    """pernas = [{"p_sem", "p_com", "o"}]. Diferenca com - sem (negativo =
    contexto melhor), media e erro-padrao."""
    n = len(pernas)
    if n < 2:
        return {"n": n}
    db = [(x["p_com"] - x["o"]) ** 2 - (x["p_sem"] - x["o"]) ** 2 for x in pernas]
    dl = [_ll(x["p_com"], x["o"]) - _ll(x["p_sem"], x["o"]) for x in pernas]

    def m_ep(v):
        m = sum(v) / len(v)
        dp = math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))
        return m, dp / math.sqrt(len(v))
    mb, eb = m_ep(db)
    ml, el = m_ep(dl)
    return {"n": n, "brier_sem": sum((x["p_sem"] - x["o"]) ** 2 for x in pernas) / n,
            "brier_com": sum((x["p_com"] - x["o"]) ** 2 for x in pernas) / n,
            "d_brier": mb, "ep_brier": eb, "d_logloss": ml, "ep_logloss": el}


def grupo(pernas: list) -> dict:
    n = len(pernas)
    if not n:
        return {"n": 0}
    lucro = [x["lucro"] for x in pernas if x.get("lucro") is not None]
    clv = [x["clv"] for x in pernas if x.get("clv") is not None]
    res = [x["o"] - x["p_pub"] for x in pernas]
    return {"n": n, "acerto": sum(x["o"] for x in pernas) / n,
            "prob": sum(x["p_pub"] for x in pernas) / n,
            "residuo": sum(res) / n,
            "roi": (sum(lucro) / len(lucro)) if lucro else None,
            "clv": (sum(clv) / len(clv)) if clv else None, "n_clv": len(clv)}


def barrada(c: dict) -> bool:
    s = c["sombra"]
    efetiva = s.get("amostra_efetiva")
    return (s.get("ev") is not None and s["ev"] <= 0) or (
        efetiva is not None and efetiva < AMOSTRA_MINIMA)


def veredito(desc: dict, conf: dict) -> str:
    total = desc.get("n", 0) + conf.get("n", 0)
    if desc.get("n", 0) < MIN_PERNAS or conf.get("n", 0) < MIN_PERNAS:
        return (f"AMOSTRA INSUFICIENTE ({total} pernas com contexto; precisa {MIN_PERNAS} "
                f"em cada metade). Manter MOTOR_CONTEXTO=shadow.")

    def melhora(r):
        return r["d_brier"] < -2 * r["ep_brier"] or r["d_logloss"] < -2 * r["ep_logloss"]

    def piora(r):
        return r["d_brier"] > 2 * r["ep_brier"] or r["d_logloss"] > 2 * r["ep_logloss"]

    if melhora(desc) and melhora(conf):
        return "CONTEXTO MELHORA A CALIBRACAO NAS DUAS METADES. Pode ligar MOTOR_CONTEXTO=on."
    if piora(desc) or piora(conf):
        return ("CONTEXTO PIORA A CALIBRACAO. Manter shadow e olhar o bloco POR FATOR pra "
                "desligar o fator culpado (MOTOR_CONTEXTO_FATORES).")
    return "SEM EFEITO MEDIVEL NA CALIBRACAO. Manter shadow; olhar o bloco CORTE (ROI/CLV)."


def _linha(nome: str, g: dict) -> str:
    if not g.get("n"):
        return f"  {nome:34} sem pernas"
    roi = f"{g['roi']:+.3f}" if g.get("roi") is not None else "  -  "
    clv = f"{g['clv']:+.3f} (n={g['n_clv']})" if g.get("clv") is not None else "-"
    return (f"  {nome:34} n={g['n']:4d}  acerto={g['acerto']:.3f}  prob={g['prob']:.3f}  "
            f"residuo={g['residuo']:+.3f}  roi/u={roi}  clv={clv}")


def main():
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("""
        SELECT fixture_id, candidates FROM engine_decisions
         WHERE fixture_id IS NOT NULL AND created_at >= %s
    """, (DESDE,))
    sombra: dict = {}
    for fixture_id, candidatos in cur.fetchall():
        if isinstance(candidatos, str):
            candidatos = json.loads(candidatos)
        for c in candidatos or []:
            if c.get("origem") == "rastro":
                continue
            s = c.get("contexto_sombra")
            partida = c.get("contexto_partida") or {}
            if not s and not partida.get("fatores_de_incerteza"):
                continue
            sombra[(fixture_id, c.get("market_type"), c.get("line"))] = {
                "sombra": s or {}, "partida": partida}

    try:
        cur.execute("""
            SELECT fixture_id, market_type, line, probability, result, profit, clv, match_date
              FROM picks_ledger
             WHERE result IN ('GREEN','RED') AND probability IS NOT NULL AND match_date >= %s
             ORDER BY match_date
        """, (DESDE,))
        ledger = cur.fetchall()
    except Exception:
        conn.rollback()
        cur.execute("""
            SELECT fixture_id, market_type, line, probability, result, profit, NULL, match_date
              FROM picks_ledger
             WHERE result IN ('GREEN','RED') AND probability IS NOT NULL AND match_date >= %s
             ORDER BY match_date
        """, (DESDE,))
        ledger = cur.fetchall()
    cur.close()
    conn.close()

    com_linha, todas = [], []
    for fid, mt, line, prob, result, lucro, clv, _d in ledger:
        c = sombra.get((fid, mt, line))
        if not c:
            continue
        perna = {"o": 1 if result == "GREEN" else 0, "p_pub": float(prob),
                 "lucro": float(lucro) if lucro is not None else None,
                 "clv": float(clv) if clv is not None else None, **c}
        todas.append(perna)
        s = c["sombra"]
        if s.get("taxa") is not None and s.get("taxa_sem_contexto") is not None:
            com_linha.append({**perna, "p_com": float(s["taxa"]),
                              "p_sem": float(s["taxa_sem_contexto"])})

    print(f"{len(sombra)} candidatos com contexto · {len(todas)} pernas liquidadas cruzadas "
          f"· {len(com_linha)} com as duas probabilidades\n")

    meio = len(com_linha) // 2
    desc, conf = pareado(com_linha[:meio]), pareado(com_linha[meio:])
    print("1. CALIBRACAO PAREADA (d < 0 = contexto melhor)")
    for nome, r in (("descoberta", desc), ("confirmacao", conf)):
        if r.get("n", 0) < 2:
            print(f"  {nome:12} sem pernas suficientes")
            continue
        print(f"  {nome:12} n={r['n']:4d}  Brier sem={r['brier_sem']:.4f} com={r['brier_com']:.4f}  "
              f"dBrier={r['d_brier']:+.4f}±{r['ep_brier']:.4f}  "
              f"dLogLoss={r['d_logloss']:+.4f}±{r['ep_logloss']:.4f}")

    print("\n2. CORTE (o que o contexto teria barrado x o que manteria)")
    print(_linha("barradas pelo contexto", grupo([x for x in com_linha if barrada(x)])))
    print(_linha("mantidas", grupo([x for x in com_linha if not barrada(x)])))

    print("\n3. POR FATOR (residuo < 0 = motor otimista nessas pernas)")
    por_fator = defaultdict(list)
    for x in todas:
        for f in x["sombra"].get("fatores") or []:
            por_fator[f"linha:{f.get('fator')}"].append(x)
        for f in x["partida"].get("fatores_de_incerteza") or []:
            por_fator[f"partida:{f.split(':', 1)[-1]}"].append(x)
    sem_fator = [x for x in todas if not x["sombra"].get("fatores")
                 and not x["partida"].get("fatores_de_incerteza")]
    print(_linha("(sem fator nenhum)", grupo(sem_fator)))
    for nome in sorted(por_fator):
        g = grupo(por_fator[nome])
        marca = "" if g["n"] >= MIN_POR_GRUPO else "   (amostra curta)"
        print(_linha(nome, g) + marca)

    print("\n4. REAVALIACAO PERTO DO APITO (alertados x nao alertados)")
    reav = reavaliados()
    if reav is None:
        print("  tabela reavaliacao_picks ainda nao existe")
    else:
        print(_linha("com alerta", grupo([x for x in reav if x["alerta"]])))
        print(_linha("sem alerta", grupo([x for x in reav if not x["alerta"]])))

    # "=== Leitura ===" e' o marcador que o /admin (AdminAgendador.
    # leituraDaMedicao) usa pra mostrar o veredito no cartao da medicao.
    print("\n=== Leitura ===")
    print(veredito(desc, conf))


def reavaliados() -> list | None:
    """Pernas liquidadas que passaram pela reavaliacao, com o alerta dela."""
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
    except Exception:
        pass
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT ON (r.pick_table, r.pick_id)
                   r.alerta, l.result, l.probability, l.profit, l.clv
              FROM reavaliacao_picks r
              JOIN picks_ledger l ON l.source_table = r.pick_table AND l.source_id = r.pick_id
             WHERE l.result IN ('GREEN','RED') AND l.probability IS NOT NULL
             ORDER BY r.pick_table, r.pick_id, r.reavaliado_em DESC
        """)
        linhas = cur.fetchall()
    except Exception:
        return None
    finally:
        cur.close()
        conn.close()
    return [{"alerta": a, "o": 1 if res == "GREEN" else 0, "p_pub": float(p),
             "lucro": float(lu) if lu is not None else None,
             "clv": float(c) if c is not None else None}
            for a, res, p, lu, c in linhas]


if __name__ == "__main__":
    main()
