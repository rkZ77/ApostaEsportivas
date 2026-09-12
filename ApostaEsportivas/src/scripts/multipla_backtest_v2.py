"""multipla_backtest_v2.py · a Multipla V1 contra a V2, nos mesmos bilhetes.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/multipla_backtest_v2.py
  DB_ENV=prod python src/scripts/multipla_backtest_v2.py --dias 90
  DB_ENV=prod python src/scripts/multipla_backtest_v2.py --secao portas

O QUE ELE MEDE
--------------
Cada bilhete ja' liquidado de `picks_multiplas` e' reprocessado com as portas
da V2, e a saida diz quantos GREEN e quantos RED cada porta teria cortado. E'
a unica pergunta que decide se a V2 entra: ela corta os RED ou corta os GREEN?

Alem disso, as perguntas que o pedido de 11/09 fez explicitamente:

  faixa de odd     2.00-2.20 e' melhor que 2.80-3.00? Nao presumir.
  numero de pernas 3 pernas aumentam muito o risco? Medir, nao supor.
  estrutura        gols+escanteio rende mais que gols+gols? Medir.
  calibracao       o que o motor anuncia como 70% ganha 70%?

DE ONDE VEM O RASTRO, E O QUE ELE NAO TEM
------------------------------------------
Os bilhetes antigos nao tem `engine_debug` (a coluna nasceu com a V2). O que
existe deles e':

  picks_multiplas.games   odd, prob_real, confidence e mercado de cada perna
  engine_decisions        amostra, ev e edge por candidato daquele dia

Cruzando os dois por (fixture_id, market_type, linha) da' pra reconstruir a
probabilidade calibrada, o gate de amostra, o de EV e o de edge. NAO da' pra
reconstruir `data_quality_score`, `risco` nem `projecao`: eles nunca foram
gravados por bilhete.

ISSO TEM UMA CONSEQUENCIA QUE PRECISA SER LIDA JUNTO COM O RESULTADO: as
portas que dependem desses tres campos SAO TRATADAS COMO NEUTRAS aqui, ou
seja, o corte medido e' um PISO. A V2 real corta pelo menos o que esta' na
tabela, e provavelmente mais. Nao e' uma estimativa do corte total.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.pick_engine_multipla import combination, component, correlation  # noqa: E402
from services.pick_engine_multipla import config as mcfg  # noqa: E402
from services.pick_engine.stats_model import wilson_interval  # noqa: E402
from utils.db_utils import get_connection  # noqa: E402


def _json(bruto):
    if isinstance(bruto, str):
        try:
            return json.loads(bruto)
        except ValueError:
            return []
    return bruto or []


def _lucro(bilhete: dict) -> float:
    """Lucro em unidades de 1u de entrada. `profit` quando existe; senao, a
    conta do resultado -- GREEN paga odd-1, RED custa a entrada."""
    if bilhete.get("profit") is not None:
        return float(bilhete["profit"])
    resultado = (bilhete.get("result") or "").upper()
    if resultado == "GREEN":
        return float(bilhete.get("total_odd") or 1) - 1
    if resultado == "RED":
        return -1.0
    return 0.0


# ---------------------------------------------------------------------------
# Reconstrucao da perna a partir do rastro da V1
# ---------------------------------------------------------------------------
def _rastro_do_dia(cur, dias: int) -> dict:
    """{(fixture_id, market_type, linha): {amostra, ev, edge, ...}} do log de
    decisao. E' de la' que sai a amostra, que `games` nunca guardou."""
    cur.execute("""
        SELECT fixture_id, candidates
          FROM engine_decisions
         WHERE pipeline = 'MULTIPLA_ENGINE'
           AND match_date >= CURRENT_DATE - %s::int
    """, (dias,))
    indice = {}
    for fixture_id, candidatos in cur.fetchall():
        for c in _json(candidatos):
            chave = (fixture_id, c.get("market_type"), c.get("line"))
            # A primeira ocorrencia manda: o log grava a linha vencedora do
            # mercado antes do rastro das perdedoras.
            indice.setdefault(chave, c)
    return indice


def _perna_reconstruida(leg: dict, fixture_id, rastro: dict) -> dict:
    """Uma perna no formato que a V2 le, com o que o historico permite.

    Os campos que nunca foram gravados entram NEUTROS -- nunca favoraveis.
    `data_quality_score` recebe o piso do gate (passa raspando, nao reprova
    nem premia) e `risco` fica BAIXO porque um valor pior reprovaria por um
    dado que nao existe. Os dois inflam o numero de bilhetes MANTIDOS, e e'
    por isso que o corte medido e' um piso.
    """
    chave = (fixture_id, leg.get("market_type"), leg.get("line"))
    do_log = rastro.get(chave) or {}

    taxa = leg.get("prob_real") or do_log.get("taxa_real")
    amostra = do_log.get("amostra")
    wilson = None
    if taxa is not None and amostra:
        # Wilson exige a contagem bruta, que nao foi gravada. Reconstituir por
        # round(taxa * amostra) e' uma APROXIMACAO: taxa_real ja' carrega peso
        # de recencia e de adversario, entao a contagem implicita nao e'
        # exatamente a que o motor contou. Serve pra ordem de grandeza do
        # encolhimento, nao pra auditar uma perna especifica.
        wilson = wilson_interval(round(float(taxa) * int(amostra)), int(amostra))

    return {
        "market_type": leg.get("market_type"),
        "market_name": leg.get("market"),
        "value_label": leg.get("line"),
        "odd": leg.get("odd"),
        "melhor_odd": leg.get("odd"),
        "best_bookmaker": leg.get("bet_house"),
        "bookmaker_odds": [{"bookmaker": leg.get("bet_house"), "odd": leg.get("odd")}],
        "taxa_real": taxa,
        "amostra": amostra,
        "wilson": wilson,
        "confidence": leg.get("confidence") or do_log.get("confidence"),
        "ev": do_log.get("ev"),
        "edge": do_log.get("edge"),
        "risco": "BAIXO",
        "data_quality_score": mcfg.MIN_DATA_QUALITY,
        "projecao": None,
        "convergence": None,
        "final_score": do_log.get("final_score") or 0.0,
        "_fixture": {
            "fixture_id": fixture_id,
            "home_team": leg.get("home_team"), "away_team": leg.get("away_team"),
            "home_team_id": leg.get("home_team_id"),
            "away_team_id": leg.get("away_team_id"),
            "league_id": leg.get("league_id"),
        },
    }


def reprocessar(bilhete: dict, rastro: dict) -> dict | None:
    """O veredito da V2 sobre um bilhete da V1. None quando falta rastro."""
    legs = _json(bilhete.get("legs"))
    if len(legs) < 2:
        return None

    pernas = []
    for leg in legs:
        fixture_id = leg.get("fixture_id")
        p = _perna_reconstruida(leg, fixture_id, rastro)
        if p["taxa_real"] is None or p["odd"] is None:
            return None
        pernas.append(component.avaliar(p))

    reprovadas = [m for p in pernas if not p["aprovada"] for m in p["motivos"]]
    # A odd do bilhete e' a que foi APOSTADA, e nao a soma reprecificada por
    # casa: a casa unica e' regra da V2 e nao existia quando estes bilhetes
    # sairam. Cobrar isso aqui mediria a mudanca de politica de casa, nao a
    # qualidade da selecao.
    avaliada = combination.avaliar(pernas)
    codigo = None
    if reprovadas:
        codigo = sorted(set(reprovadas))[0]
    elif not avaliada["aprovada"]:
        codigo = avaliada["motivos"][0]

    return {
        "decision": "PICK" if codigo is None else "NO_MULTIPLA",
        "codigo": codigo or "MANTIDO",
        "score": avaliada.get("score"),
        "probabilidade": avaliada.get("probabilidade"),
        "correlacao": (avaliada.get("correlacao") or {}).get("nivel"),
        "familias": sorted({component.familia(p) for p in pernas}),
        "pernas": len(pernas),
    }


# ---------------------------------------------------------------------------
# Secoes
# ---------------------------------------------------------------------------
def _linha(rotulo, n, greens, reds, lucro, largura=42):
    taxa = f"{greens / n * 100:5.1f}%" if n else "    --"
    roi = f"{lucro / n * 100:+6.1f}%" if n else "    --"
    print(f"  {rotulo:<{largura}} n={n:<4} green={greens:<4} red={reds:<4} "
          f"acerto={taxa}  ROI={roi}")


def _acumular(alvo, bilhete):
    res = (bilhete.get("result") or "").upper()
    alvo["n"] += 1
    alvo["g"] += 1 if res == "GREEN" else 0
    alvo["r"] += 1 if res == "RED" else 0
    alvo["lucro"] += _lucro(bilhete)


def _vazio():
    return {"n": 0, "g": 0, "r": 0, "lucro": 0.0}


def secao_portas(linhas):
    print("\n== O QUE CADA PORTA DA V2 TERIA CORTADO ==")
    print("   (um GREEN cortado e' o CUSTO da porta; um RED cortado e' o ganho)")
    por_porta = defaultdict(_vazio)
    mantidos = _vazio()
    total = _vazio()
    for bilhete, v2 in linhas:
        _acumular(total, bilhete)
        _acumular(mantidos if v2["decision"] == "PICK" else por_porta[v2["codigo"]],
                  bilhete)
    for codigo, d in sorted(por_porta.items(), key=lambda kv: -kv[1]["n"]):
        _linha(codigo, d["n"], d["g"], d["r"], d["lucro"])
    print("  " + "-" * 78)
    _linha("MANTIDOS PELA V2", mantidos["n"], mantidos["g"], mantidos["r"],
           mantidos["lucro"])
    _linha("V1 (todos)", total["n"], total["g"], total["r"], total["lucro"])


def secao_faixas(linhas):
    print("\n== FAIXA DE ODD TOTAL ==")
    print("   (a faixa da V2 e' 2.00-3.00; as linhas fora dela dizem o que ficou de fora)")
    faixas = defaultdict(_vazio)
    for bilhete, _ in linhas:
        odd = float(bilhete.get("total_odd") or 0)
        rotulo = "fora da faixa"
        for baixo, alto in mcfg.FAIXAS_DE_ODD:
            if baixo <= odd < alto:
                rotulo = f"{baixo:.2f}-{alto:.2f}"
                break
        else:
            rotulo = "< 2.00" if odd < 2.00 else "> 3.00"
        _acumular(faixas[rotulo], bilhete)
    for rotulo in sorted(faixas):
        d = faixas[rotulo]
        _linha(rotulo, d["n"], d["g"], d["r"], d["lucro"])


def secao_pernas(linhas):
    print("\n== NUMERO DE PERNAS ==")
    por_tamanho = defaultdict(_vazio)
    for bilhete, v2 in linhas:
        _acumular(por_tamanho[v2["pernas"]], bilhete)
    for tamanho in sorted(por_tamanho):
        d = por_tamanho[tamanho]
        _linha(f"{tamanho} pernas", d["n"], d["g"], d["r"], d["lucro"])


def secao_estrutura(linhas):
    print("\n== ESTRUTURA: quais combinacoes de mercado rendem ==")
    por_estrutura = defaultdict(_vazio)
    por_correlacao = defaultdict(_vazio)
    for bilhete, v2 in linhas:
        _acumular(por_estrutura["+".join(v2["familias"])], bilhete)
        _acumular(por_correlacao[v2["correlacao"] or "?"], bilhete)
    for rotulo, d in sorted(por_estrutura.items(), key=lambda kv: -kv[1]["n"]):
        _linha(rotulo, d["n"], d["g"], d["r"], d["lucro"])
    print("\n   por correlacao medida:")
    for rotulo, d in sorted(por_correlacao.items(), key=lambda kv: -kv[1]["n"]):
        _linha(rotulo, d["n"], d["g"], d["r"], d["lucro"])


def secao_calibracao(linhas):
    """O que o motor anuncia contra o que acontece. Overconfidence aparece
    aqui e em lugar nenhum mais: um bilhete de 70% que ganha 55% nao e' azar,
    e' probabilidade inflada."""
    print("\n== CALIBRACAO: probabilidade dita x taxa real ==")
    print("   (V1 = produto cru das pernas · V2 = produto calibrado e ajustado)")
    faixas = ((0.0, 0.35), (0.35, 0.45), (0.45, 0.55), (0.55, 0.70), (0.70, 1.01))
    for rotulo_fonte, chave in (("V1", None), ("V2", "probabilidade")):
        print(f"   {rotulo_fonte}:")
        for baixo, alto in faixas:
            n = greens = 0
            soma = 0.0
            for bilhete, v2 in linhas:
                p = (v2.get(chave) if chave
                     else bilhete.get("prob_combinada"))
                if p is None:
                    continue
                p = float(p)
                if not (baixo <= p < alto):
                    continue
                n += 1
                soma += p
                greens += 1 if (bilhete.get("result") or "").upper() == "GREEN" else 0
            if not n:
                continue
            dito = soma / n * 100
            real = greens / n * 100
            print(f"     {baixo:.2f}-{alto:.2f}  n={n:<4} dito={dito:5.1f}%  "
                  f"real={real:5.1f}%  erro={dito - real:+5.1f}pp")


