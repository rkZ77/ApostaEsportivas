"""Quem promete (candidato, motivo) tem que devolver os dois em TODO caminho.

O defeito que motivou o teste, achado em 15/09/2026 no motor de faltas: em
11/09 `_avaliar_fixture` passou a devolver `(candidato, motivo)` pra o log
poder nomear o descarte, e todos os `return None, motivo` foram escritos --
menos o do SUCESSO, que continuou devolvendo o dicionario sozinho.

Como o chamador faz `c, motivo = _avaliar_fixture(...)`, desempacotar um dict
de vinte chaves em duas variaveis levanta "too many values to unpack". O
`except` em volta registrava "erro ao avaliar o fixture" e seguia pro proximo
jogo, entao o motor SO' CONSEGUIA REJEITAR -- sem uma linha de erro no deploy,
sem teste vermelho, e com o log parecendo um dia sem candidato. O ultimo pick
de faltas em PROD era de 09/09, e em 12/09 havia quatro fixtures morrendo
nessa excecao: as quatro que teriam virado pick.

Por que AST e nao um pick de mentira: o caminho de sucesso de um pipeline
desses precisa de historico, odds, arbitro, classificacao e calibragem
casando ao mesmo tempo, e um teste que monta tudo isso testa a montagem, nao
o contrato. O que quebrou aqui foi a FORMA do retorno, e a forma da' pra ler
direto do modulo -- em todos os pipelines de uma vez, inclusive nos que ainda
nem existem.
"""
import ast
import pathlib

import pytest

PIPELINES = pathlib.Path(__file__).resolve().parents[1] / "src" / "engine_pipelines"


def _funcoes_desempacotadas_em_dois(arvore: ast.AST) -> set[str]:
    """Nomes de funcoes do proprio modulo cujo retorno o modulo desempacota
    em duas variaveis (`a, b = f(...)`)."""
    alvos = set()
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Assign) or len(no.targets) != 1:
            continue
        destino = no.targets[0]
        if not isinstance(destino, ast.Tuple) or len(destino.elts) != 2:
            continue
        chamada = no.value
        if isinstance(chamada, ast.Call) and isinstance(chamada.func, ast.Name):
            alvos.add(chamada.func.id)
    return alvos


def _retornos_proprios(funcao: ast.FunctionDef) -> list[ast.Return]:
    """Os `return` DESTA funcao, sem os das funcoes aninhadas dentro dela --
    `_split` e `par` devolvem tupla por conta propria e nao dizem nada sobre
    o contrato de quem as contem."""
    aninhadas = {n for f in ast.walk(funcao)
                 if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f is not funcao
                 for n in ast.walk(f)}
    return [n for n in ast.walk(funcao)
            if isinstance(n, ast.Return) and n not in aninhadas]


@pytest.mark.parametrize("caminho", sorted(PIPELINES.glob("*_pipeline.py")),
                          ids=lambda p: p.stem)
def test_retorno_de_par_e_sempre_um_par(caminho):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    alvos = _funcoes_desempacotadas_em_dois(arvore)

    for no in ast.walk(arvore):
        if not isinstance(no, ast.FunctionDef) or no.name not in alvos:
            continue
        for retorno in _retornos_proprios(no):
            valor = retorno.value
            # `return` puro devolve None, e `c, motivo = None` quebra igual.
            assert valor is not None, (
                f"{caminho.name}::{no.name} linha {retorno.lineno}: `return` "
                f"sem valor, mas o modulo desempacota o retorno em dois")
            assert isinstance(valor, ast.Tuple) and len(valor.elts) == 2, (
                f"{caminho.name}::{no.name} linha {retorno.lineno}: devolve "
                f"{type(valor).__name__}, e o modulo desempacota em dois -- "
                f"e' o bug de faltas de 11/09 (ver a docstring deste arquivo)")
