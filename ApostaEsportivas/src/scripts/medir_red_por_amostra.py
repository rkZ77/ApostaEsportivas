"""medir_red_por_amostra.py · o RED subiu: e' a amostra curta ou e' outra coisa.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD.

Uso:
  DB_ENV=prod python src/scripts/medir_red_por_amostra.py
  DB_ENV=prod python src/scripts/medir_red_por_amostra.py --desde 2026-08-01
  DB_ENV=prod python src/scripts/medir_red_por_amostra.py --produto vip

A PERGUNTA
----------
"O RED aumentou por pouco historico de time?" Sao tres perguntas, e o erro
seria responder a segunda sem responder a primeira:

  1. O RED aumentou MESMO, e em QUAL produto? Um mes ruim num produto de 8
     picks nao e' o motor piorando, e' variancia. PARTE A separa isso.
  2. A amostra explica? Amostra curta so' e' causa se os picks de amostra
     curta perderem mais dinheiro QUE os de amostra longa, na mesma janela --
     e se o volume de amostra curta tiver crescido junto. PARTE B mede as
     duas metades.
  3. Se nao for a amostra, e' o que? PARTE C corre os confundidores que o
     projeto ja' viu darem as caras: familia x DIRECAO (o erro mora em Over
     ou em Under, nunca na familia inteira -- medicao de 15/09), faixa de odd,
     liga, rodada da temporada e tipo de competicao.

POR QUE A AMOSTRA E' SUSPEITA LEGITIMA AQUI
-------------------------------------------
`config.min_amostra` e' 4 desde 28/08 (decisao do usuario: "na 5a rodada ele
gera"), e 4 e' conferido DEPOIS do filtro de mando e DEPOIS de tirar os push.
Ao mesmo tempo `confidence._AMOSTRA_INSUFICIENTE` e' 5 -- ou seja, o proprio
motor classifica como "sem estimativa, so' ruido" uma amostra que o gate
aprova. Em setembro as ligas europeias estao na 4a-6a rodada, entao a fatia de
pick nascido no piso e' a maior do ano. Isso torna a hipotese plausivel; nao a
torna medida. Este script mede.

DE ONDE SAI CADA NUMERO
-----------------------
  · resultado e dinheiro: `picks_ledger`, uma linha por PERNA -- e' a
    granularidade certa, porque o RED de uma multipla nasce numa perna so';
  · a amostra: `engine_decisions`, candidato `is_best_pick`, campo `amostra`.
    E' o n que PASSOU no gate, gravado na hora da decisao. Nao e' consulta
    nova: a consulta refeita ja' divergiu da que decidiu duas vezes (ver
    services/engine_audit/amostra.py).

CUIDADO DE LEITURA JA' CONHECIDO
--------------------------------
`amostra.do_time().jogos_lidos` passou a ser filtrado por mando em 15/09, e
quem comparar esse campo antes e depois da data compara duas definicoes. Este
script NAO usa jogos_lidos por isso: usa `candidates[].amostra`, que sempre foi
o n pos-filtro do candidato.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

# O `src/` do motor NUNCA na frente do sys.path: ele tem um main.py proprio e
# sombreia o do site quando os dois coexistem no mesmo processo (2026-09-04).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

PUSHES = ("PUSH", "VOID", "ANULADO")
MEIO_GREEN = ("HALF-WIN", "HALF_WIN", "MEIO_GREEN")


def n_da_amostra(valor):
    """O n inteiro, ou None quando a linha nao tem n de verdade.

    `_candidate_summary` (engine_pipelines/decision_log.py) grava
    `c.get("amostra", c.get("faixa_amostra"))`, e cada motor chama de
    "amostra" uma coisa diferente: VIP/Free/Multipla/Alavancagem/Bingo gravam
    o inteiro do pool, e o FALTAS grava o BLOCO da amostra
    (services/engine_audit/amostra.py -- mandante/visitante com a lista de
    jogos). Ler os dois como numero estourava a PARTE B inteira.

    Do bloco dai' pra tirar o n: `jogos_lidos` de cada lado, ja' filtrado por
    mando desde 15/09. Nao e' a mesma grandeza que o pool de um mercado de
    lado, entao o menor dos dois lados e' a leitura conservadora -- e' o time
    com menos historico que limita a estimativa.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    if isinstance(valor, dict):
        lidos = [(valor.get(lado) or {}).get("jogos_lidos")
                 for lado in ("mandante", "visitante")]
        lidos = [int(x) for x in lidos if isinstance(x, (int, float))]
        return min(lidos) if lidos else None
    return None


