"""Bilhete apostavel: uma casa so', e perna que nao se repete entre bilhetes.

Os dois defeitos sairam publicados em 10/09 e nenhum levantava excecao:

  1. O bingo do dia pedia Betano, Superbet e Bet365 na MESMA cartela -- nao
     existe bilhete assim em casa nenhuma.
  2. Bingo e multipla podiam publicar a mesma entrada do mesmo jogo. Um RED
     ali derruba os dois bilhetes inteiros de uma vez.
"""
import pytest

from services.pick_engine import bet_house
from services.pick_engine import bilhetes_do_dia


def _perna(odd, casas, taxa_real=0.75):
    return {
        "odd": odd,
        "taxa_real": taxa_real,
        "best_bookmaker": max(casas, key=casas.get) if casas else "",
        "bookmaker_odds": [{"bookmaker": c, "odd": o} for c, o in casas.items()],
    }


# --------------------------------------------------------------- casa unica

def test_escolhe_a_casa_que_cota_o_bilhete_inteiro():
    pernas = [
        _perna(1.43, {"Betano": 1.43, "Bet365": 1.41}),
        _perna(1.46, {"Superbet": 1.46, "Bet365": 1.44}),
        _perna(1.80, {"Bet365": 1.80, "Betano": 1.75}),
    ]
    novas, casa, odd_total = bet_house.aplicar_casa(pernas, 1.40, 2.00)
    assert casa == "Bet365"
    assert [p["best_bookmaker"] for p in novas] == ["Bet365"] * 3
    assert [p["odd"] for p in novas] == [1.41, 1.44, 1.80]
    assert odd_total == pytest.approx(1.41 * 1.44 * 1.80, abs=1e-4)


def test_sem_casa_comum_o_bilhete_nao_sai():
    pernas = [
        _perna(1.43, {"Betano": 1.43}),
        _perna(1.46, {"Superbet": 1.46}),
    ]
    assert bet_house.aplicar_casa(pernas, 1.40, 2.00) is None


def test_casa_comum_fora_da_faixa_nao_vale():
    """A faixa por perna e' filtro duro: a casa unica nao pode fura-la."""
    pernas = [
        _perna(1.45, {"Betano": 1.45, "Bet365": 1.45}),
        # No Bet365 esta perna custa 2.30, acima do teto de 2.00 do bingo.
        _perna(1.90, {"Betano": 1.90, "Bet365": 2.30}),
    ]
    _novas, casa, _odd = bet_house.aplicar_casa(pernas, 1.40, 2.00)
    assert casa == "Betano"


def test_entre_casas_elegiveis_ganha_a_de_maior_odd_combinada():
    pernas = [
        _perna(1.50, {"Betano": 1.50, "Bet365": 1.55}),
        _perna(1.60, {"Betano": 1.62, "Bet365": 1.60}),
    ]
    _novas, casa, odd_total = bet_house.aplicar_casa(pernas, 1.40, 2.00)
    assert casa == "Bet365"
    assert odd_total == pytest.approx(1.55 * 1.60, abs=1e-4)


def test_ev_da_perna_acompanha_a_odd_da_casa():
    pernas = [_perna(1.50, {"Betano": 1.50, "Bet365": 1.60}, taxa_real=0.70)]
    novas, _casa, _odd = bet_house.aplicar_casa(pernas, 1.40, 2.00)
    assert novas[0]["ev"] == pytest.approx(0.70 * 1.60 - 1.0, abs=1e-4)
    assert novas[0]["odd_consenso"] == 1.50


def test_perna_sem_lista_de_casas_nao_trava_o_bilhete():
    """Caminho legado: sem cotacao nenhuma nao ha' como contradizer a casa."""
    pernas = [
        _perna(1.50, {"Betano": 1.50, "Bet365": 1.55}),
        {"odd": 1.60, "taxa_real": 0.70},
    ]
    novas, casa, odd_total = bet_house.aplicar_casa(pernas, 1.40, 2.00)
    assert casa == "Bet365"
    assert novas[1]["odd"] == 1.60
    assert odd_total == pytest.approx(1.55 * 1.60, abs=1e-4)


# -------------------------------------------------- perna exclusiva por dia

class _CursorFake:
    def __init__(self, por_tabela):
        self._por_tabela = por_tabela
        self._atual = []

    def execute(self, sql, params=None):
        self._atual = next(
            (linhas for tabela, linhas in self._por_tabela.items() if tabela in sql),
            [])

    def fetchall(self):
        return self._atual


def test_pernas_da_multipla_bloqueiam_o_bingo():
    cur = _CursorFake({
        "picks_multiplas": [([{"fixture_id": 10, "market_type": "goals"},
                              {"fixture_id": 11, "market_type": "corners"}],)],
        "picks_bingo": [],
        "picks_alavancagem": [],
    })
    pares = bilhetes_do_dia.pares_em_bilhetes(cur, "CURRENT_DATE",
                                              exceto=("picks_bingo",))
    assert (10, "goals") in pares
    assert (11, "corners") in pares


def test_alavancagem_entra_pelas_colunas_de_perna():
    cur = _CursorFake({
        "picks_multiplas": [],
        "picks_bingo": [],
        "picks_alavancagem": [(20, "goals", 21, "cards", None, None)],
    })
    pares = bilhetes_do_dia.pares_em_bilhetes(cur, "CURRENT_DATE")
    assert pares == {(20, "goals"), (21, "cards")}


def test_a_propria_tabela_fica_de_fora():
    cur = _CursorFake({
        "picks_multiplas": [([{"fixture_id": 10, "market_type": "goals"}],)],
        "picks_bingo": [],
        "picks_alavancagem": [],
    })
    assert bilhetes_do_dia.pares_em_bilhetes(
        cur, "CURRENT_DATE", exceto=("picks_multiplas",)) == set()
