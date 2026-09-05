"""Contador omitido numa folha que existe vale zero -- e so' nesse caso."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from collectors.player_stats_collector_service import (
    _valor_do_campo, _ZERO_QUANDO_HA_FOLHA)


def test_contador_omitido_com_folha_vale_zero():
    """A API OMITE em vez de escrever 0: medido em PROD, `shots_on` tem 169
    zeros explicitos contra 8.115 nulls no mesmo recorte. Tratar null como
    ausencia jogava fora toda atuacao em que o jogador nao chutou, e a media
    saia 3,4x inflada (1.285 contra 0.375)."""
    assert _valor_do_campo({"shots": {"on": None}}, "shots_on", ("shots", "on"), True) == 0


def test_numero_de_verdade_passa_intacto():
    assert _valor_do_campo({"shots": {"on": 3}}, "shots_on", ("shots", "on"), True) == 3
    assert _valor_do_campo({"shots": {"on": 0}}, "shots_on", ("shots", "on"), True) == 0


def test_sem_folha_continua_ausencia():
    """A guarda e' `minutes`: jogador que nao entrou nao tem folha, e ali zero
    seria invencao -- que e' exatamente o que a regra da casa proibe."""
    assert _valor_do_campo({"shots": {"on": None}}, "shots_on", ("shots", "on"), False) is None


def test_coluna_fora_da_lista_nao_e_tocada():
    """`goals_total` fica de fora: o placar oficial vem de match_statistics,
    com 100% de cobertura, e reescrever aqui criaria uma segunda fonte."""
    assert "goals_total" not in _ZERO_QUANDO_HA_FOLHA
    assert _valor_do_campo({"goals": {"total": None}}, "goals_total",
                           ("goals", "total"), True) is None


def test_a_lista_cobre_os_contadores_que_o_motor_le():
    """Player Stats decide por saves, shots_on, shots, fouls, tackles e passes.
    Se um deles sair da lista, volta o vies que esta correcao fechou."""
    for coluna in ("saves", "shots_on", "shots_total", "fouls_committed",
                   "tackles_total"):
        assert coluna in _ZERO_QUANDO_HA_FOLHA, coluna


# --- A guarda passou a ser "esteve em campo", nao "tem campo minutes" -------

def test_reserva_que_nao_entrou_nao_vira_atuacao_de_zero():
    """minutes = 0 e' o relacionado que ficou no banco: nao e' folha."""
    from collectors.player_stats_collector_service import _tem_folha
    assert _tem_folha({"games": {"minutes": 0}}) is False
    assert _tem_folha({"games": {"minutes": None}}) is False


def test_reserva_que_entrou_conta():
    from collectors.player_stats_collector_service import _tem_folha
    assert _tem_folha({"games": {"minutes": 7}}) is True
    assert _tem_folha({"games": {"minutes": 90}}) is True
