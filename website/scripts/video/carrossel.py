"""
Carrosséis do Instagram: PNG 1080x1350, desenhados em HTML.

    python carrossel.py --listar
    python carrossel.py --todos
    python carrossel.py --carrossel banca

1080x1350 é 4:5, o formato que ocupa mais altura no feed · quadrado 1:1
desperdiça tela em celular, e 9:16 o feed corta.

Mesma identidade dos vídeos: fundo #0a0a0c, verde #00CC00, logo lido do
`frontend/public/logo.png`. O texto vive em `CARROSSEIS` aqui embaixo, junto,
pra editar tudo num lugar só.

Cada carrossel tem capa, slides de conteúdo e um último de chamada pra ação.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from cartoes import ACENTO, FUNDO, TINTA, TINTA_3, _logo_embutido

LARGURA, ALTURA = 1080, 1350

# nome -> {titulo, slides: [(titulo, corpo)], cta}
# Slide de conteúdo bom tem UMA ideia. Se precisou de dois parágrafos, era dois
# slides.
CARROSSEIS: dict[str, dict] = {
    # Versão enxuta: UMA frase por slide. Parágrafo de três linhas ninguém lê
    # passando o dedo no feed · o slide tem que ser lido de relance.
    "o-que-e": {
        "capa": ("O que é\no Pick IA?", "Em 5 telas"),
        "slides": [
            ("Achamos onde a odd está errada",
             "Todo dia, nos jogos das ligas em temporada."),
            ("Não somos casa de aposta",
             "Você aposta onde já aposta. Aqui você decide no quê."),
            ("Tem pick grátis todo dia",
             "Sem conta, sem cartão."),
            ("O histórico é público",
             "Green e red. Os dois."),
            ("E cuidamos da sua banca",
             "A parte que quase ninguém faz."),
        ],
        "cta": ("Conheça o Pick IA", "Conta grátis, com 2 dias de VIP."),
    },
    "como-funciona": {
        "capa": ("De onde vem\num pick?", "Em 5 telas"),
        "slides": [
            ("1. Lê o jogo", "Finalização, escanteio, falta, ritmo. Estatística real."),
            ("2. Calcula a chance", "A probabilidade de cada mercado naquele jogo."),
            ("3. Compara com a odd", "Odd é probabilidade disfarçada."),
            ("4. Só então vira pick", "Sem valor, o jogo não entra."),
            ("5. Fica registrado", "Green ou red, vai pro histórico público."),
        ],
        "cta": ("Confira o histórico", "O placar completo está aberto."),
    },
    "banca": {
        "capa": ("Apostar sem banca\né torcer.", "Como montar a sua"),
        "slides": [
            ("O que é banca", "O dinheiro que você separou pra apostar."),
            ("O que é unidade", "O tamanho padrão da sua entrada."),
            ("Quanto vale a unidade", "Entre 1% e 5% da banca. Nem mais."),
            ("Por que isso importa", "Unidade grande quebra você na primeira má fase."),
            ("O site avisa", "Ele trava se a unidade for grande demais."),
        ],
        "cta": ("Configure a sua", "Leva 30 segundos."),
    },
    "pegar-pick": {
        "capa": ("Por que ESSE\nmercado?", "Lendo um pick de verdade"),
        "slides": [
            ("O card diz o essencial", "Times, mercado, odd e a chance calculada."),
            ("Entenda esta análise", "Um toque abre o raciocínio inteiro."),
            ("Os números na mesa", "Dá pra discordar e não entrar."),
            ("Registre a aposta", "A casa, a odd que você pegou, as unidades."),
            ("O stake vem pronto", "Sai da sua banca, não de chute."),
        ],
        "cta": ("Veja os picks de hoje", "Publicados direto no site."),
    },
    "erros-de-banca": {
        "capa": ("5 erros que\nquebram a banca", "Nenhum é escolher mal o jogo"),
        "slides": [
            ("1. Unidade grande demais", "Cinco reds seguidos zeram você. E acontecem."),
            ("2. Dobrar depois do red", "Martingale parece conta. É armadilha."),
            ("3. Apostar pra recuperar", "É a perda decidindo por você."),
            ("4. Subir a unidade no lucro", "O primeiro red devolve duas semanas."),
            ("5. Não registrar", "Você lembra dos greens e esquece dos reds."),
        ],
        "cta": ("Configure sua banca", "O site calcula a unidade e avisa o risco."),
    },
}

_ESTILO = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:{LARGURA}px; height:{ALTURA}px; background:{FUNDO}; color:{TINTA};
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
  display:flex; flex-direction:column; padding:88px 84px;
  position:relative; overflow:hidden;
}}
body::before {{
  content:''; position:absolute; left:46%; top:56%;
  width:1250px; height:1250px; transform:translate(-50%,-50%);
  background:radial-gradient(circle, rgba(0,204,0,.16) 0%, rgba(0,204,0,0) 64%);
}}
.topo {{
  display:flex; align-items:center; gap:18px; position:relative; z-index:1;
  font-size:32px; font-weight:800; letter-spacing:-.02em;
}}
.topo img {{ width:70px; height:70px; }}
.topo .nome {{ color:{TINTA}; }}
.topo .nome span {{ color:{ACENTO}; }}
.corpo {{
  flex:1; display:flex; flex-direction:column; justify-content:center;
  position:relative; z-index:1;
}}
.barra {{ width:112px; height:8px; background:{ACENTO}; border-radius:99px; margin-bottom:44px; }}
.capa-titulo {{ font-size:104px; font-weight:900; line-height:1.02; letter-spacing:-.035em; white-space:pre-line; }}
.capa-sub {{ font-size:40px; font-weight:600; color:{TINTA_3}; margin-top:36px; }}
.num {{ font-size:34px; font-weight:900; color:{ACENTO}; letter-spacing:.06em; margin-bottom:20px; }}
.titulo {{ font-size:76px; font-weight:900; line-height:1.06; letter-spacing:-.03em; }}
/* Corpo grande porque agora é uma frase, não um parágrafo · slide de feed é
   lido de relance, com o dedo já a caminho do próximo. */
.texto {{ font-size:46px; font-weight:500; line-height:1.4; color:#c7c7cf; margin-top:34px; }}
.cta {{
  display:inline-block; margin-top:48px; padding:26px 48px; background:{ACENTO};
  color:#04140a; border-radius:20px; font-size:38px; font-weight:900;
}}
.rodape {{
  position:relative; z-index:1; font-size:26px; font-weight:600; color:{TINTA_3};
  display:flex; justify-content:space-between; align-items:center;
}}
.arraste {{ color:{ACENTO}; font-weight:800; }}
"""


