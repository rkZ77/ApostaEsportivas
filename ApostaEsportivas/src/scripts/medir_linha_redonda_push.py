"""
medir_linha_redonda_push.py · o que o PUSH faz com a amostra, com a
probabilidade publicada e com o dinheiro, na serie real.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD sem
efeito colateral.

Uso:
  DB_ENV=prod python src/scripts/medir_linha_redonda_push.py
  DB_ENV=prod python src/scripts/medir_linha_redonda_push.py --desde 2026-07-01
  DB_ENV=prod python src/scripts/medir_linha_redonda_push.py --familia goals

POR QUE PRECISOU DE SCRIPT
--------------------------
O pick Free de 15/09/2026 (CRB x Sport Recife, "Gols Menos de 3.0" @1.56)
publicou 74,1% de probabilidade sobre um card que mostrava o mercado batendo
30% nos ultimos 10 jogos do mandante e 50% nos do visitante. Os dois numeros
estao certos e medem coisas diferentes:

  · o MOTOR joga o jogo empatado com a linha fora da amostra
    (stats_model.weighted_rate, correcao de 2026-07-25) e publica a
    probabilidade CONDICIONAL a nao dar push
    (probability_model.poisson_prob_for_line);
  · o CARD do site conta o push no DENOMINADOR e nunca como verde
    (website/backend/market_form.py::resumo).

Pra o EV a convencao do motor e' a correta: numa linha com devolucao, o
break-even e' 1/odd em termos condicionais, entao comparar 74,1% com os 64,1%
implicitos na odd e comparar duas coisas da mesma especie. O que NAO esta
resolvido sao duas consequencias praticas:

  1. A AMOSTRA ENCOLHE EM SILENCIO. `config.min_amostra` e' 4, e ele e' conferido
     DEPOIS de tirar os pushes. Numa linha redonda de gols, onde o empate exato
     com a linha e' o resultado mais provavel da distribuicao, isso pode deixar
     um pick publicado apoiado em 5 ou 6 jogos sem que nada na tela diga isso.
  2. A TELA SE CONTRADIZ. O assinante ve uma probabilidade alta em cima de uma
     serie que parece ruim, e nao ha' texto nenhum explicando a diferenca.

NAO HA' NUMERO SUGERIDO NO FIM DESTE ARQUIVO, de proposito. O metodo e' o mesmo
do piso de amostra de 10/09 e dos limiares do Player Stats: reamostrar a serie
real e escolher o corte olhando volume e acerto juntos. Chutar um `min_amostra`
maior pra linha redonda sem medicao e' repetir o erro do `min_confidence` 0.72.

O QUE ELE FAZ
-------------
PARTE A · o dinheiro. Picks ja liquidados, separados por tipo de linha (redonda
x.0 contra meia x.5), por produto e por familia: quantos sairam, quantos deram
PUSH, taxa de acerto na conta oficial do projeto -- (greens + half wins) /
(total - push) -- e lucro em unidades. E' a parte que responde se existe
problema: se a linha redonda ganha dinheiro, o resto e' transparencia de tela.

PARTE B · o encolhimento. Pra cada pick de linha redonda, quantos dos jogos que
o motor LEU empataram exato com a linha. Sai da amostra gravada no
`engine_debug` (services/engine_audit/amostra.py) e nao de uma consulta nova --
a consulta refeita ja' divergiu da que decidiu duas vezes. A amostra gravada
tem teto de 10 jogos por time, entao o que se mede aqui e' a FRACAO de push,
aplicada ao `jogos_lidos` real pra estimar a amostra efetiva.

PARTE C · a contradicao da tela. Pra os mesmos picks, a taxa que o card teria
mostrado (push no denominador) contra a probabilidade publicada. A distribuicao
dessa distancia e' o tamanho do problema de confianca, separado do problema de
acerto.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

# O `src/` do motor NUNCA na frente do sys.path: ele tem um main.py proprio e
# sombreia o do site quando os dois coexistem no mesmo processo (2026-09-04).
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_utils import get_connection  # noqa: E402

#: De onde vem cada produto. A Free e o VIP sao os dois que o motor Pre Live
#: publica como pick simples com linha propria -- multipla/alavancagem guardam
#: as pernas em outra tabela e ficam fora desta medicao.
PRODUTOS = (
    ("VIP",  "picks_vip",  "probability"),
    ("Free", "picks_free", "prob_real"),
)

#: Contador da amostra gravada que corresponde a cada familia de mercado. A
#: amostra guarda os contadores de todas as familias por jogo (ver
#: engine_audit/amostra.py::_linha_do_jogo), entao nao ha' leitura nova aqui.
CONTADOR_DA_FAMILIA = {
    "goals": "gols_total",
    "corners": "escanteios_total",
    "cards": "cartoes_total",
}


def _linha_numerica(line: str | None) -> float | None:
    """O numero da linha, ou None quando o mercado nao tem linha (btts,
    resultado, dupla chance). Aceita 'Menos de 3.0', 'Under 3', 'Over 2.5'."""
    if not line:
        return None
    texto = line.replace(",", ".")
    numero = ""
    for pedaco in texto.split():
        limpo = pedaco.strip("()+")
        try:
            float(limpo)
        except ValueError:
            continue
        numero = limpo
    if not numero:
        return None
    try:
        return float(numero)
    except ValueError:
        return None


def _e_redonda(valor: float | None) -> bool:
    return valor is not None and valor % 1 == 0


def _buscar(cur, tabela: str, col_prob: str, desde: str | None) -> list:
    filtro_data = "AND match_date >= %s" if desde else ""
    params = (desde,) if desde else ()
    cur.execute(f"""
        SELECT fixture_id, match_date, market_type, line, odd,
               {col_prob} AS prob, result, profit, engine_debug
          FROM {tabela}
         WHERE result IS NOT NULL
           {filtro_data}
         ORDER BY match_date
    """, params)
    colunas = [d[0] for d in cur.description]
    return [dict(zip(colunas, r)) for r in cur.fetchall()]


def _taxa_de_acerto(linhas: list) -> tuple:
    """A conta oficial do projeto: (greens + half wins) / (total - push).

    Ela mora em um lugar so' de proposito -- a Home e a pagina de Resultados
    ja' divergiram em 3pp sobre a mesma base por terem cada uma a sua (12/09).
    """
    total = len(linhas)
    push = sum(1 for p in linhas if p["result"] in ("PUSH", "VOID", "ANULADO"))
    green = sum(1 for p in linhas if p["result"] == "GREEN")
    meio = sum(1 for p in linhas if p["result"] in ("HALF_WIN", "MEIO_GREEN"))
    base = total - push
    taxa = (green + meio * 0.5) / base if base else None
    lucro = sum(float(p["profit"] or 0) for p in linhas)
    return total, push, taxa, lucro


def _imprimir_bloco(titulo: str, grupos: dict) -> None:
    print(f"\n{titulo}")
    print(f"  {'grupo':<28} {'picks':>6} {'push':>5} {'taxa':>7} {'lucro(u)':>9}")
    for chave in sorted(grupos):
        total, push, taxa, lucro = _taxa_de_acerto(grupos[chave])
        rotulo = "-" if taxa is None else f"{taxa * 100:5.1f}%"
        print(f"  {chave:<28} {total:>6} {push:>5} {rotulo:>7} {lucro:>+9.2f}")


def parte_a(picks: list) -> None:
    print("\n" + "=" * 72)
    print("PARTE A · desempenho por tipo de linha")
    print("=" * 72)
    print("A pergunta: linha redonda perde dinheiro, ou so' assusta na tela?")

    por_tipo = defaultdict(list)
    por_produto = defaultdict(list)
    por_familia = defaultdict(list)
    for p in picks:
        tipo = "redonda (x.0)" if p["_redonda"] else "meia (x.5)"
        por_tipo[tipo].append(p)
        por_produto[f"{p['_produto']} · {tipo}"].append(p)
        if p["_redonda"]:
            por_familia[f"{p['market_type']} · redonda"].append(p)

    _imprimir_bloco("Todos os produtos", por_tipo)
    _imprimir_bloco("Por produto", por_produto)
    _imprimir_bloco("So' as redondas, por familia", por_familia)


def _fracao_de_push(pick: dict) -> tuple | None:
    """(jogos_lidos, jogos_na_amostra, empates_exatos) da amostra gravada.

    None quando o pick e' anterior a amostra (27/08/2026), quando a familia nao
    tem contador gravado, ou quando os jogos vieram sem o contador -- estatistica
    ausente nunca vira zero aqui, pelo mesmo motivo que em market_form.py.
    """
    debug = pick.get("engine_debug")
    if isinstance(debug, str):
        try:
            debug = json.loads(debug)
        except ValueError:
            return None
    amostra = (debug or {}).get("amostra")
    if not amostra:
        return None
    contador = CONTADOR_DA_FAMILIA.get(pick["market_type"])
    if not contador:
        return None

    lidos = exibidos = empates = 0
    for lado in ("mandante", "visitante"):
        bloco = amostra.get(lado) or {}
        lidos += bloco.get("jogos_lidos") or 0
        for jogo in bloco.get("jogos") or []:
            valor = jogo.get(contador)
            if valor is None:
                continue
            exibidos += 1
            if float(valor) == pick["_linha"]:
                empates += 1
    if not exibidos:
        return None
    return lidos, exibidos, empates


def parte_b(picks: list) -> None:
    print("\n" + "=" * 72)
    print("PARTE B · quanto o push encolheu a amostra")
    print("=" * 72)
    print("A amostra e' a GRAVADA no pick (teto de 10 por time), nunca uma")
    print("consulta nova. `efetiva` estima jogos_lidos x (1 - fracao de push).")

    medidos = []
    for p in picks:
        if not p["_redonda"]:
            continue
        leitura = _fracao_de_push(p)
        if leitura is None:
            continue
        lidos, exibidos, empates = leitura
        fracao = empates / exibidos
        medidos.append({**p, "_lidos": lidos, "_exibidos": exibidos,
                        "_empates": empates, "_fracao_push": fracao,
                        "_efetiva": lidos * (1 - fracao)})

    if not medidos:
        print("\n  Nenhum pick de linha redonda com amostra gravada no periodo.")
        print("  (A amostra so' existe em picks de 27/08/2026 em diante.)")
        return

    print(f"\n  {len(medidos)} pick(s) de linha redonda com amostra gravada.")
    media = sum(m["_fracao_push"] for m in medidos) / len(medidos)
    print(f"  Fracao media de jogos que empataram exato com a linha: {media * 100:.1f}%")

    faixas = defaultdict(list)
    for m in medidos:
        efetiva = m["_efetiva"]
        if efetiva < 6:
            faixas["efetiva < 6"].append(m)
        elif efetiva < 10:
            faixas["efetiva 6 a 9"].append(m)
        elif efetiva < 16:
            faixas["efetiva 10 a 15"].append(m)
        else:
            faixas["efetiva 16+"].append(m)
    _imprimir_bloco("Acerto por amostra efetiva estimada", faixas)

    print("\n  Os dez com a maior fracao de push:")
    print(f"  {'data':<12} {'familia':<10} {'linha':>7} {'push/amostra':>13} "
          f"{'lidos':>6} {'efetiva':>8} {'result':>7}")
    for m in sorted(medidos, key=lambda x: -x["_fracao_push"])[:10]:
        print(f"  {str(m['match_date']):<12} {m['market_type']:<10} "
              f"{m['_linha']:>7.1f} {m['_empates']:>5}/{m['_exibidos']:<7} "
              f"{m['_lidos']:>6} {m['_efetiva']:>8.1f} {str(m['result']):>7}")


def parte_c(picks: list) -> None:
    print("\n" + "=" * 72)
    print("PARTE C · a distancia entre o card e a probabilidade publicada")
    print("=" * 72)
    print("`card` = verdes / (jogos com dado), push no denominador, que e' o")
    print("que website/backend/market_form.py mostra. `pub` = o que o pick diz.")

    linhas = []
    for p in picks:
        if not p["_redonda"] or p["prob"] is None:
            continue
        leitura = _fracao_de_push(p)
        if leitura is None:
            continue
        # A taxa do card nao da' pra reconstruir sem reliquidar jogo a jogo, mas
        # o TETO dela da': mesmo que todo jogo nao empatado tivesse batido, o
        # push ja' consome (empates/exibidos) do denominador. A distancia contra
        # esse teto e' o piso da contradicao, nunca um numero inflado.
        _, exibidos, empates = leitura
        teto_do_card = (exibidos - empates) / exibidos
        linhas.append((p, teto_do_card, float(p["prob"]) - teto_do_card))

    if not linhas:
        print("\n  Nenhum pick de linha redonda com amostra e probabilidade no periodo.")
        return

    acima = [l for l in linhas if l[2] > 0]
    print(f"\n  {len(linhas)} pick(s) medidos · em {len(acima)} deles a probabilidade")
    print(f"  publicada esta ACIMA do teto do card (contradicao visivel na tela).")
    if acima:
        media = sum(l[2] for l in acima) / len(acima)
        print(f"  Distancia media nesses casos: {media * 100:.1f}pp")
        print(f"\n  {'data':<12} {'familia':<10} {'linha':>7} {'teto card':>10} "
              f"{'publicada':>10} {'distancia':>10} {'result':>7}")
        for p, teto, dist in sorted(acima, key=lambda x: -x[2])[:10]:
            print(f"  {str(p['match_date']):<12} {p['market_type']:<10} "
                  f"{p['_linha']:>7.1f} {teto * 100:>9.1f}% "
                  f"{float(p['prob']) * 100:>9.1f}% {dist * 100:>+9.1f}pp "
                  f"{str(p['result']):>7}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desde", help="data inicial (AAAA-MM-DD)")
    parser.add_argument("--familia", help="so' esta familia de mercado (ex: goals)")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    picks = []
    for produto, tabela, col_prob in PRODUTOS:
        for p in _buscar(cur, tabela, col_prob, args.desde):
            valor = _linha_numerica(p["line"])
            if valor is None:
                continue  # mercado sem linha: btts, resultado, dupla chance
            if args.familia and p["market_type"] != args.familia:
                continue
            picks.append({**p, "_produto": produto, "_linha": valor,
                          "_redonda": _e_redonda(valor)})

    cur.close()
    conn.close()

    if not picks:
        print("Nenhum pick liquidado com linha numerica no periodo.")
        return

    redondas = sum(1 for p in picks if p["_redonda"])
    print(f"{len(picks)} pick(s) liquidados com linha numerica · "
          f"{redondas} em linha redonda ({redondas / len(picks) * 100:.1f}%)")

    parte_a(picks)
    parte_b(picks)
    parte_c(picks)

    print("\n" + "=" * 72)
    print("Nenhum limiar foi escolhido aqui. Com a Parte A na mao da' pra saber")
    print("se o corte precisa existir; com a Parte B, onde ele cai sem matar o")
    print("volume; com a Parte C, se o problema tambem e' de texto na tela.")
    print("=" * 72)


if __name__ == "__main__":
    main()
