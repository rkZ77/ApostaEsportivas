"""live_backtest_v2.py · o motor ao vivo ANTIGO contra o NOVO, nos mesmos picks.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/live_backtest_v2.py
  DB_ENV=prod python src/scripts/live_backtest_v2.py --dias 60
  DB_ENV=prod python src/scripts/live_backtest_v2.py --secao calibracao

O QUE ELE MEDE, E O QUE ELE NAO CONSEGUE MEDIR
----------------------------------------------
MEDE, com precisao: quantos dos picks JA LIQUIDADOS cada porta nova teria
cortado, e qual era o resultado deles. Isso responde a unica pergunta que
importa antes de ligar a V2 em producao -- "ela corta os RED ou corta os
GREEN?" -- e responde com o desfecho real, nao com simulacao.

NAO CONSEGUE MEDIR, e a honestidade sobre isso e' parte do resultado: os picks
que a V2 CRIARIA e a V1 nao criou. Dois motivos, e so' o segundo tem conserta:

  1. As portas novas so' REPROVAM. Nenhuma delas aprova nada que a V1 tenha
     recusado, entao esse conjunto e' vazio POR CONSTRUCAO no que diz respeito
     a gates. Nao e' uma limitacao da medicao, e' uma propriedade do desenho.

  2. O baseline historico novo MUDA a projecao, e projecao diferente muda
     probabilidade, EV e, no limite, a decisao -- nos dois sentidos. Esse
     efeito exigiria reprocessar a partida inteira com a serie historica
     recortada na data do jogo. A secao `baseline` faz exatamente esse recorte
     e mede o DESLOCAMENTO, que e' o antecedente da mudanca de decisao; o
     replay completo depende de guardar a folha bruta de cada passada, que hoje
     so' existe pro pick escolhido.

POR QUE NAO OTIMIZAR CONTRA ESTE NUMERO
---------------------------------------
Todo pick aqui e' passado, e os limiares da V2 foram escolhidos ANTES de olhar
para ele (estao em config.py com a justificativa de cada um). Mexer nos
limiares ate' esta saida ficar bonita e' ajustar o modelo ao proprio teste --
o resultado de sempre e' um motor que explica o passado e nao acerta o futuro.
A saida separa `ate a metade da amostra` e `depois da metade` justamente pra
essa checagem: regra que so' funciona numa das metades nao e' regra.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from services.pick_engine_live import (  # noqa: E402
    contradiction_model, data_quality, history_model, orchestrator as orq,
    regime_model,
)
from services.pick_engine_live.config import LiveEngineConfig  # noqa: E402
from utils.db_utils import get_connection  # noqa: E402

#: Resultado -> quanto ele move a banca, em unidades de stake. O `profit`
#: gravado ja' traz isso, mas nem todo pick antigo tem profit preenchido --
#: entao a conta cai aqui quando falta, com a mesma convencao de
#: services/settlement.py.
FATOR = {"GREEN": None, "RED": -1.0, "PUSH": 0.0,
         "HALF_WIN": None, "HALF_LOSS": -0.5, "VOID": 0.0}


def _json(bruto):
    if isinstance(bruto, str):
        try:
            return json.loads(bruto)
        except ValueError:
            return {}
    return bruto or {}


def _lucro(linha) -> float:
    """Unidades ganhas ou perdidas. Usa `profit` quando existe."""
    resultado, odd, profit = linha["result"], float(linha["odd"] or 0), linha["profit"]
    if profit is not None:
        return float(profit)
    if resultado == "GREEN":
        return odd - 1.0
    if resultado == "HALF_WIN":
        return (odd - 1.0) / 2
    return FATOR.get(resultado, 0.0) or 0.0


def _cabecalho(texto: str) -> None:
    print("\n" + texto)
    print("-" * len(texto))


# ─────────────────────────────────────────────────────────────────────────
# Reconstrucao da V2 sobre um pick ja' gravado
# ─────────────────────────────────────────────────────────────────────────
def _v2_sobre_o_pick(debug: dict, linha: dict, config: LiveEngineConfig) -> dict:
    """Roda as portas da V2 sobre o rastro de um pick que a V1 aprovou.

    O que da' pra reconstruir do `engine_debug` sem tocar em API: estado da
    partida, pressao, ritmo, tendencia, janelas, freshness, lambda, linha, odd,
    EV e a probabilidade do mercado. Falta so' o historico -- que a V1 nao
    calculava --, e ele vem do banco, recortado na data da partida.
    """
    estado = debug.get("current_state") or {}
    familia = linha["market_type"]
    # `picks_live.line` guarda o rotulo montado por live_odds.extrair_linhas
    # ("Over 9.5" / "Under 9.5"), nao a traducao da tela -- entao a direcao sai
    # do prefixo. "mais de" fica aceito pra o caso de algum pick antigo ter
    # sido gravado ja' traduzido.
    rotulo = (linha["line"] or "").strip().lower()
    direcao = "over" if rotulo.startswith(("over", "mais")) else "under"
    linha_valor = float(linha["line_value"] or 0)

    info = {
        "disponivel": True,
        "tendencia": debug.get("trend") or {},
        "janelas": debug.get("recent_windows") or {},
        "projecao_total": (debug.get("projection") or {}).get("projecao_total"),
        "motivo": None,
    }
    pressao = debug.get("pressure")
    fresh = debug.get("freshness")
    ritmo = debug.get("rhythm")
    hist = linha.get("_historico") or {}

    alinhamento = history_model.historical_alignment(
        baseline_historico=hist.get("valor"), linha=linha_valor, direcao=direcao,
        familia=familia,
        lado_casa=(hist.get("home") or {}).get("valor"),
        lado_fora=(hist.get("away") or {}).get("valor"))

    regime = regime_model.regime(estado, pressao, ritmo, debug.get("events"), familia)
    qualidade = data_quality.cobertura(
        info, pressao, fresh, historico=hist,
        prob_mercado=(debug.get("market") or {}).get("prob_mercado"))

    conv = debug.get("convergence") or {}
    divergencia = (debug.get("confidence_breakdown") or {}).get("divergencia_modelo")
    contra = contradiction_model.contradicao(
        alinhamento=alinhamento, projecao=info["projecao_total"], linha=linha_valor,
        direcao=direcao, regime=regime, conv=conv, divergencia_modelo=divergencia)

    distancia = (info["projecao_total"] - linha_valor if direcao == "over"
                 else linha_valor - info["projecao_total"]) \
        if info["projecao_total"] is not None else None
    ajustado = orq.ev_ajustado(float(linha["ev"] or 0), qualidade, contra, alinhamento)

    motivos = orq._gates_v2(config, familia, direcao, qualidade, contra,
                            alinhamento, distancia, ajustado["adjusted_ev"])
    return {
        "reprovado_por": motivos,
        "coverage": qualidade["coverage"],
        "contradiction": contra["score"],
        "alignment": alinhamento.get("alinhamento"),
        "adjusted_ev": ajustado["adjusted_ev"],
        "margem": distancia,
        "regime": regime["estado"],
    }


def _historico_na_data(cur, linha: dict, config: LiveEngineConfig) -> dict:
    """A serie historica como ela era NA DATA DA PARTIDA.

    O corte por data e' o ponto inteiro: montar o historico com os jogos de
    hoje daria ao motor antigo informacao que ele nao tinha, e o backtest
    passaria a medir profecia em vez de modelo.
    """
    from engine_pipelines import live_pipeline as lp

    estado = {"home_team_id": linha["home_team_id"],
              "away_team_id": linha["away_team_id"],
              "league_id": linha["league_id"],
              "fixture_id": linha["fixture_id"]}
    familia = linha["market_type"]
    extrator = lp.TOTAL_DA_FAMILIA.get(familia)
    if not extrator or not all(estado.values()):
        return {}
    teto = int(config.jogos_historicos_por_lado)
    try:
        cur.execute(f"""
            SELECT fixture_id, home_team_id, away_team_id, match_date,
                   total_corners, total_goals,
                   total_yellow_cards, total_red_cards,
                   home_fouls, away_fouls,
                   home_total_shots, away_total_shots,
                   home_shots_on, away_shots_on
              FROM match_statistics
             WHERE league_id = %s
               AND status IN ('FT', 'AET', 'PEN')
               AND (home_team_id IN (%s, %s) OR away_team_id IN (%s, %s))
               AND match_date < %s
               AND match_date >= %s::date - INTERVAL '{lp.DIAS_DE_HISTORICO} days'
               AND NOT (COALESCE(home_possession, -1) = 0
                        AND COALESCE(away_possession, -1) = 0)
             ORDER BY match_date DESC
             LIMIT %s
        """, (linha["league_id"], linha["home_team_id"], linha["away_team_id"],
              linha["home_team_id"], linha["away_team_id"],
              linha["match_date"], linha["match_date"], teto * 4))
        colunas = [d[0] for d in cur.description]
        jogos = [dict(zip(colunas, r)) for r in cur.fetchall()]
    except Exception as e:
        print(f"  [aviso] historico indisponivel para fixture "
              f"{linha['fixture_id']}: {e}")
        return {}
    if not jogos:
        return {}

    lados = {}
    for lado, team_id, mando in (("home", linha["home_team_id"], "home_team_id"),
                                 ("away", linha["away_team_id"], "away_team_id")):
        contexto = [extrator(j) for j in jogos
                    if j[mando] == team_id][:teto]
        geral = [extrator(j) for j in jogos
                 if team_id in (j["home_team_id"], j["away_team_id"])][:teto]
        lados[lado] = history_model.componentes_do_lado(contexto, geral, None)
    pesos = dict(zip(history_model.PESOS_PADRAO.keys(), config.pesos_historicos))
    return history_model.baseline_do_confronto(
        lados["home"], lados["away"], pesos) or {}


# ─────────────────────────────────────────────────────────────────────────
# Secoes
# ─────────────────────────────────────────────────────────────────────────
def _resumo(nome: str, picks: list) -> None:
    if not picks:
        print(f"  {nome:<28} n=0")
        return
    lucro = sum(_lucro(p) for p in picks)
    greens = sum(1 for p in picks if p["result"] in ("GREEN", "HALF_WIN"))
    decididos = [p for p in picks if p["result"] not in ("PUSH", "VOID", None)]
    acerto = (greens / len(decididos) * 100) if decididos else 0.0
    odd = sum(float(p["odd"] or 0) for p in picks) / len(picks)
    print(f"  {nome:<28} n={len(picks):<4} acerto={acerto:5.1f}%  "
          f"lucro={lucro:+7.2f}u  ROI={lucro / len(picks) * 100:+6.1f}%  "
          f"odd media={odd:.2f}")


def secao_portas(picks: list, config: LiveEngineConfig) -> None:
    _cabecalho(f"V1 CONTRA V2 · {len(picks)} pick(s) liquidado(s)")
    if not picks:
        print("  Sem pick liquidado na janela. Nada a comparar.")
        return

    cortados = [p for p in picks if p["_v2"]["reprovado_por"]]
    mantidos = [p for p in picks if not p["_v2"]["reprovado_por"]]

    _resumo("V1 (tudo que ela aprovou)", picks)
    _resumo("V2 (o que sobrevive)", mantidos)
    _resumo("cortado pela V2", cortados)

    print("\n  Nota: 'cortado pela V2' com ROI NEGATIVO e' a V2 funcionando.")
    print("  Com ROI positivo, ela esta' cortando o que dava dinheiro -- e ai")
    print("  a porta responsavel (abaixo) e' a que precisa de limiar mais alto.")

    _cabecalho("QUANTO CADA PORTA CORTA, E O QUE ELA CORTA")
    por_porta = defaultdict(list)
    for p in cortados:
        for motivo in p["_v2"]["reprovado_por"]:
            chave = motivo.split(":")[0].split(" abaixo")[0].split(" acima")[0][:38]
            por_porta[chave].append(p)
    if not por_porta:
        print("  Nenhuma porta cortou nada nesta janela.")
    for porta, lista in sorted(por_porta.items(), key=lambda kv: -len(kv[1])):
        _resumo(porta, lista)

    # A checagem contra overfitting: a mesma regra nas duas metades da amostra.
    _cabecalho("AS DUAS METADES DA AMOSTRA (treino / validacao)")
    meio = len(picks) // 2
    for nome, fatia in (("1a metade (mais antiga)", picks[:meio]),
                        ("2a metade (mais recente)", picks[meio:])):
        sub_cortados = [p for p in fatia if p["_v2"]["reprovado_por"]]
        sub_mantidos = [p for p in fatia if not p["_v2"]["reprovado_por"]]
        print(f"\n  {nome}")
        _resumo("    V1", fatia)
        _resumo("    V2", sub_mantidos)
        _resumo("    cortado", sub_cortados)

    _cabecalho("EXEMPLOS · V1 disse PICK, V2 diz NO_PICK")
    for p in sorted(cortados, key=lambda x: _lucro(x))[:6]:
        print(f"\n  fixture {p['fixture_id']} · {p['home_team_name']} x "
              f"{p['away_team_name']} · {p['market']} {p['line']} @ {p['odd']}")
        print(f"    minuto {p['minute_at_creation']}' · resultado {p['result']} "
              f"({_lucro(p):+.2f}u) · EV declarado {float(p['ev'] or 0):+.1%}")
        v2 = p["_v2"]
        print(f"    cobertura {v2['coverage']:.0%} · contradicao "
              f"{v2['contradiction']:.0%} · alinhamento "
              + (f"{v2['alignment']:.0%}" if v2["alignment"] is not None else "n/d")
              + f" · EV ajustado {v2['adjusted_ev']:+.1%} · regime {v2['regime']}")
        for motivo in v2["reprovado_por"]:
            print(f"    -- {motivo}")


def secao_calibracao(picks: list) -> None:
    """Probabilidade prevista contra taxa real de acerto, por faixa."""
    _cabecalho(f"CALIBRACAO · {len(picks)} pick(s) liquidado(s)")
    faixas = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
              (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.01)]
    print(f"  {'faixa':<12} {'n':>4} {'previsto':>9} {'real':>7} {'erro':>8} {'lucro':>9}")
    for baixo, alto in faixas:
        fatia = [p for p in picks
                 if p["probability"] is not None
                 and baixo <= float(p["probability"]) < alto
                 and p["result"] not in ("PUSH", "VOID", None)]
        if not fatia:
            continue
        previsto = sum(float(p["probability"]) for p in fatia) / len(fatia)
        greens = sum(1 for p in fatia if p["result"] in ("GREEN", "HALF_WIN"))
        real = greens / len(fatia)
        lucro = sum(_lucro(p) for p in fatia)
        print(f"  {baixo:.0%}-{alto:.0%}{'':<4} {len(fatia):>4} {previsto:>8.1%} "
              f"{real:>7.1%} {real - previsto:>+8.1%} {lucro:>+8.2f}u")

    for rotulo, chave in (("POR FAMILIA", "market_type"),
                          ("POR FAIXA DE MINUTO", "_faixa_minuto"),
                          ("POR ALINHAMENTO HISTORICO (V2)", "_faixa_align")):
        _cabecalho(rotulo)
        grupos = defaultdict(list)
        for p in picks:
            grupos[p.get(chave)].append(p)
        for nome, fatia in sorted(grupos.items(), key=lambda kv: str(kv[0])):
            decididos = [p for p in fatia if p["result"] not in ("PUSH", "VOID", None)]
            if not decididos:
                continue
            previsto = sum(float(p["probability"] or 0) for p in decididos) / len(decididos)
            real = sum(1 for p in decididos
                       if p["result"] in ("GREEN", "HALF_WIN")) / len(decididos)
            lucro = sum(_lucro(p) for p in fatia)
            print(f"  {str(nome):<26} n={len(decididos):<4} previsto={previsto:6.1%} "
                  f"real={real:6.1%} erro={real - previsto:+6.1%} lucro={lucro:+7.2f}u")


def secao_baseline(picks: list) -> None:
    """Quanto o baseline V2 se afasta do que a V1 usou de fato."""
    _cabecalho("DESLOCAMENTO DO BASELINE · V1 contra V2")
    print("  E' o antecedente da mudanca de decisao que o backtest de portas")
    print("  nao alcanca: baseline diferente muda lambda, probabilidade e EV.")
    por_familia = defaultdict(list)
    for p in picks:
        hist = p.get("_historico") or {}
        usado = ((_json(p["engine_debug"]).get("baseline") or {}).get("valor"))
        if not hist.get("valor") or not usado:
            continue
        por_familia[p["market_type"]].append(
            (float(usado), float(hist["valor"]), hist["cobertura"]))
    if not por_familia:
        print("\n  Sem par comparavel (historico ou baseline ausente).")
        return
    for familia, pares in sorted(por_familia.items()):
        v1 = sum(a for a, _, _ in pares) / len(pares)
        v2 = sum(b for _, b, _ in pares) / len(pares)
        cob = sum(c for _, _, c in pares) / len(pares)
        maior = max(abs(b - a) for a, b, _ in pares)
        print(f"\n  {familia:<10} n={len(pares)}")
        print(f"    baseline V1 medio : {v1:.2f}")
        print(f"    baseline V2 medio : {v2:.2f}   ({v2 - v1:+.2f})")
        print(f"    maior deslocamento: {maior:.2f}")
        print(f"    cobertura media   : {cob:.0%}")


# ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Motor ao vivo V1 contra V2, nos mesmos picks (somente leitura).")
    parser.add_argument("--dias", type=int, default=120)
    parser.add_argument("--secao", choices=("tudo", "portas", "calibracao", "baseline"),
                        default="tudo")
    args = parser.parse_args()

    config = LiveEngineConfig.do_ambiente()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, fixture_id, match_date, league_id, home_team_id, away_team_id,
               home_team_name, away_team_name, market, market_type, line,
               line_value, odd, minute_at_creation, probability, ev, confidence,
               result, profit, engine_version, engine_debug
          FROM picks_live
         WHERE result IS NOT NULL
           AND created_at >= NOW() - (%s || ' days')::interval
         ORDER BY created_at
    """, (args.dias,))
    colunas = [d[0] for d in cur.description]
    picks = [dict(zip(colunas, r)) for r in cur.fetchall()]

    print("=" * 68)
    print(f"BACKTEST DO MOTOR AO VIVO · V1 contra V2 · ultimos {args.dias} dia(s)")
    print(f"config: {config.resumo()}")
    print("=" * 68)
    if not picks:
        print("\nNenhum pick liquidado na janela -- nada a medir.")
        print("Sem amostra nao existe veredito sobre qualidade de motor, e")
        print("inventar um a partir de 5 picks e' o pior resultado possivel")
        print("desta analise.")
        cur.close()
        conn.close()
        return

    for p in picks:
        debug = _json(p["engine_debug"])
        p["_historico"] = _historico_na_data(cur, p, config)
        p["_v2"] = _v2_sobre_o_pick(debug, p, config)
        minuto = p["minute_at_creation"] or 0
        p["_faixa_minuto"] = f"{(minuto // 15) * 15}-{(minuto // 15) * 15 + 14}'"
        align = p["_v2"]["alignment"]
        p["_faixa_align"] = ("sem historico" if align is None
                             else f"{int(align * 4) * 25}-{int(align * 4) * 25 + 24}%")

    if args.secao in ("tudo", "portas"):
        secao_portas(picks, config)
    if args.secao in ("tudo", "calibracao"):
        secao_calibracao(picks)
    if args.secao in ("tudo", "baseline"):
        secao_baseline(picks)
    print()

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
