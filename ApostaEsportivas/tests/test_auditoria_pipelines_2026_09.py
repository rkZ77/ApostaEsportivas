"""Auditoria de pipelines (2026-09-12): falha de API nunca vira "nao ha dado".

O fio que liga todos estes testes e' um so': ate esta data, ingestao quebrada e
ausencia legitima de dado eram indistinguiveis do meio da pipeline pra baixo. A
API-Football recusa com HTTP 200 e `errors` preenchido, e o padrao escrito em
nove coletores (`.get("response", [])`) transformava cota estourada em "o dia
tem menos jogos" / "a casa nao cotou este jogo".

Cada teste aqui fixa uma dessas fronteiras.
"""
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    # APPEND, nunca insert(0): o `src/` do motor ja' sombreou o `main.py` do
    # site uma vez. Ver project_sys_path_motor_sombreava.
    sys.path.append(str(_SRC))

from utils import api_client  # noqa: E402
from utils.api_client import (  # noqa: E402
    ApiPaginada,
    ApiQuotaEsgotada,
    ApiRecusou,
    ApiIndisponivel,
    buscar,
)


class _Resposta:
    """Dublê de `requests.Response` com o que o api_client realmente le."""

    def __init__(self, corpo, status=200, headers=None):
        self._corpo = corpo
        self.status_code = status
        self.headers = headers or {}
        self.text = str(corpo)

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._corpo


