"""O `src/` do motor no sys.path nao pode sombrear os modulos do site.

O QUE ACONTECEU
---------------
O backend precisa do motor no `sys.path` pra reusar `services`, `utils` e
`collectors` em vez de reimplementar liquidacao e coleta. Tres pontos montavam
esse caminho, e os tres com `insert(0, ...)`: `settlement_bridge` (no import do
modulo, permanente), `routers/admin.py::_no_path` (idem) e o proprio
`ApostaEsportivas/src/main.py`, que o /admin carrega por caminho pra ler o
registro de COMANDOS.

Os dois lados tem modulo de topo com o mesmo nome -- `main` e `run_dev` -- e na
frente do path quem ganha e' o motor. A partir do primeiro import de qualquer
um dos tres, `import main` no processo devolvia o CLI do motor em vez do app
FastAPI.

Em producao nunca apareceu, porque o `main` do site ja' esta' em `sys.modules`
antes de qualquer router ser importado. Na suite aparecia como 22 falhas em
tres arquivos ("module 'main' has no attribute 'app'") que PASSAVAM quando
rodados sozinhos -- o sintoma de ordem, que faz procurar o defeito no arquivo
errado. Ficaram meses assim.

A REGRA, ENTAO: o motor entra no FIM do path. `services`, `utils`,
`collectors` e `engine_pipelines` so' existem de um lado, entao pra eles a
posicao e' indiferente; `main` e `run_dev` existem nos dois, e o dono do
processo tem que ganhar.
"""
import os
import re
import subprocess
import sys

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_RAIZ = os.path.abspath(os.path.join(_BACKEND, "../.."))
_MOTOR = os.path.join(_RAIZ, "ApostaEsportivas", "src")

#: `insert(0` num caminho que termine em src/ do motor. Pega as tres formas que
#: existiam (variavel, chamada e literal) sem depender do nome da variavel.
_INSERT_NO_INICIO = re.compile(r"sys\.path\.insert\s*\(\s*0\s*,")


def _fontes_do_backend():
    for base, _dirs, arquivos in os.walk(_BACKEND):
        if any(p in base for p in ("__pycache__", os.sep + "tests", os.sep + "dist",
                                   os.sep + "static", os.sep + "migrations")):
            continue
        for nome in arquivos:
            if nome.endswith(".py"):
                yield os.path.join(base, nome)


def test_nenhum_modulo_do_backend_poe_o_motor_na_frente():
    """Varredura de fonte: `insert(0, ...)` e' o defeito, `append` e' o certo.

    So' `run_dev.py` pode: ele poe o PROPRIO diretorio do backend na frente,
    que e' o oposto do problema.
    """
    infratores = []
    for caminho in _fontes_do_backend():
        with open(caminho, encoding="utf-8", errors="replace") as fh:
            for numero, linha in enumerate(fh, 1):
                if not _INSERT_NO_INICIO.search(linha):
                    continue
                if os.path.basename(caminho) == "run_dev.py":
                    continue
                infratores.append(f"{os.path.relpath(caminho, _RAIZ)}:{numero}")
    assert not infratores, (
        "sys.path.insert(0, ...) poe o motor na frente e sombreia `main` do "
        f"site. Use append: {infratores}")


def test_o_main_do_motor_tambem_entra_pelo_fim():
    """Ele e' carregado por caminho pelo /admin, entao o insert dele vaza pro
    processo do site."""
    with open(os.path.join(_MOTOR, "main.py"), encoding="utf-8") as fh:
        cabeca = "".join(fh.readlines()[:80])
    assert not _INSERT_NO_INICIO.search(cabeca)
    assert "sys.path.append" in cabeca


@pytest.mark.skipif(not os.path.isdir(_MOTOR), reason="motor fora do checkout")
def test_importar_o_bridge_nao_troca_o_main_do_processo():
    """A prova de verdade, em processo proprio: depois de importar
    `settlement_bridge` -- que e' quem monta o caminho no import --, `main`
    ainda tem que ser o app do site."""
    codigo = (
        "import sys, os;"
        "sys.path.insert(0, os.getcwd());"
        "import settlement_bridge;"
        "import main;"
        "print(main.__file__)"
    )
    saida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=_BACKEND, capture_output=True,
        text=True, timeout=120,
        env={**os.environ, "JWT_SECRET": "teste-de-suite",
             "ENVIRONMENT": "development"},
    )
    assert saida.returncode == 0, saida.stderr[-1500:]
    resolvido = os.path.abspath(saida.stdout.strip().splitlines()[-1])
    assert resolvido == os.path.join(_BACKEND, "main.py"), (
        f"`import main` resolveu para {resolvido}")
