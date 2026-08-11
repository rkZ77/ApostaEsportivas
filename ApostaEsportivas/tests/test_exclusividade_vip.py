"""Exclusividade de jogo do VIP sobre a Dica gratuita.

Regra do usuário (2026-08-05, corrigida 2026-08-11), em escada:
  0. jogo que o VIP não usou, mercado que não saiu no VIP hoje
  1. jogo que o VIP não usou, mercado repetido de outro jogo
  2. jogo do VIP, pick diferente (outro mercado OU outra linha)
  -- o pick IDÊNTICO ao do VIP (mesmo market_type + mesma linha, no mesmo
     jogo) nunca sai, em nenhum degrau.

Correção 2026-08-11: a versão anterior bloqueava toda a família de correlação
no jogo do VIP (ex: goals/Under 3.5 num jogo onde VIP usou goals/Over 2.5).
Isso era uma sobre-restrição: "Over 2.5" e "Under 3.5" são apostas distintas
em mercados distintos. O único bloqueio correto é o pick idêntico.

O que estes testes protegem: que a Free não deixe de publicar num dia em que o
VIP consumiu todos os jogos (foi o que aconteceu em 05/08 e em 11/08), e que
a saída desse aperto não seja republicar o pick VIP.
"""
import pytest

from engine_pipelines.dica_pipeline import (
    NIVEL_JOGO_DO_VIP_MERCADO_NOVO,
    NIVEL_JOGO_LIVRE_MERCADO_NOVO,
    NIVEL_JOGO_LIVRE_MERCADO_USADO,
    _nivel_repeticao,
)

JOGO_DO_VIP, JOGO_LIVRE = 111, 222


def _pick(market_type="goals", value_label="Over 2.5"):
    return {"market_type": market_type, "value_label": value_label}


def _vip_usou(market_type="goals", value_label="Over 2.5"):
    from services.pick_engine import ranking
    return {
        JOGO_DO_VIP: {
            "grupos": {ranking.correlation_group(market_type)},
            "picks": {(market_type, value_label.lower())},
        }
    }


def test_jogo_livre_com_mercado_novo_e_o_melhor_degrau():
    nivel = _nivel_repeticao(_pick("corners", "Over 9.5"), JOGO_LIVRE, _vip_usou(), set())

    assert nivel == NIVEL_JOGO_LIVRE_MERCADO_NOVO


def test_jogo_livre_com_mercado_ja_usado_perde_pro_mercado_novo():
    """Mesmo mercado que o VIP usou em OUTRO jogo ainda é aceitável · só entra
    depois de esgotado o mercado inédito."""
    nivel = _nivel_repeticao(_pick("goals", "Under 3.5"), JOGO_LIVRE, _vip_usou(), {"goals"})

    assert nivel == NIVEL_JOGO_LIVRE_MERCADO_USADO
    assert NIVEL_JOGO_LIVRE_MERCADO_NOVO < NIVEL_JOGO_LIVRE_MERCADO_USADO


def test_jogo_do_vip_com_outro_mercado_e_o_ultimo_degrau_permitido():
    """O caso do dia curto: sem jogo livre, reaproveita o jogo mudando de
    família de mercado."""
    nivel = _nivel_repeticao(_pick("corners", "Over 9.5"), JOGO_DO_VIP, _vip_usou("goals"), set())

    assert nivel == NIVEL_JOGO_DO_VIP_MERCADO_NOVO
    assert NIVEL_JOGO_LIVRE_MERCADO_USADO < NIVEL_JOGO_DO_VIP_MERCADO_NOVO


def test_pick_identico_ao_do_vip_e_proibido():
    """"Só não repete o mesmo pick" · não é último recurso, é veto."""
    assert _nivel_repeticao(_pick("goals", "Over 2.5"), JOGO_DO_VIP, _vip_usou(), set()) is None


def test_mesma_familia_linha_diferente_no_mesmo_jogo_e_permitida():
    """Over 2.5 e Under 3.5 são apostas distintas: trocar a linha não é
    o mesmo pick, então é permitido como último recurso (nível 2).

    Corrigido em 2026-08-11: o veto de família inteira bloqueava a Dica mesmo
    quando havia uma opção legítima diferente do VIP no mesmo jogo."""
    nivel = _nivel_repeticao(_pick("goals", "Under 3.5"), JOGO_DO_VIP, _vip_usou("goals"), set())
    assert nivel == NIVEL_JOGO_DO_VIP_MERCADO_NOVO


def test_familia_agrupa_variantes_do_mesmo_dado_bruto_linha_diferente_e_permitida():
    """handicap_cards e cards são o mesmo grupo de correlação, mas picks em
    linhas diferentes não são idênticos — permitido como último recurso."""
    nivel = _nivel_repeticao(
        _pick("handicap_cards", "Home -1"), JOGO_DO_VIP, _vip_usou("cards", "Over 4.5"), set()
    )
    assert nivel == NIVEL_JOGO_DO_VIP_MERCADO_NOVO


def test_pick_identico_cards_e_proibido():
    """O pick idêntico (mesmo market_type + mesma linha) continua vetado."""
    assert _nivel_repeticao(
        _pick("cards", "Over 4.5"), JOGO_DO_VIP, _vip_usou("cards", "Over 4.5"), set()
    ) is None


def test_sem_vip_no_dia_tudo_e_o_melhor_degrau():
    assert _nivel_repeticao(_pick(), JOGO_LIVRE, {}, set()) == NIVEL_JOGO_LIVRE_MERCADO_NOVO


@pytest.mark.parametrize("label_vip,label_free", [
    ("Over 2.5", "over 2.5"),
    ("OVER 2.5", "Over 2.5"),
    ("Over 2.5", " Over 2.5 "),
])
def test_comparacao_de_linha_ignora_caixa_e_espaco(label_vip, label_free):
    """A linha vem de fontes diferentes (motor e banco) · comparar cru deixaria
    o pick idêntico passar por diferença de formatação."""
    from services.pick_engine import ranking
    vip = {JOGO_DO_VIP: {"grupos": set(), "picks": {("goals", label_vip.strip().lower())}}}
    assert ranking.correlation_group("goals") not in vip[JOGO_DO_VIP]["grupos"]

    assert _nivel_repeticao(_pick("goals", label_free), JOGO_DO_VIP, vip, set()) is None
