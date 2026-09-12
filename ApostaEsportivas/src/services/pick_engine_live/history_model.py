"""Historico contextual do confronto: o que estes dois times produzem NESTE
mando, com recencia, e o quanto isso favorece a direcao do pick.

POR QUE ISTO EXISTE (2026-09-11)
--------------------------------
Ate' hoje o baseline do motor ao vivo era montado por CAMADAS QUE SE
SOBRESCREVEM (live_pipeline: liga -> times -> mando -> arbitro -> h2h). Quem
escrevesse por ultimo mandava sozinho, e as anteriores sumiam. Isso tem dois
defeitos que sao o motivo deste modulo:

1. NAO E' UMA COMBINACAO, E' UMA SUBSTITUICAO. Quando `baseline_do_mando`
   tinha 5 jogos de cada lado, ele apagava a media de 27 jogos misturados de
   `baseline_do_confronto` -- um recorte melhor com amostra pior trocava de
   lugar com um recorte pior com amostra boa, e nada media o que se perdia.

2. NAO HAVIA RECENCIA NENHUMA. Todas as camadas usam medias simples de uma
   janela de 400 dias. Um jogo de outubro passado pesava igual ao de domingo.

O QUE ISTO MUDA, E O QUE NAO MUDA
---------------------------------
Muda: o baseline de escanteios, gols, cartoes, faltas e chutes passa a ser uma
MEDIA PONDERADA de cinco componentes, com recencia dentro de cada um, e o
peso de cada um e' configuravel.

Nao muda: as camadas antigas continuam existindo e continuam sendo a fonte dos
componentes (liga e geral). O arbitro continua mandando em cartoes DEPOIS
desta conta, porque em cartao quem apita explica mais que quem joga -- ver
live_pipeline.baseline_do_arbitro.

E POR QUE O PESO DO HISTORICO CONTRA O AO VIVO NAO ESTA AQUI
------------------------------------------------------------
Porque ele ja existe e e' MEDIDO: `residual_model.forca_do_prior` deriva da
dispersao da familia quantos JOGOS de historico o baseline vale (gols 14.3,
escanteio 1.22, cartao 0.78, falta 0.47), e dali sai o peso do proprio jogo
contra o historico a cada minuto. Uma tabela de "0-20min: 70% historico" seria
um segundo numero declarado para a mesma pergunta que ja tem resposta
derivada -- e as duas divergiriam no primeiro ajuste. Este modulo melhora o
BASELINE; quem decide o quanto ele pesa continua sendo a dispersao.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao le banco. Recebe a serie de jogos ja lida e devolve numeros, pra poder ser
testado inteiro sem subir nada.
"""
from __future__ import annotations

import math

from services.pick_engine import probability_model as pm

#: Peso de cada componente do baseline historico. Sao o ponto de partida
#: pedido pelo usuario em 2026-09-11 e estao aqui, e nao cravados na formula,
#: porque nenhum deles foi MEDIDO contra resultado -- sao uma hipotese sobre o
#: quanto o recorte recente descreve melhor que o recorte largo.
#:
#: A soma e' 1.0 com todos presentes; com componente faltando o peso e'
#: renormalizado sobre os que existem E a cobertura cai junto (quem paga a
#: renormalizacao e' a confianca, em data_quality -- nunca o silencio).
PESOS_PADRAO = {
    "last5_contexto": 0.40,
    "last10_contexto": 0.25,
    "temporada_contexto": 0.15,
    "geral": 0.10,
    "liga": 0.10,
}

#: Meia-vida da recencia, em JOGOS. Com 8, o 8o jogo mais antigo da janela
#: pesa metade do mais recente e o 16o pesa um quarto.
#:
#: E' deliberadamente alta. O pedido era "jogo recente pesa mais, mas evite
#: overfitting": meia-vida curta (2 ou 3) faz a janela de 5 virar praticamente
#: o ultimo jogo, e um unico 15-escanteios passa a definir o baseline. Com 8, a
#: recencia INCLINA a media sem sequestra-la -- dentro da janela de 5 a
#: diferenca entre o mais novo e o mais velho e' de ~35%, nao de 8x.
MEIA_VIDA_JOGOS = 8.0

#: Amostra minima por componente. Abaixo disso o componente nao entra: ele nao
#: vira "zero" nem e' preenchido com a liga -- some, e a cobertura registra
#: que sumiu. Ausencia nunca vira dado (invariante 1 de settlement.py).
MINIMO_LAST5 = 3
MINIMO_LAST10 = 6
MINIMO_TEMPORADA = 6
MINIMO_GERAL = 6