def faixa_de_amostra(n) -> str:
    """Os cortes nao sao escolhidos aqui: 5 e' onde
    `confidence._AMOSTRA_INSUFICIENTE` diz que nao ha' estimativa, e 8 e'
    `config.sample_rich_n`, onde o motor passa a dar Q=1.00. Medir nos mesmos
    cortes que o motor usa e' o que permite mexer num deles depois com base
    nisto, em vez de chutar numero novo."""
    if n is None:
        return "sem registro"
    n = int(n)
    if n < 5:
        return "4 ou menos (piso)"
    if n < 8:
        return "5 a 7 (limitada)"
    if n < 14:
        return "8 a 13 (rica)"
    return "14+ (rica longa)"


def taxa_e_lucro(linhas: list) -> tuple:
    """A conta oficial do projeto: (greens + meios) / (total - push).

    Ela mora num lugar so' de proposito -- Home e Resultados ja' divergiram em
    3pp sobre a mesma base por terem cada uma a sua (12/09).
    """
    total = len(linhas)
    push = sum(1 for p in linhas if p["result"] in PUSHES)
    green = sum(1 for p in linhas if p["result"] == "GREEN")
    meio = sum(1 for p in linhas if p["result"] in MEIO_GREEN)
    red = sum(1 for p in linhas if p["result"] == "RED")
    base = total - push
    taxa = (green + meio * 0.5) / base if base else None
    lucro = sum(float(p["profit"] or 0) for p in linhas)
    return total, push, red, taxa, lucro


def bloco(titulo: str, grupos: dict, minimo: int = 1) -> None:
    if titulo:
        print(f"\n{titulo}")
    print(f"  {'grupo':<32} {'pernas':>6} {'push':>5} {'red':>5} {'taxa':>7} {'lucro(u)':>9}")
    for chave in sorted(grupos, key=lambda k: str(k)):
        total, push, red, taxa, lucro = taxa_e_lucro(grupos[chave])
        if total < minimo:
            continue
        rotulo = "-" if taxa is None else f"{taxa * 100:5.1f}%"
        print(f"  {str(chave):<32} {total:>6} {push:>5} {red:>5} {rotulo:>7} {lucro:>+9.2f}")


# ─────────────────────────────────────────────────────────────
# Leitura
# ─────────────────────────────────────────────────────────────

def ler_pernas(cur, desde: str | None, produto: str | None) -> list:
    filtros = ["result IS NOT NULL", "match_date IS NOT NULL"]
    params = []
    if desde:
        filtros.append("match_date >= %s")
        params.append(desde)
    if produto:
        filtros.append("pick_type = %s")
        params.append(produto)
    cur.execute(f"""
        SELECT source_table, source_id, leg_number, pick_type, match_date,
               league_id, market, market_type, line, odd, odd_band,
               confidence, probability, ev, result, profit,
               competition_type, round_phase, round_label
          FROM picks_ledger
         WHERE {' AND '.join(filtros)}
         ORDER BY match_date
    """, params)
    colunas = [d[0] for d in cur.description]
    return [dict(zip(colunas, r)) for r in cur.fetchall()]


def ler_amostra_das_decisoes(cur, desde: str | None) -> dict:
    """(pick_table, pick_id) -> {amostra, confidence, taxa_real, market_type}.

    Le o candidato `is_best_pick` de cada decisao ja' ligada ao pick. Decisao
    sem elo (anterior a 28/08, ou nao preenchida por
    scripts/vincular_decisao_ao_pick.py) nao aparece -- e a PARTE B conta essas
    pernas como "sem registro" em vez de fingir um n.
    """
    filtro = "AND match_date >= %s" if desde else ""
    params = (desde,) if desde else ()
    cur.execute(f"""
        SELECT pick_table, pick_id, candidates
          FROM engine_decisions
         WHERE pick_table IS NOT NULL
           AND pick_id IS NOT NULL
           AND candidates IS NOT NULL
           {filtro}
    """, params)
    mapa = {}
    for tabela, pick_id, candidatos in cur.fetchall():
        if isinstance(candidatos, str):
            try:
                candidatos = json.loads(candidatos)
            except ValueError:
                continue
        escolhido = next((c for c in (candidatos or []) if c.get("is_best_pick")), None)
        if escolhido is None:
            # Produto de um pick so' por partida: quando o motor nao marcou o
            # melhor, o unico elegivel e' o escolhido. Mais de um elegivel sem
            # marca e' ambiguo, e ambiguo fica fora.
            elegiveis = [c for c in (candidatos or []) if c.get("eligible")]
            if len(elegiveis) == 1:
                escolhido = elegiveis[0]
        if escolhido is None:
            continue
        mapa[(tabela, int(pick_id))] = {
            "amostra": n_da_amostra(escolhido.get("amostra")),
            "confidence": escolhido.get("confidence"),
            "taxa_real": escolhido.get("taxa_real"),
            "market_type": escolhido.get("market_type"),
        }
    return mapa


