"""
As cenas e o texto que é falado nelas.

Cada cena vira um .webm de 25 a 50 segundos, formato 9:16, que `montar.py`
depois transforma em mp4 com voz, cartão de abertura, transição e fecho.

Duas regras atravessam o arquivo:

1. Nenhuma cena escreve no banco. noprod aponta pro banco de PRODUÇÃO, então
   todo POST de cadastro, setup de banca e follow de pick é interceptado em
   `estudio.bloquear_escrita`. Leitura (home, picks do dia, análise,
   resultados) é dado real; só banca e "meus picks" vêm de fixture, porque
   conta demo com follow entraria no ranking público.

2. Narração e legenda são textos diferentes. A voz conta a história inteira; a
   legenda é o resumo que cabe na tela e ainda funciona com o som desligado,
   que é como boa parte do Instagram assiste.

Os seletores saem da cópia real das telas · se algum texto de botão mudar no
front, a cena degrada com aviso em vez de derrubar a gravação.
"""
from __future__ import annotations

import re

import fixtures
from estudio import Estudio

# chave -> (o que a voz fala, o que aparece escrito)
NARRACAO: dict[str, tuple[str, str]] = {
    # 1. Convite
    "convite-01": ("Todo dia, um motor estatístico varre os jogos e separa só onde existe valor de verdade.",
                   "Todo dia, os jogos com valor real"),
    "convite-02": ("Não é palpite de grupo de WhatsApp. É probabilidade calculada, comparada com a odd da casa.",
                   "Não é palpite. É cálculo."),
    "convite-03": ("E o histórico fica aberto. Os greens e os reds, todos eles, na mesma página.",
                   "Histórico aberto. Green e red."),
    "convite-04": ("Criar conta é de graça, não pede cartão, e já libera dois dias de acesso VIP.",
                   "Conta grátis, sem cartão"),
    "convite-05": ("Leva menos de um minuto pra começar.",
                   "Menos de um minuto"),

    # 2. Visão geral
    "geral-01": ("Em trinta segundos, como o Pick IA funciona por dentro.",
                 "Como funciona por dentro"),
    "geral-02": ("O motor lê o jogo, calcula a probabilidade de cada mercado e compara com a odd oferecida.",
                 "Probabilidade contra odd"),
    "geral-03": ("Só vira pick quando a conta fecha a favor. Se não fecha, o dia passa sem pick, e tudo bem.",
                 "Sem valor, sem pick"),
    "geral-04": ("Cada pick que sai fica registrado aqui, com o resultado, pra qualquer um conferir.",
                 "Tudo registrado"),
    "geral-05": ("Acerto por liga, por dia e por mercado. Nada escondido.",
                 "Aberto por liga e por dia"),

    # 3. Banca
    "banca-01": ("Antes de pegar qualquer pick, configure sua banca. É o passo que separa aposta de gestão.",
                 "Primeiro: configure a banca"),
    "banca-02": ("Banca é quanto você separou pra apostar. Só isso, e nada além disso.",
                 "Quanto você separou"),
    "banca-03": ("Aqui, quinhentos reais.",
                 "R$ 500"),
    "banca-04": ("Depois o valor de cada unidade. Vinte e cinco reais, que é cinco por cento da banca.",
                 "Unidade: R$ 25, ou 5%"),
    "banca-05": ("O próprio site classifica o risco e avisa quando a unidade está num tamanho seguro.",
                 "O site avisa o risco"),
    "banca-06": ("A partir daí, todo pick já chega com o stake calculado pra sua banca.",
                 "Stake calculado pra você"),

    # 4. Pegar pick
    "pick-01": ("Os picks do dia ficam todos nesta tela.",
                "Os picks do dia"),
    "pick-02": ("Cada card traz o mercado, a odd e a probabilidade que o motor calculou.",
                "Mercado, odd e probabilidade"),
    "pick-03": ("E dá pra abrir o raciocínio inteiro por trás da escolha.",
                "Abra o raciocínio"),
    "pick-04": ("Entenda esta análise mostra por que aquele mercado foi escolhido, e não outro.",
                "Entenda esta análise"),
    "pick-05": ("Os números ficam na mesa. Quem decide entrar é você.",
                "Você decide"),
    "pick-06": ("Se for entrar, registre a aposta no site: a casa, a odd que você pegou e quantas unidades.",
                "Registre a aposta"),
    "pick-07": ("A sugestão de stake vem da sua banca, não de chute.",
                "Stake vem da sua banca"),

    # 5. Acompanhar
    "acomp-01": ("Tudo que você apostou fica guardado em Meus Picks.",
                 "Tudo em Meus Picks"),
    "acomp-02": ("Acerto, sequência e evolução dia a dia.",
                 "Acerto e sequência"),
    "acomp-03": ("Na Banca você vê o dinheiro, não só o placar.",
                 "O dinheiro, não só o placar"),
    "acomp-04": ("Começou com quinhentos, está em quinhentos e sessenta e cinco. Treze por cento de retorno.",
                 "R$ 500 vira R$ 565"),
    "acomp-05": ("E esse gráfico é a sua banca. Não é a média da IA, é o seu resultado.",
                 "Sua banca, seu resultado"),
    "acomp-06": ("O placar geral do site continua aberto pra qualquer um conferir.",
                 "Placar geral aberto"),

    # 6. Agente
    "agente-01": ("O Agente conhece os picks do dia e conhece a sua banca.",
                  "Ele conhece a sua banca"),
    "agente-02": ("Pergunte em português mesmo, do jeito que você falaria.",
                  "Pergunte em português"),
    "agente-03": ("Ele consulta o site na hora pra responder, com dado atual.",
                  "Consulta o site na hora"),
    "agente-04": ("Dá pra perguntar de banca, de liga, de jogo ao vivo.",
                  "Banca, liga, jogo ao vivo"),

    # Falas de fecho. Não são chamadas por nenhuma cena: `montar.py` encaixa
    # cada uma por cima do cartão final, senão o vídeo termina com vários
    # segundos de silêncio, que é onde o Instagram perde o espectador.
    # "Link na bio" em vez de soletrar o domínio · é assim que se fala ali.
    "convite-fecho": ("Crie sua conta grátis. O link está na bio.", ""),
    "geral-fecho":   ("O histórico completo está no site. Link na bio.", ""),
    "banca-fecho":   ("Comece pela banca. O link está na bio.", ""),
    "pick-fecho":    ("Os picks de hoje estão no site. Link na bio.", ""),
    "acomp-fecho":   ("Acompanhe a sua banca. O link está na bio.", ""),
    "agente-fecho":  ("Converse com o Agente. O link está na bio.", ""),
}