#: Rotulos da escala de alinhamento pedida. O valor continuo e' o que entra na
#: conta; o rotulo existe pro log e pro reasoning.
ROTULOS = (
    (0.20, "FORTEMENTE_CONTRA"),
    (0.40, "CONTRA"),
    (0.60, "NEUTRO"),
    (0.80, "FAVORAVEL"),
    (1.01, "FORTEMENTE_FAVORAVEL"),
)


def _peso_recencia(indice: int) -> float:
    """Peso do jogo na posicao `indice` (0 = mais recente)."""
    return 0.5 ** (indice / MEIA_VIDA_JOGOS)


def media_com_recencia(serie: list[float | None], limite: int | None = None) -> dict | None:
    """Media da serie (mais recente primeiro) com decaimento exponencial.

    `None` na serie e' jogo em que o provedor nao publicou aquela estatistica:
    ele SAI da media e nao conta pra amostra -- mas nao desloca os indices dos
    outros, porque a posicao e' cronologica e o decaimento e' do tempo, nao da
    disponibilidade. Contar a ausencia como zero inflaria todo Under; recontar
    a posicao faria um jogo antigo se passar por recente.
    """
    if not serie:
        return None
    usados = serie if limite is None else serie[:limite]
    soma_peso, soma_valor, n = 0.0, 0.0, 0
    for i, valor in enumerate(usados):
        if valor is None:
            continue
        peso = _peso_recencia(i)
        soma_peso += peso
        soma_valor += peso * float(valor)
        n += 1
    if n == 0 or soma_peso <= 0:
        return None
    return {"valor": round(soma_valor / soma_peso, 4), "n": n,
            "media_simples": round(
                sum(float(v) for v in usados if v is not None) / n, 4)}


def componentes_do_lado(serie_contexto: list, serie_geral: list,
                        baseline_liga: float | None) -> dict:
    """Os cinco componentes de UM lado (mandante em casa, ou visitante fora).

    `serie_contexto` sao os jogos daquele time NAQUELE mando, mais recente
    primeiro, cada item o TOTAL DA PARTIDA daquela familia -- que e' a unidade
    do mercado (o pick e' liquidado pelo total do jogo).

    `serie_geral` sao os jogos do mesmo time sem recorte de mando. Ele entra
    com peso pequeno e de proposito: e' pior recorte, mas com mais amostra, e
    serve de ancora quando o mando tem 5 jogos.
    """
    saida: dict = {}

    l5 = media_com_recencia(serie_contexto, 5)
    if l5 and l5["n"] >= MINIMO_LAST5:
        saida["last5_contexto"] = l5

    l10 = media_com_recencia(serie_contexto, 10)
    if l10 and l10["n"] >= MINIMO_LAST10:
        saida["last10_contexto"] = l10

    temporada = media_com_recencia(serie_contexto)
    if temporada and temporada["n"] >= MINIMO_TEMPORADA:
        saida["temporada_contexto"] = temporada

    geral = media_com_recencia(serie_geral)
    if geral and geral["n"] >= MINIMO_GERAL:
        saida["geral"] = geral

    if baseline_liga:
        # A liga nao tem serie: e' a media agregada que o pipeline ja' lia.
        saida["liga"] = {"valor": round(float(baseline_liga), 4), "n": None,
                         "media_simples": round(float(baseline_liga), 4)}

    return saida


def combinar(componentes: dict, pesos: dict | None = None) -> dict | None:
    """Media ponderada dos componentes presentes, com a cobertura declarada.

    `cobertura` e' a fracao do peso total que existe de verdade. Ela NAO
    corrige nada aqui -- quem a usa e' data_quality, pra descontar confianca e,
    abaixo do minimo, recusar o pick. Renormalizar em silencio e seguir como se
    tivesse todos os dados e' exatamente o que este numero existe pra impedir.
    """
    pesos = pesos or PESOS_PADRAO
    presentes = [(nome, info) for nome, info in componentes.items() if nome in pesos]
    if not presentes:
        return None
    peso_total = sum(pesos[nome] for nome, _ in presentes)
    if peso_total <= 0:
        return None
    valor = sum(pesos[nome] * info["valor"] for nome, info in presentes) / peso_total
    return {
        "valor": round(valor, 4),
        "cobertura": round(peso_total / sum(pesos.values()), 4),
        "componentes": [
            {"nome": nome, "valor": info["valor"], "peso": pesos[nome],
             "jogos": info.get("n")}
            for nome, info in sorted(presentes, key=lambda p: -pesos[p[0]])
        ],
        "ausentes": sorted(n for n in pesos if n not in componentes),
    }


