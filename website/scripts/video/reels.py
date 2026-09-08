"""
Reels de resultado: mp4 1080x1920 com narracao, montado a partir de quadros.

    python reels.py --listar
    python reels.py --todos
    python reels.py --reel setembro

POR QUE ESTE NAO GRAVA A TELA
-----------------------------
A fabrica de video que ja existia aqui (`narracao.py` -> `gravar.py` ->
`montar.py`) grava o site em movimento, e por isso precisa do site no ar, de
uma sessao logada e das fixtures de `page.route`. Isso vale pra mostrar COMO o
produto funciona.

Um reels de RESULTADO nao precisa de nada disso: o assunto e' o numero, e o
numero ja' esta' desenhado nos quadros de `stories.py`. Entao aqui os quadros
sao renderizados, nao gravados, e o roteiro se escreve em minutos em vez de
depender de uma sessao valida em producao.

O PRINCIPIO CONTINUA O MESMO
----------------------------
A narracao guia o tempo. O mp3 de cada quadro e' gerado primeiro, o quadro
segura exatamente a duracao dele mais uma pausa, e o instante em que cada fala
comeca sai da conta, nunca do ajuste na mao. Mudou a frase, roda de novo.

Voz e ffmpeg saem do mesmo lugar do resto da fabrica: `edge-tts` sem chave de
API e o `ferramentas.binario`, que acha o ffmpeg do winget.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

import edge_tts
from playwright.sync_api import sync_playwright

import ferramentas
import stories
from cartoes import _logo_embutido
from fechamento import numeros

AQUI = Path(__file__).parent
LARGURA, ALTURA = 1080, 1920
FPS = 30

# Mesma voz e mesmo ritmo de `narracao.py`. Reels com voz diferente do resto
# do perfil soa como canal de outra pessoa.
VOZ = "pt-BR-ThalitaMultilingualNeural"
RITMO = "-6%"
TOM = "+0Hz"

# Respiro depois que a fala termina. Sem isso o corte cai em cima da ultima
# silaba e o reels parece atropelado.
PAUSA = 0.65
# Entrada da fala dentro do quadro: o olho precisa de um instante pra pousar no
# numero antes de a voz comecar a explica-lo.
ENTRADA = 0.28
TRANSICAO = 0.32


# ------------------------------------------------------------------ roteiros
# Cada quadro e' um story (mesmos layouts de `stories.py`) mais a `fala`.
#
# Regra do roteiro: a fala NAO le' o quadro em voz alta. O quadro mostra o
# numero, a fala diz o que ele significa. Narracao que repete o texto na tela
# faz o espectador ler e ouvir a mesma coisa, e ele sai.

ROTEIROS: dict[str, dict] = {
    "setembro": {
        "mes": "2026-09",
        "quadros": [
            {"layout": "numero", "kicker": "{Mes} até agora", "numero": "{lucro}",
             "titulo": "{picks} picks resolvidos",
             "texto": "Em {dias} dias, por {ligas} ligas.",
             "fala": "Setembro está em mais quarenta e uma unidades, "
                     "com cento e vinte e dois picks já resolvidos."},
            {"layout": "lista", "kicker": "Dia a dia", "titulo": "Não foi reto",
             "fonte": "dias",
             "texto": "Dois dias fecharam no vermelho.",
             "fala": "E não foi uma linha reta. Dois desses dias fecharam "
                     "no vermelho, e eles estão publicados do mesmo tamanho "
                     "que os outros."},
            {"layout": "numero", "kicker": "Acerto", "numero": "{acerto}",
             "titulo": "{greens} green e {reds} red",
             "texto": "Anulado sai da conta, meio-green entra.",
             "fala": "O acerto é de sessenta e quatro por cento. "
                     "Trinta e oito picks perderam."},
            {"layout": "lista", "kicker": "Produto por produto",
             "titulo": "Nem tudo lucrou", "fonte": "produtos",
             "texto": "Dois produtos estão devendo.",
             "fala": "Aberto por produto, o ao vivo carregou o mês, "
                     "e o de jogadores é o que mais perdeu."},
            {"layout": "tela", "kicker": "Confira você mesmo",
             "titulo": "Abre sem\nconta",
             "texto": "pickia.com.br/resultados",
             "print": "mes-lista-2026-09",
             "fala": "Nada disso depende de você acreditar em mim. "
                     "O histórico inteiro abre sem conta, no pick ia ponto com "
                     "ponto b r."},
        ],
    },
    "dia": {
        "mes": "2026-09",
        "quadros": [
            {"layout": "numero", "kicker": "{dia_data}", "numero": "{dia_lucro}",
             "titulo": "{dia_greens} green, {dia_reds} red",
             "texto": "{dia_picks} picks resolvidos no dia.",
             "fala": "O dia fechou em mais onze unidades."},
            {"layout": "lista", "kicker": "{dia_curto}", "titulo": "Como saiu",
             "fonte": "dia",
             "texto": "Cada pick com odd e resultado.",
             "fala": "Estes são os picks, com a odd que estava valendo e o "
                     "resultado de cada um. Inclusive os que perderam."},
            {"layout": "tela", "kicker": "Todo dia",
             "titulo": "Tem pick\ngrátis todo dia",
             "texto": "Sem cartão.",
             "print": "resultados",
             "fala": "Tem pick grátis todo dia, e o histórico abre deslogado. "
                     "Pick ia ponto com ponto b r."},
        ],
    },
}


# --------------------------------------------------------------------- voz

async def _gerar_voz(quadros: list[dict], pasta: Path, forcar: bool) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    arquivos = []
    for i, q in enumerate(quadros):
        destino = pasta / f"{i:02d}.mp3"
        if forcar or not destino.exists():
            await edge_tts.Communicate(q["fala"], VOZ, rate=RITMO,
                                       pitch=TOM).save(str(destino))
        arquivos.append(destino)
    return arquivos


# ------------------------------------------------------------------ quadros

def _renderizar_quadros(nome: str, roteiro: dict, pasta: Path) -> list[Path]:
    """Desenha os PNG dos quadros, reusando o layout de `stories.py`."""
    pasta.mkdir(parents=True, exist_ok=True)
    mes = roteiro["mes"]

    n = dict(numeros(mes))
    n.update(stories.numeros_do_dia(mes))
    uri = _logo_embutido()
    logo = f"<img src='{uri}' alt=''>" if uri else ""

    gerados = []
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(
            viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1
        )
        for i, quadro in enumerate(roteiro["quadros"]):
            # Sem "arrasta pra cima": em reels nao existe adesivo de link, e a
            # chamada que sobra apontando pra lugar nenhum confunde.
            sem_cta = {k: v for k, v in quadro.items() if k != "cta"}
            arquivo = pasta / f"{i:02d}.png"
            pagina.set_content(stories._pagina(sem_cta, n, logo, mes, False))
            pagina.evaluate(stories._ENCAIXAR)
            pagina.screenshot(path=str(arquivo))
            gerados.append(arquivo)
        navegador.close()
    return gerados


# ------------------------------------------------------------------ montagem

def _clipe(png: Path, segundos: float, destino: Path) -> None:
    """PNG vira clipe com um pan lento.

    Mesma tecnica de `montar.py`: amplia 5% uma vez e desliza o `crop` dentro
    da folga. `zoompan` daria o mesmo efeito e levaria minutos por quadro em
    1080x1920, o que ja' estourou timeout de build uma vez.
    """
    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        "-loop", "1", "-t", f"{segundos}", "-i", str(png),
        "-vf",
        (f"scale={int(LARGURA * 1.05)}:{int(ALTURA * 1.05)},"
         f"crop={LARGURA}:{ALTURA}:'(iw-ow)/2':'(ih-oh)*(t/{segundos})',"
         f"fps={FPS},format=yuv420p,setsar=1"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        str(destino),
    ], f"clipe de {png.name}")


def _encadear(clipes: list[Path], duracoes: list[float], destino: Path) -> float:
    """Junta os clipes com crossfade e devolve a duracao total.

    O `xfade` so' sabe juntar dois de cada vez, entao a cadeia e' montada em
    laco: cada junção nova entra com o offset do que ja' foi somado. Com corte
    seco o reels fica com cara de apresentação de slide.
    """
    entradas = []
    for c in clipes:
        entradas += ["-i", str(c)]

    partes = [f"[{i}:v]fps={FPS},format=yuv420p,setsar=1[v{i}]"
              for i in range(len(clipes))]

    atual, total = "v0", duracoes[0]
    for i in range(1, len(clipes)):
        offset = total - TRANSICAO
        rotulo = f"x{i}"
        partes.append(
            f"[{atual}][v{i}]xfade=transition=fade:"
            f"duration={TRANSICAO}:offset={offset}[{rotulo}]"
        )
        atual = rotulo
        total = total + duracoes[i] - TRANSICAO

    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        *entradas, "-filter_complex", ";".join(partes), "-map", f"[{atual}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", str(destino),
    ], "encadeamento dos quadros")

    return total


def _voz_na_linha(mp3s: list[Path], inicios: list[float],
                  total: float, destino: Path) -> None:
    """Uma faixa so', com cada fala atrasada ate' o segundo do seu quadro."""
    entradas, filtros, rotulos = [], [], []
    for i, (mp3, t) in enumerate(zip(mp3s, inicios)):
        atraso = int(round(t * 1000))
        entradas += ["-i", str(mp3)]
        filtros.append(
            f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
            f"channel_layouts=stereo,adelay={atraso}|{atraso}[a{i}]"
        )
        rotulos.append(f"a{i}")

    mistura = "".join(f"[{r}]" for r in rotulos)
    filtros.append(
        f"{mistura}amix=inputs={len(rotulos)}:normalize=0:dropout_transition=0[m]"
    )
    filtros.append("[m]apad[aout]")

    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        *entradas, "-filter_complex", ";".join(filtros),
        "-map", "[aout]", "-t", f"{total}",
        "-c:a", "aac", "-b:a", "192k", str(destino),
    ], "faixa de narração")


def montar(nome: str, pronto: Path, trabalho: Path, forcar_voz: bool) -> Path:
    roteiro = ROTEIROS[nome]
    quadros = roteiro["quadros"]

    pasta = trabalho / nome
    pasta.mkdir(parents=True, exist_ok=True)

    mp3s = asyncio.run(_gerar_voz(quadros, pasta / "voz", forcar_voz))
    pngs = _renderizar_quadros(nome, roteiro, pasta / "quadros")

    # A duracao de cada quadro sai da fala dele. E' a regra da fabrica inteira:
    # o audio manda no tempo, a imagem obedece.
    duracoes = [ferramentas.duracao(m) + ENTRADA + PAUSA for m in mp3s]

    clipes = []
    for i, (png, dur) in enumerate(zip(pngs, duracoes)):
        clipe = pasta / f"clipe-{i:02d}.mp4"
        _clipe(png, dur, clipe)
        clipes.append(clipe)
        print(f"  quadro {i:02d}  {dur:5.2f}s  \"{quadros[i]['fala'][:46]}...\"")

    mudo = pasta / "mudo.mp4"
    total = _encadear(clipes, duracoes, mudo)

    # O crossfade come TRANSICAO de cada emenda, entao o inicio de um quadro
    # nao e' a soma das duracoes anteriores: e' a soma menos o que ja' foi
    # comido. Sem esse desconto a voz vai atrasando a cada quadro.
    inicios, acumulado = [], 0.0
    for i, dur in enumerate(duracoes):
        inicios.append(acumulado + ENTRADA)
        acumulado += dur - TRANSICAO

    voz = pasta / "voz.m4a"
    _voz_na_linha(mp3s, inicios, total, voz)

    pronto.mkdir(parents=True, exist_ok=True)
    final = pronto / f"reels-{nome}.mp4"
    ferramentas.rodar([
        ferramentas.binario("ffmpeg"), "-y", "-loglevel", "error",
        "-i", str(mudo), "-i", str(voz),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-t", f"{total}",
        "-movflags", "+faststart", str(final),
    ], "mp4 final")

    tamanho = final.stat().st_size / 1_048_576
    print(f"  pronto     {final.name}  ({total:.1f}s, {tamanho:.1f} MB)")
    return final


def main() -> int:
    p = argparse.ArgumentParser(description="Gera reels 1080x1920 com narração")
    p.add_argument("--reel", action="append", default=[])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--forcar-voz", action="store_true",
                   help="regera os mp3 mesmo que já existam")
    p.add_argument("--manter-temporarios", action="store_true")
    p.add_argument("--pronto", default=str(AQUI / "pronto"))
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.listar:
        print("reels disponíveis:\n")
        for nome, r in ROTEIROS.items():
            print(f"  {nome:<12} {len(r['quadros'])} quadros, {r['mes']}")
        return 0

    escolhidos = list(ROTEIROS) if args.todos else args.reel
    if not escolhidos:
        print("erro: use --reel <nome>, --todos ou --listar", file=sys.stderr)
        return 2

    desconhecidos = [c for c in escolhidos if c not in ROTEIROS]
    if desconhecidos:
        print(f"erro: não existe: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    trabalho = AQUI / "saida" / "reels"
    for nome in escolhidos:
        print(f"\n[{nome}]")
        montar(nome, Path(args.pronto), trabalho, args.forcar_voz)

    if not args.manter_temporarios:
        shutil.rmtree(trabalho, ignore_errors=True)

    print(f"\npronto em {Path(args.pronto).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
