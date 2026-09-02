"""O fechamento mensal e as chaves da alavancagem (02/09/2026).

Bug visto no log de PRODUCAO, repetindo a cada abertura do sino:

    [NOTIF] Falha no sync do fechamento mensal (user 2): 'greens_this_month'

`_get_alavancagem_month_stats` passou a contar CAMINHOS quando a alavancagem
deixou de ser pick avulso e virou "caminho" (ver project_alavancagem_caminhos),
mas `sync_monthly_close_notification` continuou pedindo as chaves antigas,
`greens_this_month` e `reds_this_month`. O KeyError caía no try/except de
`notifications.py` e virava um WARNING.

O efeito nao era um erro na tela: era o fechamento mensal NUNCA ser criado pra
quem tem alavancagem configurada. Falha silenciosa, que e o pior tipo -- o
usuario nao ve nada de errado, so' nao recebe uma coisa que deveria receber.

Estes testes travam o CONTRATO entre as duas funcoes, que e o que faltava: a
que produz o dicionario e a que o consome vivem no mesmo arquivo e mesmo assim
divergiram.
"""

import io
import os
import re


def _fonte_banca() -> str:
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with io.open(os.path.join(raiz, "routers", "banca.py"), encoding="utf-8") as f:
        return f.read()


def _chaves_devolvidas(fonte: str) -> set:
    """As chaves do dict que `_get_alavancagem_month_stats` retorna."""
    corpo = fonte.split("def _get_alavancagem_month_stats")[1]
    corpo = corpo[corpo.index("    return {"):]
    corpo = corpo[:corpo.index("\n    }")]
    return set(re.findall(r'"([a-z_]+)":', corpo))


def test_o_consumidor_usa_chaves_que_existem():
    """A garantia que faltava. Sem ela, renomear uma chave aqui volta a
    desligar o fechamento mensal sem ninguem perceber."""
    fonte = _fonte_banca()
    devolvidas = _chaves_devolvidas(fonte)

    trecho = fonte.split("def sync_monthly_close_notification")[1]
    trecho = trecho[:trecho.index("\ndef ")] if "\ndef " in trecho else trecho
    usadas = set(re.findall(r'alav\["([a-z_]+)"\]', trecho))

    assert usadas, "o fechamento parou de olhar a alavancagem"
    faltando = usadas - devolvidas
    assert not faltando, f"chaves que nao existem mais: {sorted(faltando)}"


def test_as_chaves_mortas_nao_voltam():
    """`greens_this_month` e `reds_this_month` eram de PICK. A alavancagem
    conta caminho: um caminho de seis greens e' UM caminho, nao seis."""
    # So' o CODIGO conta: o comentario que explica a correcao cita os dois
    # nomes de proposito, e apagar essa memoria seria pior que o teste.
    codigo = "\n".join(
        l for l in _fonte_banca().splitlines() if not l.lstrip().startswith("#")
    )
    assert "greens_this_month" not in codigo
    assert "reds_this_month" not in codigo


def test_o_criterio_de_atividade_e_o_mesmo_do_front():
    """A tela e o sino tem que concordar sobre "houve alavancagem neste mes".
    Se divergirem, o modal abre dizendo uma coisa e a notificacao outra."""
    fonte = _fonte_banca()
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    caminho = os.path.join(raiz, "frontend", "src", "components", "MonthlyCloseModal.tsx")
    with io.open(caminho, encoding="utf-8") as f:
        front = f.read()

    assert 'alav["closed_this_month"] > 0 or alav["busted_this_month"]' in fonte
    assert "closed_this_month > 0 || data.alavancagem.busted_this_month" in front
