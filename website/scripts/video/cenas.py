"""
As cenas e o texto falado nelas.

Cada cena é um vídeo curto de um assunto só, entre 20 e 35 segundos · é o
formato que o Instagram e o TikTok premiam, e é mais fácil de refazer quando um
pedaço envelhece. Vídeo longo cobrindo tudo foi descartado: dava 70 segundos e
ninguém termina.

Duas regras atravessam o arquivo:

1. Nenhuma cena escreve no banco. noprod aponta pro banco de PRODUÇÃO, então
   todo POST de cadastro, setup de banca e follow de pick é interceptado em
   `estudio.bloquear_escrita`. Leitura é dado real; só banca e "meus picks" vêm
   de fixture, porque conta demo com follow entraria no ranking público.

2. Narração e legenda são textos diferentes. A voz conta a história; a legenda
   é o resumo curto que ainda funciona com o som desligado, que é como boa
   parte do Instagram assiste.

Sobre o tom da narração: é escrita pra ser FALADA, não lida. Frase curta,
"pra" em vez de "para", nada de tríade publicitária. Texto de anúncio é o que
faz voz sintética soar de robô · o problema quase nunca é a voz, é o texto.
"""
from __future__ import annotations

import re

import fixtures
from estudio import Estudio

# chave -> (o que a voz fala, o que aparece escrito)
NARRACAO: dict[str, tuple[str, str]] = {
    # ── 1. Convite ───────────────────────────────────────────────────────
    "convite-01": ("Você aposta no escuro?",
                   "Você aposta no escuro?"),
    "convite-02": ("Todo dia a gente varre os jogos e separa só onde tem valor de verdade.",
                   "Todo dia, os jogos com valor"),
    "convite-03": ("Não é palpite de grupo. É conta, comparada com a odd da casa.",
                   "Não é palpite. É conta."),
    "convite-fecho": ("Dá uma olhada. O link tá na bio.", ""),

    # ── 2. Cadastro ──────────────────────────────────────────────────────
    "cadastro-01": ("Criar conta aqui é de graça e não pede cartão.",
                    "Grátis, sem cartão"),
    "cadastro-02": ("Nome, usuário, email. Pronto.",
                    "Nome, usuário, email"),
    "cadastro-03": ("E já entra com dois dias de VIP liberados.",
                    "2 dias de VIP na hora"),
    "cadastro-fecho": ("Leva menos de um minuto. Link na bio.", ""),

    # ── 3. Como funciona ─────────────────────────────────────────────────
    "como-funciona-01": ("Como a gente escolhe um pick?",
                         "Como escolhemos um pick"),
    "como-funciona-02": ("O motor lê o jogo e calcula a chance de cada mercado acontecer.",
                         "Calcula a chance real"),
    "como-funciona-03": ("Aí compara com a odd que a casa tá pagando.",
                         "Compara com a odd"),
    "como-funciona-04": ("Se a conta não fecha a favor, o dia passa sem pick. E tudo bem.",
                         "Sem valor, sem pick"),
    "como-funciona-fecho": ("Tá tudo explicado no site. Link na bio.", ""),

    # ── 4. Resultados ────────────────────────────────────────────────────
    "resultados-01": ("Todo pick que sai fica registrado aqui.",
                      "Tudo fica registrado"),
    "resultados-02": ("Os greens e os reds. Os dois, na mesma página.",
                      "Green e red, os dois"),
    "resultados-03": ("Dá pra ver por liga, por dia e por mercado.",
                      "Por liga, dia e mercado"),
    "resultados-fecho": ("Confere você mesmo. Link na bio.", ""),

    # ── 5. Configurar banca ──────────────────────────────────────────────
    "banca-config-01": ("Antes de pegar pick, configura a banca.",
                        "Primeiro: a banca"),
    "banca-config-02": ("Banca é quanto você separou pra apostar. Só isso.",
                        "Quanto você separou"),
    "banca-config-03": ("Aqui, quinhentos reais. E cada unidade vale vinte e cinco.",
                        "R$ 500 · unidade de R$ 25"),
    "banca-config-04": ("O site avisa na hora se a unidade ficou grande demais.",
                        "O site avisa o risco"),
    "banca-config-fecho": ("Comece por aí. Link na bio.", ""),

    # ── 6. Abrir um pick ─────────────────────────────────────────────────
    "pick-abrir-01": ("Os picks do dia ficam todos aqui.",
                      "Os picks do dia"),
    "pick-abrir-02": ("Cada card mostra o mercado, a odd e a chance calculada.",
                      "Mercado, odd e chance"),
    "pick-abrir-03": ("E você pode abrir o raciocínio inteiro.",
                      "Abra o raciocínio"),
    "pick-abrir-04": ("Aqui tá por que esse mercado foi escolhido, e não outro.",
                      "Por que esse mercado"),
    "pick-abrir-fecho": ("Os picks de hoje tão no site. Link na bio.", ""),

    # ── 7. Registrar a aposta ────────────────────────────────────────────
    "pick-registrar-01": ("Decidiu entrar? Registra a aposta no site.",
                          "Registre a aposta"),
    "pick-registrar-02": ("A casa, a odd que você pegou e quantas unidades.",
                          "Casa, odd e unidades"),
    "pick-registrar-03": ("E o tamanho da entrada sai da sua banca, não de chute.",
                          "Stake vem da sua banca"),
    "pick-registrar-fecho": ("Testa aí. Link na bio.", ""),

    # ── 8. Meus picks ────────────────────────────────────────────────────
    "meus-picks-01": ("Tudo que você apostou fica guardado aqui.",
                      "Tudo em Meus Picks"),
    "meus-picks-02": ("Acerto, sequência, e como foi cada dia.",
                      "Acerto e sequência"),
    "meus-picks-03": ("Sem planilha, sem anotar no caderno.",
                      "Sem planilha"),
    "meus-picks-fecho": ("Acompanhe a sua. Link na bio.", ""),

    # ── 9. Minha banca ───────────────────────────────────────────────────
    "minha-banca-01": ("Na banca você vê o dinheiro, não só o placar.",
                       "O dinheiro, não o placar"),
    "minha-banca-02": ("Começou com quinhentos, tá em quinhentos e sessenta e cinco.",
                       "R$ 500 vira R$ 565"),
    "minha-banca-03": ("E esse gráfico é o seu resultado. Não é a média da IA.",
                       "Seu resultado, não a média"),
    "minha-banca-fecho": ("Faz a sua. Link na bio.", ""),

    # ── 10. Agente ───────────────────────────────────────────────────────
    "agente-01": ("Esse é o agente. Ele conhece os picks do dia e a sua banca.",
                  "Ele conhece a sua banca"),
    "agente-02": ("Pergunta em português mesmo, do jeito que você falaria.",
                  "Pergunte normal"),
    "agente-03": ("Ele consulta o site na hora pra te responder.",
                  "Consulta na hora"),
    "agente-fecho": ("Conversa com ele. Link na bio.", ""),

    # ── 11. Ranking ──────────────────────────────────────────────────────
    "ranking-01": ("Dá pra ver como os outros estão indo.",
                   "O ranking é público"),
    "ranking-02": ("O ranking é dos usuários, com a banca de cada um.",
                   "Banca de quem usa"),
    "ranking-03": ("Não é a nossa média. É gente de verdade seguindo os picks.",
                   "Gente de verdade"),
    "ranking-fecho": ("Entra e compara. Link na bio.", ""),

    # ── 12. Múltiplas ────────────────────────────────────────────────────
    "multipla-01": ("Múltipla não é juntar palpite pra inflar odd.",
                    "Múltipla não é inflar odd"),
    "multipla-02": ("Cada perna passa pelo mesmo filtro de valor que um pick sozinho.",
                    "Cada perna tem que ter valor"),
    "multipla-03": ("Se uma perna não fecha a conta, a múltipla não sai.",
                    "Perna fraca, múltipla não sai"),
    "multipla-fecho": ("Vê as de hoje. Link na bio.", ""),

    # ── 13. Saque ────────────────────────────────────────────────────────
    "saque-01": ("Ganhou e quer tirar? Registra o saque aqui.",
                 "Registre o saque"),
    "saque-02": ("A banca cai junto, e a unidade se ajusta ao novo tamanho.",
                 "A unidade se ajusta"),
    "saque-03": ("É isso que impede você de sacar o lucro e continuar apostando como se ele estivesse lá.",
                 "Sem apostar dinheiro que saiu"),
    "saque-fecho": ("Organiza a sua. Link na bio.", ""),
}

