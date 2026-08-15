"""
Localiza ffmpeg e ffprobe.

O winget instala o Gyan.FFmpeg e mexe no PATH, mas o aviso dele é literal: só
vale em shell novo. Então não dá pra confiar só em `shutil.which` na mesma
sessão em que foi instalado · aqui procura no PATH primeiro e cai no diretório
de pacotes do winget depois.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


def _do_winget(nome: str) -> Path | None:
    raiz = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not raiz.is_dir():
        return None
    for pasta in raiz.glob("Gyan.FFmpeg*"):
        for achado in pasta.rglob(nome):
            return achado
    return None


@lru_cache(maxsize=4)
def binario(nome: str) -> str:
    """Caminho de 'ffmpeg' ou 'ffprobe'. Levanta se não achar."""
    exe = nome if os.name != "nt" else f"{nome}.exe"

    no_path = shutil.which(nome)
    if no_path:
        return no_path

    achado = _do_winget(exe)
    if achado:
        return str(achado)

    raise RuntimeError(
        f"{nome} não encontrado. Instale com:  winget install Gyan.FFmpeg\n"
        "Se acabou de instalar, abra um terminal novo ou rode daqui mesmo · "
        "este módulo procura no diretório do winget também."
    )


def duracao(caminho: Path) -> float:
    """Duração de um arquivo de mídia, em segundos."""
    saida = subprocess.run(
        [binario("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(caminho)],
        capture_output=True, text=True, check=True,
    )
    return float(saida.stdout.strip())


def rodar(args: list[str], descricao: str) -> None:
    """Executa ffmpeg e mostra a cauda do log se der errado."""
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        cauda = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg falhou em {descricao}:\n{cauda}")
