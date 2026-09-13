"""
medir_limiares_player_stats.py · o PROB_MINIMA e o EDGE_MINIMO do motor de
jogador, reamostrados na serie real em vez de escolhidos.

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD sem
efeito colateral.

Uso:
  DB_ENV=prod python src/scripts/medir_limiares_player_stats.py
  DB_ENV=prod python src/scripts/medir_limiares_player_stats.py --metodo shots_on

POR QUE PRECISOU DE SCRIPT
--------------------------
`config.PROB_MINIMA` (0.62) e `config.EDGE_MINIMO` (0.04) foram escolhidos
quando a media dos contadores estava INFLADA. Em 2026-09-03 o commit 89ad5bd7
descobriu que a API-Football OMITE o contador em vez de escrever zero, e que o
motor lia o historico com `AND coluna IS NOT NULL` -- ou seja, ficava so' com as
atuacoes em que o jogador chutou. A correcao e o backfill (19.996 linhas em
PROD) derrubaram a media de chute no alvo de jogador de linha de 1.285 pra
0.375.

Os limiares nao foram remedidos depois disso. Com a media real e o phi medido,
`PROB_MINIMA` de 62% exige media perto de 1.2 numa populacao cuja media e' 0.35,
e o `EDGE_MINIMO` de 4% cobra, em cima disso, uma odd acima da que a casa paga
pelo mesmo evento. A janela em que os dois cortes se satisfazem ao mesmo tempo
pode ter fechado -- e isso e' pergunta de medicao, nao de opiniao.

O metodo e' o mesmo do piso de amostra em 10/09: reamostrar a serie real. Nao
ha' numero sugerido no fim deste arquivo de proposito. O que ele imprime e' a
tabela que permite ESCOLHER o numero olhando volume e acerto real juntos.

O QUE ELE FAZ
-------------
Caminhada pra frente, sem olhar o futuro. Pra cada atuacao do jogador, na ordem
cronologica:

  1. monta a serie com as atuacoes ANTERIORES (mesmo recorte de competicao,
     mesmo filtro de 60 minutos e mesmo limite de leitura do motor);
  2. exige o piso de amostra do metodo, como o motor exige;
  3. projeta com `count_model.analisar` -- a mesma media ponderada, o mesmo
     ajuste de mando e o mesmo phi medido na base;
  4. compara a probabilidade projetada com o que ACONTECEU naquela atuacao.

PARTE A: calibragem. A probabilidade projetada bate com a frequencia real, por
faixa? E' a pergunta que decide se o corte pode ser baixado: um piso alto sobre
um modelo bem calibrado so' corta volume; sobre um modelo otimista, ele e' a
unica coisa segurando o prejuizo.

PARTE B: o funil dos limiares. Pra cada piso de probabilidade candidato, quanto
volume sobra e qual o acerto real do que sobrou.

PARTE C: o aperto do edge. Usa as odds que existem em `odds_values` pras mesmas
fixtures, quando existem, e mostra quantos dos candidatos que passam no piso de
probabilidade ainda passam no piso de edge. E' onde se ve' se o motor esta'
morrendo de probabilidade ou de preco.

    ATENCAO: `odds_values` E' SNAPSHOT, NAO HISTORICO (medido em PROD,
    2026-09-13: 7.249 linhas, todas do MESMO dia, 2 fixtures). A coleta
    sobrescreve. Entao a Parte C so' tem o que casar quando a janela da
    caminhada alcanca o dia que esta' gravado agora -- no resto ela imprime
    "nenhuma atuacao casou" e isso NAO quer dizer que a casa nao cotou.

    Pra medir o edge de verdade e' preciso acumular: ou `odds_snapshot_service`
    passa a guardar prop de jogador, ou a Parte C roda todo dia sobre o dia
    corrente e alguem soma. Mesma limitacao que o CLV ja' tinha.

O QUE ELE NAO FAZ
-----------------
Nao mede titularidade, minutos, qualidade do dado nem contradicao. Aquelas
camadas reprovam ANTES e sao de outra natureza (elas perguntam se o numero quer
dizer alguma coisa, nao se ele paga). Misturar as duas perguntas numa tabela so'
foi justamente o que escondeu este problema por nove dias.
"""
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from services.player_stats_engine import config as cfg
from services.player_stats_engine import count_model
from services.player_stats_engine import methods as cat
from services.player_stats_engine import player_history
from utils.db_utils import get_connection, linhas_dict

#: Ate' onde a caminhada volta. Uma temporada inteira e' o suficiente pra ter
#: volume e nao arrasta um regime de coleta anterior ao backfill de 03/09 --
#: que e' justamente o dado que este script NAO pode usar como referencia.
DIAS = 240

#: As linhas que a casa publica nestes mercados. Nao vem do banco de proposito:
#: o que se quer medir e' o modelo, e amarrar a medicao na oferta do dia
#: misturaria "o modelo erra" com "a casa nao ofereceu".
LINHAS = (0.5, 1.5, 2.5)