# Sufixo das falas que tocam sobre o cartão de fecho.
SUFIXO_FECHO = "fecho"

#
# `titulo` é subtítulo do gancho, não pode repetir a marca · o logo já está no
# canto do cartão, e "Pick IA" embaixo de "Pick IA" só ocupa espaço.
#
CARTOES: dict[str, dict[str, str]] = {
    "convite":        {"gancho": "Você aposta no escuro?",
                       "titulo": "Picks de futebol com valor calculado",
                       "fecho": "Veja os picks de hoje", "cta": "pickia.com.br"},
    "cadastro":       {"gancho": "Conta grátis em 1 minuto",
                       "titulo": "Sem cartão, com 2 dias de VIP",
                       "fecho": "Crie sua conta grátis", "cta": "pickia.com.br"},
    "como-funciona":  {"gancho": "De onde vem o pick?",
                       "titulo": "Chance calculada contra a odd da casa",
                       "fecho": "Entenda o método", "cta": "pickia.com.br"},
    "resultados":     {"gancho": "Cadê o histórico?",
                       "titulo": "Green e red, tudo na mesma página",
                       "fecho": "Confira os resultados", "cta": "pickia.com.br"},
    "banca-config":   {"gancho": "Apostar sem banca é torcer.",
                       "titulo": "O passo que separa aposta de gestão",
                       "fecho": "Comece pela banca", "cta": "pickia.com.br"},
    "pick-abrir":     {"gancho": "Por que ESSE mercado?",
                       "titulo": "O raciocínio por trás de cada escolha",
                       "fecho": "Veja os picks de hoje", "cta": "pickia.com.br"},
    "pick-registrar": {"gancho": "Quanto apostar?",
                       "titulo": "O stake sai da sua banca, não de chute",
                       "fecho": "Monte a sua banca", "cta": "pickia.com.br"},
    "meus-picks":     {"gancho": "Ainda anota em planilha?",
                       "titulo": "Suas apostas organizadas sozinhas",
                       "fecho": "Acompanhe as suas", "cta": "pickia.com.br"},
    "minha-banca":    {"gancho": "R$ 500 viram quanto?",
                       "titulo": "Sua banca acompanhada dia a dia",
                       "fecho": "Acompanhe a sua", "cta": "pickia.com.br"},
    "agente":         {"gancho": "Pergunta e ele responde.",
                       "titulo": "Um agente que consulta o site na hora",
                       "fecho": "Converse com o Agente", "cta": "pickia.com.br"},
    "ranking":        {"gancho": "Como os outros\nestão indo?",
                       "titulo": "O ranking de quem segue os picks",
                       "fecho": "Compare com a sua", "cta": "pickia.com.br"},
    "multipla":       {"gancho": "Múltipla é\nsó juntar odd?",
                       "titulo": "Cada perna passa pelo mesmo filtro",
                       "fecho": "Veja as múltiplas de hoje", "cta": "pickia.com.br"},
    "saque":          {"gancho": "Tirou o lucro.\nE a banca?",
                       "titulo": "Sacar sem bagunçar a contabilidade",
                       "fecho": "Organize a sua banca", "cta": "pickia.com.br"},
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


def _sem_picks(e: Estudio) -> bool:
    if e.page.locator("button:has-text('Entenda esta análise')").count():
        return False
    print("  [aviso] nenhum pick na tela · a janela do motor é só HOJE, "
          "então sem pick publicado esta cena sai vazia")
    return True


# ─────────────────────────────────────────────────────────────────────────────
def convite(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.ir("/", espera=2.2)
    fala(e, "convite-01")
    e.rolar(500, ms=1200)
    fala(e, "convite-02")
    e.rolar(540, ms=1200)
    fala(e, "convite-03")
    e.rolar_ate("text=Ver histórico completo", ms=1000)
    e.pausa(1.0)
    e.legenda(None)


def cadastro(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.ir("/", espera=2.0)
    _aviso(e.rolar_ate("a:has-text('Criar conta grátis')", ms=1100), "CTA de cadastro")
    fala(e, "cadastro-01")
    if e.tocar("a:has-text('Criar conta grátis')", depois=1.6):
        fala(e, "cadastro-02")
        _aviso(e.digitar("#reg-name", "Lucas Andrade"), "campo nome")
        _aviso(e.digitar("#reg-username", "lucas.andrade"), "campo usuário")
        _aviso(e.digitar("#reg-email", "lucas@exemplo.com"), "campo email")
        # O POST está bloqueado e a cena nem chega a enviar: termina no
        # formulário preenchido, que é o frame de chamada pra ação.
        fala(e, "cadastro-03")
    e.legenda(None)


def como_funciona(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.ir("/como-funciona", espera=2.0)
    fala(e, "como-funciona-01")
    e.rolar(420, ms=1000)
    fala(e, "como-funciona-02")
    e.rolar(420, ms=1000)
    fala(e, "como-funciona-03")
    e.rolar(420, ms=1000)
    fala(e, "como-funciona-04")
    e.legenda(None)


def resultados(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.ir("/resultados", espera=2.4)
    fala(e, "resultados-01")
    e.rolar(460, ms=1100)
    fala(e, "resultados-02")
    e.rolar(500, ms=1100)
    fala(e, "resultados-03")
    e.rolar(460, ms=1100)
    e.pausa(0.8)
    e.legenda(None)


def banca_config(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca_zerada())
    e.ir("/banca", espera=2.2)
    fala(e, "banca-config-01")
    ok = e.tocar("button:has-text('Configurar banca')", depois=1.3)
    if not ok:
        ok = e.tocar("text=Configurar banca", depois=1.3)
    _aviso(ok, "botão configurar banca")
    fala(e, "banca-config-02")
    _aviso(e.digitar("input[placeholder='Ex: 500']", "500", atraso=170), "campo banca")
    _aviso(e.digitar("input[placeholder='Ex: 5']", "25", atraso=180), "campo unidade")
    fala(e, "banca-config-03")
    e.rolar_ate("text=Banca saudável", ms=700, folga=200)
    fala(e, "banca-config-04")
    e.legenda(None)


def pick_abrir(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    e.ir("/picks", espera=3.0)
    if _sem_picks(e):
        return
    fala(e, "pick-abrir-01")
    e.rolar(220, ms=800)
    fala(e, "pick-abrir-02")
    fala(e, "pick-abrir-03")
    if e.tocar("button:has-text('Entenda esta análise')", depois=1.8):
        fala(e, "pick-abrir-04")
        e.rolar(300, ms=900)
        e.pausa(1.4)
        e.page.keyboard.press("Escape")
    e.legenda(None)


def pick_registrar(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    e.ir("/picks", espera=3.0)
    if _sem_picks(e):
        return
    fala(e, "pick-registrar-01")
    if e.tocar("button:has-text('Apostar')", depois=1.6):
        fala(e, "pick-registrar-02")
        e.apontar("[aria-label='Aumentar unidades']")
        fala(e, "pick-registrar-03")
        e.pausa(0.8)
    e.legenda(None)


def meus_picks(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    e.ir("/meus-picks", espera=2.6)
    fala(e, "meus-picks-01")
    e.rolar(340, ms=950)
    fala(e, "meus-picks-02")
    e.rolar(400, ms=1000)
    fala(e, "meus-picks-03")
    e.legenda(None)


def minha_banca(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    e.ir("/banca", espera=2.4)
    fala(e, "minha-banca-01")
    e.rolar(360, ms=1000)
    fala(e, "minha-banca-02")
    e.rolar(400, ms=1000)
    fala(e, "minha-banca-03")
    e.legenda(None)


def agente(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    if ctx.get("chat_fake"):
        e.mockar_bruto(re.compile(r"/api/chat"), _CHAT_FAKE, "text/event-stream")
    e.ir("/agente", espera=2.4)
    fala(e, "agente-01")
    campo = "textarea[placeholder^='Pergunte sobre picks']"
    fala(e, "agente-02")
    _aviso(e.digitar(campo, "Quais os picks do site pra hoje?", atraso=45), "campo do agente")
    e.page.keyboard.press("Enter")
    fala(e, "agente-03")
    e.pausa(5.0)
    e.legenda(None)


def ranking(e: Estudio, ctx: dict) -> None:
    # `/public/leaderboard` é público, então esta cena não precisa de sessão.
    e.bloquear_escrita(*ESCRITA)
    e.ir("/", espera=2.4)
    # A seção some sozinha quando ninguém tem 3 picks resolvidos no mês
    # (`leaders.length === 0` devolve null em Home.tsx). Sem ela a cena não
    # tem assunto, então encerra em vez de gravar a home genérica.
    if not e.rolar_ate("text=Quem está indo melhor", ms=1300, folga=110):
        print("  [aviso] o bloco de ranking não está na home · sem usuário "
              "com 3 picks resolvidos no mês, ele não renderiza")
        return
    fala(e, "ranking-01")
    fala(e, "ranking-02")
    e.rolar(300, ms=900)
    fala(e, "ranking-03")
    e.legenda(None)


def multipla(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    # A aba é escolhida pelo hash da URL · ver o efeito de `setTab` em Picks.tsx.
    e.ir("/picks#multiplas", espera=3.0)
    fala(e, "multipla-01")
    e.rolar(240, ms=850)
    fala(e, "multipla-02")
    fala(e, "multipla-03")
    e.rolar(300, ms=900)
    e.legenda(None)


def saque(e: Estudio, ctx: dict) -> None:
    e.bloquear_escrita(*ESCRITA)
    e.mockar(ROTA_BANCA, fixtures.banca())
    e.ir("/banca/saque", espera=2.4)
    fala(e, "saque-01")
    _aviso(e.digitar("input[placeholder='Ex: 500']", "150", atraso=200), "campo de saque")
    fala(e, "saque-02")
    e.rolar_ate("text=Banca depois do saque", ms=700, folga=180)
    fala(e, "saque-03")
    e.legenda(None)


# nome -> (descrição, função, precisa de login)
CENAS: dict[str, tuple[str, callable, bool]] = {
    "convite":        ("Chamada: você aposta no escuro?", convite, False),
    "cadastro":       ("Criar conta grátis em 1 minuto", cadastro, False),
    "como-funciona":  ("De onde vem o pick", como_funciona, False),
    "resultados":     ("O histórico aberto", resultados, False),
    "banca-config":   ("Configurar a banca do zero", banca_config, True),
    "pick-abrir":     ("Abrir um pick e ver a análise", pick_abrir, True),
    "pick-registrar": ("Registrar a aposta e o stake", pick_registrar, True),
    "meus-picks":     ("Acompanhar suas apostas", meus_picks, True),
    "minha-banca":    ("A evolução da sua banca", minha_banca, True),
    "agente":         ("Conversar com o Agente IA", agente, True),
    "ranking":        ("O ranking público de quem segue", ranking, False),
    "multipla":       ("Como uma múltipla é montada", multipla, True),
    "saque":          ("Sacar sem bagunçar a banca", saque, True),
}


def falas_da_cena(nome: str) -> list[str]:
    """Chaves de narração de uma cena, na ordem em que aparecem."""
    return [k for k in NARRACAO if k.startswith(f"{nome}-")]


def fala_de_fecho(nome: str) -> str:
    """Chave da fala que toca sobre o cartão final."""
    return f"{nome}-{SUFIXO_FECHO}"