# ─────────────────────────────────────────────────────────────
# PARTE A · a curva
# ─────────────────────────────────────────────────────────────

def _semana(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def parte_a(pernas: list) -> None:
    print("\n" + "=" * 78)
    print("PARTE A · o RED subiu? onde?")
    print("=" * 78)
    print("Semana = segunda a domingo da data do JOGO. `red` conta pernas RED.")

    por_semana = defaultdict(list)
    por_produto = defaultdict(list)
    por_semana_produto = defaultdict(list)
    for p in pernas:
        s = _semana(p["match_date"])
        por_semana[s].append(p)
        por_produto[p["pick_type"] or "?"].append(p)
        por_semana_produto[(p["pick_type"] or "?", s)].append(p)

    bloco("Todos os produtos, por semana", por_semana)
    bloco("Por produto, na janela inteira", por_produto)

    print("\nPor produto e semana (so' semanas com 5+ pernas do produto)")
    print(f"  {'produto':<14}{'semana':<12} {'pernas':>6} {'red':>5} {'taxa':>7} {'lucro(u)':>9}")
    for chave in sorted(por_semana_produto):
        linhas = por_semana_produto[chave]
        total, push, red, taxa, lucro = taxa_e_lucro(linhas)
        if total < 5:
            continue
        rotulo = "-" if taxa is None else f"{taxa * 100:5.1f}%"
        print(f"  {chave[0]:<14}{chave[1]:<12} {total:>6} {red:>5} {rotulo:>7} {lucro:>+9.2f}")


# ─────────────────────────────────────────────────────────────
# PARTE B · a amostra
# ─────────────────────────────────────────────────────────────

def parte_b(pernas: list, amostras: dict) -> None:
    print("\n" + "=" * 78)
    print("PARTE B · a amostra que decidiu explica o RED?")
    print("=" * 78)
    print("`amostra` = n do candidato is_best_pick em engine_decisions (pos-filtro")
    print("de mando, pos-remocao de push). Nao e' consulta nova.")

    com_registro = []
    for p in pernas:
        reg = amostras.get((p["source_table"], int(p["source_id"]))) or {}
        p["_amostra"] = reg.get("amostra")
        p["_conf_decisao"] = reg.get("confidence")
        if p["_amostra"] is not None:
            com_registro.append(p)

    cobertura = len(com_registro) / len(pernas) * 100 if pernas else 0
    print(f"\n  Cobertura: {len(com_registro)} de {len(pernas)} pernas com amostra"
          f" gravada ({cobertura:.0f}%).")
    if not com_registro:
        print("  Sem amostra gravada na janela. Rode scripts/vincular_decisao_ao_pick.py")
        print("  ou encurte a janela com --desde. PARTE B para aqui.")
        return

    por_faixa = defaultdict(list)
    por_produto_faixa = defaultdict(list)
    for p in com_registro:
        faixa = faixa_de_amostra(p["_amostra"])
        por_faixa[faixa].append(p)
        por_produto_faixa[f"{p['pick_type']} · {faixa}"].append(p)
    bloco("Desempenho por faixa de amostra", por_faixa)
    bloco("Por produto e faixa (5+ pernas)", por_produto_faixa, minimo=5)

    # A segunda metade da pergunta: a fatia de amostra curta CRESCEU?
    print("\nFatia de pick nascido no piso, por semana")
    print("  (taxa caindo nas semanas em que a fatia sobe = a amostra e' causa;")
    print("   fatia estavel com taxa caindo = a causa e' outra)")
    print(f"  {'semana':<12} {'pernas':>6} {'n<5':>6} {'n<8':>6} {'n medio':>8} {'taxa':>7} {'lucro(u)':>9}")
    por_semana = defaultdict(list)
    for p in com_registro:
        por_semana[_semana(p["match_date"])].append(p)
    for s in sorted(por_semana):
        linhas = por_semana[s]
        total, push, red, taxa, lucro = taxa_e_lucro(linhas)
        curtas = sum(1 for p in linhas if int(p["_amostra"]) < 5)
        limitadas = sum(1 for p in linhas if int(p["_amostra"]) < 8)
        media = sum(int(p["_amostra"]) for p in linhas) / len(linhas)
        rotulo = "-" if taxa is None else f"{taxa * 100:5.1f}%"
        print(f"  {s:<12} {total:>6} {curtas:>6} {limitadas:>6} {media:>8.1f}"
              f" {rotulo:>7} {lucro:>+9.2f}")

    # O cruzamento que separa "amostra curta" de "confianca mal cobrada": o
    # caso ruim e' o pick de n<5 que ainda assim saiu com confidence alta, ou
    # seja, o desconto de amostra nao chegou a doer.
    curtas = [p for p in com_registro if int(p["_amostra"]) < 5]
    if curtas:
        faixas_conf = defaultdict(list)
        for p in curtas:
            conf = p["_conf_decisao"] if p["_conf_decisao"] is not None else p["confidence"]
            if conf is None:
                faixas_conf["conf sem registro"].append(p)
                continue
            conf = float(conf)
            rotulo = "<0.60" if conf < 0.60 else "0.60-0.69" if conf < 0.70 else "0.70+"
            faixas_conf[f"conf {rotulo}"].append(p)
        bloco("Amostra no piso (n<5) x confianca publicada", faixas_conf)


# ─────────────────────────────────────────────────────────────
# PARTE C · os confundidores
# ─────────────────────────────────────────────────────────────

def _direcao(line: str | None) -> str:
    if not line:
        return "?"
    t = line.lower()
    if "mais de" in t or "over" in t or "acima" in t:
        return "Over"
    if "menos de" in t or "under" in t or "abaixo" in t:
        return "Under"
    if t.strip() in ("yes", "sim"):
        return "Sim"
    if t.strip() in ("no", "nao", "não"):
        return "Nao"
    return "outro"


def _rodada(round_label: str | None):
    """O numero da rodada, quando a API escreveu um ("Regular Season - 12")."""
    if not round_label:
        return None
    for pedaco in round_label.replace("-", " ").split():
        if pedaco.isdigit():
            return int(pedaco)
    return None


def parte_c(pernas: list) -> None:
    print("\n" + "=" * 78)
    print("PARTE C · e se nao for a amostra")
    print("=" * 78)

    por_familia_direcao = defaultdict(list)
    por_odd = defaultdict(list)
    por_liga = defaultdict(list)
    por_rodada = defaultdict(list)
    por_competicao = defaultdict(list)
    for p in pernas:
        por_familia_direcao[f"{p['market_type'] or '?'} · {_direcao(p['line'])}"].append(p)
        por_odd[p["odd_band"] or "sem faixa"].append(p)
        por_liga[p["league_id"]].append(p)
        por_competicao[p["competition_type"] or "?"].append(p)
        r = _rodada(p["round_label"])
        if r is not None:
            por_rodada["rodada 1-5" if r <= 5 else "rodada 6-10" if r <= 10
                       else "rodada 11-20" if r <= 20 else "rodada 21+"].append(p)

    bloco("Familia x direcao (5+ pernas): o erro mora numa direcao, nao na familia",
          por_familia_direcao, minimo=5)
    bloco("Faixa de odd", por_odd)
    bloco("Tipo de competicao", por_competicao)
    bloco("Rodada da temporada (proxy de quanto historico existia)", por_rodada)
    bloco("Ligas com 8+ pernas", por_liga, minimo=8)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", help="data minima do jogo (YYYY-MM-DD)")
    ap.add_argument("--produto", help="filtra um pick_type do ledger (vip, free, multipla...)")
    args = ap.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        pernas = ler_pernas(cur, args.desde, args.produto)
        if not pernas:
            print("Nenhuma perna liquidada na janela.")
            return
        print(f"{len(pernas)} perna(s) liquidada(s) de "
              f"{pernas[0]['match_date']} a {pernas[-1]['match_date']}.")
        amostras = ler_amostra_das_decisoes(cur, args.desde)
        parte_a(pernas)
        parte_b(pernas, amostras)
        parte_c(pernas)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
