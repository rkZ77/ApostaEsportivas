"""Recalibracao da tabela empirica de faltas contra o banco, a cada rodada.

O PROBLEMA QUE ISTO RESOLVE
--------------------------
A tabela de fouls_model._FAIXAS_POR_LINHA foi medida uma vez, em 2026-08-01,
contra os jogos que existiam naquele dia (946), e duas linhas (20.5 e 21.5)
entraram em 11/08 como estimativa DERIVADA, nao medida -- o proprio comentario
delas pede "refazer a medicao com os 946 jogos originais" como proxima revisao
obrigatoria. Enquanto isso a base cresce toda semana e ninguem remede.

Uma tabela congelada nao envelhece de forma visivel: ela continua devolvendo
numero, e o numero continua parecendo medido. O motor nao tem como perceber que
esta' usando a foto de um campeonato que ja' mudou.

O PEDIDO (usuario, 2026-08-16): "adiciona no fluxo dos pipelines pra fazer isso
sempre". Ou seja, remedir deixa de ser tarefa manual que alguem lembra de rodar
e passa a ser parte da geracao do pick.

NAO E' AGENDAMENTO. Roda dentro da execucao do pipeline de faltas, que continua
sendo disparado na mao -- este projeto nao tem nada agendado desde que
scheduler.py foi deletado em 01/08.

POR QUE ELE TAMBEM DESTRAVA O MANDO
-----------------------------------
O bloqueio pra separar casa e fora em faltas era de CONSISTENCIA, nao de
qualidade: a tabela tinha sido calibrada com media de mando misturado, entao
trocar so' a entrada do pipeline quebrava o mapeamento faixa -> taxa em
silencio. Com a tabela recalculada pelo MESMO metodo que o pipeline usa pra
montar a previsao, os dois lados passam a se mover juntos e o descasamento deixa
de existir. Por isso `usar_mando` atravessa este modulo inteiro: quem decide e' o
pipeline, e a calibragem obedece.

O QUE PROTEGE CONTRA RECALIBRAGEM RUIM
--------------------------------------
Celula com amostra pequena NAO substitui a congelada -- fica a de 01/08, que tem
50 a 159 jogos por tras. A troca e' celula a celula, nunca tabela inteira: uma
faixa com dado novo abundante entra, a vizinha sem dado nao entra, e o resultado
continua sendo uma tabela completa. Se o banco estiver vazio ou inacessivel,
devolve a congelada inteira e o pipeline roda como antes.
"""
from __future__ import annotations

from collections import defaultdict

from services.pick_engine.fouls_model import (
    LINHAS_SUPORTADAS, MIN_JOGOS_TIME, _FAIXAS_POR_LINHA,
)

#: Limites superiores de cada faixa de previsao. Sao os MESMOS da tabela
#: congelada de propósito: recalibrar tem que produzir uma tabela comparavel
#: celula a celula com a antiga, senao nao da' pra dizer o que mudou.
LIMITES_FAIXA = (22.0, 24.0, 26.0, 28.0, 999.0)

#: Minimo de jogos numa celula pra ela substituir a congelada.
#:
#: ESCOLHIDO, NAO MEDIDO, e vale dizer isso em voz alta: uma taxa vinda de 30
#: jogos carrega erro padrao de uns 9 pontos percentuais, o que ja' e' grande
#: perto das diferencas que separam as faixas. Abaixo disso a "atualizacao"
#: seria trocar um numero medido em 159 jogos por ruido. Se a base crescer
#: muito, subir este piso e' mais seguro que baixar.
MIN_AMOSTRA_CELULA = 30


def carregar_jogos(cur) -> list:
    """Jogos encerrados com folha de faltas completa, em ordem cronologica.

    A ordem importa e nao e' detalhe: a previsao de cada jogo so' pode usar os
    ANTERIORES a ele, que e' a regra que a tabela original ja' seguia.
    """
    cur.execute("""
        SELECT fixture_id, match_date, home_team_id, away_team_id,
               home_fouls, away_fouls
        FROM match_statistics
        WHERE home_fouls IS NOT NULL
          AND away_fouls IS NOT NULL
          AND match_date IS NOT NULL
        ORDER BY match_date, fixture_id
    """)
    return [
        {"fixture_id": r[0], "match_date": r[1],
         "home_team_id": r[2], "away_team_id": r[3],
         "home_fouls": float(r[4]), "away_fouls": float(r[5])}
        for r in cur.fetchall()
    ]