# Sufixo das falas que tocam sobre o cartão de fecho.
SUFIXO_FECHO = "fecho"

# Cartão de abertura e de fecho de cada cena, desenhados em `cartoes.py`.
#
# `titulo` é subtítulo do gancho, não pode repetir a marca · o logo já está no
# canto do cartão, e "Pick IA" embaixo de "Pick IA" só ocupa espaço.
#
CARTOES: dict[str, dict[str, str]] = {
    "convite":     {"gancho": "Você aposta no escuro?",
                    "titulo": "Picks de futebol com valor calculado",
                    "fecho":  "Crie sua conta grátis",
                    "cta":    "pickia.com.br"},
    "visao-geral": {"gancho": "Como isso funciona?",
                    "titulo": "Do jogo até o pick, passo a passo",
                    "fecho":  "Veja o histórico completo",
                    "cta":    "pickia.com.br"},
    "banca":       {"gancho": "Apostar sem banca é torcer.",
                    "titulo": "O passo que separa aposta de gestão",
                    "fecho":  "Comece pela banca",
                    "cta":    "pickia.com.br"},
    "pegar-pick":  {"gancho": "De onde vem esse pick?",
                    "titulo": "O raciocínio por trás de cada escolha",
                    "fecho":  "Veja os picks de hoje",
                    "cta":    "pickia.com.br"},
    "acompanhar":  {"gancho": "R$ 500 viram quanto?",
                    "titulo": "Sua banca acompanhada dia a dia",
                    "fecho":  "Acompanhe a sua",
                    "cta":    "pickia.com.br"},
    "agente":      {"gancho": "Pergunta e ele responde.",
                    "titulo": "Um agente que consulta o site na hora",
                    "fecho":  "Converse com o Agente",
                    "cta":    "pickia.com.br"},
}

