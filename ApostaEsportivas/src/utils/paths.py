"""Caminhos fixos do pipeline, ancorados no arquivo e nao no cwd.

Todo modulo que grava .jsonl montava o proprio caminho com um numero
diferente de "..", e nem todos passavam por abspath(). Sem abspath, quando
__file__ chega relativo (script chamado por caminho relativo, com o cwd em
outro lugar), o join vira um caminho relativo ao cwd e o arquivo aparece
num diretorio "logs" paralelo -- foi assim que ApostaEsportivas/src/logs/
nasceu, ao lado do ApostaEsportivas/logs/ de verdade.

Uma constante so, resolvida uma vez, elimina as duas armadilhas.
"""
import os

# utils/paths.py -> src/ -> ApostaEsportivas/
PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOGS_DIR = os.path.join(PIPELINE_ROOT, "logs")


def log_path(filename: str) -> str:
    """Caminho absoluto de um .jsonl dentro de ApostaEsportivas/logs/."""
    return os.path.join(LOGS_DIR, filename)
