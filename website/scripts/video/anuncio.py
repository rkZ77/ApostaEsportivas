"""
Anúncio de 25s pro Reels: mp4 1080x1920, MUDO, renderizado quadro a quadro.

    python anuncio.py                  captura as telas do site e renderiza
    python anuncio.py --sem-captura    reusa as telas já capturadas
    python anuncio.py --quadros 0,4.5,13   só tira PNGs desses instantes (conferência)

POR QUE MUDO
------------
A narração é gravada depois, pelo criador, por cima. Então o vídeo não tem voz
nem trilha: sai com uma faixa de áudio em silêncio só pra editor e Instagram
não reclamarem de arquivo sem áudio.

COMO FUNCIONA
-------------
`anuncio.html` é a animação inteira, escrita como função do tempo. Aqui a
página abre com ?render, e pra cada quadro chamamos `__seek(t)` e fotografamos.
Não é gravação de tela: quadro lento de capturar não vira quadro pulado.

As telas que aparecem dentro do celular (home e planos) são o site de verdade,
capturadas de `--url` (padrão: produção, só páginas públicas, só leitura).
A página de planos é cortada nos cartões Free e Pick IA de propósito: o bloco
de histórico no topo dela traz lucro e ROI, e anúncio de captação não mostra
promessa de resultado.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AQUI = Path(__file__).parent
TELAS = AQUI / "saida" / "anuncio"
QUADROS = AQUI / "saida" / "anuncio-quadros"
PRONTO = AQUI / "pronto"
LARGURA, ALTURA, FPS, DURACAO = 1080, 1920, 30, 25.0

# Esconde o que é fixo no rodapé (barra de navegação, "Testar o VIP", cookies).
# O cabeçalho fica: ele é parte de reconhecer o site.
_SEM_RODAPE = """
for (const el of document.querySelectorAll('body *')) {
  const cs = getComputedStyle(el);
  if (cs.position === 'fixed' && el.getBoundingClientRect().top > 300) el.style.display = 'none';
}
"""


# Logos do mesmo CDN que o site usa (API-Football). Ficam em cache local: a
# renderização não pode depender da rede no meio dos 750 quadros. Os ids batem
# com `frontend/src/lib/paisDaLiga.ts` (ligas) e com a API (times) · se trocar
# um time da parede da cena 1, troque aqui e em JOGOS do anuncio.html juntos.
LOGOS = TELAS / "logos"
LIGAS = [71, 39, 140, 135, 78, 2, 61, 13, 73, 72, 88, 94, 40, 11, 253]
TIMES = [127, 121, 40, 49, 541, 529, 505, 489, 157, 165, 131, 126, 42, 47, 85, 81,
         530, 536, 130, 119, 496, 492, 50, 33, 211, 212, 120, 124, 194, 197, 168, 173,
         133, 135, 34, 66, 497, 487, 543, 533, 128, 118, 80, 91, 51, 45, 499, 502,
         2618, 139]  # Botafogo SP e Ponte Preta: o pick real dos vídeos 02 e 05


def _baixar(url: str, destino: Path) -> None:
    """Baixa um arquivo; se o DNS local não resolver, tenta via DNS-over-HTTPS.

    Nesta máquina o DNS local não resolve `media.api-sports.io` (o domínio pai
    resolve; algum filtro pega o subdomínio). O `curl` do Windows aceita
    --doh-url e contorna sem mexer na configuração de rede.
    """
    import subprocess
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            destino.write_bytes(r.read())
        return
    except urllib.error.URLError:
        pass
    subprocess.run(
        ["curl.exe", "-sf", "--doh-url", "https://1.1.1.1/dns-query",
         "-A", "Mozilla/5.0", "-o", str(destino), url],
        check=True,
    )


def baixar_logos() -> None:
    for tipo, ids in (("leagues", LIGAS), ("teams", TIMES)):
        pasta = LOGOS / tipo
        pasta.mkdir(parents=True, exist_ok=True)
        for i in ids:
            destino = pasta / f"{i}.png"
            if not destino.exists():
                _baixar(f"https://media.api-sports.io/football/{tipo}/{i}.png", destino)
    print(f"  logos   {len(LIGAS)} ligas, {len(TIMES)} times em {LOGOS}")


def _ffmpeg() -> str:
    """O ffmpeg completo do winget se existir; senão o que vem com imageio-ffmpeg."""
    try:
        import ferramentas
        return ferramentas.binario("ffmpeg")
    except Exception:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()


def capturar(url: str) -> None:
    TELAS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        ctx = nav.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=3,
            is_mobile=True, has_touch=True, locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        p = ctx.new_page()
        for rota, nome, inteira in (("/", "home", False), ("/planos", "planos", True)):
            p.goto(url.rstrip("/") + rota, wait_until="networkidle")
            p.wait_for_timeout(1500)
            aceitar = p.get_by_role("button", name="Entendi")
            if aceitar.count():
                aceitar.first.click()
                p.wait_for_timeout(400)
            p.evaluate(_SEM_RODAPE)
            p.wait_for_timeout(300)
            destino = TELAS / f"{nome}.png"
            if inteira:
                p.screenshot(path=str(destino), full_page=True)
            else:
                p.screenshot(path=str(destino), clip={"x": 0, "y": 0, "width": 390, "height": 1200},
                             full_page=True)
            print(f"  tela {nome:<7} {destino}")
        nav.close()


def _abrir(pw, html: Path):
    nav = pw.chromium.launch()
    pagina = nav.new_page(viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1)
    pagina.goto(html.resolve().as_uri() + "?render")
    pagina.wait_for_function("window.__pronto === true", timeout=60000)
    # O anúncio original declara DURACAO aqui; os da série dizem no <body>.
    dur = pagina.evaluate("window.DUR || null") or DURACAO
    return nav, pagina, float(dur)


def conferir(html: Path, instantes: list[float]) -> list[Path]:
    QUADROS.mkdir(parents=True, exist_ok=True)
    feitos = []
    with sync_playwright() as pw:
        nav, pagina, _ = _abrir(pw, html)
        for t in instantes:
            pagina.evaluate(f"__seek({t})")
            destino = QUADROS / f"{html.stem}-t{t:05.2f}.png"
            pagina.screenshot(path=str(destino))
            feitos.append(destino)
            print(f"  {destino}")
        nav.close()
    return feitos


def renderizar(html: Path, nome: str) -> Path:
    pasta = QUADROS / html.stem
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    with sync_playwright() as pw:
        nav, pagina, dur = _abrir(pw, html)
        total = int(round(dur * FPS))
        for i in range(total):
            pagina.evaluate(f"__seek({i / FPS})")
            pagina.screenshot(path=str(pasta / f"{i:04d}.jpg"), type="jpeg", quality=94)
            if i % 150 == 0:
                print(f"  {html.stem}  quadro {i:4d}/{total}")
        nav.close()

    PRONTO.mkdir(parents=True, exist_ok=True)
    final = PRONTO / f"{nome}.mp4"
    QUADROS_DA_VEZ = pasta
    import subprocess
    cmd = [
        _ffmpeg(), "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", str(QUADROS_DA_VEZ / "%04d.jpg"),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map", "0:v", "-map", "1:a", "-shortest",
        # JPEG vem em range cheio (yuvj420p); sem converter pra range de TV
        # o preto do fundo chega lavado em parte dos players.
        "-vf", "scale=in_range=full:out_range=tv,format=yuv420p", "-color_range", "tv",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17",
        "-profile:v", "high", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg falhou:\n" + proc.stderr[-2000:])
    shutil.rmtree(QUADROS_DA_VEZ, ignore_errors=True)
    print(f"  pronto  {final}  ({final.stat().st_size / 1_048_576:.1f} MB)")
    return final


SERIE = AQUI / "anuncios"


def _escolher(videos: list[str], todos: bool) -> list[tuple[Path, str]]:
    """(html, nome do mp4). Sem --video nem --todos: o anúncio original."""
    if todos:
        return [(h, f"pickia-{h.stem}") for h in sorted(SERIE.glob("[0-9][0-9]-*.html"))]
    if not videos:
        return [(AQUI / "anuncio.html", "anuncio-pickia-25s")]
    saida = []
    for v in videos:
        achados = sorted(SERIE.glob(f"{v}*.html"))
        if not achados:
            raise SystemExit(f"erro: nenhum vídeo começa com {v!r} em {SERIE}")
        saida += [(h, f"pickia-{h.stem}") for h in achados]
    return saida


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Anúncios PickIA 1080x1920, sem voz")
    ap.add_argument("--url", default="https://pickia.com.br")
    ap.add_argument("--sem-captura", action="store_true", help="reusa telas e logos já baixados")
    ap.add_argument("--video", action="append", default=[],
                    help="prefixo de anuncios/NN-*.html (ex.: 03). Repetível.")
    ap.add_argument("--todos", action="store_true", help="renderiza a série inteira")
    ap.add_argument("--quadros", help="só tira PNGs nesses instantes (segundos, vírgula)")
    a = ap.parse_args()

    escolhidos = _escolher(a.video, a.todos)
    baixar_logos()
    if not a.sem_captura:
        if any(h.parent == SERIE for h, _ in escolhidos):
            import telas
            telas.capturar(a.url)
        else:
            capturar(a.url)
    for html, nome in escolhidos:
        if a.quadros:
            feitos = conferir(html, [float(x) for x in a.quadros.split(",")])
            # Folha de contato: os instantes lado a lado, pra revisar de uma vez.
            from PIL import Image
            mini = [Image.open(f).resize((432, 768)) for f in feitos]
            folha = Image.new("RGB", (432 * len(mini), 768))
            for i, m in enumerate(mini):
                folha.paste(m, (i * 432, 0))
            folha.save(QUADROS / f"{html.stem}-folha.png")
        else:
            renderizar(html, nome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