@pytest.fixture(autouse=True)
def _chave(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """Zera o backoff: o retry e' comportamento testado, a espera nao."""
    monkeypatch.setattr(api_client.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------------
# A RECUSA COM HTTP 200
# ---------------------------------------------------------------------------

def test_cota_estourada_levanta_em_vez_de_devolver_lista_vazia(monkeypatch):
    """O bug central da auditoria, na sua forma mais cara.

    A API devolve 200 com `errors.requests` quando a cota do dia acaba.
    `raise_for_status()` passa limpo, `response` vem `[]`, e o coletor concluia
    "nao ha odd pra este jogo". O pick saia com uma casa a menos na mediana --
    ou o dia saia com menos jogos -- sem nada em lugar nenhum registrando isso.
    """
    corpo = {
        "get": "odds",
        "errors": {"requests": "You have reached the request limit for the day"},
        "response": [],
    }
    monkeypatch.setattr(api_client.requests, "get",
                        lambda *a, **k: _Resposta(corpo))

    with pytest.raises(ApiQuotaEsgotada):
        buscar("odds", {"fixture": 1}, origem="teste")


def test_recusa_que_nao_e_cota_tambem_levanta(monkeypatch):
    """Parametro invalido e plano sem acesso chegam pelo mesmo caminho."""
    corpo = {"errors": {"bookmaker": "The bookmaker field must be an integer."},
             "response": []}
    monkeypatch.setattr(api_client.requests, "get",
                        lambda *a, **k: _Resposta(corpo))

    with pytest.raises(ApiRecusou) as excinfo:
        buscar("odds", {"fixture": 1}, origem="teste")
    # Nao pode ser classificado como cota: a reacao a cota e' parar a rodada.
    assert not isinstance(excinfo.value, ApiQuotaEsgotada)


def test_errors_vazio_e_sucesso(monkeypatch):
    """`errors` vem como LISTA VAZIA no caminho feliz.

    Por isso a checagem e' `if erros:` e nao `is not None` -- com o segundo,
    toda resposta bem sucedida levantaria.
    """
    corpo = {"errors": [], "response": [{"fixture": {"id": 42}}],
             "paging": {"current": 1, "total": 1}}
    monkeypatch.setattr(api_client.requests, "get",
                        lambda *a, **k: _Resposta(corpo))

    assert buscar("fixtures", {"date": "2026-09-12"}, origem="teste") == [
        {"fixture": {"id": 42}}
    ]


def test_lista_vazia_com_sucesso_continua_sendo_lista_vazia(monkeypatch):
    """O outro lado do contrato: ausencia legitima de dado NAO levanta."""
    corpo = {"errors": [], "response": [], "paging": {"current": 1, "total": 1}}
    monkeypatch.setattr(api_client.requests, "get",
                        lambda *a, **k: _Resposta(corpo))

    assert buscar("fixtures", {"date": "2026-09-12"}, origem="teste") == []


# ---------------------------------------------------------------------------
# PAGINACAO
# ---------------------------------------------------------------------------

def test_paginacao_busca_todas_as_paginas(monkeypatch):
    """Ler so' a pagina 1 devolve resposta bem formada e INCOMPLETA."""
    paginas = {
        1: {"errors": [], "response": [{"id": 1}], "paging": {"current": 1, "total": 3}},
        2: {"errors": [], "response": [{"id": 2}], "paging": {"current": 2, "total": 3}},
        3: {"errors": [], "response": [{"id": 3}], "paging": {"current": 3, "total": 3}},
    }

    def _get(url, headers=None, params=None, timeout=None):
        return _Resposta(paginas[params.get("page", 1)])

    monkeypatch.setattr(api_client.requests, "get", _get)

    assert buscar("fixtures", {"date": "x"}, origem="teste") == [
        {"id": 1}, {"id": 2}, {"id": 3}
    ]


def test_paginas_demais_levanta_em_vez_de_varrer_a_cota(monkeypatch):
    """`/odds` sem `fixture` devolve o mundo. Ja aconteceu em 09/09."""
    corpo = {"errors": [], "response": [{"id": 1}],
             "paging": {"current": 1, "total": api_client.MAX_PAGINAS + 1}}
    monkeypatch.setattr(api_client.requests, "get",
                        lambda *a, **k: _Resposta(corpo))

    with pytest.raises(ApiPaginada):
        buscar("odds", {}, origem="teste")


# ---------------------------------------------------------------------------
# RETRY
# ---------------------------------------------------------------------------

def test_http_429_tenta_de_novo_e_pode_ter_sucesso(monkeypatch):
    corpo_ok = {"errors": [], "response": [{"id": 7}],
                "paging": {"current": 1, "total": 1}}
    chamadas = {"n": 0}

    def _get(*a, **k):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return _Resposta({}, status=429)
        return _Resposta(corpo_ok)

    monkeypatch.setattr(api_client.requests, "get", _get)

    assert buscar("fixtures", {"date": "x"}, origem="teste") == [{"id": 7}]
    assert chamadas["n"] == 2


def test_http_400_nao_repete(monkeypatch):
    """Filtro errado nao se conserta repetindo -- so' gasta cota."""
    chamadas = {"n": 0}

    def _get(*a, **k):
        chamadas["n"] += 1
        return _Resposta({}, status=400)

    monkeypatch.setattr(api_client.requests, "get", _get)

    with pytest.raises(ApiIndisponivel):
        buscar("fixtures", {"date": "x"}, origem="teste")
    assert chamadas["n"] == 1


def test_cota_esgotada_nao_repete(monkeypatch):
    """Repetir nao devolve cota. Tem que subir na primeira."""
    corpo = {"errors": {"requests": "limit reached"}, "response": []}
    chamadas = {"n": 0}

    def _get(*a, **k):
        chamadas["n"] += 1
        return _Resposta(corpo)

    monkeypatch.setattr(api_client.requests, "get", _get)

    with pytest.raises(ApiQuotaEsgotada):
        buscar("odds", {"fixture": 1}, origem="teste")
    assert chamadas["n"] == 1


# ---------------------------------------------------------------------------
# COLETA DE FIXTURES: TUDO OU NADA
# ---------------------------------------------------------------------------

def test_uma_data_utc_que_falha_aborta_a_coleta_inteira(monkeypatch):
    """As 4 datas UTC formam UM dia brasileiro.

    Salvar o que veio quando uma delas falha produz um dia incompleto com cara
    de completo, e o motor escolhe o melhor pick de uma amostra que nao e' a do
    dia. Antes de 2026-09-12 a data que falhava virava `[]` e as outras tres
    seguiam normalmente.
    """
    from collectors import fixture_collector_service as fcs

    servico = fcs.FixtureCollectorService()
    chamadas = {"n": 0}

    def _por_data(_self, _data):
        chamadas["n"] += 1
        if chamadas["n"] == 3:
            raise fcs.ApiFootballError("429 na terceira data")
        return []

    monkeypatch.setattr(fcs.FixtureCollectorService, "get_fixtures_by_date",
                        _por_data)

    with pytest.raises(fcs.ApiFootballError):
        servico.collect_fixtures_today_br()


# ---------------------------------------------------------------------------
# JOGO EM ANDAMENTO NAO E' CANDIDATO PRE-JOGO
# ---------------------------------------------------------------------------

def test_get_fixtures_today_nao_aceita_jogo_ao_vivo():
    """Multipla e Bingo leem fixture por este metodo.

    'LIVE' saiu da Dica em 11/08 com um comentario afirmando ter varrido os
    seis geradores; varreu os seis que tinham query PROPRIA, e estes dois
    ficaram de fora por um mes. Uma perna de bilhete podia ser um jogo em
    andamento cotado a um preco que nao existia mais.
    """
    import inspect
    import re
    from services import fixtures_service

    fonte = inspect.getsource(fixtures_service.FixturesService.get_fixtures_today)

    # A linha do filtro, nao o corpo inteiro: o docstring cita 'LIVE' de
    # proposito (explica por que ele saiu) e nao pode derrubar o teste.
    filtros = re.findall(r"f\.status\s+IN\s*\(([^)]*)\)", fonte)
    assert filtros, "o filtro de status sumiu de get_fixtures_today"
    for filtro in filtros:
        assert "LIVE" not in filtro, (
            "get_fixtures_today voltou a aceitar jogo ao vivo: "
            "multipla e bingo passariam a montar bilhete com jogo em andamento"
        )
        assert "NS" in filtro and "TBD" in filtro


# ---------------------------------------------------------------------------
# DATA QUALITY SCORE: PISO DURO E RECENCIA
# ---------------------------------------------------------------------------

def test_dqs_abaixo_do_piso_reprova_todas_as_linhas():
    """Ate 2026-09-12 o DQS nao bloqueava nada.

    O unico efeito era encarecer o min_edge, e a conta tem teto: com DQS=0 o
    limiar subia 40%, entao uma fixture sem cobertura, com integridade
    quebrada e outlier em tudo ainda gerava pick.
    """
    from services.pick_engine import ranking
    from services.pick_engine.config import DEFAULT_CONFIG

    candidato = {
        "odd": 1.90, "edge": 0.50, "ev": 0.40, "taxa_real": 0.62,
        "bookmakers_count": 3, "value": "Over", "line": "2.5",
    }

    avaliadas = ranking.evaluate_all_lines(
        [candidato], DEFAULT_CONFIG, data_quality_score=10.0)

    assert len(avaliadas) == 1
    motivo = avaliadas[0]["reject_reason"]
    assert motivo is not None
    assert "qualidade de dado" in motivo
    # O motivo tem que ser NOMEADO, nao sumir: a distribuicao de reject_reason
    # por dia e' como o motor e' lido.
    assert "DQS" in motivo


def test_dqs_acima_do_piso_nao_reprova_por_qualidade():
    from services.pick_engine import ranking
    from services.pick_engine.config import DEFAULT_CONFIG

    candidato = {
        "odd": 1.90, "edge": 0.50, "ev": 0.40, "taxa_real": 0.62,
        "bookmakers_count": 3, "value": "Over", "line": "2.5",
    }

    avaliadas = ranking.evaluate_all_lines(
        [candidato], DEFAULT_CONFIG, data_quality_score=95.0)

    motivo = avaliadas[0]["reject_reason"]
    assert motivo is None or "qualidade de dado" not in motivo


def test_recencia_penaliza_amostra_velha():
    """Dez jogos de tres meses atras nao valem dez jogos de tres semanas."""
    from services.pick_engine import data_validation as dv

    assert dv.recencia_component(3) == 100.0
    assert dv.recencia_component(14) == 100.0
    assert dv.recencia_component(60) == 0.0
    assert dv.recencia_component(90) == 0.0
    # Decai de forma monotona no meio da faixa.
    assert 0 < dv.recencia_component(40) < dv.recencia_component(20) < 100


def test_recencia_desconhecida_nao_penaliza():
    """Ausencia de medida nao pode virar acusacao."""
    from services.pick_engine import data_validation as dv

    assert dv.recencia_component(None) == 100.0


# ---------------------------------------------------------------------------
# FUSO: match_datetime JA E' BRASILIA
# ---------------------------------------------------------------------------

def test_data_br_de_converte_de_utc_e_nao_de_brasilia():
    """A funcao esta' certa; o docstring dela e' que mentia.

    Ela converte UTC -> BR, e e' isso que `match_statistics.match_date`
    precisa. O erro era o unico chamador passar `fixtures.match_datetime`, que
    ja' e' Brasilia: tirava 3 horas de um horario ja convertido e jogava pro
    dia anterior todo jogo entre 00:00 e 02:59 BRT.
    """
    from datetime import datetime
    from utils.data_br import data_br_de

    # 01:30 UTC de 12/09 e' 22:30 de 11/09 em Brasilia.
    assert data_br_de(datetime(2026, 9, 12, 1, 30)).isoformat() == "2026-09-11"
    assert data_br_de(None) is None


def test_dias_desde_a_ultima_nao_perde_um_dia_no_jogo_de_madrugada():
    """Jogo de 01:00 BRT: `.date()` direto tem que dar o dia do jogo."""
    from datetime import date, datetime

    from engine_pipelines.player_stats_pipeline import _dias_desde_a_ultima

    fixture = {"match_datetime": datetime(2026, 9, 12, 1, 0)}
    atuacoes = [{"match_date": date(2026, 9, 2)}]

    # 10 dias, nao 11: o jogo e' do dia 12 em Brasilia, que e' como o coletor
    # gravou. Passar por `data_br_de` aqui devolvia dia 11 e somava um dia.
    assert _dias_desde_a_ultima(atuacoes, fixture) == 10


# ---------------------------------------------------------------------------
# FREIO DE COTA
# ---------------------------------------------------------------------------

def test_pode_gastar_recusa_quando_a_cota_acabaria():
    from services import api_quota

    with api_quota._lock:
        api_quota._estado.update({
            "dia": __import__("datetime").date.today(),
            "limite": 7500,
            "restante_min": 60,
            "origem": "teste",
        })
    try:
        # 100 requisicoes com 60 de saldo e margem 50: nao cabe.
        assert api_quota.pode_gastar(100) is False
        # 2 requisicoes ainda deixariam 58, abaixo da margem de 50? Nao: cabe.
        assert api_quota.pode_gastar(2) is True
    finally:
        with api_quota._lock:
            api_quota._estado.update({"dia": None, "restante_min": None})


def test_pode_gastar_autoriza_quando_ainda_nao_ha_medida():
    """`None` nao e' zero.

    Recusar por falta de informacao pararia o motor num dia em que nada ha' de
    errado -- e o cabecalho do modulo e' explicito: instrumentacao nao derruba
    o motor.
    """
    from services import api_quota

    with api_quota._lock:
        api_quota._estado.update({"dia": None, "restante_min": None})

    assert api_quota.pode_gastar(500) is True


# ---------------------------------------------------------------------------
# EV E FAIR ODD (o que a auditoria conferiu e passou)
# ---------------------------------------------------------------------------

def test_ev_e_edge_batem_com_a_formula():
    from services.pick_engine.market_model import edge_and_ev, implied_prob

    # EV = p*odd - 1
    r = edge_and_ev(taxa_real=0.55, odd=2.00, prob_baseline=0.50)
    assert r["ev"] == pytest.approx(0.10)
    assert r["edge"] == pytest.approx(0.05)

    # fair_odd = 1/p
    assert implied_prob(2.00) == pytest.approx(0.50)
    assert implied_prob(0) == 0.0


def test_no_vig_soma_um():
    from services.pick_engine.market_model import no_vig_pair_prob

    a, b = no_vig_pair_prob(1.90, 1.90)
    assert a + b == pytest.approx(1.0, abs=1e-3)
