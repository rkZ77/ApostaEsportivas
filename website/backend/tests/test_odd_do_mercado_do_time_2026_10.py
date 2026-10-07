"""A odd de "agora" precisa ser do MESMO mercado do pick (2026-10-07).

Caso real: "Total de Cartões Visitante · Menos de 3.5" publicado a 1.60 aparecia
com "odd agora 3.85" · era a odd de menos de 3.5 cartões no JOGO INTEIRO. A
busca so' recebia a familia (cards) e a linha, e nao sabia de quem era o
mercado.
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ.setdefault("JWT_SECRET", "teste")

from routers.live import _find_prematch_odd  # noqa: E402

LIVRO = [{
    "id": 8, "name": "Bet365",
    "bets": [
        {"name": "Cards Over/Under", "values": [
            {"value": "Under 3.5", "odd": "3.85"}, {"value": "Over 3.5", "odd": "1.25"}]},
        {"name": "Away Team Total Cards", "values": [
            {"value": "Under 3.5", "odd": "1.62"}, {"value": "Over 3.5", "odd": "2.20"}]},
        {"name": "Corners Over Under", "values": [{"value": "Over 9.5", "odd": "1.90"}]},
    ],
}]
CASAS = {8}


def test_mercado_do_visitante_le_o_mercado_do_visitante():
    odd, casa = _find_prematch_odd("cards", "Menos de 3.5", LIVRO, CASAS,
                                   "Total de Cartões Visitante")
    assert odd == 1.62 and casa == "Bet365"


def test_mercado_do_jogo_continua_lendo_o_do_jogo():
    assert _find_prematch_odd("cards", "Menos de 3.5", LIVRO, CASAS, "Total de Cartões")[0] == 3.85
    # Sem nome (chamada antiga) o comportamento e' o de antes.
    assert _find_prematch_odd("cards", "Menos de 3.5", LIVRO, CASAS)[0] == 3.85


def test_sem_mercado_do_time_no_livro_nao_inventa_odd():
    # O livro nao tem escanteios do mandante: nada, e nao a odd do jogo.
    assert _find_prematch_odd("corners", "Mais de 9.5", LIVRO, CASAS,
                              "Escanteios Casa Mais/Menos") == (None, None)


def test_mercado_de_um_tempo_nao_casa_com_o_jogo_inteiro():
    assert _find_prematch_odd("corners", "Mais de 9.5", LIVRO, CASAS,
                              "Total de Escanteios (1º Tempo)") == (None, None)