def secao_volume(linhas):
    """Quantos bilhetes por dia, e o que cada posicao do dia rendeu. Responde
    "o segundo bilhete do dia vale a pena?" sem precisar supor."""
    print("\n== BILHETES POR DIA ==")
    por_dia = defaultdict(list)
    for bilhete, v2 in linhas:
        por_dia[bilhete["match_date"]].append((bilhete, v2))
    por_quantidade = defaultdict(_vazio)
    por_posicao = defaultdict(_vazio)
    for _dia, doDia in por_dia.items():
        for posicao, (bilhete, _v2) in enumerate(
                sorted(doDia, key=lambda b: b[0].get("created_at") or 0), start=1):
            _acumular(por_quantidade[len(doDia)], bilhete)
            _acumular(por_posicao[posicao], bilhete)
    for q in sorted(por_quantidade):
        d = por_quantidade[q]
        _linha(f"dias com {q} bilhete(s)", d["n"], d["g"], d["r"], d["lucro"])
    print("\n   por posicao no dia:")
    for p in sorted(por_posicao):
        d = por_posicao[p]
        _linha(f"bilhete #{p} do dia", d["n"], d["g"], d["r"], d["lucro"])


SECOES = {
    "portas": secao_portas,
    "faixas": secao_faixas,
    "pernas": secao_pernas,
    "estrutura": secao_estrutura,
    "calibracao": secao_calibracao,
    "volume": secao_volume,
}


