"""A conta de taxa de acerto do site, escrita uma vez só.

POR QUE ESTE ARQUIVO EXISTE

A mesma pergunta ("quantos por cento a IA acerta?") era respondida por oito
lugares diferentes do backend, e sete deles faziam `greens / total`. Isso erra
em dois casos que o motor produz todos os dias:

  PUSH      anulada -- ninguem ganhou nem perdeu. Ficava no denominador,
            puxando a taxa pra baixo como se fosse derrota. A anulacao por
            falta de estatistica (ver o motor) torna isso comum.
  HALF-WIN  linha asiatica que ganhou metade. E' acerto, e sumia da conta.

O resultado aparecia na tela: a mesma base de 780 picks saia 63,3% no topo da
aba Picks e 66% na pagina de Resultados, porque so' esta ultima descontava as
anuladas. Duas telas do mesmo produto discordando em publico e' pior que um
numero conservador -- quem compara conclui que uma das duas mente.

A regra e' a do `taxaAcerto` de frontend/src/utils/format.ts, e as duas
precisam continuar iguais: meio-green conta como acerto, anulada sai do
denominador, HALF-LOSS continua derrota.
"""


def taxa_acerto(greens: int, total: int, half_wins: int = 0, push: int = 0) -> float:
    """Percentual de acerto com uma casa decimal. `total` e' o resolvido.

    Devolve 0.0 quando nao sobra nada no denominador (dia sem pick liquidado,
    ou um conjunto so' de anuladas).
    """
    resolvidos = (total or 0) - (push or 0)
    if resolvidos <= 0:
        return 0.0
    return round(((greens or 0) + (half_wins or 0)) / resolvidos * 100, 1)
