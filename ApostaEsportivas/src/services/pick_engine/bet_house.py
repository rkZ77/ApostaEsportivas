"""Casa unica para bilhetes de multiplas pernas (bingo, multipla, alavancagem).

O PROBLEMA (achado do usuario, 2026-09-10)
------------------------------------------
Cada perna nascia com `best_bookmaker` proprio -- a casa de MAIOR odd daquela
linha, escolhida perna a perna. Numa pick simples isso e' certo: o usuario
abre a casa indicada e aposta. Num bilhete combinado e' impossivel: nao existe
bilhete de 4 pernas espalhado por Betano, Superbet e Bet365. O bingo publicado
em 10/09 pedia quatro casas diferentes para uma cartela so'.

A REGRA
-------
O bilhete inteiro sai de UMA casa. A casa e' escolhida DEPOIS que as pernas ja'
foram escolhidas -- o preco nunca decide qual perna entra (ver a regra de
"escolha do pick sem preco"): ele so' decide onde a cartela ja' montada e'
apostada. Uma casa so' e' elegivel quando:

  1. cota TODAS as pernas do bilhete, e
  2. a odd dela em cada perna cai dentro da faixa dura do pipeline.

O criterio (2) e' o que impede a casa unica de furar a faixa por tabela: a
faixa e' filtro duro desde 14/08 e continua valendo para a odd publicada.
Entre as casas elegiveis ganha a de maior odd combinada -- as pernas ja' estao
decididas nesse ponto, entao isso e' puro ganho para o usuario, nunca uma troca
de qualidade por preco. Empate resolve por nome, so' pra escolha ser
deterministica entre execucoes.

Quando NENHUMA casa cobre o bilhete inteiro, o combo e' descartado e o motor
tenta o proximo. Preferimos o dia sem bilhete a um bilhete que nao da' pra
apostar.
"""

from __future__ import annotations


def _odds_por_casa(perna: dict) -> dict[str, float]:
    """{casa: odd} das cotacoes validas desta perna.

    `bookmaker_odds` vem do odds_service ja' limpo (pares corrompidos fora).
    Quando a perna nao carrega a lista -- caminho antigo, ou pipeline que nao
    propaga -- sobra a casa da melhor odd, que e' o comportamento anterior.
    """
    odds = {}
    for row in perna.get("bookmaker_odds") or []:
        casa = (row.get("bookmaker") or "").strip()
        try:
            odd = float(row.get("odd") or 0)
        except (TypeError, ValueError):
            continue
        if casa and odd > 1.0:
            # Mesma casa duas vezes na mesma linha nao deveria acontecer;
            # se acontecer, fica a maior (e' a que o usuario encontraria).
            odds[casa] = max(odds.get(casa, 0.0), odd)
    if not odds:
        casa = (perna.get("best_bookmaker") or "").strip()
        odd = float(perna.get("melhor_odd") or perna.get("odd") or 0)
        if casa and odd > 1.0:
            odds[casa] = odd
    return odds


def escolher_casa(pernas, odd_min: float, odd_max: float) -> tuple | None:
    """(casa, odds_por_perna) da melhor casa que cobre o bilhete inteiro.

    `odds_por_perna` sai na MESMA ordem de `pernas` -- None em cada perna que
    nao trouxe cotacao nenhuma (ver abaixo), pra ela seguir com a odd que ja'
    tinha. Devolve None quando nenhuma casa cota todas as pernas informadas
    dentro da faixa.

    Perna SEM cotacao nenhuma nao trava o bilhete: ela nao tem como contradizer
    a casa escolhida, e travar aqui derrubaria o produto inteiro no dia em que
    a lista de casas nao chegar. Quando NENHUMA perna traz cotacao, nao ha'
    informacao pra decidir e o bilhete segue como antes, com casa vazia.
    """
    pernas = list(pernas)
    if not pernas:
        return None

    mapas = [_odds_por_casa(p) for p in pernas]
    informados = [m for m in mapas if m]
    if not informados:
        return "", [None] * len(pernas)

    comuns = set(informados[0])
    for m in informados[1:]:
        comuns &= set(m)
    if not comuns:
        return None

    melhor = None
    for casa in sorted(comuns):
        odds = [m.get(casa) if m else None for m in mapas]
        if any(o is not None and not (odd_min <= o <= odd_max) for o in odds):
            continue
        combinada = 1.0
        for o in odds:
            if o is not None:
                combinada *= o
        if melhor is None or combinada > melhor[0]:
            melhor = (combinada, casa, odds)

    if melhor is None:
        return None
    return melhor[1], melhor[2]


def aplicar_casa(pernas, odd_min: float, odd_max: float) -> tuple | None:
    """Reprecifica o bilhete inteiro na casa unica.

    Devolve (pernas_reprecificadas, casa, odd_total) ou None quando nao ha'
    casa comum. Cada perna volta como COPIA com:

      odd             -- a odd daquela casa (e' a que o site publica e a que o
                         usuario encontra ao abrir o bilhete)
      best_bookmaker  -- a casa unica
      odd_consenso    -- a odd de avaliacao que passou pelos gates, preservada
                         pra auditoria poder comparar depois
      ev              -- recalculado sobre a odd nova, pra o numero gravado nao
                         descrever um preco que o bilhete nao tem

    `taxa_real`, `confidence` e o resto do rastro nao mudam: a casa nao altera
    a estimativa, so' o preco.
    """
    escolha = escolher_casa(pernas, odd_min, odd_max)
    if escolha is None:
        return None
    casa, odds = escolha

    novas = []
    odd_total = 1.0
    for perna, odd in zip(pernas, odds):
        if odd is None:
            # Sem cotacao propria: fica com o preco que ja' tinha e com a casa
            # do bilhete quando existe uma.
            nova = {**perna}
            if casa:
                nova["best_bookmaker"] = casa
            odd_total *= float(perna["odd"])
            novas.append(nova)
            continue
        odd = round(float(odd), 2)
        nova = {**perna,
                "odd_consenso": perna.get("odd"),
                "odd": odd,
                "best_bookmaker": casa}
        try:
            nova["ev"] = round(float(perna["taxa_real"]) * odd - 1.0, 4)
        except (KeyError, TypeError, ValueError):
            pass
        novas.append(nova)
        odd_total *= odd

    return novas, casa, round(odd_total, 4)
