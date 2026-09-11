"""Cartoes nao liquidavam quando a API omitia "Red Cards" (2026-08-14).

Medido em producao: 21,3% das partidas encerradas (40 de 66 so' em agosto)
tinham amarelos preenchidos e vermelhos NULL. Como o total de cartoes e'
`amarelos + 2*vermelhos`, o total inteiro virava None e NENHUM mercado de
cartao daquela partida podia ser liquidado -- travando, entre outras, a
alavancagem id=65 de 13/08 (Mirassol x LDU, 3 amarelos, "Over 2.5" obvio).

A correcao nao adivinha o vermelho. Ela usa o fato de que vermelho nunca e'
negativo, entao o total e' PELO MENOS os amarelos, e liquida so' quando esse
piso ja' decide sozinho.

## O QUE MUDOU EM 2026-09-10

Cartao deixou de ser liquidado pela folha. A folha soma o amarelo do tecnico e
o do reserva que nao entrou junto com os de quem estava em campo, e a casa nao
paga por esse numero -- agora quem conta e' `services/cartoes_validos`, evento
a evento, contra a escalacao.

Isso NAO aposentou o piso: as funcoes de `settlement` continuam iguais e
continuam testadas logo abaixo. O que mudou e' que a partida que o piso
resgatava (vermelho omitido na folha) passa a ter vermelho CONHECIDO pelos
eventos, entao ela liquida pelo total exato em vez do piso. O piso segue de
pe' pra quem o chamar; a familia de cartoes so' deixou de precisar dele.

E a partida que NAO da' pra validar deixou de liquidar de proposito: contar
cartao de banco como cartao de campo nao produz so' um total errado, produz um
GREEN falso.
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


def _validada(y_home, y_away, r_home=0, r_away=0, **extra):
    """A mesma folha, ja' com a contagem elegivel gravada pela validacao."""
    return {**_stats(hy=y_home, ay=y_away, hr=r_home, ar=r_away),
            "valid_yellow_home": y_home, "valid_yellow_away": y_away,
            "valid_red_home": r_home, "valid_red_away": r_away,
            "cards_excluded": 0, "cards_validation": "VALIDADO", **extra}


class _CursorFake:
    """Devolve uma linha de match_statistics com os nomes de coluna reais."""

    def __init__(self, campos):
        self._campos = campos
        self.description = [(k,) for k in campos]

    def execute(self, *_a, **_k):
        return None

    def fetchone(self):
        return tuple(self._campos.values())


def test_folha_sozinha_nao_liquida_mais_cartao():
    """Sem validacao, os contadores de cartao nao viram numero nenhum.

    E' a invariante 1 estendida a elegibilidade: a folha sabe QUANTOS cartoes
    sairam e nao sabe de QUEM, e nao saber de quem e' um tipo de ausencia.
    """
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_stats(hy=2, ay=1)))
    assert stats["total_cards"] is None
    assert stats["total_cards_min"] is None


def test_contagem_validada_liquida_pelo_total_exato():
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_validada(2, 1)))
    assert stats["total_cards"] == 3           # 3 amarelos, 0 vermelho medido
    assert stats["total_yellow"] == 3


def test_sem_amarelo_nao_ha_nem_piso():
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_stats(hy=None, ay=1)))
    assert stats["total_cards_min"] is None


def test_com_vermelho_conhecido_o_total_exato_manda():
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_validada(2, 1, r_home=1)))
    assert stats["total_cards"] == 5           # 3 amarelos + 2 pelo vermelho
    assert stats["total_cards_min"] == 3


def test_o_caso_real_que_travou_a_alavancagem():
    """Mirassol x LDU, 13/08: 3 amarelos em campo, Cartoes Over 2.5.

    Continua GREEN. O que mudou e' o caminho: antes era o piso cobrindo o
    vermelho omitido pela folha, agora e' a contagem elegivel, que SABE o
    vermelho (zero, medido nos eventos) em vez de contorna-lo.
    """
    chk = AIResultCheckerService()
    stats = chk.get_fixture_result(1, _CursorFake(_validada(2, 1)))
    resultado, fator = chk.evaluate_pick(
        "Cartões Mais/Menos", "Over 2.5", 1.14, stats, market_type="cards")
    assert resultado == "GREEN"
    assert fator == Decimal("1")


def test_o_amarelo_do_banco_nao_entra_no_total_liquidado():
    """A folha diz 8, a validacao diz 7, e "Over 7.5" e' RED.

    E' o exemplo do enunciado da regra, do outro lado do sistema: o numero que
    liquida e' o validado, e a diferenca de UM cartao inverte o resultado.
    """
    chk = AIResultCheckerService()
    folha_com_banco = _validada(4, 3, home_yellow_cards=5, cards_excluded=1)
    stats = chk.get_fixture_result(1, _CursorFake(folha_com_banco))
    assert stats["total_cards"] == 7
    assert chk.evaluate_pick("Cartões Mais/Menos", "Over 7.5", 1.9, stats,
                             market_type="cards")[0] == "RED"


def test_under_de_cartoes_liquida_pela_contagem_validada():
    chk = AIResultCheckerService()
    estourado = chk.get_fixture_result(1, _CursorFake(_validada(4, 3)))
    assert chk.evaluate_pick("Cartões Mais/Menos", "Under 5.5", 1.8, estourado,
                             market_type="cards")[0] == "RED"
    ganho = chk.get_fixture_result(1, _CursorFake(_validada(2, 1)))
    assert chk.evaluate_pick("Cartões Mais/Menos", "Under 5.5", 1.8, ganho,
                             market_type="cards")[0] == "GREEN"


def test_validacao_incerta_nao_liquida():
    """INCERTO nao e' "quase validado": e' cartao que nao deu pra classificar.

    Quem resolve o pick preso e' a anulacao por falta de estatistica, nao uma
    suposicao daqui.
    """
    chk = AIResultCheckerService()
    incerta = {**_validada(4, 3), "cards_validation": "INCERTO"}
    stats = chk.get_fixture_result(1, _CursorFake(incerta))
    assert stats["total_cards"] is None
    assert chk.evaluate_pick("Cartões Mais/Menos", "Under 5.5", 1.8, stats,
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