def main():
    ap = argparse.ArgumentParser(
        description="Multipla: V1 contra V2 (somente leitura)")
    ap.add_argument("--dias", type=int, default=120)
    ap.add_argument("--secao", choices=sorted(SECOES), action="append")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, match_date, multipla_name, games AS legs, total_odd,
               prob_combinada, ev_combined, score_combo, result, profit, created_at
          FROM picks_multiplas
         WHERE result IS NOT NULL
           AND match_date >= CURRENT_DATE - %s::int
      ORDER BY match_date
    """, (args.dias,))
    colunas = [d[0] for d in cur.description]
    bilhetes = [dict(zip(colunas, r)) for r in cur.fetchall()]
    rastro = _rastro_do_dia(cur, args.dias)
    cur.close()
    conn.close()

    print(f"Multipla · backtest V1 x V2 · {len(bilhetes)} bilhete(s) liquidados "
          f"nos ultimos {args.dias} dias · {len(rastro)} candidato(s) no rastro")
    if not bilhetes:
        print("Sem bilhete liquidado no periodo. Nada a medir -- e isso NAO e' "
              "um resultado a favor nem contra a V2.")
        return

    linhas, sem_rastro = [], 0
    for b in bilhetes:
        v2 = reprocessar(b, rastro)
        if v2 is None:
            sem_rastro += 1
            continue
        linhas.append((b, v2))
    print(f"{len(linhas)} reprocessados · {sem_rastro} sem rastro suficiente")
    if not linhas:
        return

    for nome in (args.secao or list(SECOES)):
        SECOES[nome](linhas)

    print("\nLEIA O CORTE COMO PISO: data quality, risco e projecao nao foram "
          "gravados nestes bilhetes e entram neutros. A V2 real corta pelo "
          "menos o que esta' acima, e provavelmente mais.")
    print("E um GREEN cortado nao prova que a porta esta' errada, nem um RED "
          "mantido que ela esta' certa: a pergunta e' se a evidencia do dia "
          "sustentava a aposta.")


if __name__ == "__main__":
    main()
