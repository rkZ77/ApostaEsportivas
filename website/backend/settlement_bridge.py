"""Reexporta o modulo de liquidacao do motor pro backend do site.

`services/settlement.py` vive em ApostaEsportivas/src/ e e' a fonte unica da
matematica de GREEN/RED/PUSH/HALF-*. O backend precisa da MESMA implementacao
(nao de uma copia): foi ter duas que produziu, entre outras divergencias, um
PUSH de perna virando RED de um lado e PUSH do bilhete inteiro do outro.

O Dockerfile copia ApostaEsportivas/src/ pra /app/pipeline e exporta
PIPELINE_SRC_PATH; em desenvolvimento o caminho relativo resolve sozinho.
Mesma busca de diretorio ja usada por routers/admin.py::_find_pipeline_dir.

O import e' obrigatorio de proposito -- sem ele nao existe fallback "meia
boca" que liquide pick de um jeito diferente; a API sobe com erro claro no
lugar de gradear errado em silencio.
"""

import os
import sys


def _pipeline_dir() -> str:
    if env := os.getenv("PIPELINE_SRC_PATH"):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.abspath(os.path.join(here, "../../ApostaEsportivas/src")),
        os.path.abspath(os.path.join(os.getcwd(), "ApostaEsportivas/src")),
        os.path.abspath(os.path.join(here, "pipeline")),
    ):
        if os.path.isdir(candidate):
            return candidate
    return ""


_DIR = _pipeline_dir()
if _DIR and _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from services import settlement  # noqa: E402

__all__ = ["settlement"]
