"""Aba Estatisticas do Raio-X (15/10/2026): folha completa do jogo, ao vivo e
encerrado, sem gastar cota quando o banco ou o cache ja' tem."""
import time

import pytest

import estatisticas_do_jogo as ed
from routers import live


def _time(tid, cheia, h1=None):
    t = {"team": {"id": tid}, "statistics": [{"type": k, "value": v} for k, v in cheia.items()]}
    if h1 is not None:
        t["statistics_1h"] = [{"type": k, "value": v} for k, v in h1.items()]
    return t


FOLHA = [
    _time(20, {"Ball Possession": "42%", "Total Shots": 8, "Corner Kicks": 3, "Offsides": None,
               "expected_goals": "0.71", "Fouls": 11},
          {"Total Shots": 3, "Corner Kicks": 1}),
    _time(10, {"Ball Possession": "58%", "Total Shots": 14, "Corner Kicks": 7, "Offsides": 2,
               "expected_goals": "1.84", "Fouls": 9},
          {"Total Shots": 6, "Corner Kicks": 4}),
]


def test_numero_le_percentual_decimal_e_vazio():
    assert ed.numero("58%") == 58 and ed.numero("1.84") == 1.84
    assert ed.numero(7) == 7 and ed.numero(None) is None and ed.numero("") is None


def test_folha_ao_vivo_pelo_id_do_time_com_os_tres_periodos():
    p = ed.da_folha(FOLHA, home_id=10, away_id=20, status="2H")
    jogo = {l["chave"]: l for l in p["jogo"]}
    # O mandante e' o id 10, mesmo vindo em 2o na resposta.
    assert (jogo["posse"]["casa"], jogo["posse"]["fora"]) == (58, 42) and jogo["posse"]["pct"]
    assert jogo["xg"]["casa"] == 1.84
    assert (jogo["impedimentos"]["casa"], jogo["impedimentos"]["fora"]) == (2, 0)   # null ao vivo e' zero
    assert [l["chave"] for l in p["jogo"]][:2] == ["posse", "xg"]                     # ordem do SofaScore
    segundo = {l["chave"]: l for l in p["2t"]}
    assert (segundo["chutes"]["casa"], segundo["chutes"]["fora"]) == (8, 5)
    assert "posse" not in segundo                                                    # posse nao soma


def test_no_primeiro_tempo_nao_ha_1t_separado_nem_2t():
    p = ed.da_folha(FOLHA, 10, 20, "1H")
    assert set(p) == {"jogo"}
    assert set(ed.da_folha(FOLHA, 10, 20, "HT")) == {"jogo", "1t"}


def test_do_banco_monta_jogo_e_tempos():
    linha = {"home_possession": "55%", "away_possession": "45%", "home_corners": 9, "away_corners": 2,
             "home_corners_1h": 5, "away_corners_1h": 1, "home_xg": None, "away_xg": None}
    p = ed.do_banco(linha)
    assert {l["chave"] for l in p["jogo"]} == {"posse", "escanteios"}                # xG nulo some
    assert p["2t"][0] == {"chave": "escanteios", "rotulo": "Escanteios", "casa": 4, "fora": 1, "pct": False}


class _Cur:
    def __init__(self, linha=None, futuro=False, jogadores=()):
        self.linha, self.futuro, self.jogadores, self._r = linha, futuro, list(jogadores), None
        self.connection = self

    def execute(self, sql, params=None):
        if "FROM player_match_stats" in sql:
            self._r = self.jogadores
        elif "FROM match_statistics" in sql:
            self._r = self.linha
        elif "FROM fixtures" in sql:
            self._r = {"futuro": self.futuro}

    def fetchone(self):
        return self._r

    def fetchall(self):
        return self._r

    def rollback(self): pass
    def close(self): pass


class _Conn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur
    def close(self): pass
    def rollback(self): pass


@pytest.fixture
def api(monkeypatch):
    """Conta as idas a API-Football."""
    chamadas = []
    monkeypatch.setattr(live.requests, "get",
                        lambda *a, **k: chamadas.append(a) or (_ for _ in ()).throw(RuntimeError("sem rede")))
    monkeypatch.setattr(live, "_fix_cache", {})
    monkeypatch.setattr(live, "_stats_cache", {})
    return chamadas


def _banco(monkeypatch, **kw):
    monkeypatch.setattr(live, "get_connection", lambda: _Conn(_Cur(**kw)))


def test_encerrado_no_banco_nao_chama_a_api(api, monkeypatch):
    _banco(monkeypatch, linha={"status": "FT", "home_goals": 2, "away_goals": 0,
                               "home_corners": 6, "away_corners": 3})
    r = live.montar_estatisticas(1)
    assert r["fonte"] == "banco" and r["periodos"]["jogo"][0]["chave"] == "escanteios"
    assert api == []


def test_encerrado_traz_desarme_e_duelo_da_folha_dos_jogadores(api, monkeypatch):
    _banco(monkeypatch,
           linha={"status": "FT", "home_goals": 1, "away_goals": 0, "home_team_id": 10,
                  "away_team_id": 20, "home_corners": 6, "away_corners": 3},
           jogadores=[{"fixture_id": 1, "team_id": 10, "desarmes": 18, "duelos_ganhos": 50},
                      {"fixture_id": 1, "team_id": 20, "desarmes": 12, "duelos_ganhos": 41}])
    jogo = {l["chave"]: l for l in live.montar_estatisticas(1)["periodos"]["jogo"]}
    assert (jogo["desarmes"]["casa"], jogo["desarmes"]["fora"]) == (18, 12)
    assert jogo["duelos_ganhos"]["rotulo"] == "Duelos ganhos" and api == []


def test_media_da_liga_dos_jogadores_so_com_os_dois_times():
    import estatisticas_de_jogadores as ej
    m = ej.medias_da_liga({1: {10: {"desarmes": 18}, 20: {"desarmes": 12}},
                           2: {10: {"desarmes": 20}}})            # so' um time com folha
    assert m == {"desarmes": {"media": 30.0, "jogos": 1}}
    # A consulta so' conta time com 11 jogadores em campo.
    assert "HAVING COUNT(*) >= 11" in ej._sql() and "minutes > 0" in ej._sql()


def test_jogo_que_nao_comecou_nao_chama_a_api(api, monkeypatch):
    _banco(monkeypatch, futuro=True)
    assert live.montar_estatisticas(1) == {"status": "NS", "fonte": "nenhuma", "periodos": {}}
    assert api == []


def test_ao_vivo_com_cache_quente_le_do_cache(api, monkeypatch):
    _banco(monkeypatch)
    agora = time.time()
    live._fix_cache[1] = (agora, {"fixture": {"status": {"short": "2H", "elapsed": 70}},
                                  "teams": {"home": {"id": 10}, "away": {"id": 20}},
                                  "goals": {"home": 1, "away": 0}})
    live._stats_cache[1] = (agora, FOLHA, "2H")
    r = live.montar_estatisticas(1)
    assert r["fonte"] == "ao_vivo" and r["elapsed"] == 70 and "2t" in r["periodos"]
    assert api == []


def test_cota_alta_nao_busca_mesmo_com_cache_velho(api, monkeypatch):
    _banco(monkeypatch)
    velho = time.time() - 600
    live._fix_cache[1] = (velho, {"fixture": {"status": {"short": "2H"}}, "teams": {}, "goals": {}})
    live._stats_cache[1] = (velho, FOLHA, "2H")
    monkeypatch.setattr(live.api_quota, "estado_atual", lambda: {"pct_usado": 95})
    r = live.montar_estatisticas(1)
    assert api == [] and r["periodos"]["jogo"]
