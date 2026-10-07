"""Chave do árbitro: o mesmo nome escrito de jeitos diferentes vira UMA pessoa.

POR QUE EXISTE (2026-10-07)
---------------------------
Árbitro se liga à partida pelo NOME (`match_statistics.referee`), porque é só
isso que a API-Football entrega. E ela escreve a mesma pessoa de mais de um
jeito, conforme a competição: "Raphael Claus" num jogo, "Raphael Claus, Brazil"
no outro, "Raphael  Claus" com espaço duplo, com acento ou sem. Todo o projeto
comparava o texto exato (`WHERE referee = %s`). Cada grafia virava um árbitro
separado, com a amostra partida em pedaços, e o jogo de hoje achava só o
pedaço que tivesse a grafia de hoje. O resultado era cair no fallback da liga,
ou no gate "árbitro sem dado confiável", com o histórico dele gravado no banco.

O QUE A CHAVE IGNORA: o país depois da vírgula, acento, caixa, ponto e espaço
repetido. O QUE ELA NÃO TENTA: juntar abreviação ("R. Claus") com o nome
inteiro. Dois árbitros diferentes podem abreviar igual, e juntar pessoas
diferentes é pior do que deixar uma amostra partida.

A MESMA REGRA EM DOIS LUGARES, DE PROPÓSITO: `chave_do_arbitro` (Python, pro
parâmetro) e `sql_chave` (SQL, pra coluna). As duas usam as mesmas tabelas de
acento abaixo. O site tem uma cópia em website/backend/arbitro.py, e há teste
cobrando que as duas fiquem iguais.
"""
import re

#: Letras acentuadas e o equivalente sem acento, posição por posição.
COM_ACENTO = "ÁÀÂÃÄÅáàâãäåÉÈÊËéèêëÍÌÎÏíìîïÓÒÔÕÖØóòôõöøÚÙÛÜúùûüÇçÑñÝýÿŠšŽžČčĆćŁłŞşĞğ"
SEM_ACENTO = "AAAAAAaaaaaaEEEEeeeeIIIIiiiiOOOOOOooooooUUUUuuuuCcNnYyySsZzCcCcLlSsGg"

_TABELA = str.maketrans(COM_ACENTO, SEM_ACENTO)


def chave_do_arbitro(nome: str | None) -> str | None:
    """'Raphael Claus, Brazil' -> 'raphael claus'. None sem nome."""
    if not nome:
        return None
    base = nome.split(",", 1)[0].translate(_TABELA).lower()
    base = re.sub(r"[.\s]+", " ", base).strip()
    return base or None


def sql_chave(coluna: str) -> str:
    """A mesma chave como expressão SQL sobre `coluna`.

    Só usa funções IMMUTABLE (split_part, translate, lower, regexp_replace,
    btrim), então serve de índice de expressão. Nenhum `%` no texto: ela entra
    em consulta com parâmetro do psycopg2 sem precisar de escape.
    """
    return (f"NULLIF(btrim(regexp_replace(lower(translate(split_part({coluna}, ',', 1), "
            f"'{COM_ACENTO}', '{SEM_ACENTO}')), '[.[:space:]]+', ' ', 'g')), '')")
