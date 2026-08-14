"""Cartoes nao liquidavam quando a API omitia "Red Cards" (2026-08-14).

Medido em producao: 21,3% das partidas encerradas (40 de 66 so' em agosto)
tinham amarelos preenchidos e vermelhos NULL. Como o total de cartoes e'
`amarelos + 2*vermelhos`, o total inteiro virava None e NENHUM mercado de
cartao daquela partida podia ser liquidado -- travando, entre outras, a
alavancagem id=65 de 13/08 (Mirassol x LDU, 3 amarelos, "Over 2.5" obvio).

A correcao nao adivinha o vermelho. Ela usa o fato de que vermelho nunca e'
negativo, entao o total e' PELO MENOS os amarelos, e liquida so' quando esse
piso ja' decide sozinho.
"""
import pytest
from decimal import Decimal

from services import settlement
from services.ai_result_checker_service import AIResultCheckerService


# ───────────────────── o piso na fonte unica de liquidacao ──────────────────


def test_piso_resolve_over_ja_batido():
    """3 amarelos contra Over 2.5: descobrir depois que houve um vermelho leva
    o total pra 5 e nao muda nada. A conclusao nao depende do que falta."""
    assert settlement.settle_over_under_com_piso(None, 2.5, "over", piso=3) == (
        settlement.GREEN, Decimal("1"))


def test_piso_resolve_under_ja_estourado():
    assert settlement.settle_over_under_com_piso(None, 2.5, "under", piso=3) == (
        settlement.RED, Decimal("-1"))


def test_piso_nao_decide_quando_o_que_falta_ainda_importa():
    """2 amarelos contra Over 2.5: um vermelho levaria a 4 (GREEN) e nenhum
    deixaria em 2 (RED). O piso nao pode afirmar nada."""
    assert settlement.settle_over_under_com_piso(None, 2.5, "over", piso=2) == settlement.UNRESOLVED
    assert settlement.settle_over_under_com_piso(None, 2.5, "under", piso=2) == settlement.UNRESOLVED


def test_piso_exatamente_na_linha_nao_decide():
    """Piso 3 contra linha 3.0: sem vermelho seria PUSH, com vermelho seria
    Over. Continua indeterminado."""
    assert settlement.settle_over_under_com_piso(None, 3.0, "over", piso=3) == settlement.UNRESOLVED


def test_valor_exato_ignora_o_piso():
    """Nenhum caso que ja liquidava passa a liquidar diferente."""
    com_piso = settlement.settle_over_under_com_piso(2, 2.5, "over", piso=99)
    sem_piso = settlement.settle_over_under(2, 2.5, "over")
    assert com_piso == sem_piso == (settlement.RED, Decimal("-1"))


def test_sem_valor_e_sem_piso_segue_indeterminado():
    assert settlement.settle_over_under_com_piso(None, 2.5, "over") == settlement.UNRESOLVED


def test_piso_respeita_linha_fora_da_grade():
    """Invariante 2: linha fora da grade asiatica nunca vira RED."""
    assert settlement.settle_over_under_com_piso(None, "abc", "over", piso=9) == settlement.UNRESOLVED


# ──────────────────── o piso chegando pelo checker ──────────────────────────


def _stats(hy, ay, hr=None, ar=None):
    """Folha crua como get_fixture_result a le, com vermelhos omitidos."""
    return {"home_yellow_cards": hy, "away_yellow_cards": ay,
            "home_red_cards": hr, "away_red_cards": ar,
            "home_goals": 1, "away_goals": 1, "total_goals": 2, "status": "FT"}


class _CursorFake:
    """Devolve uma linha de match_statistics com os nomes de coluna reais."""

    def __init__(self, campos):
        self._campos = campos
        self.description = [(k,) for k in campos]

    def execute(self, *_a, **_k):
        return None

    def fetchone(self):
        return tuple(self._campos.values())


def test_get_fixture_result_expoe_o_piso_quando_falta_vermelho():
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_stats(hy=2, ay=1)))
    assert stats["total_cards"] is None        # o exato segue desconhecido
    assert stats["total_cards_min"] == 3       # o piso e' conhecido


def test_sem_amarelo_nao_ha_nem_piso():
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_stats(hy=None, ay=1)))
    assert stats["total_cards_min"] is None


def test_com_vermelho_conhecido_o_total_exato_manda():
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_stats(hy=2, ay=1, hr=1, ar=0)))
    assert stats["total_cards"] == 5           # 3 amarelos + 2 pelo vermelho
    assert stats["total_cards_min"] == 3


def test_o_caso_real_que_travou_a_alavancagem():
    """Mirassol x LDU, 13/08: 2+1 amarelos, vermelhos NULL, Cartoes Over 2.5."""
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_stats(hy=2, ay=1)))
    resultado, fator = chk.evaluate_pick(
        "Cartões Mais/Menos", "Over 2.5", 1.14, stats, market_type="cards")
    assert resultado == "GREEN"
    assert fator == Decimal("1")


def test_under_de_cartoes_sem_vermelho_so_resolve_quando_ja_estourou():
    chk = AIResultCheckerService()
    estourado = chk.get_fixture_result(1, _CursorFake(_stats(hy=4, ay=3)))
    assert chk.evaluate_pick("Cartões Mais/Menos", "Under 5.5", 1.8, estourado,
                             market_type="cards")[0] == "RED"
    # 3 amarelos contra Under 5.5: um vermelho ainda mudaria o resultado.
    indefinido = chk.get_fixture_result(1, _CursorFake(_stats(hy=2, ay=1)))
    assert chk.evaluate_pick("Cartões Mais/Menos", "Under 5.5", 1.8, indefinido,
                             market_type="cards")[0] is None


def test_o_piso_nao_vaza_para_outras_familias():
    """Escanteio ausente nao tem piso -- ausencia ali continua sendo ausencia
    (invariante 1, e o incidente Fortaleza x Palmeiras que a originou)."""
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(
        {**_stats(hy=2, ay=1), "home_corners": None, "away_corners": None,
         "total_corners": None}))
    assert stats.get("total_corners") is None
    assert chk.evaluate_pick("Escanteios Mais/Menos", "Over 8.5", 1.8, stats,
                             market_type="corners")[0] is None
