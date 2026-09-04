"""
medir_faltas_mando_e_pressao.py · as duas medicoes que faltam pra fechar o
pedido de 2026-08-16 ("quero o motor de faltas e goleiros igual ao de picks").

SOMENTE LEITURA. Nenhum INSERT/UPDATE/DELETE -- pode rodar contra PROD sem
efeito colateral.

Uso:
  DB_ENV=prod python src/scripts/medir_faltas_mando_e_pressao.py

O QUE ELE RESPONDE, E POR QUE PRECISOU DE SCRIPT
------------------------------------------------
PARTE A -- MANDO. O motor generico separou casa e fora em 2026-08-08
(stats_model.pool_and_field), com diferenca medida de +27% na Serie A e +36% na
Serie B. A correcao chegou em goleiros_pipeline em 16/08, mas NAO pode ser
aplicada em faltas sem esta medicao: o fouls_model nao e' parametrico -- a
probabilidade sai de uma tabela empirica que foi calibrada com media de mando
MISTURADO. Trocar a entrada sem remedir a tabela quebra o mapeamento faixa ->
taxa em silencio, que e' o pior tipo de erro que este motor pode ter.

Por isso a Parte A calcula os DOIS metodos sobre exatamente a mesma amostra:
sem comparacao pareada, qualquer diferenca poderia ser so' recorte diferente.

PARTE B -- PRESSAO COMPETITIVA. A hipotese do usuario: "juiz da' muita falta e o
jogo e' pego pelo contexto, briga de rebaixamento, ele da' faltas". As pecas pra
ligar isso ja' existem (competitive_pressure.pressao_da_partida), mas ligar sem
medir seria inventar numero -- todo o resto dos dois modelos foi medido contra
946 jogos, e essa e' a regra da casa.

LOOKAHEAD: NAO HA, E ISSO CUSTOU TRABALHO
-----------------------------------------
Toda media de time usa SO' jogos anteriores aquele, como a tabela original de
fouls_model ja' fazia.

Na Parte B o problema e' maior: `league_standings` guarda a foto ATUAL da
temporada, nao a tabela na data do jogo. Usar ela direto responderia "times que
TERMINARAM perto do rebaixamento fazem mais falta", que e' outra pergunta e vem
contaminada pelo proprio resultado. Por isso a tabela e' RECONSTRUIDA rodada a
rodada a partir dos resultados de match_statistics.

APROXIMACAO ASSUMIDA, a unica: as faixas de zona (o que e' Libertadores, o que
e' rebaixamento) vem do `description` da foto atual, mapeado por POSICAO. Isso e'
regulamento da competicao, nao classificacao -- o Brasileirao rebaixa 4 do
comeco ao fim da temporada. O que muda por rodada e' QUEM esta' em cada posicao,
e isso a reconstrucao resolve.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PYTHONUNBUFFERED", "1")

from utils.db_utils import get_connection
from services.pick_engine import competitive_pressure as cp
from services.pick_engine import fouls_calibration as fc
from services.pick_engine.fouls_model import (
    LINHAS_SUPORTADAS, MIN_JOGOS_TIME, _FAIXAS_POR_LINHA,
)

# Os limites vem do modulo de calibragem, nao repetidos aqui: desde 2026-08-16 o
# pipeline recalibra a tabela a cada rodada usando essas mesmas faixas, e duas
# copias da mesma constante e' como a medicao e a producao passam a discordar
# sem ninguem perceber.
LIMITES_FAIXA = fc.LIMITES_FAIXA
ROTULO_FAIXA = ("previsto <22", "previsto 22-24", "previsto 24-26",
                "previsto 26-28", "previsto 28+")

# Faixas de intensidade da Parte B.
LIMITES_PRESSAO = (0.20, 0.40, 0.60, 0.80, 1.01)
ROTULO_PRESSAO = ("intensidade <0.20", "0.20-0.40", "0.40-0.60",
                  "0.60-0.80", "0.80+")


def _indice(valor, limites):
    for i, limite in enumerate(limites):
        if valor < limite:
            return i
    return len(limites) - 1


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def carregar_jogos(cur):
    """Jogos encerrados com folha de faltas completa, em ordem cronologica."""
    cur.execute("""
        SELECT fixture_id, league_id, season, match_date,
               home_team_id, away_team_id,
               home_fouls, away_fouls,
               COALESCE(home_goals_90, home_goals),
               COALESCE(away_goals_90, away_goals)
        FROM match_statistics
        WHERE home_fouls IS NOT NULL
          AND away_fouls IS NOT NULL
          AND match_date IS NOT NULL
        ORDER BY match_date, fixture_id
    """)
    return [
        {"fixture_id": r[0], "league_id": r[1], "season": r[2], "match_date": r[3],
         "home_team_id": r[4], "away_team_id": r[5],
         "home_fouls": float(r[6]), "away_fouls": float(r[7]),
         "home_goals": r[8], "away_goals": r[9]}
        for r in cur.fetchall()
    ]


def carregar_descricoes(cur):
    """{(league_id, season): {rank: description}} -- o desenho das zonas."""
    mapa: dict = defaultdict(dict)
    try:
        cur.execute("""
            SELECT league_id, season, rank, description
            FROM league_standings
            WHERE rank IS NOT NULL
        """)
    except Exception as e:
        print(f"[AVISO] league_standings indisponivel ({e}); Parte B sera' pulada.")
        return {}
    for league_id, season, rank, description in cur.fetchall():
        mapa[(league_id, season)][rank] = description
    return mapa


###############################################################################
# PARTE A -- a tabela de faixas com e sem separacao de mando
###############################################################################
def medir_mando(jogos):
    """Para cada jogo, a previsao pelos dois metodos, mais o total real.

    `misto` reproduz o que faltas_pipeline._media_faltas faz hoje: soma os jogos
    do time em casa e fora no mesmo balde. `mando` conta so' os jogos no mando
    em que o time vai jogar, que e' o que pool_and_field faz no motor generico.
    """
    por_metodo = {
        "mando": fc.previsoes(jogos, usar_mando=True),
        "misto": fc.previsoes(jogos, usar_mando=False),
    }

    # So' entra na comparacao o jogo que tem OS DOIS metodos disponiveis --
    # comparar medias sobre amostras diferentes e' o erro que a docstring de
    # fouls_model ja' documenta ("o 0.418 NAO e' o mesmo numero que o 0.155").
    # fc.previsoes devolve na ordem dos jogos, mas pula jogo sem historico
    # suficiente, e o metodo por mando pula MAIS (pool menor). Por isso o
    # pareamento e' por fixture_id, nao por posicao na lista.
    indexado = {
        metodo: {a["fixture_id"]: a for a in amostras}
        for metodo, amostras in por_metodo.items()
    }
    comuns = set(indexado["mando"]) & set(indexado["misto"])

    return [
        {"real": indexado["mando"][fid]["real"],
         "mando": indexado["mando"][fid]["previsto"],
         "misto": indexado["misto"][fid]["previsto"]}
        for fid in sorted(comuns)
    ]


def tabela_de_faixas(amostras, metodo):
    """{indice_faixa: {"n":, "real_medio":, linha: taxa_over}} pelo metodo dado."""
    baldes: dict = defaultdict(list)
    for a in amostras:
        baldes[_indice(a[metodo], LIMITES_FAIXA)].append(a)

    saida = {}
    for idx, itens in sorted(baldes.items()):
        reais = [i["real"] for i in itens]
        linha_taxas = {
            linha: sum(1 for i in itens if i["real"] > linha) / len(itens)
            for linha in LINHAS_SUPORTADAS
        }
        saida[idx] = {"n": len(itens), "real_medio": _media(reais),
                      "taxas": linha_taxas}
    return saida


def erro_medio(amostras, metodo):
    return _media([abs(a[metodo] - a["real"]) for a in amostras])


def imprimir_parte_a(amostras):
    print("\n" + "=" * 78)
    print("PARTE A - TABELA DE FALTAS, MANDO MISTURADO x MANDO SEPARADO")
    print("=" * 78)

    if not amostras:
        print("Nenhum jogo com os dois metodos disponiveis. Base curta demais.")
        return

    print(f"\nAmostra pareada: {len(amostras)} jogos "
          f"(exige >= {MIN_JOGOS_TIME} jogos previos de cada lado NOS DOIS metodos)")
    print(f"Erro absoluto medio da previsao (misturado): {erro_medio(amostras, 'misto'):.2f} faltas")
    print(f"Erro absoluto medio da previsao (por mando): {erro_medio(amostras, 'mando'):.2f} faltas")
    print("\n(menor e' melhor - se o mando nao reduzir o erro, nao ha motivo pra"
          "\n remedir a tabela e o pipeline de faltas fica como esta')")

    for metodo in ("misto", "mando"):
        tab = tabela_de_faixas(amostras, metodo)
        print(f"\n--- metodo: {metodo.upper()} ---")
        cabecalho = "faixa".ljust(16) + "n".rjust(5) + "real".rjust(8)
        for linha in LINHAS_SUPORTADAS:
            cabecalho += f"Ov{linha}".rjust(9)
        print(cabecalho)
        for idx in sorted(tab):
            d = tab[idx]
            row = ROTULO_FAIXA[idx].ljust(16) + str(d["n"]).rjust(5) + f"{d['real_medio']:.1f}".rjust(8)
            for linha in LINHAS_SUPORTADAS:
                row += f"{d['taxas'][linha] * 100:.1f}%".rjust(9)
            print(row)

    print("\n--- o que esta' HOJE em fouls_model._FAIXAS_POR_LINHA ---")
    cabecalho = "faixa".ljust(16)
    for linha in LINHAS_SUPORTADAS:
        cabecalho += f"Ov{linha}".rjust(9)
    print(cabecalho)
    for idx in range(len(LIMITES_FAIXA)):
        row = ROTULO_FAIXA[idx].ljust(16)
        for linha in LINHAS_SUPORTADAS:
            faixas = _FAIXAS_POR_LINHA.get(linha) or []
            taxa = faixas[idx][1] if idx < len(faixas) else None
            row += (f"{taxa * 100:.1f}%".rjust(9) if taxa is not None else "-".rjust(9))
        print(row)
    print("\nATENCAO: a tabela de hoje foi medida com o mando MISTURADO. Comparar"
          "\ncom o bloco 'MANDO' acima e' a decisao -- se as taxas mudarem de faixa,"
          "\ntrocar a entrada do pipeline sem trocar a tabela produziria pick errado.")


###############################################################################
# PARTE C -- faltas POR TIME (mercado Fouls. Home / Away Total)
###############################################################################
# Faixas na escala de UM time. A media da base e' 11.39 faltas por time por jogo
# (fouls_model.MEDIA_FALTAS_TIME), entao os cortes ficam em volta dela -- as
# faixas do total (22/24/26/28) nao servem aqui, sao de outra escala.
LIMITES_FAIXA_TIME = (10.0, 11.0, 12.0, 13.0, 999.0)
ROTULO_FAIXA_TIME = ("previsto <10", "previsto 10-11", "previsto 11-12",
                     "previsto 12-13", "previsto 13+")

# Linhas plausiveis pro mercado por time. NAO sao as linhas confirmadas do
# mercado -- ninguem coletou "Fouls. Home Total" ainda (o pipeline filtra esses
# nomes fora hoje). E' uma varredura em volta da media pra saber se ALGUMA linha
# tem taxa utilizavel; a coleta real depois diz quais existem, do mesmo jeito que
# aconteceu com o total em 2026-08-02 (o modelo so' sabia 22.5 e o mercado
# oferecia 24.5+).
LINHAS_TIME = (8.5, 9.5, 10.5, 11.5, 12.5, 13.5, 14.5)


def medir_por_time(jogos):
    """Uma amostra por TIME por jogo (dois por partida), no mando dele.

    Responde se o mercado por time e' modelavel: hoje o pipeline so' avalia o
    total do jogo e descarta "Fouls. Home Total"/"Away Total" pelo nome.
    """
    hist: dict = defaultdict(list)   # (team_id, mando) -> faltas
    amostras = []

    for j in jogos:
        for mando, tid, faltas in (
            ("home", j["home_team_id"], j["home_fouls"]),
            ("away", j["away_team_id"], j["away_fouls"]),
        ):
            anterior = hist[(tid, mando)]
            if len(anterior) >= MIN_JOGOS_TIME:
                amostras.append({"previsto": _media(anterior), "real": faltas,
                                 "mando": mando})
        # Só depois de usar os dois lados, senao o jogo entraria na propria previsao.
        hist[(j["home_team_id"], "home")].append(j["home_fouls"])
        hist[(j["away_team_id"], "away")].append(j["away_fouls"])

    return amostras


def imprimir_parte_c(amostras):
    print("\n" + "=" * 78)
    print("PARTE C - FALTAS POR TIME (o mercado que o pipeline ainda nao avalia)")
    print("=" * 78)

    if not amostras:
        print("Sem amostra suficiente.")
        return

    mae = _media([abs(a["previsto"] - a["real"]) for a in amostras])
    print(f"\nAmostra: {len(amostras)} atuacoes de time "
          f"(>= {MIN_JOGOS_TIME} jogos previos NO MESMO MANDO)")
    print(f"Erro absoluto medio: {mae:.2f} faltas por time")

    baldes: dict = defaultdict(list)
    for a in amostras:
        baldes[_indice(a["previsto"], LIMITES_FAIXA_TIME)].append(a)

    cabecalho = "faixa".ljust(16) + "n".rjust(6) + "real".rjust(8)
    for linha in LINHAS_TIME:
        cabecalho += f"Ov{linha}".rjust(8)
    print("\n" + cabecalho)
    for idx in sorted(baldes):
        itens = baldes[idx]
        row = (ROTULO_FAIXA_TIME[idx].ljust(16) + str(len(itens)).rjust(6)
               + f"{_media([i['real'] for i in itens]):.1f}".rjust(8))
        for linha in LINHAS_TIME:
            taxa = sum(1 for i in itens if i["real"] > linha) / len(itens)
            row += f"{taxa * 100:.0f}%".rjust(8)
        print(row)

    print("\nCOMO LER: procure celula com taxa >= 60% (o PROB_MIN dos pipelines)"
          "\nE com n que sustente o numero. Se nenhuma linha tiver isso, o mercado"
          "\npor time nao vira pick e nao vale coletar odd dele. Se tiver, essa"
          "\ntabela E' o modelo -- e' assim que a do total foi construida.")


###############################################################################
# PARTE B -- pressao competitiva x faltas
###############################################################################
def reconstruir_e_medir(jogos, descricoes):
    """Caminha a temporada acumulando a tabela e mede a pressao ANTES de cada
    jogo (a tabela nunca inclui o jogo que esta' sendo medido)."""
    por_competicao: dict = defaultdict(list)
    for j in jogos:
        por_competicao[(j["league_id"], j["season"])].append(j)

    medidos = []
    for (league_id, season), lista in por_competicao.items():
        if not cp.vale_para_a_competicao(league_id):
            continue  # copa/mata-mata: "distancia do rebaixamento" nao existe
        ranks = descricoes.get((league_id, season))
        if not ranks:
            continue

        times = {t for j in lista for t in (j["home_team_id"], j["away_team_id"])}
        estado = {t: {"pontos": 0, "gp": 0, "gc": 0, "jogos": 0, "form": []}
                  for t in times}

        for j in lista:
            tabela = _montar_tabela(estado, ranks)
            pressao = cp.pressao_da_partida(
                tabela, j["home_team_id"], j["away_team_id"], league_id)
            if pressao.get("disponivel"):
                medidos.append({
                    "intensidade": pressao["intensidade"],
                    "assimetria": pressao["assimetria"],
                    "rebaixamento": _envolve_rebaixamento(pressao),
                    "real": j["home_fouls"] + j["away_fouls"],
                })
            _aplicar_resultado(estado, j)

    return medidos


def _montar_tabela(estado, ranks):
    linhas = sorted(
        ({"team_id": t, "team_name": str(t), "points": e["pontos"],
          "goal_diff": e["gp"] - e["gc"], "played": e["jogos"],
          "form": "".join(e["form"][-5:]) or None}
         for t, e in estado.items()),
        key=lambda l: (-l["points"], -l["goal_diff"]),
    )
    for i, linha in enumerate(linhas, start=1):
        linha["rank"] = i
        linha["description"] = ranks.get(i)
    return linhas


def _aplicar_resultado(estado, j):
    gh, ga = j["home_goals"], j["away_goals"]
    h, a = estado[j["home_team_id"]], estado[j["away_team_id"]]
    h["jogos"] += 1
    a["jogos"] += 1
    if gh is None or ga is None:
        return
    h["gp"] += gh
    h["gc"] += ga
    a["gp"] += ga
    a["gc"] += gh
    if gh > ga:
        h["pontos"] += 3
        h["form"].append("W")
        a["form"].append("L")
    elif ga > gh:
        a["pontos"] += 3
        a["form"].append("W")
        h["form"].append("L")
    else:
        h["pontos"] += 1
        a["pontos"] += 1
        h["form"].append("D")
        a["form"].append("D")


#: Mesmo limiar que cp.descrever usa pra decidir se a situacao de um lado merece
#: virar frase. Abaixo disso o time tem o rebaixamento "abaixo dele" no sentido
#: puramente geometrico, sem que isso signifique nada.
NECESSIDADE_RELEVANTE = 0.25


def _envolve_rebaixamento(pressao):
    """Algum lado esta' de fato brigando contra o rebaixamento?

    A primeira versao disto aceitava qualquer time cujo `risco_abaixo` fosse
    REBAIXAMENTO, e o teste sintetico expos o erro na hora: 756 de 760 jogos
    entraram no recorte. Faz sentido -- numa tabela de 20 times, a fronteira
    mais proxima ABAIXO de quase todo mundo e' o rebaixamento, inclusive a do
    lider. Um recorte que pega 99,5% da amostra nao recorta nada.

    Agora exige uma das duas: estar DENTRO da zona, ou ter o rebaixamento como
    risco mais proximo COM necessidade relevante -- que e' a medida de "quao
    perto disso eu estou, dado o que ainda da' pra disputar".
    """
    for lado in ("home", "away"):
        s = pressao.get(lado) or {}
        if not s.get("disponivel"):
            continue
        if s.get("zona_atual") == cp.REBAIXAMENTO:
            return True
        risco_e_queda = (s.get("risco_abaixo") or {}).get("tipo") == cp.REBAIXAMENTO
        if risco_e_queda and s.get("necessidade", 0.0) >= NECESSIDADE_RELEVANTE:
            return True
    return False


def imprimir_parte_b(medidos):
    print("\n" + "=" * 78)
    print("PARTE B - PRESSAO COMPETITIVA x FALTAS")
    print("=" * 78)

    if not medidos:
        print("Nenhum jogo mensuravel (liga de pontos corridos com tabela coletada).")
        return

    print(f"\nJogos medidos: {len(medidos)}")
    geral = _media([m["real"] for m in medidos])
    print(f"Media geral de faltas: {geral:.2f}\n")

    baldes = defaultdict(list)
    for m in medidos:
        baldes[_indice(m["intensidade"], LIMITES_PRESSAO)].append(m["real"])

    print("faixa".ljust(20) + "n".rjust(6) + "faltas".rjust(9) + "vs geral".rjust(10))
    for idx in sorted(baldes):
        vals = baldes[idx]
        m = _media(vals)
        print(ROTULO_PRESSAO[idx].ljust(20) + str(len(vals)).rjust(6)
              + f"{m:.2f}".rjust(9) + f"{m - geral:+.2f}".rjust(10))

    com = [m["real"] for m in medidos if m["rebaixamento"]]
    sem = [m["real"] for m in medidos if not m["rebaixamento"]]
    print("\n--- recorte direto da hipotese: algum lado DENTRO da zona de"
          " rebaixamento, ou brigando contra ela ---")
    if com and sem:
        print(f"COM rebaixamento em jogo: n={len(com)}  faltas={_media(com):.2f}")
        print(f"SEM rebaixamento em jogo: n={len(sem)}  faltas={_media(sem):.2f}")
        print(f"diferenca: {_media(com) - _media(sem):+.2f} faltas por jogo")
    else:
        print("Um dos lados ficou vazio -- sem base pra comparar.")

    print("\nCOMO DECIDIR COM ISTO: o efeito precisa ser grande o bastante pra"
          "\nmover a previsao entre faixas da tabela (as faixas tem 2 faltas de"
          "\nlargura). Diferenca de 0.3 falta por jogo e' real e IRRELEVANTE aqui:"
          "\nnao muda a faixa, entao nao mudaria pick nenhum.")


def run():
    conn = get_connection()
    cur = conn.cursor()
    try:
        jogos = carregar_jogos(cur)
        print(f"[MEDICAO] {len(jogos)} jogos com folha de faltas completa.")
        if not jogos:
            return
        imprimir_parte_a(medir_mando(jogos))
        imprimir_parte_c(medir_por_time(jogos))
        imprimir_parte_b(reconstruir_e_medir(jogos, carregar_descricoes(cur)))
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