#: Pisos de probabilidade varridos na Parte B. O atual (0.62) esta' no meio de
#: proposito, pra a tabela mostrar os dois lados dele.
PISOS = (0.50, 0.54, 0.56, 0.58, 0.60, 0.62, 0.65, 0.70, 0.75)

#: Pisos de edge varridos na Parte C.
PISOS_EDGE = (0.00, 0.02, 0.03, 0.04, 0.06, 0.08)


def _folhas(cur, metodo: cat.Metodo, dias: int) -> list:
    """Todas as atuacoes de 60+ minutos do contador, na ordem cronologica.

    Mesmo filtro de minutos do `player_history`, e `IS NOT NULL` sobre uma base
    que ja' passou pelo backfill de zero implicito -- sem ele a amostra aqui
    seria a mesma amostra enviesada que gerou o problema.
    """
    cur.execute(f"""
        SELECT p.player_id, p.player_name, p.team_id, p.match_date, p.fixture_id,
               p.league_id, p.season, p.minutes, p.{metodo.coluna} AS valor,
               CASE WHEN f.home_team_id = p.team_id THEN 'home'
                    WHEN f.away_team_id = p.team_id THEN 'away'
               END AS mando
          FROM player_match_stats p
          LEFT JOIN fixtures f ON f.fixture_id = p.fixture_id
         WHERE p.{metodo.coluna} IS NOT NULL
           AND COALESCE(p.minutes, 0) >= %s
           AND p.match_date >= CURRENT_DATE - %s
      ORDER BY p.player_id, p.league_id, p.season, p.match_date
    """, (player_history.MIN_MINUTOS, dias))
    return linhas_dict(cur)


def _phi(cur, metodo: cat.Metodo) -> float:
    """O phi que o motor usaria hoje -- a mesma funcao, nao uma copia."""
    medida = count_model.medir_dispersao(cur, metodo)
    return float(medida.get("phi") or metodo.phi_congelado)


