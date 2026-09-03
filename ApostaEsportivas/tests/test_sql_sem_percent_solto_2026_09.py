"""Um `%` escrito dentro de um SQL derruba a consulta inteira.

O CASO, DUAS VEZES NO MESMO DIA (2026-09-02)
---------------------------------------------
Comentario dentro do SQL com um numero em porcentagem:

    -- tem cobertura de 100% (medido: zero nulos)      <- player_history
    -- "saves" volta null em 59% das atuacoes          <- coletor de jogador

O psycopg2 le' `%` como inicio de placeholder e estoura
`IndexError: tuple index out of range` -- sem citar a linha do comentario, sem
dizer que o problema e' um texto. No coletor, o efeito foi
"0 linhas de jogador gravadas" em TODAS as fixtures, com a mensagem
generica "Erro na fixture X, pulando" repetida vinte vezes.

E' um erro de escrita que parece erro de dados, e por isso custa caro achar.

O QUE ESTE TESTE FAZ
--------------------
Le os SQL do codigo do motor e exige que todo `%` seja `%s` ou `%%`. Nao
interpreta SQL: procura o caractere onde ele nao pode estar.
"""
import os
import re

RAIZ = os.path.join(os.path.dirname(__file__), "..", "src")

#: Trecho entre aspas triplas que contem palavra-chave de SQL. Nao e' um parser
#: -- e' o recorte mais simples que pega o caso real, que e' sempre um bloco
#: `cur.execute("""...""")`.
_BLOCO = re.compile(r'"""(.*?)"""', re.DOTALL)
_E_SQL = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b.*\b(FROM|INTO|SET|VALUES|WHERE)\b",
    re.IGNORECASE | re.DOTALL)

#: `%` valido: o placeholder `%s` e os operadores de format() (`%I`, `%L`).
#: O escape `%%` sai ANTES da busca -- olhar so' o proximo caractere marcaria o
#: segundo `%` de um `%%round%%` como solto, que e' justamente a forma correta
#: de escrever LIKE em SQL parametrizado.
_PERCENT_INVALIDO = re.compile(r"%(?![sIL])")


def _sem_escapes(sql: str) -> str:
    """Troca cada `%%` por dois espacos, preservando as posicoes."""
    return sql.replace("%%", "  ")


def _arquivos_python():
    for pasta, _dirs, arquivos in os.walk(RAIZ):
        if "__pycache__" in pasta:
            continue
        for nome in arquivos:
            if nome.endswith(".py"):
                yield os.path.join(pasta, nome)


def test_nenhum_sql_tem_percent_solto():
    problemas = []
    for caminho in _arquivos_python():
        with open(caminho, encoding="utf-8") as f:
            fonte = f.read()
        for bloco in _BLOCO.findall(fonte):
            if not _E_SQL.search(bloco):
                continue
            for achado in _PERCENT_INVALIDO.finditer(_sem_escapes(bloco)):
                inicio = max(0, achado.start() - 60)
                trecho = " ".join(bloco[inicio:achado.start() + 5].split())
                problemas.append(
                    f"{os.path.relpath(caminho, RAIZ)}: ...{trecho}")

    assert not problemas, (
        "`%` solto dentro de SQL — o psycopg2 lê como placeholder e a consulta "
        "estoura com IndexError. Escreva 'por cento' ou escape com %%:\n  "
        + "\n  ".join(problemas))
