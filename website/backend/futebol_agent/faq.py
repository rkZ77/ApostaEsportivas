"""Respostas fixas sobre o site/planos, resolvidas por fuzzy-match local.

Perguntas genéricas ("quais os planos", "como funciona a alavancagem")
não precisam de IA nem de dados ao vivo — responder direto aqui evita
chamar a API do Claude, então fica liberado pra qualquer plano (inclusive
free) sem custo e sem limite diário. Só a análise real de jogos (tools +
Claude) continua exclusiva de quem paga.
"""

from rapidfuzz import fuzz, process

from routers.payments import PLANS

_MATCH_THRESHOLD = 82


def _plans_text() -> str:
    linhas = [f"• **{p['title']}**: R${p['price']:.2f} ({p['days']} dias de acesso)" for p in PLANS.values()]
    return "\n".join(linhas)


_FAQ: list[dict] = [
    {
        "id": "sobre",
        "perguntas": [
            "o que é o pickia", "o que é esse site", "sobre o site", "sobre o pickia",
            "o que vocês fazem", "como funciona o site", "o que é isso aqui", "pra que serve o site",
        ],
        "resposta": (
            "O **PickIA** é uma plataforma de picks esportivos gerados por IA, com cobertura do "
            "Brasileirão, Copa do Brasil, Libertadores, Sul-Americana e principais ligas europeias.\n\n"
            "A IA analisa estatísticas, forma recente dos times e odds de mercado pra sugerir apostas. "
            "Picks novos são publicados todos os dias por volta das 07h na aba Hoje."
        ),
    },
    {
        "id": "planos",
        "perguntas": [
            "quais os planos", "quanto custa o vip", "preço do vip", "valores das assinaturas",
            "quanto custa a assinatura", "planos disponiveis", "quanto é pra assinar",
            "qual o valor do plano", "quanto custa ser vip", "preços", "me fala sobre os planos",
            "me responda sobre os planos", "me explica os planos", "quero saber sobre os planos",
        ],
        "resposta": None,
    },
    {
        "id": "pick_vip",
        "perguntas": [
            "o que é o pick vip", "como funciona o pick vip", "o que vem no vip",
            "quantos picks por dia", "quantas picks o vip tem",
        ],
        "resposta": (
            "O **Pick VIP** é o pick principal da plataforma: 1 pick por dia com confiança média acima "
            "de 70%, incluindo time, mercado, linha, odd e casa de apostas sugerida. É exclusivo de "
            "assinantes VIP/trial."
        ),
    },
    {
        "id": "multipla",
        "perguntas": [
            "o que é a múltipla", "como funciona a multipla", "o que é multipla do dia",
        ],
        "resposta": (
            "A **Múltipla** combina 2 picks do dia com alta correlação estatística, buscando "
            "multiplicar o retorno com os 2 greens. Também é exclusiva de assinantes VIP/trial."
        ),
    },
    {
        "id": "alavancagem",
        "perguntas": [
            "o que é alavancagem", "como funciona a alavancagem", "como funciona a série de alavancagem",
            "o que é a banca de alavancagem",
        ],
        "resposta": (
            "A **Alavancagem** é um sistema progressivo de banca, separado da banca principal:\n\n"
            "• Começa com R$50 (ou o valor que você configurar)\n"
            "• A cada GREEN, o lucro é reinvestido integralmente na próxima aposta\n"
            "• A cada RED, a banca reseta pro valor inicial e uma nova série começa\n"
            "• Odd alvo por volta de 1.50, com picks de alta consistência\n\n"
            "Objetivo: encadear greens seguidos e multiplicar a banca ao longo da série."
        ),
    },
    {
        "id": "pick_seguro",
        "perguntas": [
            "o que é o pick seguro", "tem pick gratis", "pick gratuito", "tem algum pick de graça",
            "o que o plano free tem", "como funciona o pick seguro",
        ],
        "resposta": (
            "O **Pick Seguro** é gratuito e liberado pra todo mundo, inclusive plano free. É publicado "
            "diariamente e geralmente cobre um mercado mais defensivo (over/under baixo).\n\n"
            "Pick VIP, Múltipla e Alavancagem, além do chat com análise ao vivo, são exclusivos de "
            "assinantes VIP ou trial."
        ),
    },
    {
        "id": "banca",
        "perguntas": [
            "como funciona a banca", "o que é unidade", "como configuro minha banca",
            "o que é stake", "como funciona o gerenciamento de banca",
        ],
        "resposta": (
            "Você define sua banca inicial e o valor da unidade (ex: banca R$1000, unidade R$20 = 2% "
            "por unidade). Cada Pick VIP tem um stake recomendado em unidades (ex: 1u, 2u, 3u), pra "
            "você dimensionar a aposta com base na confiança da IA.\n\n"
            "A banca de alavancagem é separada da banca principal e segue regras próprias."
        ),
    },
    {
        "id": "trial",
        "perguntas": [
            "tem teste gratis", "como funciona o trial", "posso testar o vip", "trial gratuito",
            "como ativo o trial", "tenho direito a trial",
        ],
        "resposta": (
            "Sim: usuários com CPF cadastrado no perfil podem ativar um **trial gratuito de 2 dias** com "
            "acesso completo ao VIP, uma única vez por CPF. Ative em Perfil → Ativar Trial."
        ),
    },
    {
        "id": "pagamento",
        "perguntas": [
            "formas de pagamento", "aceita pix", "posso pagar com cartão", "como pago a assinatura",
            "quais formas de pagamento vocês aceitam",
        ],
        "resposta": (
            "O pagamento é processado via Mercado Pago, com Pix, cartão de crédito e demais opções "
            "disponíveis no checkout. A confirmação do VIP é automática assim que o pagamento é aprovado."
        ),
    },
    {
        "id": "cancelamento",
        "perguntas": [
            "como cancelo", "como cancelar assinatura", "tem fidelidade", "cobra automatico",
            "renova sozinho", "é assinatura recorrente",
        ],
        "resposta": (
            "Não há cobrança recorrente automática: cada plano é um pagamento único com validade "
            "própria (30, 90, 180 ou 365 dias) que expira sozinho ao final do período. Não precisa "
            "cancelar nada — se quiser continuar VIP depois, é só renovar."
        ),
    },
    {
        "id": "horario_picks",
        "perguntas": [
            "que horas saem os picks", "quando saem as picks do dia", "que horas publicam os picks",
            "horário dos picks", "que horas sai o pick do dia", "que horas sai o pick",
        ],
        "resposta": "Os picks do dia (VIP, Múltipla, Alavancagem e Pick Seguro) são publicados diariamente por volta das 07h na aba Hoje.",
    },
    {
        "id": "sobre_a_ia",
        "perguntas": [
            "qual ia você usa", "que modelo de ia é esse", "você é o chatgpt", "quem te criou",
            "qual tecnologia por trás do agente", "você é a claude",
        ],
        "resposta": "Sou um agente de IA proprietário do PickIA, treinado para análise esportiva.",
    },
]

