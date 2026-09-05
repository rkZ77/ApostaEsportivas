# -*- coding: utf-8 -*-
"""A casa parou de cotar, ou o problema e' nosso?

O DIA QUE ORIGINOU ISTO (05/09/2026)
------------------------------------
Os quatro motores de pre-jogo passaram o dia sem gerar UM pick, e a causa nao
estava em nenhum deles: Betano e Superbet pararam de ser servidas pela API,
sobrou a Bet365 sozinha, e o piso de consenso do motor
(`pick_engine/config.min_bookmakers_count = 2`) reprovou TODA linha.

`resumo_das_casas()` passou a avisar quando isso acontece, mas ele so' fala
depois de uma coleta inteira e so' sabe dizer "esta casa nao veio nos jogos que
eu pedi". Duas perguntas continuavam sem resposta, e sao elas que separam um
diagnostico do outro:

    a casa sumiu pra TODO MUNDO, ou so' pros jogos que eu pedi?
    ela sumiu HOJE, ou faz dias?

`/odds` por LIGA e TEMPORADA responde as duas, porque a resposta traz a janela
de datas que aquela casa cobre. Medido no dia, liga 39 temporada 2026:

    Bet365    10 jogos, 3 paginas, 29/08 ate 06/09   viva
    1xBet     10 jogos, 3 paginas, 29/08 ate 06/09   viva
    Betano     9 jogos, 1 pagina,  29/08 ate 31/08   parada ha 5 dias
    Superbet   9 jogos, 1 pagina,  29/08 ate 31/08   parada ha 5 dias

Duas casas com a data congelada no MESMO dia nao e' cobertura de jogo: e' o
provedor. Nenhuma mudanca nossa produz um corte por casa E por data.
"""
import pytest

from scripts import checar_casas_na_api as checar


class _Resposta:
    def __init__(self, corpo):
        self._corpo = corpo

    def raise_for_status(self):
        return None

    def json(self):
        return self._corpo


def _jogo(data):
    return {"fixture": {"id": 1, "date": f"{data}T15:00:00+00:00"},
            "bookmakers": [{"id": 32, "name": "Betano", "bets": []}]}


@pytest.fixture
def api(monkeypatch):
    def montar(corpo):
        monkeypatch.setattr(checar.requests, "get",
                            lambda *a, **k: _Resposta(corpo))
    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")
    return montar


def test_janela_da_casa_devolve_a_primeira_e_a_ultima_data(api):
    """O numero que decide. Uma casa viva cobre ate' os jogos de amanha."""
    api({"errors": [], "results": 3, "paging": {"total": 1},
         "response": [_jogo("2026-08-31"), _jogo("2026-08-29"), _jogo("2026-08-30")]})
    j = checar.janela_da_casa("k", 32, 39, 2026)
    assert j["primeira"] == "2026-08-29"
    assert j["ultima"] == "2026-08-31"
    assert j["jogos"] == 3
    assert j["erro"] is None


def test_casa_sem_nenhum_jogo_nao_vira_data_nula_silenciosa(api):
    """Resposta vazia e' um diagnostico, nao um buraco: quem le precisa saber
    que a consulta funcionou e a casa nao tem nada."""
    api({"errors": [], "results": 0, "paging": {"total": 0}, "response": []})
    j = checar.janela_da_casa("k", 32, 39, 2026)
    assert j["jogos"] == 0
    assert j["primeira"] is None and j["ultima"] is None
    assert j["erro"] is None


def test_recusa_com_http_200_nao_e_confundida_com_casa_parada(api):
    """A API-Football recusa com 200 e o motivo dentro de `errors`. Ler isso
    como "a casa parou" mandaria procurar o defeito no lugar errado -- foi
    exatamente o erro que custou o dia 05/09 no motor ao vivo."""
    api({"errors": {"requests": "You have reached the request limit for the day"},
         "results": 0, "response": []})
    j = checar.janela_da_casa("k", 32, 39, 2026)
    assert j["erro"] is not None
    assert "request limit" in j["erro"]


def test_a_lista_de_casas_tem_fallback(monkeypatch):
    """Mesma regra do coletor: tabela ausente nao pode virar "nenhuma casa pra
    checar", que e' o diagnostico oposto do verdadeiro."""
    def _explode():
        raise RuntimeError("sem banco")
    monkeypatch.setattr(checar, "get_connection", _explode)
    casas = checar.casas_ativas()
    assert {c[0] for c in casas} == {8, 11, 32, 34}
