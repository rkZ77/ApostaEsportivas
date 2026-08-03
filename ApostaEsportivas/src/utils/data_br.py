"""Data corrente e data de jogo em horario de Brasilia, para SQL.

POR QUE ISSO EXISTE
-------------------
O banco roda em UTC (`SHOW timezone` = UTC), entao `CURRENT_DATE` e' a data
UTC. O produto e' brasileiro: usuario, horario de publicacao e a coluna
`match_date` das tabelas de pick sao todos em horario de Brasilia.

Entre 21:00 e 00:00 de Brasilia as duas datas divergem -- o banco ja virou o
dia e o Brasil nao. Todo pipeline filtrava `f.match_datetime::date =
CURRENT_DATE`, entao rodar o pipeline nesse intervalo procurava os jogos do
dia SEGUINTE e nao achava nada. Foi o que aconteceu em 2026-08-02: 4 jogos e
10.659 odds no banco, e todos os pipelines dizendo "nenhum jogo de hoje".

QUAL COLUNA PRECISA DE CONVERSAO
--------------------------------
`fixtures.match_datetime` NAO precisa: o coletor ja grava em horario de
Brasilia (`convert_utc_to_br_naive` em fixture_collector_service.py). Comparar
direto: `f.match_datetime::date = HOJE_BR`. Converter de novo tiraria 3 horas
e jogava pro dia anterior tudo que comeca entre 00:00 e 02:59 BR -- justamente
os jogos de virada de meia-noite que o coletor faz questao de incluir.

`match_statistics.match_date` E' UTC (aquele collector guarda o ISO da API sem
converter). Essa sim precisa de `data_br()`.

Duas convencoes na mesma base, cada uma escrita por um collector diferente.
Antes de comparar data de uma coluna nova, conferir qual dos dois casos ela e'.

COMO USAR
---------
    from utils.data_br import HOJE_BR, data_br

    f"WHERE f.match_datetime::date = {HOJE_BR}"        # coluna ja em BR
    f"WHERE {data_br('ms.match_date')} = {HOJE_BR}"    # coluna em UTC

Sao fragmentos de SQL, nao parametros: entram por f-string. Nao recebem
entrada de usuario -- `data_br` so' e' chamado com nome de coluna escrito no
proprio codigo.
"""

TZ_BR = "America/Sao_Paulo"

# Data de hoje em Brasilia. Substitui CURRENT_DATE em tudo que e' "do dia".
HOJE_BR = f"((NOW() AT TIME ZONE '{TZ_BR}')::date)"


def data_br_de(dt):
    """Versao Python de `data_br`, pra quando a data ja veio pro processo.

    `match_datetime` chega do banco como datetime ingenuo em UTC. Chamar
    `.date()` direto nele devolve a data UTC -- que e' o dia seguinte pra
    qualquer jogo a partir de 21:00 de Brasilia. Recebe None e devolve None.
    """
    if dt is None:
        return None
    from datetime import timezone
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(TZ_BR)).date()


def data_br(coluna: str) -> str:
    """Data brasileira de uma coluna `timestamp without time zone` em UTC.

    O primeiro AT TIME ZONE diz "esse timestamp ingenuo e' UTC" e devolve
    timestamptz; o segundo converte pra Brasilia. A ordem importa: inverter
    da' um resultado que parece certo e erra por 6 horas.
    """
    return f"(({coluna}) AT TIME ZONE 'UTC' AT TIME ZONE '{TZ_BR}')::date"
