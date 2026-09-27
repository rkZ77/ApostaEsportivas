# -*- coding: utf-8 -*-
"""Calendario, eventos por minuto e clima (2026-09-27).

Coletas de contexto: entram no dossie da IA e na medicao, nao na conta do
motor (ate' serem medidas). Nada toca banco nem rede.
"""
from datetime import datetime

from collectors import calendario_service, clima_service, eventos_collector_service


def test_temporada_inteira_vira_linha_com_horario_de_brasilia():
    resposta = [{
        "fixture": {"id": 10, "date": "2026-10-01T22:00:00+00:00", "status": {"short": "NS"},
                    "venue": {"city": "Curitiba"}},
        "league": {"round": "Regular Season - 29", "country": "Brazil"},
        "teams": {"home": {"id": 1}, "away": {"id": 2}},
    }]
    (linha,) = calendario_service.linhas_da_temporada(resposta, 71, 2026)
    assert linha[0] == 10 and linha[1] == 71
    assert linha[4] == datetime(2026, 10, 1, 19, 0)      # 22h UTC = 19h em Brasilia
    assert linha[7] == "NS" and linha[8] == "Curitiba" and linha[9] == "Brazil"


class _Cursor:
    def __init__(self, linhas):
        self.linhas = linhas

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.linhas


def test_carga_do_time_descanso_proximo_e_desgaste():
    quando = datetime(2026, 10, 1, 19, 0)
    jogos = [(datetime(2026, 9, 20, 16, 0), 71), (datetime(2026, 9, 27, 16, 0), 13),
             (quando, 71), (datetime(2026, 10, 4, 16, 0), 13)]
    carga = calendario_service.carga_do_time(_Cursor(jogos), 1, quando)
    assert carga["jogos_ultimos_14_dias"] == 2
    assert carga["dias_desde_o_ultimo"] == 4.1
    assert carga["dias_ate_o_proximo"] == 2.9
    assert carga["proximo_liga_id"] == 13                 # o proximo e' de copa


def test_eventos_viram_linhas_com_minuto_e_acrescimo():
    resposta = [{"time": {"elapsed": 90, "extra": 3}, "team": {"id": 1}, "player": {"id": 9},
                 "type": "Goal", "detail": "Normal Goal"},
                {"time": {"elapsed": 30, "extra": None}, "team": {"id": 2}, "player": {"id": 7},
                 "type": "Card", "detail": "Red Card"}]
    linhas = eventos_collector_service.linhas_de_eventos(55, resposta)
    assert linhas[0] == (55, 0, 90, 3, 1, 9, "Goal", "Normal Goal")
    assert linhas[1][6:] == ("Card", "Red Card")


def test_pais_da_liga_desambigua_a_cidade():
    assert clima_service.PAIS_ISO["Brazil"] == "BR"
    assert clima_service._chave("Santos", "BR") != clima_service._chave("Santos", None)
