"""CORRELATION_SCORE: quanto duas pernas deixam de ser duas apostas.

O PRODUTO ASSUME INDEPENDENCIA, E A INDEPENDENCIA FOI MEDIDA
------------------------------------------------------------
`prob_combinada = p1 * p2` so' vale se as pernas forem independentes. Em
2026-08-20 isso foi medido em 2.677 bilhetes de 2 pernas, fora da amostra:

    recorte                bilhetes   produto diz   real     erro
    mesma familia               717        71.5%   72.5%   -1.0pp
    familias diferentes       1.960        70.1%   70.8%   -0.7pp

O produto e' praticamente nao-enviesado, e perna repetida NAO e' pior. Por
isso este modulo NAO reintroduz um piso de prob_combinada nem proibe familia
repetida entre jogos diferentes: isso ja' foi proposto, medido e reprovado, e
refazer a regra contra a medicao seria trocar dado por intuicao.

O QUE A MEDICAO NAO COBRE, E E' O QUE ESTE MODULO TRATA
-------------------------------------------------------
Aqueles 2.677 bilhetes sao todos de JOGOS DIFERENTES. A dependencia que fica
de fora e' a do MESMO jogo, e ela nao e' simetrica:

  * duas pernas de Over no mesmo jogo sao positivamente correlacionadas na
    direcao "o jogo abriu" -- ganham juntas mais vezes do que o produto diz,
    o que torna o produto CONSERVADOR (erra pro lado certo);
  * uma perna de Over com uma de Under no mesmo jogo e' o caso contrario, e
    o produto passa a ANUNCIAR MAIS chance do que existe.

Como o segundo caso existe e nao ha' medicao propria pra ele, a V2 escolhe o
caminho conservador: MESMO JOGO e' HIGH e nao combina por padrao (o teto
`MAX_PERNAS_MESMO_JOGO` diz a mesma coisa do outro lado). Isso APERTA o que a
V1 permitia desde 28/08 -- e aperta de proposito, a pedido de 11/09.

UNKNOWN NAO E' LOW
------------------
Quando o par nao se encaixa em nenhuma regra conhecida (mercado sem familia
resolvida, liga ausente), a resposta e' UNKNOWN e ela PAGA penalidade. Tratar
desconhecido como independente e' a forma mais comum de inflar a probabilidade
de um bilhete sem nunca escrever um numero errado.
"""
from __future__ import annotations

from itertools import combinations

from services.pick_engine_multipla import component
from services.pick_engine_multipla import config as cfg


LOW, MEDIUM, HIGH, UNKNOWN = "LOW", "MEDIUM", "HIGH", "UNKNOWN"

_ORDEM = (LOW, MEDIUM, UNKNOWN, HIGH)


def _direcao(perna: dict) -> str:
    """over / under / outra. E' o que separa "as duas pernas querem o mesmo
    jogo" de "uma quer o oposto da outra"."""
    valor = (perna.get("_direction") or perna.get("value") or "").strip().lower()
    if valor in ("over", "under"):
        return valor
    return "outra"


def classificar_par(a: dict, b: dict) -> tuple[str, str]:
    """(nivel, motivo) da correlacao entre duas pernas."""
    jogo_a, jogo_b = component.jogo(a), component.jogo(b)
    fam_a, fam_b = component.familia(a), component.familia(b)

    if not fam_a or not fam_b:
        return UNKNOWN, "familia de mercado nao resolvida em uma das pernas"

    if jogo_a is None or jogo_b is None:
        return UNKNOWN, "perna sem jogo identificado"

    if jogo_a == jogo_b:
        if fam_a == fam_b:
            return HIGH, "mesma partida e mesma familia de mercado"
        if _direcao(a) != _direcao(b) and "outra" not in (_direcao(a), _direcao(b)):
            return HIGH, "mesma partida em direcoes opostas (Over contra Under)"
        return HIGH, "mesma partida: as duas pernas dependem do mesmo jogo"

    if component.times(a) & component.times(b):
        return HIGH, "a mesma equipe sustenta as duas pernas"

    liga_a, liga_b = component.liga(a), component.liga(b)
    if liga_a is not None and liga_a == liga_b and fam_a == fam_b:
        # Mesma rodada, mesma liga, mesmo mercado: arbitragem, calendario e
        # estilo de competicao sao compartilhados. Nao e' o mesmo jogo, mas
        # tambem nao e' sorteio independente.
        return MEDIUM, "mesma liga e mesma familia de mercado"

    if fam_a == fam_b:
        # Medido em 2026-08-20: sem vies detectavel entre jogos diferentes.
        return LOW, "familias iguais em ligas diferentes (independencia medida)"

    return LOW, "jogos, equipes e familias diferentes"


def do_combo(pernas) -> dict:
    """Correlacao do bilhete inteiro: manda o PIOR par.

    Media de correlacao esconderia exatamente o caso que importa -- um
    bilhete de tres pernas com dois pares LOW e um HIGH nao e' "quase
    independente", e' um bilhete de duas apostas vendido como tres.
    """
    pares = []
    pior = LOW
    for a, b in combinations(pernas, 2):
        nivel, motivo = classificar_par(a, b)
        pares.append({"nivel": nivel, "motivo": motivo})
        if _ORDEM.index(nivel) > _ORDEM.index(pior):
            pior = nivel

    return {
        "nivel": pior,
        "nota": cfg.NOTA_CORRELACAO.get(pior, 0.0),
        "penalidade": cfg.PENALIDADE_CORRELACAO.get(pior, 1.0),
        "pares": pares,
    }


def prob_ajustada(prob_produto_calibrado: float, correlacao: dict) -> float:
    """P_combined_adjusted: o produto das probabilidades CALIBRADAS,
    descontado do que ele ainda nao sabe.

    A INCERTEZA DA AMOSTRA JA' FOI COBRADA, e por isso nao aparece aqui: ela
    esta' dentro de cada `probabilidade_calibrada` (component.py). Descontar
    de novo neste ponto seria cobrar a mesma evidencia duas vezes -- o erro
    que o motor ja' evitou uma vez quando tirou convergence_adjustment das
    familias com sinal de Poisson.

    Sobra a CORRELACAO, que e' a unica coisa que o produto de fato ignora.
    HIGH nem chega aqui: o combo e' descartado antes de ser pontuado.

    Nunca ajusta pra cima. Duas pernas de Over no mesmo jogo MERECERIAM
    ajuste positivo (a dependencia ali e' favoravel), e mesmo assim nao
    recebem -- errar pro lado conservador e' a unica assimetria que nao custa
    dinheiro.
    """
    ajustada = float(prob_produto_calibrado) * (
        1.0 - float(correlacao.get("penalidade") or 0.0))
    return round(max(0.0, min(1.0, ajustada)), 4)
