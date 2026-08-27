# -*- coding: utf-8 -*-
"""`"Red Cards": null` numa folha PUBLICADA e' ZERO, nao ausencia.

O DEFEITO
---------
A API-Football publica zero explicito em todo contador da folha de
/fixtures/statistics -- escanteio, falta, impedimento, chute, amarelo. O UNICO
tipo que ela devolve como `null` e' "Red Cards", e ela faz isso no caso normal:
ninguem foi expulso.

Medido em 2026-08-26 sobre 10 partidas FT sorteadas (20 folhas):

    tipo              null   zero explicito   >0
    Corner Kicks         0                1   19
    Offsides             0                4   16
    Yellow Cards         0                1   19
    Red Cards           18                1    1
    (demais)             0                0   20

Os tres leitores de folha do projeto tratavam esse null como "nao publicado".
Consequencia no banco (DEV, agosto/2026): 95 jogos FT, 12 com vermelho -- os 12
em que houve expulsao. ZERO jogos com vermelho igual a zero. O motor derruba do
pool de cartoes todo jogo sem vermelho (stats_model._tem_folha_de_cartao_
completa), entao 87% da amostra de cartoes evaporava, e nenhum mercado de
cartao liquidava ao vivo (_stat_value soma amarelo+vermelho e devolve None se
faltar um).

O QUE ESTE TESTE PROTEGE
------------------------
As duas metades ao mesmo tempo, porque corrigir uma quebrando a outra ja'
aconteceu duas vezes neste codigo:

  * folha PUBLICADA + campo vazio -> ZERO
  * folha AUSENTE (vazia ou so' de nulls) -> None em TUDO

A segunda e' a invariante 1 de services/settlement.py, nascida dos 99 jogos FT
gravados com escanteio, falta e chute todos em 0 quando a API nao respondeu.
"""
import pytest

from utils import stat_sheet


def _folha_completa(red=None):
    """Folha como a API manda num FT normal: tudo preenchido, vermelho vazio."""
    return [
        {"type": "Shots on Goal", "value": 3},
        {"type": "Total Shots", "value": 11},
        {"type": "Fouls", "value": 14},
        {"type": "Corner Kicks", "value": 0},
        {"type": "Offsides", "value": 0},
        {"type": "Ball Possession", "value": "44%"},
        {"type": "Yellow Cards", "value": 1},
        {"type": "Red Cards", "value": red},
        {"type": "Goalkeeper Saves", "value": 3},
    ]


# ── folha publicada: vazio e' zero ───────────────────────────────────────
def test_vermelho_vazio_em_folha_publicada_e_zero():
    assert stat_sheet.ler_valor(_folha_completa(), "Red Cards") == 0


def test_vermelho_explicito_continua_valendo():
    assert stat_sheet.ler_valor(_folha_completa(red=2), "Red Cards") == 2
    assert stat_sheet.ler_valor(_folha_completa(red=0), "Red Cards") == 0


def test_zero_explicito_de_outro_contador_nao_vira_ausencia():
    """Escanteio 0 e impedimento 0 sao numeros reais e tem que sobreviver."""
    folha = _folha_completa()
    assert stat_sheet.ler_valor(folha, "Corner Kicks") == 0
    assert stat_sheet.ler_valor(folha, "Offsides") == 0


def test_tipo_fora_da_folha_continua_desconhecido():
    """Ausencia da CHAVE e' outra coisa: aquele contador nao veio mesmo."""
    assert stat_sheet.ler_valor(_folha_completa(), "Dangerous Attacks") is None


# ── folha ausente: nada vira zero (invariante 1 do settlement) ───────────
def test_folha_vazia_nao_produz_zero():
    assert stat_sheet.ler_valor([], "Red Cards") is None
    assert stat_sheet.ler_valor([], "Corner Kicks") is None
    assert stat_sheet.ler_folha([]) == {}


def test_folha_so_de_nulls_nao_produz_zero():
    """O stub que a API devolve quando nao tem o jogo: nenhum valor preenchido.

    E' o caso que fabricou 99 jogos FT com escanteio, falta e chute em 0 -- 94
    deles com gol.
    """
    stub = [{"type": t, "value": None}
            for t in ("Corner Kicks", "Fouls", "Total Shots", "Red Cards")]
    assert stat_sheet.folha_publicada(stub) is False
    assert stat_sheet.ler_valor(stub, "Corner Kicks") is None
    assert stat_sheet.ler_valor(stub, "Red Cards") is None
    assert stat_sheet.ler_folha(stub) == {}


# ── SO' o vermelho entra na regra ────────────────────────────────────────
@pytest.mark.parametrize("tipo", ["Corner Kicks", "Fouls", "Yellow Cards",
                                  "Shots on Goal", "Ball Possession",
                                  "expected_goals"])
def test_vazio_em_qualquer_outro_tipo_continua_sendo_ausencia(tipo):
    """A regra e' estreita de proposito -- ver _VAZIO_E_ZERO.

    So' o vermelho foi medido usando `null` como zero. Generalizar por
    elegancia trocaria um bug barato (perder um numero) por um caro (fabricar
    zero, que vira pick errado).
    """
    folha = [i for i in _folha_completa() if i["type"] != tipo]
    folha.append({"type": tipo, "value": None})
    assert stat_sheet.ler_valor(folha, tipo) is None
    assert tipo not in stat_sheet.ler_folha(folha)


def test_percentual_preenchido_perde_o_simbolo():
    assert stat_sheet.ler_valor(_folha_completa(), "Ball Possession") == 44.0


# ── soma que respeita ausencia ───────────────────────────────────────────
def test_soma_com_parcela_desconhecida_e_desconhecida():
    assert stat_sheet.somar(2, None) is None
    assert stat_sheet.somar(2, 0) == 2


# ── os tres leitores concordam ───────────────────────────────────────────
def test_coletor_em_lote_grava_zero_no_vermelho():
    """collectors/match_statistics_sync_service.extract_stat."""
    from collectors.match_statistics_sync_service import extract_stat
    assert extract_stat(_folha_completa(), "Red Cards") == 0
    assert extract_stat([], "Red Cards") is None


def test_motor_ao_vivo_le_zero_no_vermelho():
    """services/pick_engine_live/live_feed.ler_estatisticas."""
    from services.pick_engine_live.live_feed import ler_estatisticas, total_da_familia
    bruto = [{"team": {"id": 10}, "statistics": _folha_completa()},
             {"team": {"id": 20}, "statistics": _folha_completa()}]
    casa, fora = ler_estatisticas(bruto, 10, 20)
    assert casa["Red Cards"] == 0 and fora["Red Cards"] == 0
    # amarelo 1 + vermelho 0, dos dois lados, com vermelho valendo 2 pontos
    assert total_da_familia(casa, fora, "cards") == 2


def test_motor_ao_vivo_sem_folha_nao_inventa_zero():
    from services.pick_engine_live.live_feed import ler_estatisticas
    bruto = [{"team": {"id": 10}, "statistics": []},
             {"team": {"id": 20}, "statistics": []}]
    assert ler_estatisticas(bruto, 10, 20) == ({}, {})
