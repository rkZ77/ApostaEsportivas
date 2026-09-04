"""Dá pra mexer na banca no meio do mês sem reescrever o passado.

O QUE TRAVAVA
-------------
`/setup` SOBRESCREVE `bankroll_start` sem deixar rastro do porquê, e por isso é
travado em uma configuração por mês. A trava é certa: sem registro, trocar o
número no meio do mês distorce o histórico de risco em silêncio.

O efeito colateral é que a operação legítima mais comum do produto ("subi minha
banca de R$500 pra R$1.000 no dia 12") não tinha porta nenhuma, e a única porta
existente estava fechada com a chave certa pelo motivo errado.

E MUDAR A UNIDADE ERA PIOR QUE TRAVADO, ERA ERRADO
--------------------------------------------------
`user_followed_picks` só guardava `stake_units`, então o R$ de toda aposta
passada era recalculado com o `unit_value` de HOJE. Passar de R$10 pra R$20
dobrava, retroativamente, o P&L em reais, a banca atual e o fechamento do mês.
Esse era o "erro de cálculo" que a trava evitava por fora, sem nomear.

Com a unidade gravada na aposta, aposta velha continua valendo o que valia. Aí
a trava perde a razão de existir para esse caso, e ele ganha porta própria.
"""
import inspect
import re

from routers import banca


def _fonte(fn):
    return inspect.getsource(getattr(fn, "__wrapped__", fn))


# ── a unidade congela na aposta ───────────────────────────────────────────
def test_o_pnl_usa_a_unidade_da_aposta():
    fonte = _fonte(banca._compute_follow_pnl)
    assert 'follow.get("unit_value")' in fonte
    # `or unit_value` e' a linha antiga que a migracao nao alcancou: ela mantem
    # o comportamento de antes, que e' o unico que nao inventa numero novo.
    assert "or unit_value" in fonte


def test_seguir_um_pick_grava_a_unidade_do_momento():
    fonte = inspect.getsource(banca)
    insert = fonte[fonte.index("INSERT INTO user_followed_picks"):][:600]
    assert "unit_value" in insert
    assert "SELECT unit_value FROM user_banca" in insert


def test_toda_consulta_que_calcula_pnl_traz_a_unidade():
    """Faltar em UMA delas e' o modo de falhar silencioso: aquela tela volta a
    reescrever o passado, e so' ela."""
    fonte = inspect.getsource(banca)
    selects = re.findall(r"SELECT uf\.[^\"]+?FROM user_followed_picks", fonte, re.S)
    comuns = [s for s in selects if "stake_units" in s and "cashout_amount" in s]
    assert comuns, "nenhuma consulta de P&L encontrada"
    for s in comuns:
        assert "uf.unit_value" in s, s[:120]


# ── as portas novas ───────────────────────────────────────────────────────
def test_deposito_registra_em_vez_de_sobrescrever():
    fonte = _fonte(banca.deposit_banca)
    assert "INSERT INTO banca_deposits" in fonte
    assert "bankroll_before" in fonte and "bankroll_after" in fonte
    # Mesma protecao do saque contra dois pedidos concorrentes.
    assert "pg_advisory_xact_lock" in fonte


def test_deposito_soma_sobre_a_banca_ATUAL():
    """Somar sobre `bankroll_start` ignoraria todo o lucro desde o último
    fechamento · o depósito comeria o resultado do mês."""
    fonte = _fonte(banca.deposit_banca)
    assert "_compute_bankroll_current" in fonte
    assert "bankroll_current + body.amount" in fonte


def test_trocar_unidade_nao_tem_trava_mensal():
    fonte = _fonte(banca.trocar_unidade)
    assert "last_manual_setup_month" not in fonte


def test_trocar_unidade_mantem_o_piso_de_20():
    """Não é burocracia: com menos que isso uma sequência ruim normal quebra a
    banca. É o mesmo limite do /setup."""
    fonte = _fonte(banca.trocar_unidade)
    assert "< 20" in fonte
    assert "_compute_bankroll_current" in fonte, "o piso mede a banca de hoje"


def test_trocar_unidade_nao_mexe_no_bankroll():
    """Ela muda o tamanho da próxima aposta, e nada mais."""
    fonte = _fonte(banca.trocar_unidade)
    update = fonte[fonte.index("UPDATE user_banca"):]
    assert "bankroll_start" not in update


# ── a trava que fica ──────────────────────────────────────────────────────
def test_o_setup_continua_travado_uma_vez_por_mes():
    """Ele é o único que reescreve a banca sem dizer por quê."""
    fonte = _fonte(banca.setup_banca)
    assert "last_manual_setup_month" in fonte


def test_a_mensagem_da_trava_aponta_as_portas_novas():
    """Mandar "espera o fechamento" quando existe uma porta aberta é pior que
    não ter porta: a pessoa acredita."""
    fonte = _fonte(banca.setup_banca)
    msg = fonte[fonte.index("Você já reconfigurou"):fonte.index("Você já reconfigurou") + 500]
    assert "Depositar" in msg and "Sacar" in msg and "unidade" in msg
