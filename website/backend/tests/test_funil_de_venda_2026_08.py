"""Funil de venda: a oferta sai de uma fonte so, e a tela de pagar tem prova.

Nada aqui toca banco nem sobe navegador. O que se verifica e o ACOPLAMENTO
entre as telas do funil, que e onde os tres defeitos desta leva moravam:

  * a lista do que o VIP entrega era escrita a mao em dois lugares, e a tela de
    pagar tinha a versao curta -- sete modulos que a assinatura abre nao eram
    mencionados justamente ali;
  * /planos deslogado, que e a pagina que o menu aponta e que ranqueia na
    busca, nao mostrava um numero de desempenho sequer;
  * "vai cobrar sozinho todo mes?" nao era respondido em lugar nenhum do site,
    embora a resposta seja favoravel ao produto (a cobranca e avulsa).
"""

import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------- uma fonte para a oferta

def test_catalogo_de_modulos_existe_e_separa_free_de_vip():
    src = _front("lib/oferta.ts")
    assert "export const MODULOS" in src
    assert "MODULOS_FREE" in src and "MODULOS_VIP" in src
    # O `plano` e o que separa as duas colunas da pagina de planos.
    assert "plano: 'vip'" in src and "plano: 'ambos'" in src


@pytest.mark.parametrize("modulo", [
    "Picks VIP", "Picks ao vivo", "Múltiplas", "Alavancagem", "Pick Boost",
    "Estatística de jogador", "Mercado de faltas", "Defesas de goleiro",
    "Agente de futebol",
])
def test_todo_produto_pago_esta_no_catalogo(modulo):
    """O que a assinatura abre tem que estar listado onde ela e vendida.

    A lista antiga do Checkout citava tres destes nove. Os outros seis eram
    produto entregue e nao anunciado na tela da compra.
    """
    assert modulo in _front("lib/oferta.ts")


@pytest.mark.parametrize("tela", ["pages/Checkout.tsx", "pages/Planos.tsx", "home/Products.tsx"])
def test_as_tres_telas_leem_do_catalogo(tela):
    assert "lib/oferta" in _front(tela)


def test_nenhuma_tela_reescreve_a_lista_a_mao():
    """A vitrine da Home tinha o array local `PRODUCTS` e o Checkout tinha o
    seu, com outro texto. Duas listas divergindo em silencio e exatamente o que
    a fonte unica veio impedir."""
    assert "const PRODUCTS" not in _front("home/Products.tsx")
    checkout = _front("pages/Checkout.tsx")
    assert "'Análise de probabilidades'" not in checkout
    assert "'Suporte ao Agente de IA'" not in checkout


# --------------------------------------------------------- sem recorrencia

def test_frase_da_cobranca_mora_no_catalogo():
    """Ela descreve o COMPORTAMENTO do backend (uma `preference` do
    MercadoPago, que cobra uma vez), nao uma escolha de copy. Solta dentro de
    duas telas, viraria mentira em duas telas no dia em que a cobranca mudar."""
    assert "SEM_RENOVACAO_AUTOMATICA" in _front("lib/oferta.ts")


@pytest.mark.parametrize("tela", ["pages/Checkout.tsx", "pages/Planos.tsx"])
def test_a_ausencia_de_recorrencia_aparece_onde_se_decide(tela):
    assert "SEM_RENOVACAO_AUTOMATICA" in _front(tela)


def test_a_frase_so_vale_enquanto_a_cobranca_for_avulsa():
    """Guarda-costas do texto acima: se `preapproval` (assinatura recorrente do
    MercadoPago) aparecer no backend, a promessa deixou de ser verdadeira e
    este teste tem que cair junto."""
    with open(os.path.join(_BACKEND, "routers", "payments.py"), encoding="utf-8") as f:
        pagamentos = f.read()
    assert "preapproval" not in pagamentos, (
        "a cobranca virou recorrente -- tirar SEM_RENOVACAO_AUTOMATICA de "
        "lib/oferta.ts no mesmo commit"
    )


# ----------------------------------------------------- prova onde se decide

@pytest.mark.parametrize("tela", ["pages/Checkout.tsx", "pages/Planos.tsx"])
def test_as_telas_de_decisao_mostram_o_historico(tela):
    assert "ProvaPublica" in _front(tela)


def test_prova_nao_escreve_numero_a_mao():
    """Todo numero sai de /public/results, o mesmo endpoint da Home e da pagina
    de Resultados. Contador fabricado ja saiu deste site uma vez."""
    src = _front("components/ProvaPublica.tsx")
    assert "/public/results" in src


def test_prova_pede_o_minimo():
    """A faixa le tres campos do `summary` e nao usa `recent`. `slim=1` corta a
    rota de sete consultas para tres; `recent_limit` tem que respeitar o `ge=1`
    da rota, entao zero nao serve (devolveria 422)."""
    src = _front("components/ProvaPublica.tsx")
    assert "slim: 1" in src
    m = re.search(r"recent_limit:\s*(\d+)", src)
    assert m and int(m.group(1)) >= 1


def test_prova_some_quando_nao_ha_historico():
    """Uma faixa de zeros ao lado de um botao de pagar e pior que faixa
    nenhuma."""
    src = _front("components/ProvaPublica.tsx")
    assert "if (carregou && (!resumo || !resumo.total)) return null" in src


# --------------------------------------------------------- grade de precos

def test_o_numero_grande_da_grade_e_o_preco_por_mes():
    """Entre quatro totais de periodos diferentes, o anual e o MAIOR da grade
    justamente por ser o mais barato por mes -- e era assim que ele aparecia. O
    que se compara entre periodos e o valor mensal."""
    src = _front("pages/Planos.tsx")
    grade = src[src.index("Escolha o período"):src.index("Testar o VIP grátis")]
    assert "text-lg font-black" in grade
    posicao_mes = grade.index("fmtPlanPrice(pl.price_per_month)")
    posicao_total = grade.index("fmtPlanPrice(pl.price)")
    assert posicao_mes < posicao_total, "o preco por mes tem que vir primeiro"


def test_selo_de_melhor_preco_e_lido_da_grade():
    """Fixar no anual deixaria o selo no plano errado no dia de um reajuste que
    mudasse a ordem."""
    assert "maiorEconomia" in _front("pages/Planos.tsx")


def test_mensal_nao_repete_o_proprio_preco():
    """"R$ 39,90 por mes" com "R$ 39,90 no total" logo abaixo faz o cartao
    parecer quebrado."""
    assert "pl.months > 1 &&" in _front("pages/Planos.tsx")


def test_selos_do_checkout_dividem_uma_linha():
    """Eram dois `absolute` opostos, `left-3` e `right-3`. No trimestral, o
    unico plano que carrega os dois, eles se encontravam no meio: numa tela de
    390px saia "Popu" com "Economize 17%" impresso por cima."""
    src = _front("pages/Checkout.tsx")
    assert "-top-2.5 left-3" not in src
    assert "-top-2.5 right-3" not in src
    assert "-top-2.5 inset-x-2 flex items-center justify-between" in src