def _odds_do_metodo(cur, metodo: cat.Metodo, dias: int) -> dict:
    """{(fixture_id, nome_normalizado, n): odd} -- a melhor odd oferecida.

    Serve so' pra Parte C. Casa por NOME e nao por player_id porque
    `odds_values` guarda o nome publicado pela casa, que e' justamente o que o
    `name_match` resolve no motor. Aqui a comparacao e' grosseira de proposito:
    o que se quer e' a ordem de grandeza do aperto, nao reproduzir o casamento.
    """
    from services.player_stats_engine import name_match

    nomes = tuple(sorted(metodo.nomes_mercado))
    #  e nao : o nome da coluna em . E a data sai da
    # PROPRIA tabela (), sem join em fixtures -- ela ja' carrega
    # o retrato da partida, e o join so' adicionava um jeito de perder linha.
    cur.execute("""
        SELECT ov.fixture_id, ov.value_name, ov.odd_value AS odd
          FROM odds_values ov
         WHERE LOWER(TRIM(ov.market_name)) = ANY(%s)
           AND ov.match_datetime::date >= CURRENT_DATE - %s
    """, (list(nomes), dias))
    melhor: dict = {}
    for linha in linhas_dict(cur):
        parsed = name_match.parse_valor(linha.get("value_name"))
        if not parsed:
            continue
        nome, n = parsed
        try:
            odd = float(linha.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        if odd <= 1:
            continue
        chave = (linha["fixture_id"], nome.strip().lower(), n)
        if odd > melhor.get(chave, 0):
            melhor[chave] = odd
    return melhor


def caminhar(folhas: list, metodo: cat.Metodo, phi: float) -> list:
    """Um registro por (atuacao, linha) projetavel. Sem olhar o futuro."""
    por_serie: dict = defaultdict(list)
    for f in folhas:
        por_serie[(f["player_id"], f["league_id"], f["season"])].append(f)

    registros = []
    for _chave, serie in por_serie.items():
        anteriores: list = []
        for atual in serie:
            # O motor le' as MAIS RECENTES primeiro e corta no limite.
            historico = list(reversed(anteriores))[:player_history.LIMITE_ATUACOES]
            if len(historico) >= metodo.min_atuacoes:
                valores = [float(a["valor"]) for a in historico]
                no_mando = ([float(a["valor"]) for a in historico
                             if a.get("mando") == atual.get("mando")]
                            if (metodo.mando_relevante and atual.get("mando"))
                            else [])
                for linha in LINHAS:
                    analise = count_model.analisar(
                        valores=valores, linha=linha, phi=phi,
                        valores_no_mando=no_mando)
                    if not analise:
                        continue
                    registros.append({
                        "fixture_id": atual["fixture_id"],
                        "nome": (atual.get("player_name") or "").strip().lower(),
                        "n": int(linha + 0.5),
                        "linha": linha,
                        "prob": float(analise["probability"]),
                        "esperado": float(analise["esperado"]),
                        "amostra": len(valores),
                        "acertou": float(atual["valor"]) > linha,
                    })
            anteriores.append(atual)
    return registros


def imprimir_parte_a(registros: list) -> None:
    print("\nPARTE A · calibragem (a probabilidade projetada descreve o que aconteceu?)")
    print("  faixa          n      previsto    real      erro")
    faixas = [(0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    for lo, hi in faixas:
        dentro = [r for r in registros if lo <= r["prob"] < hi]
        if not dentro:
            continue
        previsto = sum(r["prob"] for r in dentro) / len(dentro)
        real = sum(1 for r in dentro if r["acertou"]) / len(dentro)
        print(f"  {lo:.0%}-{hi:.0%}   {len(dentro):>7}   {previsto:>7.1%}  "
              f"{real:>7.1%}   {(previsto - real) * 100:>+6.1f}pp")


def imprimir_parte_b(registros: list) -> None:
    print("\nPARTE B · funil do piso de probabilidade")
    print(f"  (o piso de hoje e' {cfg.PROB_MINIMA:.0%})")
    print("  piso     passam    % do total    acerto real    erro do modelo")
    total = len(registros) or 1
    for piso in PISOS:
        passam = [r for r in registros if r["prob"] >= piso]
        if not passam:
            print(f"  {piso:.0%}    {0:>7}          0.0%             --")
            continue
        real = sum(1 for r in passam if r["acertou"]) / len(passam)
        previsto = sum(r["prob"] for r in passam) / len(passam)
        marca = "  <- atual" if abs(piso - cfg.PROB_MINIMA) < 1e-9 else ""
        print(f"  {piso:.0%}    {len(passam):>7}   {len(passam) / total:>9.1%}    "
              f"{real:>9.1%}      {(previsto - real) * 100:>+6.1f}pp{marca}")


def imprimir_parte_c(registros: list, odds: dict) -> None:
    print("\nPARTE C · o aperto do edge (so' o que a casa cotou)")
    com_odd = []
    for r in registros:
        odd = odds.get((r["fixture_id"], r["nome"], r["n"]))
        if not odd or odd < cfg.ODD_MIN:
            continue
        com_odd.append({**r, "odd": odd, "edge": r["prob"] - 1 / odd})
    if not com_odd:
        print("  nenhuma atuacao casou com oferta da casa na janela -- sem Parte C.")
        return
    print(f"  {len(com_odd)} de {len(registros)} projecoes tem odd na faixa "
          f"(piso {cfg.ODD_MIN}).")
    print(f"  (o piso de edge de hoje e' {cfg.EDGE_MINIMO:.0%})")
    print("  piso prob   piso edge    passam    acerto real    lucro/unidade")
    for piso in (0.56, 0.58, 0.60, cfg.PROB_MINIMA, 0.65):
        for piso_edge in PISOS_EDGE:
            passam = [r for r in com_odd
                      if r["prob"] >= piso and r["edge"] >= piso_edge]
            if not passam:
                continue
            greens = [r for r in passam if r["acertou"]]
            lucro = (sum(r["odd"] - 1 for r in greens)
                     - (len(passam) - len(greens)))
            marca = ("  <- atual"
                     if (abs(piso - cfg.PROB_MINIMA) < 1e-9
                         and abs(piso_edge - cfg.EDGE_MINIMO) < 1e-9) else "")
            print(f"  {piso:>8.0%}   {piso_edge:>9.0%}   {len(passam):>7}    "
                  f"{len(greens) / len(passam):>9.1%}    "
                  f"{lucro / len(passam):>+11.3f}u{marca}")


def main() -> None:
    alvo = None
    if "--metodo" in sys.argv:
        alvo = sys.argv[sys.argv.index("--metodo") + 1]

    conn = get_connection()
    cur = conn.cursor()
    try:
        for metodo in cat.METODOS:
            if alvo and metodo.slug != alvo:
                continue
            print("=" * 78)
            print(f"{metodo.slug} · {metodo.label} · piso de amostra "
                  f"{metodo.min_atuacoes}")
            print("=" * 78)
            phi = _phi(cur, metodo)
            folhas = _folhas(cur, metodo, DIAS)
            print(f"  {len(folhas)} atuacoes de 60+ min nos ultimos {DIAS} dias, "
                  f"phi {phi}")
            if not folhas:
                continue
            valores = [float(f["valor"]) for f in folhas]
            media = sum(valores) / len(valores)
            zeros = sum(1 for v in valores if v == 0)
            print(f"  media da base {media:.3f} · "
                  f"{zeros / len(valores):.1%} das folhas sao zero")
            registros = caminhar(folhas, metodo, phi)
            print(f"  {len(registros)} projecoes com amostra suficiente")
            if not registros:
                print("  sem projecao: o piso de amostra nao e' alcancado na janela.")
                continue
            imprimir_parte_a(registros)
            imprimir_parte_b(registros)
            imprimir_parte_c(registros, _odds_do_metodo(cur, metodo, DIAS))
            print()
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