def previsoes(jogos: list, usar_mando: bool) -> list:
    """[{fixture_id, previsto, real}] por jogo, sem lookahead.

    O fixture_id vai junto porque quem compara os dois metodos precisa PAREAR
    por jogo: com mando o pool e' menor, entao mais jogos ficam sem historico
    suficiente e as duas listas nao saem do mesmo tamanho nem na mesma ordem.

    usar_mando=False reproduz faltas_pipeline._media_faltas como ele e' hoje:
    os jogos do time em casa e fora entram no mesmo balde. True conta so' os
    jogos no mando em que o time vai jogar, que e' o que stats_model.
    pool_and_field faz no motor generico desde 2026-08-08.
    """
    historico: dict = defaultdict(list)
    amostras = []

    for j in jogos:
        h, a = j["home_team_id"], j["away_team_id"]
        chave_casa = (h, "home") if usar_mando else (h, None)
        chave_fora = (a, "away") if usar_mando else (a, None)

        casa, fora = historico[chave_casa], historico[chave_fora]
        if len(casa) >= MIN_JOGOS_TIME and len(fora) >= MIN_JOGOS_TIME:
            amostras.append({
                "fixture_id": j["fixture_id"],
                "previsto": sum(casa) / len(casa) + sum(fora) / len(fora),
                "real": j["home_fouls"] + j["away_fouls"],
            })

        # Só depois de usar: o jogo atual nunca entra na propria previsao.
        historico[chave_casa].append(j["home_fouls"])
        historico[chave_fora].append(j["away_fouls"])

    return amostras


def _indice_faixa(previsto: float) -> int:
    for i, limite in enumerate(LIMITES_FAIXA):
        if previsto < limite:
            return i
    return len(LIMITES_FAIXA) - 1


def medir(amostras: list, linhas=LINHAS_SUPORTADAS) -> dict:
    """{linha: {indice_faixa: (taxa, n)}} a partir das amostras."""
    baldes: dict = defaultdict(list)
    for a in amostras:
        baldes[_indice_faixa(a["previsto"])].append(a["real"])

    medida: dict = {}
    for linha in linhas:
        por_faixa = {}
        for idx, reais in baldes.items():
            n = len(reais)
            por_faixa[idx] = (sum(1 for r in reais if r > linha) / n, n)
        medida[linha] = por_faixa
    return medida


def mesclar(medida: dict, min_amostra: int = MIN_AMOSTRA_CELULA) -> tuple[dict, list]:
    """Tabela final no formato de _FAIXAS_POR_LINHA, mais o relatorio do que
    mudou.

    Celula a celula: entra a recalibrada quando tem amostra, senao fica a
    congelada. O relatorio existe pra a troca nunca ser silenciosa -- o pipeline
    imprime, e o pick guarda o resumo em engine_debug.
    """
    tabela: dict = {}
    relatorio: list = []
    trocadas = 0

    for linha, congelada in _FAIXAS_POR_LINHA.items():
        nova_linha = []
        por_faixa = medida.get(linha, {})
        for idx, (limite, taxa_antiga, n_antigo) in enumerate(congelada):
            recal = por_faixa.get(idx)
            if recal is not None and recal[1] >= min_amostra:
                taxa, n = recal
                nova_linha.append((limite, round(taxa, 4), n))
                trocadas += 1
                # So' diferenca que move a agulha vira linha de relatorio: com
                # 30 celulas, listar variacao de meio ponto percentual esconderia
                # a que importa no meio do ruido.
                if abs(taxa - taxa_antiga) >= 0.02:
                    relatorio.append(
                        f"Over {linha} faixa <{limite}: "
                        f"{taxa_antiga * 100:.1f}% (n={n_antigo}) -> "
                        f"{taxa * 100:.1f}% (n={n})")
            else:
                nova_linha.append((limite, taxa_antiga, n_antigo))
        tabela[linha] = nova_linha

    return tabela, {"celulas_trocadas": trocadas, "mudancas": relatorio}


def recalibrar(cur, usar_mando: bool = False,
               min_amostra: int = MIN_AMOSTRA_CELULA) -> tuple[dict, dict]:
    """(tabela, diagnostico). Nunca levanta: falha devolve a congelada.

    Calibragem e' melhoria, nao requisito -- derrubar a geracao de pick porque a
    remedicao falhou seria trocar um problema pequeno por um grande. Mesmo
    criterio que StandingsService ja' usa pra classificacao.
    """
    diagnostico = {"usou_mando": usar_mando, "origem": "congelada",
                   "jogos": 0, "amostras": 0, "celulas_trocadas": 0,
                   "mudancas": [], "erro": None}
    try:
        jogos = carregar_jogos(cur)
        amostras = previsoes(jogos, usar_mando)
        diagnostico["jogos"] = len(jogos)
        diagnostico["amostras"] = len(amostras)
        if not amostras:
            return dict(_FAIXAS_POR_LINHA), diagnostico

        tabela, resumo = mesclar(medir(amostras), min_amostra)
        diagnostico.update({"origem": "recalibrada", **resumo})
        return tabela, diagnostico
    except Exception as e:
        diagnostico["erro"] = str(e)
        return dict(_FAIXAS_POR_LINHA), diagnostico
