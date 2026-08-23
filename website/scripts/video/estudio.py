"""
Motor de gravação dos vídeos curtos do Pick IA.

Grava o site rodando de verdade num viewport 9:16 e devolve um .webm por cena,
pronto pra importar no CapCut. Três coisas que o Playwright não dá de graça e
que este módulo resolve:

1. Cursor. A gravação do Playwright não desenha o mouse -- o vídeo sairia com
   coisas acontecendo sozinhas. `_OVERLAY_JS` injeta um cursor falso que segue
   os eventos de mousemove reais que o `page.mouse` dispara.
2. Legenda. Sem ffmpeg utilizável nesta máquina (o que vem junto do Playwright
   é build reduzida, só webm/vp8), a legenda tem que ser queimada na hora da
   gravação. Vira um overlay no DOM.
3. Movimento. `scrollIntoView` corta seco e roda feio em vídeo; `__rolarAte`
   faz easing em requestAnimationFrame.

O overlay é anexado no `document.body`, fora da raiz do React, então sobrevive
à troca de rota do react-router sem ser remontado.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# 540x960 é 9:16 exato e ainda cai no layout mobile do site (o breakpoint `sm`
# do Tailwind é 640px).
#
# O vídeo é gravado NO TAMANHO DO VIEWPORT de propósito. O Playwright captura
# em pixels CSS e ignora `device_scale_factor`, e só reduz a imagem pra caber
# em `record_video_size` · nunca amplia. Pedindo 1080x1920 aqui, a página saía
# desenhada 1:1 no canto superior esquerdo de um quadro cinza. Quem amplia pra
# 1080x1920 é o `montar.py`, com lanczos, num 2x exato.
VIEWPORT = {"width": 540, "height": 960}
VIDEO = dict(VIEWPORT)

_OVERLAY_JS = r"""
(() => {
  if (window.__estudio) return;
  window.__estudio = { pronto: false };

  const montar = () => {
    if (!document.body || document.getElementById('__estudio_cursor')) return;

    const cursor = document.createElement('div');
    cursor.id = '__estudio_cursor';
    cursor.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'width:26px', 'height:26px',
      'margin:-13px 0 0 -13px', 'border-radius:50%',
      'background:rgba(255,255,255,.20)', 'border:2px solid rgba(255,255,255,.92)',
      'box-shadow:0 3px 14px rgba(0,0,0,.55)', 'pointer-events:none',
      'z-index:2147483646', 'opacity:0',
      'transition:opacity .18s ease, transform .12s ease', 'will-change:transform'
    ].join(';');
    document.body.appendChild(cursor);

    // Legenda de apoio: com narração por cima ela não carrega a informação
    // sozinha, então é curta e some entre as falas. Barra inferior no verde da
    // marca (#00CC00) pra amarrar com a identidade do site.
    const faixa = document.createElement('div');
    faixa.id = '__estudio_legenda';
    faixa.style.cssText = [
      'position:fixed', 'left:0', 'right:0', 'bottom:0', 'padding:0 18px 96px',
      'display:flex', 'justify-content:center', 'pointer-events:none',
      'z-index:2147483647', 'opacity:0',
      'transition:opacity .26s ease, transform .26s ease',
      'transform:translateY(8px)'
    ].join(';');
    const texto = document.createElement('span');
    texto.style.cssText = [
      /* 26px num quadro de 540 vira 52px no 1080 final · tamanho de legenda
         de Reels. Se mexer no VIEWPORT, mexa aqui junto. */
      'font:800 26px/1.28 Inter,system-ui,-apple-system,"Segoe UI",sans-serif',
      'letter-spacing:-.01em', 'color:#fff', 'text-align:center',
      'background:rgba(10,10,12,.88)',
      '-webkit-backdrop-filter:blur(8px)', 'backdrop-filter:blur(8px)',
      'padding:13px 18px', 'border-radius:14px',
      'border-bottom:3px solid #00CC00', 'max-width:94%',
      'text-shadow:0 1px 4px rgba(0,0,0,.95)',
      'box-shadow:0 10px 34px rgba(0,0,0,.55)'
    ].join(';');
    faixa.appendChild(texto);
    document.body.appendChild(faixa);

    addEventListener('mousemove', e => {
      cursor.style.opacity = '1';
      cursor.style.left = e.clientX + 'px';
      cursor.style.top = e.clientY + 'px';
    }, true);

    // Toque: o círculo encolhe e uma onda sai dele, senão o clique some no vídeo.
    addEventListener('mousedown', e => {
      cursor.style.transform = 'scale(.72)';
      const onda = document.createElement('div');
      onda.style.cssText = [
        'position:fixed', 'left:' + e.clientX + 'px', 'top:' + e.clientY + 'px',
        'width:14px', 'height:14px', 'margin:-7px 0 0 -7px', 'border-radius:50%',
        'border:2px solid rgba(255,255,255,.85)', 'pointer-events:none',
        'z-index:2147483645', 'opacity:.9'
      ].join(';');
      document.body.appendChild(onda);
      onda.animate(
        [{ transform: 'scale(1)', opacity: .9 }, { transform: 'scale(4.5)', opacity: 0 }],
        { duration: 520, easing: 'cubic-bezier(.22,.61,.36,1)' }
      ).onfinish = () => onda.remove();
    }, true);
    addEventListener('mouseup', () => { cursor.style.transform = 'scale(1)'; }, true);

    window.__legenda = t => {
      if (!t) {
        faixa.style.opacity = '0';
        faixa.style.transform = 'translateY(8px)';
        return;
      }
      texto.textContent = t;
      faixa.style.opacity = '1';
      faixa.style.transform = 'translateY(0)';
    };

    window.__rolarAte = (destino, ms) => new Promise(resolve => {
      const inicio = window.scrollY;
      const delta = destino - inicio;
      if (Math.abs(delta) < 2 || ms <= 0) { window.scrollTo(0, destino); return resolve(); }
      const t0 = performance.now();
      const suave = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
      const passo = agora => {
        const p = Math.min(1, (agora - t0) / ms);
        window.scrollTo(0, inicio + delta * suave(p));
        p < 1 ? requestAnimationFrame(passo) : resolve();
      };
      requestAnimationFrame(passo);
    });

    window.__estudio.pronto = true;
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', montar);
  } else {
    montar();
  }
  // A troca de rota do react-router não remonta o body, mas um goto novo sim --
  // e aí este script roda de novo com o guard lá em cima.
  setTimeout(montar, 300);
})();
"""


class Estudio:
    """Sessão de gravação. Um `Estudio` = uma cena = um arquivo .webm."""

    def __init__(
        self,
        base_url: str,
        saida: Path,
        nome: str,
        headless: bool = True,
        tempos: dict[str, float] | None = None,
        sessao: Path | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.saida = saida
        self.nome = nome
        self.headless = headless
        # Sessão salva por `gravar.py --login-manual`. Ver `logar` pra saber
        # por que o login automatizado não é opção neste site.
        self.sessao = sessao
        # chave da fala -> duração do mp3 em segundos, de `narracao.py`
        self.tempos = tempos or {}
        # onde cada fala começa, em segundos desde o primeiro frame do vídeo.
        # `montar.py` usa isso pra encaixar cada mp3 na linha do tempo.
        self.marcas: list[dict] = []
        self._pw = None
        self._browser = None
        self._ctx = None
        self._t0 = 0.0
        self.page: Page | None = None

    # ── ciclo de vida ────────────────────────────────────────────────────
    def __enter__(self) -> "Estudio":
        self.saida.mkdir(parents=True, exist_ok=True)
        self._tmp = self.saida / "_bruto"
        self._tmp.mkdir(exist_ok=True)

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--hide-scrollbars", "--force-color-profile=srgb"],
        )
        opcoes = dict(
            viewport=VIEWPORT,
            device_scale_factor=1,
            is_mobile=True,
            has_touch=True,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            record_video_dir=str(self._tmp),
            record_video_size=VIDEO,
        )
        if self.sessao and self.sessao.exists():
            opcoes["storage_state"] = str(self.sessao)
        self._ctx = self._browser.new_context(**opcoes)
        # Aceita os cookies antes da página nascer. O banner é `fixed
        # bottom-0` e cobria justamente a faixa da legenda em toda cena.
        self._ctx.add_init_script(
            "try { localStorage.setItem('cookie_consent', '1'); } catch (e) {}"
        )
        self._ctx.add_init_script(_OVERLAY_JS)
        self.page = self._ctx.new_page()
        # O Playwright começa a capturar junto com a página, então este é o
        # zero da linha do tempo do vídeo. Um erro constante de alguns
        # milissegundos aqui desloca a narração inteira por igual, o que é
        # imperceptível · o que não pode é o erro variar entre falas.
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        video = self.page.video if self.page else None
        try:
            self.saida.mkdir(parents=True, exist_ok=True)
            (self.saida / f"{self.nome}.marcas.json").write_text(
                json.dumps({"cena": self.nome, "marcas": self.marcas},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._ctx.close()  # o arquivo só é finalizado no close do contexto
            if video:
                destino = self.saida / f"{self.nome}.webm"
                if destino.exists():
                    destino.unlink()
                video.save_as(str(destino))
                # save_as copia; sem isso o bruto do Playwright ia se acumulando
                # com nome de hash a cada gravação.
                try:
                    Path(video.path()).unlink(missing_ok=True)
                except Exception:
                    pass
                print(f"  video: {destino}")
        finally:
            self._browser.close()
            self._pw.stop()
            try:
                self._tmp.rmdir()
            except OSError:
                pass

    # ── navegação ────────────────────────────────────────────────────────
    def ir(self, rota: str, espera: float = 1.6) -> None:
        self.page.goto(f"{self.base_url}{rota}", wait_until="domcontentloaded")
        self.page.wait_for_timeout(int(espera * 1000))
        self.limpar_overlays()

    def limpar_overlays(self) -> None:
        """
        Tira do caminho o que cobre o rodapé da tela.

        A barra "Testar o VIP por 2 dias" da home só tem estado em React (nada
        de localStorage), então some com clique e volta a cada carga · por isso
        isto roda em todo `ir`, e não uma vez só. Sem barulho se não existir.
        """
        fechar = self.page.locator("[aria-label='Fechar chamada']")
        try:
            if fechar.count():
                fechar.first.click(timeout=1500)
                self.pausa(0.35)
        except Exception:
            pass

        # Some com o selo ADMIN do topo. A gravação roda numa conta admin, mas
        # o vídeo é sobre o que o ASSINANTE vê · deixar "ADMIN" na tela mostra
        # uma interface que nenhum cliente tem.
        try:
            self.page.evaluate("""() => {
                for (const el of document.querySelectorAll('span,div,small,b')) {
                    if (el.children.length === 0 &&
                        el.textContent.trim().toUpperCase() === 'ADMIN') {
                        el.style.display = 'none';
                    }
                }
            }""")
        except Exception:
            pass

    def pausa(self, segundos: float) -> None:
        self.page.wait_for_timeout(int(segundos * 1000))

    # ── legenda ──────────────────────────────────────────────────────────
    def legenda(self, texto: str | None, segurar: float = 0.0) -> None:
        """Escreve a legenda queimada. `segurar` mantém ela na tela e segue."""
        self.page.evaluate("t => window.__legenda && window.__legenda(t)", texto)
        if segurar:
            self.pausa(segurar)

    def falar(self, texto: str, segundos: float) -> None:
        """Legenda + tempo fixo. Use `fala` quando houver narração."""
        self.legenda(texto)
        self.pausa(segundos)

    def fala(self, chave: str, legenda: str, respiro: float = 0.45) -> None:
        """
        Uma batida de narração.

        Marca o instante, escreve a legenda e segura a tela pelo tempo REAL do
        mp3 gerado em `narracao.py`, mais um respiro. É isso que faz a imagem
        acompanhar a voz sem ninguém ajustar tempo na mão · se a frase mudar, o
        mp3 muda de duração e a cena se ajusta sozinha na próxima gravação.

        Sem tempos carregados (rodando só pra ver a tela), cai num tempo de
        leitura estimado pela quantidade de caracteres.
        """
        duracao = self.tempos.get(chave)
        if duracao is None:
            duracao = max(1.8, min(7.0, len(legenda) / 16.5))
        self.marcas.append({
            "chave": chave,
            "t": round(time.monotonic() - self._t0, 3),
            "dur": round(duracao, 3),
        })
        self.legenda(legenda)
        self.pausa(duracao + respiro)

    # ── movimento ────────────────────────────────────────────────────────
    def rolar(self, pixels: int, ms: int = 900) -> None:
        self.page.evaluate(
            "([d, ms]) => window.__rolarAte(window.scrollY + d, ms)", [pixels, ms]
        )
        self.pausa(ms / 1000 + 0.25)

    def rolar_ate(self, seletor: str, ms: int = 900, folga: int = 140) -> bool:
        alvo = self.page.locator(seletor).first
        if not alvo.count():
            return False
        caixa = alvo.bounding_box()
        if not caixa:
            return False
        self.page.evaluate(
            "([y, ms]) => window.__rolarAte(Math.max(0, window.scrollY + y), ms)",
            [caixa["y"] - folga, ms],
        )
        self.pausa(ms / 1000 + 0.25)
        return True

    def apontar(self, alvo, passos: int = 22) -> bool:
        """Leva o cursor até o elemento sem clicar."""
        loc = self.page.locator(alvo).first if isinstance(alvo, str) else alvo
        if not loc.count():
            return False
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        caixa = loc.bounding_box()
        if not caixa:
            return False
        self.page.mouse.move(
            caixa["x"] + caixa["width"] / 2,
            caixa["y"] + caixa["height"] / 2,
            steps=passos,
        )
        self.pausa(0.45)
        return True

    def tocar(self, alvo, antes: float = 0.35, depois: float = 1.1) -> bool:
        """Aponta, pausa, clica. Devolve False se o elemento não existir."""
        if not self.apontar(alvo):
            return False
        self.pausa(antes)
        self.page.mouse.down()
        self.pausa(0.09)
        self.page.mouse.up()
        self.pausa(depois)
        return True

    def digitar(self, seletor: str, texto: str, atraso: int = 85) -> bool:
        campo = self.page.locator(seletor).first
        if not campo.count():
            return False
        if not self.tocar(campo, depois=0.25):
            return False
        campo.type(texto, delay=atraso)
        self.pausa(0.35)
        return True

    # ── interceptação de rede ────────────────────────────────────────────
    def mockar(self, padrao: re.Pattern, payload) -> None:
        """Devolve JSON fixo para um endpoint. Nada chega no banco."""
        self._ctx.route(padrao, lambda rota: rota.fulfill(json=payload))

    def mockar_bruto(self, padrao: re.Pattern, corpo: str, tipo: str) -> None:
        """Igual a `mockar`, mas com corpo cru · usado pro SSE do agente."""
        self._ctx.route(
            padrao,
            lambda rota: rota.fulfill(status=200, content_type=tipo, body=corpo),
        )

    def bloquear_escrita(self, *padroes: re.Pattern) -> None:
        """
        Mata POST/PUT/DELETE que gravariam em produção.

        noprod aponta pro banco de PROD, então toda cena que mexe em banca,
        follow de pick ou cadastro passa por aqui. GET segue normal, porque é
        justamente o dado real que faz o vídeo valer.
        """
        def porteiro(rota):
            if rota.request.method in ("POST", "PUT", "PATCH", "DELETE"):
                rota.fulfill(status=204, body="")
            else:
                rota.continue_()

        for p in padroes:
            self._ctx.route(p, porteiro)

    def logar(self, identificador: str, senha: str) -> bool:
        """
        Login pelo formulário do site.

        Só funciona onde o Turnstile está desligado (`TURNSTILE_SECRET_KEY`
        ausente no servidor). Em produção, com o captcha ligado, ele detecta o
        navegador instrumentado e nenhum token é emitido · nesse caso o
        caminho é o cookie do navegador comum, via `sessao.py`.
        """
        self.ir("/login", espera=1.6)
        campo = self.page.locator("#login-identifier")
        if not campo.count():
            print("  [erro] campo de login não encontrado")
            return False
        campo.fill(identificador)
        self.page.locator("#password").fill(senha)
        self.page.keyboard.press("Enter")
        try:
            self.page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        except Exception:
            erro = self.page.locator("text=/senha|inválid|incorret|seguran/i")
            detalhe = ""
            try:
                if erro.count():
                    detalhe = f" · o site disse: {erro.first.inner_text()[:90]}"
            except Exception:
                pass
            print(f"  [erro] login não completou{detalhe}")
            return False
        self.pausa(1.6)
        return True

    def sessao_valida(self) -> bool:
        """
        Confere se a sessão carregada ainda vale, olhando uma rota privada.

        Não existe login automatizado neste site, e não é limitação do script:
        `/api/auth/login` e `/api/auth/register` passam por `_verify_captcha`,
        e o Turnstile detecta navegador instrumentado (a Cloudflare devolve 401
        no challenge, com e sem interface gráfica). Derrotar isso seria burlar
        um controle de segurança, então o caminho é outro: a pessoa loga à mão
        uma vez em `gravar.py --login-manual` e o estado é reaproveitado aqui.

        Atenção: o backend guarda um `session_token` único por usuário, então
        logar de novo em outro lugar invalida a sessão salva. Grave logo depois
        de salvar.
        """
        self.ir("/meus-picks", espera=2.0)
        if "/login" in self.page.url:
            return False
        return True


def esperar_carregar(page: Page, segundos: float = 8.0) -> None:
    """Espera a rede sossegar, mas sem derrubar a cena se algo ficar pendurado."""
    fim = time.time() + segundos
    try:
        page.wait_for_load_state("networkidle", timeout=int(segundos * 1000))
    except Exception:
        pass
    while time.time() < fim and page.locator("[data-loading='true']").count():
        page.wait_for_timeout(200)
