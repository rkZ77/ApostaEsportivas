"""Fechamento da alavancagem: TODA perna gravada tem que ser conferida.

Antes o checker so' olhava a perna 2 quando `tipo == 'combinacao'` -- valor que
o pipeline nunca grava (ele usa simples/dupla/tripla). Toda 'dupla' caia no
ramo de perna unica: graduada so' pela perna 1, mas paga com odd_combined das
duas. Perna 2 perdendo virava GREEN indevido com profit inflado, sem erro
nenhum no log. Aconteceu com 3 picks reais em producao (ids 21, 25 e 31).
A perna 3 nao era lida por ninguem.
"""
from decimal import Decimal

import pytest

from services import ai_result_checker_alavancagem as mod


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.updates = []

    def execute(self, sql, params=None):
        self._last = sql
        if sql.strip().upper().startswith("SELECT"):
            self._pending = list(self._rows)
        elif "UPDATE" in sql.upper():
            self.updates.append(params)

    def fetchall(self):
        return getattr(self, "_pending", [])

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def _row(tipo, pernas, odd_combined, market_types=None):
    """Monta a tupla no formato exato do SELECT do checker (24 colunas).

    Cada perna carrega 7 campos desde 2026-08-14 -- market_type_N entrou
    porque o checker classificava a perna readivinhando pelo TEXTO do
    mercado, quando o motor ja' gravou o tipo na hora de criar o pick.
    """
    market_types = market_types or {}
    campos = []
    for i in range(3):
        if i < len(pernas):
            fid, mkt, ln, odd = pernas[i]
            campos += [fid, mkt, ln, Decimal(str(odd)),
                       f"Casa{i+1}", f"Fora{i+1}", market_types.get(i + 1)]
        else:
            campos += [None, None, None, None, None, None, None]
    return (1, tipo, *campos, Decimal(str(odd_combined)))


def _run(monkeypatch, row, resultados_por_fixture, capturar=None):
    cur = _FakeCursor([row])
    monkeypatch.setattr(mod, "get_connection", lambda: _FakeConn(cur))
    checker = mod.AIResultCheckerAlavancagem()

    def _fake_check(fid, mkt, ln, odd, c, home=None, away=None, market_type=None):
        if capturar is not None:
            capturar.append({"fixture": fid, "market": mkt, "market_type": market_type})
        return resultados_por_fixture[fid]

    monkeypatch.setattr(checker, "_check_pick", _fake_check)
    # A perna pendente agora consulta get_fixture_result pra distinguir
    # "fixture nao coletada" de "mercado nao liquidavel" no log.
    monkeypatch.setattr(checker._checker, "get_fixture_result",
                        lambda fid, cur=None: None)
    checker.check_all_results()
    return cur.updates


def test_dupla_com_perna_2_red_fecha_red(monkeypatch):
    row = _row("dupla", [(101, "Gols Mais/Menos", "Over 1.5", 1.20),
                         (202, "Cartões Mais/Menos", "Under 5.5", 1.25)], 1.50)

    updates = _run(monkeypatch, row, {101: "GREEN", 202: "RED"})

    assert len(updates) == 1
    resultado, profit, _pk = updates[0]
    assert resultado == "RED"
    assert profit == Decimal("-1")


def test_dupla_com_as_duas_green_fecha_green(monkeypatch):
    row = _row("dupla", [(101, "Gols Mais/Menos", "Over 1.5", 1.20),
                         (202, "Cartões Mais/Menos", "Under 5.5", 1.25)], 1.50)

    updates = _run(monkeypatch, row, {101: "GREEN", 202: "GREEN"})

    resultado, profit, _pk = updates[0]
    assert resultado == "GREEN"
    assert profit == Decimal("1.50") - Decimal("1")


def test_tripla_confere_a_perna_3(monkeypatch):
    row = _row("tripla", [(101, "Gols Mais/Menos", "Over 1.5", 1.15),
                          (202, "Cartões Mais/Menos", "Under 5.5", 1.15),
                          (303, "Escanteios Mais/Menos", "Over 7.5", 1.15)], 1.52)

    updates = _run(monkeypatch, row, {101: "GREEN", 202: "GREEN", 303: "RED"})

    resultado, _profit, _pk = updates[0]
    assert resultado == "RED"


def test_simples_continua_graduada_pela_unica_perna(monkeypatch):
    row = _row("simples", [(101, "Gols Mais/Menos", "Over 1.5", 1.42)], 1.42)

    updates = _run(monkeypatch, row, {101: "GREEN"})

    resultado, profit, _pk = updates[0]
    assert resultado == "GREEN"
    assert profit == Decimal("1.42") - Decimal("1")


def test_perna_sem_stats_deixa_o_pick_pendente(monkeypatch):
    """Sem stats de uma das pernas o pick nao pode fechar: tem que continuar
    NULL e ser reavaliado na proxima rodada."""
    row = _row("dupla", [(101, "Gols Mais/Menos", "Over 1.5", 1.20),
                         (202, "Cartões Mais/Menos", "Under 5.5", 1.25)], 1.50)

    updates = _run(monkeypatch, row, {101: "GREEN", 202: None})

    assert updates == []


def test_market_type_gravado_e_usado_em_vez_de_readivinhado(monkeypatch):
    """O motor grava market_type_N ao criar o pick, e o checker nunca lia.
    Toda perna era reclassificada pelo TEXTO do mercado -- que funciona pros
    nomes conhecidos e falha calado em qualquer outro, deixando o bilhete
    pendente pra sempre."""
    row = _row("dupla",
               [(101, "Gols Mais/Menos", "Over 1.5", 1.20),
                (202, "Cartões Mais/Menos", "Under 5.5", 1.25)],
               1.50, market_types={1: "goals", 2: "cards"})
    vistos = []

    _run(monkeypatch, row, {101: "GREEN", 202: "GREEN"}, capturar=vistos)

    assert [v["market_type"] for v in vistos] == ["goals", "cards"]
