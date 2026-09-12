"""boost_backtest_v2.py · o Pick Boost V1 contra a V2, nos mesmos picks.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/boost_backtest_v2.py
  DB_ENV=prod python src/scripts/boost_backtest_v2.py --dias 60
  DB_ENV=prod python src/scripts/boost_backtest_v2.py --secao calibracao

O QUE ELE CONSEGUE MEDIR
------------------------
Tudo que a V2 REPROVA. Cada pick ja' liquidado de `picks_boost` e' reprocessado
com as portas novas, e a saida diz quantos GREEN e quantos RED cada porta teria
cortado. E' a unica pergunta que importa antes de ligar a V2: ela corta os RED
ou corta os GREEN?

A reconstrucao e' possivel porque o `engine_debug` da V1 ja' grava a amostra
jogo a jogo (gols de FT e de HT por partida, ver services/engine_audit/
amostra.py). Dela saem a frequencia do par, a distribuicao do primeiro tempo e
a dispersao -- ou seja, o HT_RISK e o TAIL_RISK sao recalculados sobre os
MESMOS jogos que o motor leu naquele dia, e nao sobre uma consulta refeita hoje
(que ja' divergiu duas vezes neste projeto).

O QUE ELE NAO CONSEGUE MEDIR, e a honestidade sobre isso e' parte do resultado
------------------------------------------------------------------------------
  1. Os picks que a V2 CRIARIA e a V1 nao criou: nao existem. Toda porta nova
     so' reprova, entao esse conjunto e' vazio por construcao. O que NAO e'
     vazio, e tambem nao e' medivel aqui, sao os jogos que a V1 descartou por
     Score e que a V2 poderia aprovar com o Score Final -- eles nao viraram
     linha de `picks_boost`, so' de `engine_decisions`, e sem odd casada e sem
     resultado liquidado nao ha' desfecho pra medir.

  2. O efeito do encolhimento sobre a DECISAO. Ele muda a probabilidade, que
     muda EV e edge, que mudam a porta 1 -- isso esta' medido. Mas ele tambem
     mudaria o Score, e Score diferente muda a ORDEM, e ordem diferente muda
     quem entrou no teto de 8 da rodada. Esse efeito de segunda ordem exigiria
     reprocessar o dia inteiro, inclusive os jogos que nunca viraram pick.

POR QUE NAO OTIMIZAR CONTRA ESTA SAIDA
--------------------------------------
Todo pick aqui e' passado, e os limiares da V2 foram escolhidos ANTES de olhar
pra ele (estao em config.py, cada um com a justificativa). Mexer nos limiares
ate' a saida ficar bonita e' ajustar o modelo ao proprio teste, e o resultado
de sempre e' um motor que explica o passado e erra o futuro. A secao `estabilidade`
parte a amostra na metade justamente pra essa checagem: regra que so' funciona
numa das metades nao e' regra.

E UM GREEN NAO PROVA QUE A DECISAO ESTAVA CERTA. A pergunta e' se a evidencia
disponivel NO DIA sustentava a aposta; o desfecho de um jogo e' uma amostra de
tamanho um.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from statistics import pstdev

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from services.pick_engine_boost import (  # noqa: E402
    calibration, config as cfg, contradiction, decision, ht_risk, joint,
    quality, shrinkage,
)
from utils.db_utils import get_connection  # noqa: E402

#: Resultado -> quanto move a banca, em unidades de stake. Mesma convencao de
#: services/settlement.py. GREEN depende da odd, entao fica None e e' resolvido
#: com o `profit` gravado ou com a odd do proprio pick.
FATOR = {"RED": -1.0, "PUSH": 0.0, "VOID": 0.0, "HALF_LOSS": -0.5}


def _json(bruto):
    if isinstance(bruto, str):
        try:
            return json.loads(bruto)
        except ValueError:
            return {}
    return bruto or {}


def _lucro(pick: dict) -> float:
    if pick.get("profit") is not None:
        return float(pick["profit"])
    resultado = (pick.get("result") or "").upper()
    if resultado in FATOR:
        return FATOR[resultado]
    if resultado == "GREEN":
        return float(pick.get("odd") or 1) - 1
    if resultado == "HALF_WIN":
        return (float(pick.get("odd") or 1) - 1) / 2
    return 0.0


# ---------------------------------------------------------------------------
# Reconstrucao da V2 a partir do rastro da V1
# ---------------------------------------------------------------------------
def _jogos_do_time(amostra: dict, lado: str) -> list:
    return ((amostra or {}).get(lado) or {}).get("jogos") or []


def _perfil_reconstruido(jogos: list) -> dict:
    """So' os campos que a V2 precisa, recalculados dos jogos gravados."""
    ft = [int(j["gols_pro"]) + int(j["gols_contra"]) for j in jogos
          if j.get("gols_pro") is not None and j.get("gols_contra") is not None]
    ht = [int(j["gols_ht"]) for j in jogos if j.get("gols_ht") is not None]
    pares = 0
    for j in jogos:
        if j.get("gols_ht") is None or j.get("gols_pro") is None or j.get("gols_contra") is None:
            continue
        if int(j["gols_pro"]) + int(j["gols_contra"]) >= 2 and int(j["gols_ht"]) <= 2:
            pares += 1
    com_os_dois = sum(1 for j in jogos if j.get("gols_ht") is not None
                      and j.get("gols_pro") is not None)
    media_ht = sum(ht) / len(ht) if ht else None
    return {
        "jogos": len(ft), "jogos_com_ht": len(ht), "jogos_no_mando": None,
        "over15_acertos": sum(1 for t in ft if t >= 2), "over15_total": len(ft),
        "under25_ht_acertos": sum(1 for t in ht if t <= 2), "under25_ht_total": len(ht),
        "media_gols_ht": round(media_ht, 3) if media_ht is not None else None,
        "desvio_gols_ht": round(pstdev([float(t) for t in ht]), 3) if len(ht) > 1 else None,
        "ht_2mais": sum(1 for t in ht if t >= 2),
        "ht_3mais": sum(1 for t in ht if t >= 3),
        "ht_exatos_2": sum(1 for t in ht if t == 2),
        "ht_max": max(ht) if ht else None,
        "par_acertos": pares, "par_total": com_os_dois,
        "media_gols_total": round(sum(ft) / len(ft), 3) if ft else None,
        "freq_over15": round(sum(1 for t in ft if t >= 2) / len(ft), 4) if ft else None,
        "freq_under25_ht": round(sum(1 for t in ht if t <= 2) / len(ht), 4) if ht else None,
        "freq_over15_mando": None,
    }