_QUESTIONS: list[str] = []
_QUESTION_ENTRY: list[int] = []
for _idx, _entry in enumerate(_FAQ):
    for _q in _entry["perguntas"]:
        _QUESTIONS.append(_q)
        _QUESTION_ENTRY.append(_idx)

# Preenche a resposta dinâmica de planos com os preços reais (fonte única: routers.payments.PLANS)
for _entry in _FAQ:
    if _entry["id"] == "planos":
        _entry["resposta"] = (
            "Planos disponíveis:\n\n"
            f"{_plans_text()}\n\n"
            "Todos dão acesso completo ao VIP (Pick VIP, Múltipla, Alavancagem e chat com análise ao "
            "vivo) durante o período. Pagamento único via Mercado Pago, sem cobrança recorrente."
        )
        break


def match_faq(user_text: str) -> str | None:
    """Retorna a resposta fixa se a pergunta bater com algum tópico de FAQ, senão None."""
    text = (user_text or "").strip()
    if len(text) < 3:
        return None

    # token_set_ratio (não WRatio): WRatio usa partial_ratio p/ strings de tamanho
    # muito diferente, o que dava falso positivo alto em perguntas reais de jogos
    # (ex.: "quantos escanteios o palmeiras fez" batia 85+ com "o que é o pickia"
    # só por sobreposição de caracteres). token_set_ratio exige overlap de palavras.
    match = process.extractOne(text, _QUESTIONS, scorer=fuzz.token_set_ratio, score_cutoff=_MATCH_THRESHOLD)
    if not match:
        return None

    _, _score, idx = match
    return _FAQ[_QUESTION_ENTRY[idx]]["resposta"]