def _pagina(corpo: str, rodape_dir: str, logo: str) -> str:
    return (
        f"<!doctype html><meta charset='utf-8'><style>{_ESTILO}</style>"
        f"<div class='topo'>{logo}<span class='nome'>Pick<span>IA</span></span></div>"
        f"<div class='corpo'>{corpo}</div>"
        f"<div class='rodape'><span>pickia.com.br</span>"
        f"<span class='arraste'>{rodape_dir}</span></div>"
    )


def render(nome: str, destino: Path) -> list[Path]:
    dados = CARROSSEIS[nome]
    destino.mkdir(parents=True, exist_ok=True)
    logo_uri = _logo_embutido()
    logo = f'<img src="{logo_uri}" alt="">' if logo_uri else ""

    titulo_capa, sub_capa = dados["capa"]
    paginas = [(
        f"<div class='barra'></div>"
        f"<div class='capa-titulo'>{titulo_capa}</div>"
        f"<div class='capa-sub'>{sub_capa}</div>",
        "arraste →",
    )]

    total = len(dados["slides"])
    for i, (titulo, texto) in enumerate(dados["slides"], start=1):
        paginas.append((
            f"<div class='num'>{i:02d} / {total:02d}</div>"
            f"<div class='titulo'>{titulo}</div>"
            f"<div class='texto'>{texto}</div>",
            "arraste →",
        ))

    cta_titulo, cta_texto = dados["cta"]
    paginas.append((
        f"<div class='barra'></div>"
        f"<div class='titulo'>{cta_titulo}</div>"
        f"<div class='texto'>{cta_texto}</div>"
        f"<div><span class='cta'>pickia.com.br</span></div>",
        "link na bio",
    ))

    gerados: list[Path] = []
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(
            viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1
        )
        for i, (corpo, rodape) in enumerate(paginas):
            arquivo = destino / f"{nome}-{i:02d}.png"
            pagina.set_content(_pagina(corpo, rodape, logo))
            pagina.screenshot(path=str(arquivo))
            gerados.append(arquivo)
        navegador.close()

    return gerados


def main() -> int:
    p = argparse.ArgumentParser(description="Gera carrosséis 1080x1350 pro Instagram")
    p.add_argument("--carrossel", action="append", default=[])
    p.add_argument("--todos", action="store_true")
    p.add_argument("--listar", action="store_true")
    p.add_argument("--saida", default=str(Path(__file__).parent / "carrossel"))
    args = p.parse_args()

    if args.listar:
        print("carrosséis disponíveis:\n")
        for nome, d in CARROSSEIS.items():
            print(f"  {nome:<15} {len(d['slides']) + 2} slides · {d['capa'][1]}")
        return 0

    escolhidos = list(CARROSSEIS) if args.todos else args.carrossel
    if not escolhidos:
        print("erro: use --carrossel <nome>, --todos ou --listar", file=sys.stderr)
        return 2

    desconhecidos = [c for c in escolhidos if c not in CARROSSEIS]
    if desconhecidos:
        print(f"erro: não existe: {', '.join(desconhecidos)}", file=sys.stderr)
        return 2

    saida = Path(args.saida)
    for nome in escolhidos:
        arquivos = render(nome, saida)
        print(f"[{nome}] {len(arquivos)} slides em {saida / nome}-NN.png")

    print(f"\npronto em {saida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
