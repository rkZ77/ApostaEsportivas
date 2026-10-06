"""
Recortes do site real pros anúncios (`anuncios/*.html`).

    python telas.py                 captura tudo de https://pickia.com.br
    python telas.py --url URL       outro ambiente
    python telas.py --so banca      só os recortes cujo nome começa assim

Cada recorte é um pedaço de uma página, achado pelo TÍTULO da seção e não por
pixel: o site muda de altura toda semana (lista de jogos do dia, ligas em
temporada) e um recorte por coordenada fixa sairia cortando no meio.

As telas que pedem conta (banca, meus picks, agente) abrem com sessão simulada
SÓ NO NAVEGADOR: `/api/auth/me` e `/api/banca` são respondidos aqui, com a banca
de demonstração de `fixtures.py`. Nenhum login acontece e nenhuma escrita sai:
todo POST/PUT/PATCH/DELETE é devolvido como 204 antes de chegar no servidor
(mesmo motivo do `Estudio.bloquear_escrita`: produção é produção).

O que NÃO dá pra capturar assim, de propósito: a análise completa de um pick
(mercado, linha e o texto da IA). Ela é conteúdo de assinante, e simular a
resposta seria inventar uma análise. Com uma sessão VIP real em `sessao.json`
(ver README, `gravar.py --login-manual`) dá pra acrescentar esses recortes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import fixtures

AQUI = Path(__file__).parent
SAIDA = AQUI / "saida" / "anuncio" / "telas"
LARGURA = 390
DPR = 3

# Usuário da sessão simulada. Só existe dentro do navegador da captura.
_USUARIO = {
    "id": 999999, "name": "Demo", "username": "demo", "email": "demo@pickia.com.br",
    "plan": "vip", "tier": "pro", "expires_at": "2027-12-31T00:00:00",
    "email_verified": True, "trial_used": True, "tutorial_status": "done",
    "is_admin": False, "role": "user",
}

# nome -> (rota, precisa de conta, título que ancora o recorte, folga acima, altura)
# título None = do topo da página. Altura em px de CSS (largura 390).
RECORTES: dict[str, tuple[str, bool, str | None, int, int]] = {
    "home-topo":            ("/",                         False, None, 0, 1180),
    "palpites-fila":        ("/palpites-de-futebol-hoje", False, "Jogos de hoje na fila da análise", 24, 940),
    "palpites-ligas":       ("/palpites-de-futebol-hoje", False, "Palpites por campeonato", 24, 760),
    "palpites-resolvidos":  ("/palpites-de-futebol-hoje", False, "Últimos palpites resolvidos", 24, 1000),
    "resultados-grafico":   ("/resultados",               False, "Picks por dia", 22, 300),
    "resultados-lista":     ("/resultados",               False, "Picks recentes", 40, 1300),
    "como-funciona":        ("/como-funciona",            False, None, 0, 3600),
    "planos-free":          ("/planos",                   False, "Para conferir o método antes de assinar.", 80, 540),
    "planos-pickia":        ("/planos",                   False, "Tudo do Free, mais os 8 módulos de pré-jogo.", 80, 1720),
    "planos-pro":           ("/planos",                   False, "Picks ao vivo", 150, 760),
    "banca-topo":           ("/banca",                    True,  None, 0, 1180),
    "banca-evolucao":       ("/banca",                    True,  "Evolução da banca", 40, 330),
    "banca-historico":      ("/banca",                    True,  "Últimos picks apostados", 16, 900),
    "banca-distribuicao":   ("/banca",                    True,  "Distribuição de resultados", 40, 200),
    "meus-picks-dia":       ("/meus-picks",               True,  "Como foi por dia", 40, 340),
    "agente":               ("/agente",                   True,  None, 0, 844),
}

# Barra de navegação, banners e o aviso de cookies são `fixed` no rodapé. No
# recorte de página inteira eles caem no meio do conteúdo, então saem.
_SEM_RODAPE = """() => {
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' && el.getBoundingClientRect().top > 300) el.style.display = 'none';
  }
}"""

# Topo do menor elemento cujo texto é exatamente o título.
_ACHAR = """(t) => {
  let melhor = null;
  for (const el of document.querySelectorAll('h1,h2,h3,h4,p,span,div,button,a')) {
    if (el.textContent.trim() !== t) continue;
    if (!melhor || melhor.contains(el)) melhor = el;
  }
  return melhor ? melhor.getBoundingClientRect().top + scrollY : null;
}"""


def _contexto(nav, conta: bool):
    ctx = nav.new_context(
        viewport={"width": LARGURA, "height": 844}, device_scale_factor=DPR,
        is_mobile=True, has_touch=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
    )

    def responder(route):
        req = route.request
        if req.method != "GET":
            return route.fulfill(status=204, body="")
        if conta and "/api/auth/me" in req.url:
            return route.fulfill(json=_USUARIO)
        if conta and "/api/banca" in req.url and "fechamentos" not in req.url:
            return route.fulfill(json=fixtures.banca())
        return route.continue_()

    ctx.route("**/api/**", responder)
    if conta:
        ctx.add_init_script(
            f"localStorage.setItem('user', {json.dumps(json.dumps(_USUARIO))});"
        )
    return ctx


def _abrir(p, url: str) -> None:
    # networkidle nunca chega em algumas rotas (polling), então load + espera.
    p.goto(url, wait_until="load", timeout=60000)
    p.wait_for_timeout(2500)
    aceitar = p.get_by_role("button", name="Entendi")
    if aceitar.count():
        aceitar.first.click()
        p.wait_for_timeout(300)
    # Rola a página inteira: seção que entra com animação ao aparecer sai
    # vazia no print se ninguém passou por ela.
    altura = p.evaluate("document.documentElement.scrollHeight")
    for y in range(0, altura, 450):
        p.evaluate(f"scrollTo(0, {y})")
        p.wait_for_timeout(120)
    p.evaluate("scrollTo(0, 0)")
    p.wait_for_timeout(700)
    p.evaluate(_SEM_RODAPE)


def capturar(base: str, so: str = "") -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    escolhidos = {n: r for n, r in RECORTES.items() if n.startswith(so)}
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for conta in (False, True):
            lote = {n: r for n, r in escolhidos.items() if r[1] == conta}
            if not lote:
                continue
            ctx = _contexto(nav, conta)
            p = ctx.new_page()
            aberta = None
            for nome, (rota, _, titulo, folga, altura) in lote.items():
                try:
                    if rota != aberta:
                        _abrir(p, base.rstrip("/") + rota)
                        aberta = rota
                    y = 0
                    if titulo:
                        y = p.evaluate(_ACHAR, titulo)
                        if y is None:
                            print(f"  [aviso] {nome}: título não achado: {titulo!r}")
                            continue
                        y = max(0, y - folga)
                    total = p.evaluate("document.documentElement.scrollHeight")
                    altura = min(altura, total - y)
                    destino = SAIDA / f"{nome}.png"
                    p.screenshot(path=str(destino), full_page=True,
                                 clip={"x": 0, "y": y, "width": LARGURA, "height": altura})
                    print(f"  tela {nome:<20} y={int(y):>5}  h={int(altura)}")
                except Exception as erro:
                    print(f"  [aviso] {nome}: {erro}")
            ctx.close()
        nav.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Recortes do site real pros anúncios")
    ap.add_argument("--url", default="https://pickia.com.br")
    ap.add_argument("--so", default="", help="prefixo do nome do recorte")
    a = ap.parse_args()
    capturar(a.url, a.so)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