# Endpoints que gravam. Bloqueados em toda cena, sem exceção.
ESCRITA = (
    re.compile(r"/api/banca/setup"),
    re.compile(r"/api/banca/follow"),
    re.compile(r"/api/banca/withdraw"),
    re.compile(r"/api/banca/reset-month"),
    re.compile(r"/api/auth/register"),
)

ROTA_BANCA = re.compile(r"/api/banca(\?.*)?$")

# Resposta canned do agente, no formato SSE que `useAgentChat` espera.
# Só usada com --chat-fake; por padrão a cena fala com o agente de verdade.
_CHAT_FAKE = "".join(
    f"data: {linha}\n\n" for linha in [
        '{"type":"status","text":"consultando picks do dia"}',
        '{"type":"chunk","text":"Hoje o motor liberou ","first":true}',
        '{"type":"chunk","text":"**4 picks**: 2 no VIP e 2 no free.\\n\\n"}',
        '{"type":"chunk","text":"O de maior confiança é o Over 2.5 "}',
        '{"type":"chunk","text":"em Palmeiras x Fortaleza, odd 1.82.\\n\\n"}',
        '{"type":"chunk","text":"Sua banca está em R$ 565,25, então a unidade "}',
        '{"type":"chunk","text":"sugerida para esse pick é de 2u."}',
        '{"type":"done"}',
    ]
)


def fala(e: Estudio, chave: str) -> None:
    """Narra uma batida e segura a tela pelo tempo real do áudio."""
    e.fala(chave, NARRACAO[chave][1])


