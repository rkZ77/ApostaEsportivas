"""Raio-X: jogo de quem entrou do banco conta na serie do jogador (11/10/2026).

A API escreve null quando o lance nao aconteceu, e gol/passe chegam null do
coletor. O "bateu X de N" tratava null como "sem dado" e tirava o jogo da
conta: so' entravam os jogos em que o jogador marcou. Nenhum teste toca banco.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

from routers import fixtures  # noqa: E402

TIME = 10


def _linha(fixture_id, minutos, reserva, gols):
    linha = {"team_id": TIME, "fixture_id": fixture_id, "match_date": date(2026, 10, fixture_id),
             "player_id": 7, "player_name": "Atacante", "position": "F",
             "minutes": minutos, "rating": None, "is_substitute": reserva}
    linha.update({col: None for col in fixtures._CAMPOS_JOGADOR.values()})
    linha["goals_total"] = gols
    return linha


class _Cur:
    def __init__(self, linhas):
        self.linhas = linhas

    def execute(self, sql, args=None):
        pass

    def fetchall(self):
        return self.linhas


def test_reserva_sem_gol_entra_na_serie_com_zero():
    linhas = [_linha(1, 90, False, 1), _linha(2, 20, True, None), _linha(3, 15, True, None)]
    saida = fixtures._jogadores_dos_times(_Cur(linhas), {TIME: [1, 2, 3]}, {})
    jogos = saida[TIME][0]["jogos"]
    assert [g["gols"] for g in jogos] == [1, 0, 0]
    assert [g["titular"] for g in jogos] == [True, False, False]
    assert all(g["passes"] == 0 for g in jogos)