def baseline_do_confronto(lado_casa: dict, lado_fora: dict,
                          pesos: dict | None = None) -> dict | None:
    """A expectativa desta partida: o lado de casa do mandante com o lado de
    fora do visitante.

    Os dois lados sao estimativas do MESMO numero (o total da partida), cada
    uma vista de um time -- entao a combinacao e' a media simples delas, que e'
    a mesma convencao que `live_pipeline.baseline_do_mando` ja' usava. Um lado
    sozinho tambem vale, com a cobertura cortada pela metade: meia leitura de
    um confronto e' pior que duas, e melhor que a media da liga.
    """
    casa = combinar(lado_casa, pesos)
    fora = combinar(lado_fora, pesos)
    lados = [l for l in (casa, fora) if l]
    if not lados:
        return None
    valor = sum(l["valor"] for l in lados) / len(lados)
    cobertura = sum(l["cobertura"] for l in lados) / 2.0  # falta um lado = cai pela metade
    return {
        "valor": round(valor, 4),
        "cobertura": round(cobertura, 4),
        "home": casa,
        "away": fora,
        "lados_disponiveis": len(lados),
    }


def _rotulo(alinhamento: float) -> str:
    for corte, nome in ROTULOS:
        if alinhamento < corte:
            return nome
    return "FORTEMENTE_FAVORAVEL"


def historical_alignment(baseline_historico: float | None, linha: float,
                         direcao: str, familia: str,
                         lado_casa: float | None = None,
                         lado_fora: float | None = None) -> dict:
    """O historico deste confronto favorece ESTA direcao, nesta linha?

    A conta nao e' "a media e' maior que a linha", e sim quantos DESVIOS a
    media esta' do outro lado -- porque 10.4 escanteios contra linha 9.5 e'
    quase nada (o desvio da familia e' 4.3) e 2.9 gols contra linha 2.5 e'
    bem mais (o desvio e' 1.8). Sem normalizar pela dispersao, escanteio
    sempre pareceria mais alinhado que gol so' por ter numero maior.

        z = (historico - linha) / desvio_padrao, com o sinal virado pro Under
        alinhamento = logistica(1.4 * z)   ->  0.5 quando o historico cai
                                               exatamente na linha

    O desvio padrao vem da dispersao MEDIDA do projeto (probability_model:
    var = phi * media), nao de um numero novo.

    `lado_casa` e `lado_fora` sao opcionais e nao mudam o valor: eles medem se
    os dois lados contam a mesma historia. Dois lados discordando e' um
    alinhamento medio que esconde desacordo, e quem usa isso e' o
    contradiction_model.
    """
    if baseline_historico is None or baseline_historico <= 0:
        return {"disponivel": False, "alinhamento": None, "rotulo": None,
                "motivo": "sem baseline historico"}
    direcao = (direcao or "").strip().lower()
    if direcao not in ("over", "under"):
        return {"disponivel": False, "alinhamento": None, "rotulo": None,
                "motivo": f"direcao invalida ({direcao})"}

    phi = pm.dispersao(familia, "total")
    desvio = math.sqrt(max(1e-6, phi * float(baseline_historico)))
    z = (float(baseline_historico) - float(linha)) / desvio
    z_dir = z if direcao == "over" else -z
    alinhamento = 1.0 / (1.0 + math.exp(-1.4 * z_dir))

    concordancia = None
    if lado_casa is not None and lado_fora is not None:
        acima_casa = lado_casa > linha
        acima_fora = lado_fora > linha
        concordancia = bool(acima_casa == acima_fora)

    return {
        "disponivel": True,
        "alinhamento": round(alinhamento, 4),
        "rotulo": _rotulo(alinhamento),
        "z": round(z_dir, 4),
        "baseline_historico": round(float(baseline_historico), 3),
        "linha": linha,
        "direcao": direcao,
        "desvio_padrao": round(desvio, 3),
        "dispersao_phi": round(phi, 3),
        "lado_casa": lado_casa,
        "lado_fora": lado_fora,
        "lados_concordam": concordancia,
        "motivo": None,
    }