def _aviso(ok: bool, o_que: str) -> None:
    if not ok:
        print(f"  [aviso] não encontrei: {o_que}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Convite · chamada pra conhecer o site e criar conta
# ─────────────────────────────────────────────────────────────────────────────
def convite(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)

    e.ir("/", espera=2.2)
    fala(e, "convite-01")

    e.rolar(520, ms=1300)
    fala(e, "convite-02")

    e.rolar(560, ms=1300)
    fala(e, "convite-03")

    # Prova antes do pedido: o bloco de resultados vem antes do CTA de propósito.
    _aviso(e.rolar_ate("text=Ver histórico completo", ms=1100), "link de histórico")
    e.pausa(1.2)

    _aviso(e.rolar_ate("a:has-text('Criar conta grátis')", ms=1200), "CTA de cadastro")
    fala(e, "convite-04")

    if e.tocar("a:has-text('Criar conta grátis')", depois=1.8):
        _aviso(e.digitar("#reg-name", "Lucas Andrade"), "campo nome")
        _aviso(e.digitar("#reg-username", "lucas.andrade"), "campo usuário")
        _aviso(e.digitar("#reg-email", "lucas@exemplo.com"), "campo email")
        # O POST está bloqueado, mas a cena nem chega a enviar: termina no
        # formulário preenchido, que é o frame de chamada pra ação.
        fala(e, "convite-05")

    e.legenda(None)
    e.pausa(0.8)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Visão geral · o que o site faz
# ─────────────────────────────────────────────────────────────────────────────
def visao_geral(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)

    e.ir("/como-funciona", espera=2.0)
    fala(e, "geral-01")

    e.rolar(430, ms=1000)
    fala(e, "geral-02")

    e.rolar(430, ms=1000)
    fala(e, "geral-03")

    e.ir("/resultados", espera=2.4)
    fala(e, "geral-04")

    e.rolar(520, ms=1200)
    fala(e, "geral-05")

    e.rolar(520, ms=1200)
    e.pausa(1.2)

    e.legenda(None)
    e.pausa(0.8)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Configurar a banca
# ─────────────────────────────────────────────────────────────────────────────
def banca(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    # Começa "não configurada" pra cena poder mostrar o formulário do zero.
    e.mockar(ROTA_BANCA, fixtures.banca_zerada())

    e.ir("/banca", espera=2.2)
    fala(e, "banca-01")

    ok = e.tocar("button:has-text('Configurar banca')", depois=1.4)
    if not ok:
        ok = e.tocar("text=Configurar banca", depois=1.4)
    _aviso(ok, "botão configurar banca")

    fala(e, "banca-02")
    _aviso(e.digitar("input[placeholder='Ex: 500']", "500", atraso=190), "campo banca inicial")
    fala(e, "banca-03")

    _aviso(e.digitar("input[placeholder='Ex: 5']", "25", atraso=200), "campo unidade")
    fala(e, "banca-04")

    # A própria tela classifica o risco. Vale o close: é o argumento da cena.
    e.rolar_ate("text=Banca saudável", ms=800, folga=200)
    fala(e, "banca-05")
    fala(e, "banca-06")

    e.legenda(None)
    e.pausa(0.8)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pegar um pick e entender a análise
# ─────────────────────────────────────────────────────────────────────────────
def pegar_pick(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())

    e.ir("/picks", espera=3.0)

    cartoes = e.page.locator("button:has-text('Entenda esta análise')")
    if not cartoes.count():
        print("  [aviso] nenhum pick na tela · a janela do motor é só HOJE, "
              "então sem pick publicado esta cena sai vazia")
        return

    fala(e, "pick-01")
    e.rolar(240, ms=900)
    fala(e, "pick-02")
    fala(e, "pick-03")

    if e.tocar(cartoes.first, depois=2.0):
        fala(e, "pick-04")
        e.rolar(320, ms=1000)
        e.pausa(1.2)
        e.rolar(320, ms=1000)
        fala(e, "pick-05")
        e.page.keyboard.press("Escape")
        e.pausa(1.2)

    fala(e, "pick-06")
    if e.tocar("button:has-text('Apostar')", depois=1.8):
        e.apontar("[aria-label='Aumentar unidades']")
        fala(e, "pick-07")

    e.legenda(None)
    e.pausa(0.8)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Acompanhar · meus picks, minha banca, resultados
# ─────────────────────────────────────────────────────────────────────────────
def acompanhar(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())

    e.ir("/meus-picks", espera=2.6)
    fala(e, "acomp-01")
    e.rolar(360, ms=1000)
    fala(e, "acomp-02")
    e.rolar(420, ms=1100)
    e.pausa(1.0)

    e.ir("/banca", espera=2.4)
    fala(e, "acomp-03")
    e.rolar(380, ms=1000)
    fala(e, "acomp-04")
    e.rolar(420, ms=1100)
    fala(e, "acomp-05")

    e.ir("/resultados", espera=2.4)
    fala(e, "acomp-06")
    e.rolar(480, ms=1200)
    e.pausa(1.2)

    e.legenda(None)
    e.pausa(0.8)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Agente IA
# ─────────────────────────────────────────────────────────────────────────────
def agente(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())

    if ctx.get("chat_fake"):
        e.mockar_bruto(re.compile(r"/api/chat"), _CHAT_FAKE, "text/event-stream")

    e.ir("/agente", espera=2.4)
    fala(e, "agente-01")

    campo = "textarea[placeholder^='Pergunte sobre picks']"
    fala(e, "agente-02")
    _aviso(e.digitar(campo, "Quais os picks do site pra hoje?", atraso=55), "campo do agente")
    e.pausa(0.5)
    e.page.keyboard.press("Enter")

    fala(e, "agente-03")
    e.pausa(5.0)
    fala(e, "agente-04")
    e.rolar(300, ms=900)
    e.pausa(1.2)

    e.legenda(None)
    e.pausa(0.8)


# nome -> (descrição, função, precisa de login)
CENAS: dict[str, tuple[str, callable, bool]] = {
    "convite":     ("Chamada pra conhecer o site e criar conta", convite, False),
    "visao-geral": ("O que o site faz, de ponta a ponta", visao_geral, False),
    "banca":       ("Configurar a banca do zero", banca, True),
    "pegar-pick":  ("Pegar um pick e abrir a análise", pegar_pick, True),
    "acompanhar":  ("Meus picks, minha banca e resultados", acompanhar, True),
    "agente":      ("Conversar com o Agente IA", agente, True),
}


PREFIXOS = {
    "convite": "convite-", "visao-geral": "geral-", "banca": "banca-",
    "pegar-pick": "pick-", "acompanhar": "acomp-", "agente": "agente-",
}


def falas_da_cena(nome: str) -> list[str]:
    """Chaves de narração de uma cena, na ordem em que aparecem."""
    p = PREFIXOS[nome]
    return [k for k in NARRACAO if k.startswith(p)]


def fala_de_fecho(nome: str) -> str:
    """Chave da fala que toca sobre o cartão final."""
    return f"{PREFIXOS[nome]}{SUFIXO_FECHO}"
