"""Exclusividade de jogo do VIP sobre a Dica gratuita.

Regra do usuário (2026-08-05), em escada:
  0. jogo que o VIP não usou, mercado que não saiu no VIP hoje
  1. jogo que o VIP não usou, mercado repetido de outro jogo
  2. jogo do VIP, mercado de outra família
  -- e o pick IDÊNTICO ao do VIP nunca sai, em nenhum degrau.

O que estes testes protegem: que a Free não deixe de publicar num dia em que o
VIP consumiu todos os jogos (foi o que aconteceu em 05/08, com 4 jogos e 4
picks VIP), e que a saída desse aperto não seja republicar o pick VIP.
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


def test_mesma_familia_no_mesmo_jogo_tambem_e_proibida():
    """Over 2.5 e Under 3.5 no mesmo jogo são a mesma aposta com outra roupa:
    trocar a linha não deveria driblar a regra."""
    assert _nivel_repeticao(_pick("goals", "Under 3.5"), JOGO_DO_VIP, _vip_usou("goals"), set()) is None


def test_familia_agrupa_variantes_do_mesmo_dado_bruto():
    """cards e handicap_cards são o mesmo grupo de correlação: se o VIP usou um
    no jogo, o outro não escapa pela troca de estrutura."""
    assert _nivel_repeticao(
        _pick("handicap_cards", "Home -1"), JOGO_DO_VIP, _vip_usou("cards", "Over 4.5"), set()
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
