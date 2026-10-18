"""Vinte partidas por requisicao (18/10/2026): utils/lote_de_partidas."""
from utils import lote_de_partidas as lp
from utils.api_client import ApiQuotaEsgotada


def _api(sem_bloco=(), falha_lote=False, cota=False):
    chamadas = []

    def buscar(recurso, params, origem=None):
        chamadas.append(params["ids"])
        if cota:
            raise ApiQuotaEsgotada("fixtures", {"requests": "limite"})
        if falha_lote:
            raise RuntimeError("500")
        ids = [int(x) for x in params["ids"].split("-")]
        return [{"fixture": {"id": f}, **({} if f in sem_bloco else {"events": [{"f": f}]})} for f in ids]
    return buscar, chamadas


def test_vinte_por_requisicao_e_o_que_faltou_vai_avulso(monkeypatch):
    buscar, chamadas = _api(sem_bloco={7})
    monkeypatch.setattr(lp, "buscar", buscar)
    avulsas = []
    saida = list(lp.percorrer(range(1, 26), "events", lambda f: avulsas.append(f) or ["avulsa"], 10, "t"))
    assert [len(c.split("-")) for c in chamadas] == [20, 5]
    assert avulsas == [7]
    assert dict(saida)[7] == ["avulsa"] and dict(saida)[1] == [{"f": 1}]
    assert len(saida) == 25


def test_teto_conta_lote_e_avulsa(monkeypatch):
    buscar, chamadas = _api(sem_bloco={1, 2})
    monkeypatch.setattr(lp, "buscar", buscar)
    saida = list(lp.percorrer(range(1, 41), "events", lambda f: [], 2, "t"))
    # 1 lote + 1 avulsa = teto 2: a partida 2 e o segundo lote ficam pra depois.
    assert len(chamadas) == 1 and [f for f, _ in saida][:1] == [1] and 2 not in dict(saida)


def test_lote_que_falha_vai_uma_por_uma(monkeypatch):
    buscar, _ = _api(falha_lote=True)
    monkeypatch.setattr(lp, "buscar", buscar)
    saida = list(lp.percorrer([1, 2], "events", lambda f: ["av"], 10, "t"))
    assert saida == [(1, ["av"]), (2, ["av"])]


def test_cota_esgotada_encerra(monkeypatch):
    buscar, _ = _api(cota=True)
    monkeypatch.setattr(lp, "buscar", buscar)
    assert list(lp.percorrer([1, 2], "events", lambda f: 1 / 0, 10, "t")) == []


def test_avulsa_que_falha_pula_sem_derrubar(monkeypatch):
    buscar, _ = _api(sem_bloco={1})
    monkeypatch.setattr(lp, "buscar", buscar)
    saida = list(lp.percorrer([1, 2], "events", lambda f: 1 / 0, 10, "t"))
    assert saida == [(2, [{"f": 2}])]
