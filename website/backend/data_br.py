"""Data corrente em horario de Brasilia, para SQL.

O banco roda em UTC, entao `CURRENT_DATE` e' a data UTC. O produto e'
brasileiro: `picks_*.match_date` e tudo que a tela chama de "hoje" sao em
horario de Brasilia.

Entre 21:00 e 00:00 de Brasilia as duas datas divergem -- o banco ja virou o
dia e o Brasil nao. Foi o que aconteceu em 2026-08-02: 4 picks VIP gravados
com match_date 02/08 e o painel do admin mostrando "0 picks hoje", porque
comparava com CURRENT_DATE, que ja era 03/08.

O gemeo deste arquivo no motor e' ApostaEsportivas/src/utils/data_br.py --
os dois precisam concordar, senao o pipeline grava num dia e a tela procura
noutro.
"""

TZ_BR = "America/Sao_Paulo"

HOJE_BR = f"((NOW() AT TIME ZONE '{TZ_BR}')::date)"


def data_br(coluna: str) -> str:
    """Data brasileira de uma coluna `timestamp without time zone` em UTC.

    O primeiro AT TIME ZONE diz "esse timestamp ingenuo e' UTC"; o segundo
    converte pra Brasilia. Inverter a ordem erra por 6 horas em silencio.
    """
    return f"(({coluna}) AT TIME ZONE 'UTC' AT TIME ZONE '{TZ_BR}')::date"
