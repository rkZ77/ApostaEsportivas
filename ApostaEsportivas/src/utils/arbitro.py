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


# ── NOME COMPLETO, NOME CURTO E ABREVIAÇÃO (18/10/2026) ──────────────────────
# A API escreve a mesma pessoa de três jeitos na mesma temporada. Medido em
# PROD no Ramon Abatti (Brasileirão 2026, 16 jogos): "R. Abatti" 11,
# "Ramon Abatti" 4, "Ramon Abatti Abel, Brazil" 1. Pela chave sozinha o
# Raio-X via 4.
#
# AS REGRAS, nesta ordem:
#  1. Nome curto (2 palavras ou mais) é a mesma pessoa do nome longo que COMEÇA
#     com ele, se só existir UM nome longo assim ("ramon abatti" e "ramon
#     abatti abel").
#  2. Abreviação ("r abatti": primeira palavra de uma letra) é a mesma pessoa
#     dos nomes completos com a mesma inicial em que o resto APARECE, em
#     sequência ("p zanovelli" em "paulo cesar zanovelli da silva": a API
#     abrevia pelo sobrenome mais conhecido, nem sempre o primeiro). Junta só
#     se todos esses nomes tiverem o MESMO primeiro nome: com "rafael silva" e
#     "roberto silva" no banco, "r silva" fica sozinho -- juntar pessoas
#     diferentes é pior que deixar a amostra partida.
#
#  Simulado em PROD em 18/10/2026: de 428 grafias abreviadas, 310 juntam
#  (1.504 jogos que estavam soltos) e 11 ficam sozinhas por ambiguidade
#  ("j pinheiro" tem três Pinheiros com J; "d silva" tem três Silvas).

def _comeca_com(longo: list, curto: list) -> bool:
    return len(longo) > len(curto) and longo[:len(curto)] == curto


def _abreviado(t: list) -> bool:
    return len(t) >= 2 and len(t[0]) == 1


def chaves_equivalentes(chave: str | None, conhecidas) -> list:
    """As chaves da MESMA pessoa entre as `conhecidas` (inclui a própria)."""
    if not chave:
        return []
    todas = {c for c in set(conhecidas or ()) if c} | {chave}
    pai = {c: c for c in todas}

    def raiz(c):
        while pai[c] != c:
            pai[c] = pai[pai[c]]
            c = pai[c]
        return c

    def unir(a, b):
        pai[raiz(a)] = raiz(b)

    partes = {c: c.split() for c in todas}
    completas = [c for c in todas if not _abreviado(partes[c])]
    for curta in completas:                                   # regra 1
        if len(partes[curta]) < 2:
            continue
        longas = [c for c in completas if _comeca_com(partes[c], partes[curta])]
        if len(longas) == 1:
            unir(curta, longas[0])
    for abrev in [c for c in todas if _abreviado(partes[c])]:  # regra 2
        inicial, resto = partes[abrev][0], " " + " ".join(partes[abrev][1:]) + " "
        compativeis = [c for c in completas
                       if len(partes[c]) >= 2 and partes[c][0][0] == inicial
                       and resto in " " + " ".join(partes[c][1:]) + " "]
        if compativeis and len({partes[c][0] for c in compativeis}) == 1:
            for c in compativeis:
                unir(abrev, c)
    alvo = raiz(chave)
    return sorted(c for c in todas if raiz(c) == alvo)


def sql_candidatas(coluna: str) -> str:
    """Chaves da coluna que podem ser a mesma pessoa: as que começam com a
    mesma LETRA (o nome curto, o longo e a abreviação começam todos igual).
    Parâmetro em `parametros_candidatas`. Sem `%` no texto."""
    return f"left({sql_chave(coluna)}, 1) = %s"


def parametros_candidatas(chave: str) -> tuple:
    return (chave[:1],)
