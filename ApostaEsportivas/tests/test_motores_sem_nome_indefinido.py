"""Nenhum motor pode ter nome indefinido.

REGRESSAO REAL (2026-08-28). O pipeline de faltas usava `context_gate` e
`tie_effect` sem importar nenhum dos dois. Nao era erro de import -- o modulo
carregava normalmente; o NameError so' estourava na linha 298, ja' dentro do
laco de fixtures, onde ha' um `except Exception` que registra "erro ao avaliar
o fixture" e segue pro proximo jogo.

O resultado era um motor que rodava, imprimia resumo, fechava a execucao com
status COMPLETED -- e descartava TODA partida que chegasse ao ponto de ser
avaliada de verdade (as outras morriam antes, por historico ou falta de
oferta, e produziam a mesma linha de descarte). Nenhum sintoma apontava pra um
import faltando.

Um `python -m pyflakes` teria pego os dois em um segundo. Por isso o teste
existe: e' barato, e o custo de nao ter e' um motor silenciosamente morto.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

#: Tudo que decide pick. Nao varre o projeto inteiro de proposito: scripts
#: soltos e codigo de IA legado tem pendencia propria e reprovariam o teste por
#: motivo que nao e' este.
PASTAS = (
    "engine_pipelines",
    "services/pick_engine",
    "services/pick_engine_live",
    "services/pick_engine_boost",
    "services/player_stats_engine",
    "services/engine_audit",
)


@pytest.mark.parametrize("pasta", PASTAS)
def test_sem_nome_indefinido(pasta):
    arquivos = sorted(str(p) for p in (SRC / pasta).glob("*.py"))
    assert arquivos, f"{pasta} sem arquivo .py · caminho errado?"

    saida = subprocess.run(
        [sys.executable, "-m", "pyflakes", *arquivos],
        capture_output=True, text=True, cwd=SRC,
    ).stdout

    # So' nome indefinido. pyflakes tambem reclama de import nao usado e de
    # star-import, que sao estilo -- travar isso aqui transformaria o teste
    # num linter e ele passaria a reprovar por coisa que nao quebra motor.
    culpados = [l for l in saida.splitlines() if "undefined name" in l]
    assert not culpados, "nome indefinido em motor:\n" + "\n".join(culpados)