def reprocessar(pick: dict) -> dict | None:
    """O que a V2 teria decidido sobre ESTE pick. None quando falta rastro."""
    debug = _json(pick.get("engine_debug"))
    confronto = dict(debug.get("confronto") or {})
    if not confronto:
        return None
    amostra = debug.get("amostra") or {}
    ph = _perfil_reconstruido(_jogos_do_time(amostra, "mandante"))
    pa = _perfil_reconstruido(_jogos_do_time(amostra, "visitante"))
    if not ph["jogos"] or not pa["jogos"]:
        return None

    # Encolhimento com o baseline GLOBAL: o baseline por liga precisaria da
    # composicao da liga na data do jogo, e reconsultar hoje seria olhar jogos
    # que aconteceram DEPOIS da decisao. Vies de futuro num backtest e' pior
    # que um baseline generico.
    from services.pick_engine_boost import baseline as bl
    base = bl.GLOBAL

    lam_ft, lam_ht_v1 = confronto.get("lambda_ft"), confronto.get("lambda_ht")
    lam_ht = shrinkage.encolher_media(
        [(p.get("media_gols_ht"), p.get("under25_ht_total")) for p in (ph, pa)],
        base["gols_ht"], cfg.PSEUDO_JOGOS_HT) or lam_ht_v1

    def media(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    freq_par = media([shrinkage.encolher(p["par_acertos"], p["par_total"], base["par"],
                                         cfg.PSEUDO_JOGOS_HT) for p in (ph, pa)])
    freq_ft = media([shrinkage.encolher(p["over15_acertos"], p["over15_total"],
                                        base["over15_ft"], cfg.PSEUDO_JOGOS_FT)
                     for p in (ph, pa)])
    freq_ht = media([shrinkage.encolher(p["under25_ht_acertos"], p["under25_ht_total"],
                                        base["under25_ht"], cfg.PSEUDO_JOGOS_HT)
                     for p in (ph, pa)])
    modelo_par = joint.probabilidade_do_par(lam_ft, lam_ht)
    prob_par = None
    if modelo_par is not None and freq_par is not None:
        prob_par = round(modelo_par * 0.55 + freq_par * 0.45, 4)
    elif modelo_par is not None:
        prob_par = modelo_par

    from services.pick_engine_boost import stats_model as sm
    dist = sm.distribuicao_ht(ph, pa)

    confronto_v2 = {
        **confronto,
        "lambda_ht": lam_ht,
        "freq_over15": freq_ft, "freq_under25_ht": freq_ht,
        "freq_par": freq_par, "prob_modelo_par": modelo_par,
        "prob_combinada": prob_par,
        "margem_ft": round(float(lam_ft) - cfg.LINHA_OVER_FT, 3) if lam_ft else None,
        "margem_ht": round(cfg.LINHA_UNDER_HT - float(lam_ht), 3) if lam_ht else None,
        "divergencia_modelo_historico": (round(modelo_par - freq_par, 4)
                                         if modelo_par is not None and freq_par is not None
                                         else None),
        "distribuicao_ht": dist,
        "consistencia": {"min_amostra_ft": min(ph["over15_total"], pa["over15_total"]),
                         "min_amostra_ht": min(ph["under25_ht_total"], pa["under25_ht_total"])},
    }

    odd = float(pick.get("odd") or 0) or None
    calibrada = calibration.calibrar(prob_par)
    prob_final = calibrada.get("prob")
    ev = round(prob_final * odd - 1, 4) if prob_final and odd else None
    edge = round(prob_final - 1 / odd, 4) if prob_final and odd else None

    risco = ht_risk.calcular(lam_ht, dist)
    tail = ht_risk.tail_risk(dist)
    qual = quality.data_quality(ph, pa, [], [])
    classe = shrinkage.classe_de_amostra(
        min(confronto_v2["consistencia"]["min_amostra_ft"],
            confronto_v2["consistencia"]["min_amostra_ht"]))
    conv = quality.convergencia({
        "freq_over15": freq_ft, "prob_modelo_ft": confronto.get("prob_modelo_ft"),
        "margem_ft": confronto_v2["margem_ft"], "freq_under25_ht": freq_ht,
        "prob_modelo_ht": confronto.get("prob_modelo_ht"),
        "margem_ht": confronto_v2["margem_ht"],
    })
    contras = contradiction.detectar(confronto_v2, risco, ev, debug.get("score"))
    dims = decision.scores(confronto_v2, float(debug.get("score") or 0), risco, qual,
                           conv, ph, pa, ev)
    pen = decision.penalidades(risco, confronto_v2, edge)
    final = decision.score_final(dims, pen)
    veredito = decision.avaliar(
        ev=ev, edge=edge, qualidade=qual, convergencia=conv, risco_ht=risco,
        tail=tail, confronto=confronto_v2, contradicoes=contras,
        calibrada=calibrada, amostra_classe=classe, score_final_valor=final)

    return {
        "veredito": veredito, "ev": ev, "edge": edge, "prob_v2": prob_final,
        "prob_v1": float(pick["prob_real"]) if pick.get("prob_real") is not None else None,
        "ht_risk": risco["score"], "tail": tail["score"], "data_quality": qual["score"],
        "convergencia": conv["fracao"], "margem_ft": confronto_v2["margem_ft"],
        "classe": classe, "score_final": final,
        "score_v1": float(debug.get("score") or 0),
    }


# ---------------------------------------------------------------------------
# Secoes
# ---------------------------------------------------------------------------
def _linha(rotulo, n, greens, reds, lucro, largura=38):
    taxa = f"{greens / n * 100:5.1f}%" if n else "    --"
    roi = f"{lucro / n * 100:+6.1f}%" if n else "    --"
    print(f"  {rotulo:<{largura}} n={n:<4} green={greens:<4} red={reds:<4} "
          f"acerto={taxa}  ROI={roi}")


def secao_portas(linhas):
    print("\n== O QUE CADA PORTA DA V2 TERIA CORTADO ==")
    print("   (so' picks ja' liquidados; um GREEN cortado e' o custo da porta)")
    por_porta = defaultdict(lambda: {"n": 0, "g": 0, "r": 0, "lucro": 0.0})
    mantidos = {"n": 0, "g": 0, "r": 0, "lucro": 0.0}
    for pick, v2 in linhas:
        res = (pick.get("result") or "").upper()
        lucro = _lucro(pick)
        alvo = (mantidos if v2["veredito"]["decision"] == "PICK"
                else por_porta[v2["veredito"]["codigo"]])
        alvo["n"] += 1
        alvo["g"] += 1 if res == "GREEN" else 0
        alvo["r"] += 1 if res == "RED" else 0
        alvo["lucro"] += lucro
    for codigo, d in sorted(por_porta.items(), key=lambda kv: -kv[1]["n"]):
        _linha(codigo, d["n"], d["g"], d["r"], d["lucro"])
    print("  " + "-" * 74)
    _linha("MANTIDOS PELA V2", mantidos["n"], mantidos["g"], mantidos["r"],
           mantidos["lucro"])
    total = {"n": 0, "g": 0, "r": 0, "lucro": 0.0}
    for pick, _ in linhas:
        res = (pick.get("result") or "").upper()
        total["n"] += 1
        total["g"] += 1 if res == "GREEN" else 0
        total["r"] += 1 if res == "RED" else 0
        total["lucro"] += _lucro(pick)
    _linha("V1 (todos)", total["n"], total["g"], total["r"], total["lucro"])


def secao_calibracao(linhas):
    """A tabela que alimenta cfg.CALIBRACAO_MEDIDA -- se houver amostra."""
    print("\n== CALIBRACAO: probabilidade dita x taxa real ==")
    faixas = [(0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75),
              (0.75, 0.80), (0.80, 1.01)]
    print("   V1 = prob_real gravada (produto das pernas) · V2 = par recalculado")
    for rotulo, chave in (("V1", "prob_v1"), ("V2", "prob_v2")):
        print(f"  -- {rotulo} --")
        for piso, teto in faixas:
            grupo = [(p, v) for p, v in linhas
                     if v.get(chave) is not None and piso <= v[chave] < teto]
            n = len(grupo)
            greens = sum(1 for p, _ in grupo if (p.get("result") or "").upper() == "GREEN")
            reds = sum(1 for p, _ in grupo if (p.get("result") or "").upper() == "RED")
            lucro = sum(_lucro(p) for p, _ in grupo)
            dito = sum(v[chave] for _, v in grupo) / n if n else 0
            alerta = ""
            if n >= cfg.MIN_AMOSTRA_CALIBRACAO and n:
                if greens / n < dito - 0.05:
                    alerta = "  <-- inflada"
            _linha(f"{piso:.2f}-{teto:.2f} (dito {dito * 100:4.1f}%){alerta}",
                   n, greens, reds, lucro)
        print(f"     amostra minima por faixa pra valer: {cfg.MIN_AMOSTRA_CALIBRACAO}")


def secao_faixas(linhas):
    print("\n== DESEMPENHO POR FAIXA DOS INDICADORES NOVOS ==")
    grupos = {
        "HT_RISK": (lambda v: v["ht_risk"], [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]),
        "TAIL_RISK": (lambda v: v["tail"], [(0, 20), (20, 40), (40, 60), (60, 101)]),
        "DATA_QUALITY": (lambda v: v["data_quality"], [(0, 70), (70, 80), (80, 90), (90, 101)]),
        "MARGEM_FT": (lambda v: v["margem_ft"], [(0, 0.4), (0.4, 0.7), (0.7, 1.0), (1.0, 9)]),
        "EV": (lambda v: v["ev"], [(-9, 0), (0, 0.05), (0.05, 0.12), (0.12, 9)]),
    }
    for nome, (leitor, faixas) in grupos.items():
        print(f"  -- {nome} --")
        for piso, teto in faixas:
            grupo = [(p, v) for p, v in linhas
                     if leitor(v) is not None and piso <= leitor(v) < teto]
            n = len(grupo)
            _linha(f"{piso} a {teto}", n,
                   sum(1 for p, _ in grupo if (p.get("result") or "").upper() == "GREEN"),
                   sum(1 for p, _ in grupo if (p.get("result") or "").upper() == "RED"),
                   sum(_lucro(p) for p, _ in grupo))


def secao_amostra(linhas):
    print("\n== DESEMPENHO POR CLASSE DE AMOSTRA ==")
    print("   (e' daqui que sai o k honesto de PSEUDO_JOGOS_*, nao do palpite)")
    for classe in ("MUITO_FRACA", "LIMITADA", "RAZOAVEL", "BOA", "FORTE"):
        grupo = [(p, v) for p, v in linhas if v["classe"] == classe]
        _linha(classe, len(grupo),
               sum(1 for p, _ in grupo if (p.get("result") or "").upper() == "GREEN"),
               sum(1 for p, _ in grupo if (p.get("result") or "").upper() == "RED"),
               sum(_lucro(p) for p, _ in grupo))


def secao_estabilidade(linhas):
    """A mesma regra nas duas metades da amostra, em ordem de data."""
    print("\n== ESTABILIDADE: primeira metade x segunda metade ==")
    print("   Regra que so' funciona numa das metades nao e' regra.")
    ordenadas = sorted(linhas, key=lambda x: str(x[0].get("match_date")))
    meio = len(ordenadas) // 2
    for rotulo, parte in (("1a metade", ordenadas[:meio]), ("2a metade", ordenadas[meio:])):
        cortados = [(p, v) for p, v in parte if v["veredito"]["decision"] != "PICK"]
        mantidos = [(p, v) for p, v in parte if v["veredito"]["decision"] == "PICK"]
        _linha(f"{rotulo} · cortados pela V2", len(cortados),
               sum(1 for p, _ in cortados if (p.get("result") or "").upper() == "GREEN"),
               sum(1 for p, _ in cortados if (p.get("result") or "").upper() == "RED"),
               sum(_lucro(p) for p, _ in cortados))
        _linha(f"{rotulo} · mantidos pela V2", len(mantidos),
               sum(1 for p, _ in mantidos if (p.get("result") or "").upper() == "GREEN"),
               sum(1 for p, _ in mantidos if (p.get("result") or "").upper() == "RED"),
               sum(_lucro(p) for p, _ in mantidos))


SECOES = {"portas": secao_portas, "calibracao": secao_calibracao,
          "faixas": secao_faixas, "amostra": secao_amostra,
          "estabilidade": secao_estabilidade}


def main():
    ap = argparse.ArgumentParser(description="Pick Boost: V1 contra V2 (somente leitura)")
    ap.add_argument("--dias", type=int, default=120)
    ap.add_argument("--secao", choices=sorted(SECOES), action="append")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, match_date, home_team, away_team, odd, prob_real, confidence,
               score, ev, edge, result, profit, engine_debug
          FROM picks_boost
         WHERE result IS NOT NULL
           AND match_date >= CURRENT_DATE - %s::int
      ORDER BY match_date
    """, (args.dias,))
    colunas = [d[0] for d in cur.description]
    picks = [dict(zip(colunas, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"Pick Boost · backtest V1 x V2 · {len(picks)} pick(s) liquidados "
          f"nos ultimos {args.dias} dias")
    if not picks:
        print("Sem pick liquidado no periodo. Nada a medir -- e isso NAO e' um "
              "resultado a favor nem contra a V2.")
        return

    linhas = []
    sem_rastro = 0
    for p in picks:
        v2 = reprocessar(p)
        if v2 is None:
            sem_rastro += 1
            continue
        linhas.append((p, v2))
    print(f"{len(linhas)} reprocessados · {sem_rastro} sem rastro suficiente "
          f"no engine_debug")
    if not linhas:
        return

    for nome in (args.secao or list(SECOES)):
        SECOES[nome](linhas)

    print("\nLembrete: um GREEN cortado nao prova que a porta esta' errada, e um "
          "RED mantido nao prova que ela esta' certa. A pergunta e' se a "
          "evidencia do dia sustentava a aposta.")


if __name__ == "__main__":
    main()
