"""A tela de sucesso confirma a COMPRA, não o estado em que a conta já estava.

O caso que quebrou com dois planos: quem assina o Pick IA e compra o Pro já é
`plan = 'vip'` na primeira volta do laço de confirmação. A tela dizia "plano
ativado" antes de o webhook rodar e mandava pra /picks com o Ao Vivo ainda
trancado. O mesmo vale pra renovação, que também já entra como `vip`.

Não há runner de teste no frontend (typecheck e build são a checagem), então
estes testes leem a fonte. O comportamento em si foi verificado no navegador,
com a volta do MercadoPago simulada nos dois estados.
"""
from pathlib import Path

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _checkout() -> str:
    return (_FRONT / "pages" / "Checkout.tsx").read_text(encoding="utf-8")


def test_a_confirmacao_nao_olha_so_o_plano():
    """`plan === 'vip'` sozinho é verdadeiro ANTES da compra pra quem já
    assinava, que é justamente quem faz upgrade e quem renova."""
    src = _checkout()
    assert "compraJaValendo(" in src
    assert "const virouVip" not in src, "a regra antiga voltou"


def test_o_tier_comprado_precisa_estar_valendo():
    src = _checkout()
    trecho = src[src.index("function compraJaValendo"):]
    trecho = trecho[:trecho.index("\n}")]
    assert "compra.tier === 'pro'" in trecho
    assert "conta.plan_tier" in trecho


def test_a_validade_precisa_ter_andado():
    """É o que separa "já era assinante" de "acabou de pagar"."""
    src = _checkout()
    trecho = src[src.index("function compraJaValendo"):]
    trecho = trecho[:trecho.index("\n}")]
    assert "compra.expiraAntes" in trecho


def test_sem_a_memoria_da_compra_a_tela_nao_trava():
    """Aba anônima ou storage bloqueado não pode deixar quem pagou preso numa
    tela que nunca confirma: sem a memória, cai na regra antiga."""
    src = _checkout()
    trecho = src[src.index("function compraJaValendo"):]
    trecho = trecho[:trecho.index("\n}")]
    assert "if (!compra) return true" in trecho


def test_a_compra_e_guardada_antes_de_sair_pro_mercadopago():
    src = _checkout()
    trecho = src[src.index("const handleCheckout"):]
    trecho = trecho[:trecho.index("window.location.href")]
    assert "sessionStorage.setItem(CHAVE_COMPRA" in trecho
    assert "tier: selected.tier" in trecho
    assert "expiraAntes: user?.expires_at" in trecho


def test_o_storage_bloqueado_nao_derruba_o_checkout():
    """`sessionStorage` lança em aba anônima com site data bloqueado, e isso
    não pode impedir a ida pro MercadoPago."""
    src = _checkout()
    trecho = src[src.index("sessionStorage.setItem(CHAVE_COMPRA"):]
    assert "} catch {" in trecho[:400]


def test_a_tela_de_pendente_usa_a_mesma_regra():
    """Pix e boleto voltam por ali, e a regra não pode divergir."""
    src = _checkout()
    trecho = src[src.index("function PendingPage"):]
    trecho = trecho[:trecho.index("function ")] if "function " in trecho[20:] else trecho
    assert "compraJaValendo(" in src[src.index("function PendingPage"):src.index("function PendingPage") + 2000]
