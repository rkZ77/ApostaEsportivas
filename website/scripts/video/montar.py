"""
Monta o vídeo final: cartão de abertura, cena gravada, cartão de fecho, voz
por cima e transição entre as partes. Saída em mp4 H.264, pronto pro Instagram.

    python montar.py --cena convite
    python montar.py --todas --musica trilha.mp3

Ordem do processo inteiro:

    1. narracao.py   gera a voz e mede a duração de cada fala
    2. gravar.py     grava a tela segurando o tempo de cada fala
    3. montar.py     junta tudo                      <- você está aqui

A sincronia sai das marcas que `gravar.py` deixou em `saida/<cena>.marcas.json`:
cada fala guardou em que segundo do vídeo ela começou. Aqui esse instante só é
deslocado pelo tempo do cartão de abertura, e a voz cai exatamente onde a ação
acontece · ninguém ajusta áudio na mão.

Trabalha em três passos com arquivo intermediário em vez de um filtergraph
gigante, porque quando algo dá errado dá pra abrir o passo que quebrou.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cartoes
import ferramentas
from cenas import CARTOES, CENAS, fala_de_fecho

AQUI = Path(__file__).parent

ABERTURA = 2.4   # segundos de cartão inicial
FECHO_MIN = 3.2  # piso do cartão final · cresce se a fala de fecho for maior
TRANSICAO = 0.5  # duração do crossfade
FPS = 30
LARGURA, ALTURA = 1080, 1920

# Volume da trilha por baixo da narração. Baixo de propósito: música alta
# competindo com voz é o erro mais comum em vídeo de produto.
VOLUME_TRILHA = 0.09


def _cartao_para_clipe(png: Path, segundos: float, destino: Path) -> None:
    """
    Transforma o PNG num clipe com um pan lento.

    Cartão parado por dois segundos e meio num Reels parece travamento, então
    ele precisa de movimento · mas `zoompan` reescala o quadro inteiro a cada
    frame e em 1080x1920 leva minutos por cartão, o que é inaceitável num
    passo de build. Aqui a imagem é ampliada 5% uma vez só e o `crop` desliza
    dentro dela, que é praticamente de graça e dá o mesmo efeito.
    """
    largura_folga = int(LARGURA * 1.05)
    altura_folga = int(ALTURA * 1.05)
    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        "-loop", "1", "-t", f"{segundos}", "-i", str(png),
        "-vf",
        (f"scale={largura_folga}:{altura_folga},"
         f"crop={LARGURA}:{ALTURA}:'(iw-ow)/2':'(ih-oh)*(t/{segundos})',"
         f"fps={FPS},format=yuv420p,setsar=1"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        str(destino),
    ], f"clipe do cartão {png.name}")


def _juntar_video(abertura: Path, cena: Path, fecho: Path, dur_cena: float,
                  dur_fecho: float, destino: Path) -> float:
    """Encadeia abertura, cena e fecho com crossfade. Devolve a duração total."""
    off1 = ABERTURA - TRANSICAO
    off2 = (ABERTURA + dur_cena - TRANSICAO) - TRANSICAO
    total = ABERTURA + dur_cena + dur_fecho - 2 * TRANSICAO

    normal = f"scale={LARGURA}:{ALTURA},fps={FPS},format=yuv420p,setsar=1"
    filtro = (
        f"[0:v]{normal}[v0];"
        f"[1:v]{normal}[v1];"
        f"[2:v]{normal}[v2];"
        f"[v0][v1]xfade=transition=fade:duration={TRANSICAO}:offset={off1}[x1];"
        f"[x1][v2]xfade=transition=fade:duration={TRANSICAO}:offset={off2}[vout]"
    )

    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        "-i", str(abertura), "-i", str(cena), "-i", str(fecho),
        "-filter_complex", filtro, "-map", "[vout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-an",
        str(destino),
    ], "junção com transição")

    return total


def _trilha_de_voz(marcas: list[dict], pasta_voz: Path,
                   total: float, destino: Path) -> bool:
    """
    Monta a faixa de narração posicionando cada mp3 no segundo em que a fala
    aconteceu na gravação. Devolve False se não houver nada pra montar.
    """
    entradas, filtros, rotulos = [], [], []

    for i, marca in enumerate(marcas):
        mp3 = pasta_voz / f"{marca['chave']}.mp3"
        if not mp3.exists():
            print(f"  [aviso] sem áudio para {marca['chave']}, fala mudada")
            continue
        # O cartão de abertura empurra tudo pra frente, menos o tempo que ele
        # perde no crossfade com a cena.
        atraso = int(round((ABERTURA - TRANSICAO + marca["t"]) * 1000))
        entradas += ["-i", str(mp3)]
        rotulo = f"a{len(rotulos)}"
        filtros.append(
            f"[{len(rotulos)}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
            f"channel_layouts=stereo,adelay={atraso}|{atraso}[{rotulo}]"
        )
        rotulos.append(rotulo)

    if not rotulos:
        return False

    mistura = "".join(f"[{r}]" for r in rotulos)
    filtros.append(
        f"{mistura}amix=inputs={len(rotulos)}:normalize=0:dropout_transition=0[m]"
    )
    filtros.append(f"[m]apad[aout]")

    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        *entradas, "-filter_complex", ";".join(filtros),
        "-map", "[aout]", "-t", f"{total}",
        "-c:a", "aac", "-b:a", "192k",
        str(destino),
    ], "trilha de voz")

    return True


def _finalizar(video: Path, voz: Path | None, musica: Path | None,
               total: float, destino: Path) -> None:
    """Junta imagem, voz e trilha opcional no mp4 final."""
    args = [ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
            "-i", str(video)]

    if voz:
        args += ["-i", str(voz)]
    if musica:
        args += ["-stream_loop", "-1", "-i", str(musica)]

    if voz and musica:
        filtro = (
            f"[2:a]volume={VOLUME_TRILHA},atrim=0:{total},"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[mus];"
            f"[1:a][mus]amix=inputs=2:normalize=0:dropout_transition=0[aout]"
        )
        args += ["-filter_complex", filtro, "-map", "0:v", "-map", "[aout]"]
    elif voz:
        args += ["-map", "0:v", "-map", "1:a"]
    elif musica:
        args += ["-filter_complex", f"[1:a]volume={VOLUME_TRILHA},atrim=0:{total}[aout]",
                 "-map", "0:v", "-map", "[aout]"]
    else:
        args += ["-map", "0:v"]

    args += ["-c:v", "copy", "-t", f"{total}"]
    if voz or musica:
        args += ["-c:a", "aac", "-b:a", "192k"]
    args += ["-movflags", "+faststart", str(destino)]

    ferramentas.rodar(args, "mp4 final")


def montar(nome: str, saida: Path, pasta_voz: Path,
           pronto: Path, musica: Path | None, manter: bool) -> bool:
    bruto = saida / f"{nome}.webm"
    if not bruto.exists():
        print(f"  [erro] falta {bruto.name} · rode gravar.py --cena {nome}")
        return False

    tmp = pronto / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    dur_cena = ferramentas.duracao(bruto)
    print(f"  cena gravada: {dur_cena:.1f}s")

    # O cartão final tem que caber a fala de fecho inteira, senão a chamada
    # pra ação é cortada no meio · foi o que aconteceu na primeira montagem.
    chave_fecho = fala_de_fecho(nome)
    mp3_fecho = pasta_voz / nome / f"{chave_fecho}.mp3"
    dur_fecho = FECHO_MIN
    if mp3_fecho.exists():
        dur_fecho = max(FECHO_MIN, ferramentas.duracao(mp3_fecho) + 1.1)

    png_abertura, png_fecho = cartoes.render(nome, CARTOES[nome], AQUI / "cartoes")
    clipe_abertura = tmp / f"{nome}-abertura.mp4"
    clipe_fecho = tmp / f"{nome}-fecho.mp4"
    _cartao_para_clipe(png_abertura, ABERTURA, clipe_abertura)
    _cartao_para_clipe(png_fecho, dur_fecho, clipe_fecho)

    mudo = tmp / f"{nome}-mudo.mp4"
    total = _juntar_video(clipe_abertura, bruto, clipe_fecho,
                          dur_cena, dur_fecho, mudo)
    print(f"  com cartões : {total:.1f}s (fecho {dur_fecho:.1f}s)")

    voz = None
    arquivo_marcas = saida / f"{nome}.marcas.json"
    if arquivo_marcas.exists():
        marcas = json.loads(arquivo_marcas.read_text(encoding="utf-8"))["marcas"]

        # A fala de fecho não veio da gravação: ela é encaixada aqui, por cima
        # do cartão final. `_trilha_de_voz` soma (ABERTURA - TRANSICAO) a todo
        # `t`, então o valor guardado desconta isso pra cair no ponto certo.
        if mp3_fecho.exists():
            inicio_fecho = total - dur_fecho + 0.35
            marcas.append({
                "chave": chave_fecho,
                "t": round(inicio_fecho - (ABERTURA - TRANSICAO), 3),
            })

        candidata = tmp / f"{nome}-voz.m4a"
        if _trilha_de_voz(marcas, pasta_voz / nome, total, candidata):
            voz = candidata
            print(f"  narração    : {len(marcas)} falas encaixadas")
    else:
        print("  [aviso] sem marcas de tempo · vídeo sai mudo")

    pronto.mkdir(parents=True, exist_ok=True)
    final = pronto / f"{nome}.mp4"
    _finalizar(mudo, voz, musica, total, final)

    if not manter:
        shutil.rmtree(tmp, ignore_errors=True)

    tamanho = final.stat().st_size / 1_048_576
    print(f"  pronto      : {final}  ({total:.1f}s, {tamanho:.1f} MB)")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Monta o vídeo final pro Instagram")
    p.add_argument("--cena", action="append", default=[])
    p.add_argument("--todas", action="store_true")
    p.add_argument("--saida", default=str(AQUI / "saida"),
                   help="pasta com os .webm de gravar.py")
    p.add_argument("--voz", default=str(AQUI / "voz"))
    p.add_argument("--pronto", default=str(AQUI / "pronto"))
    p.add_argument("--musica", default=None,
                   help="trilha de fundo opcional (mp3), entra bem baixa")
    p.add_argument("--manter-temporarios", action="store_true")
    args = p.parse_args()

    escolhidas = list(CENAS) if args.todas else args.cena
    if not escolhidas:
        print("erro: use --cena <nome> ou --todas", file=sys.stderr)
        return 2

    desconhecidas = [c for c in escolhidas if c not in CENAS]
    if desconhecidas:
        print(f"erro: cena desconhecida: {', '.join(desconhecidas)}", file=sys.stderr)
        return 2

    musica = Path(args.musica) if args.musica else None
    if musica and not musica.exists():
        print(f"erro: trilha não encontrada: {musica}", file=sys.stderr)
        return 2

    falhas = []
    for nome in escolhidas:
        print(f"\n[{nome}]")
        try:
            if not montar(nome, Path(args.saida), Path(args.voz),
                          Path(args.pronto), musica, args.manter_temporarios):
                falhas.append(nome)
        except Exception as erro:
            print(f"  [erro] {erro}")
            falhas.append(nome)

    print()
    if falhas:
        print(f"terminou com problema em: {', '.join(falhas)}")
        return 1
    print(f"tudo pronto em {Path(args.pronto).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
