"""Campinho do Raio-X (07/10/2026): escalacao oficial/provavel e desfalques."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import escalacao as esc  # noqa: E402


def _bloco(team_id, xi=True):
    return {"team": {"id": team_id}, "formation": "4-3-3", "coach": {"name": "Técnico"},
            "startXI": [{"player": {"id": 1, "name": "Goleiro", "number": 1, "pos": "G", "grid": "1:1"}},
                        {"player": {"id": 9, "name": "Centroavante", "number": 9, "pos": "F", "grid": "4:2"}}] if xi else [],
            "substitutes": [{"player": {"id": 20, "name": "Reserva", "number": 20, "pos": "M", "grid": None}},
                            {"player": {"id": None, "name": "Sem id"}}]}


def test_oficial_le_formacao_posicao_e_grid():
    times = esc.ler_escalacao_oficial([_bloco(10)])
    t = times[10]
    assert t["formacao"] == "4-3-3" and t["tecnico"] == "Técnico"
    assert [j["posicao"] for j in t["titulares"]] == ["G", "A"]   # F do provedor vira A(tacante)
    assert t["titulares"][1]["grid"] == "4:2"
    assert [j["player_id"] for j in t["reservas"]] == [20]        # jogador sem id fica de fora


def test_bloco_sem_titular_nao_e_escalacao():
    assert esc.ler_escalacao_oficial([_bloco(10, xi=False)]) == {}


@pytest.mark.parametrize("tipo, motivo, categoria, texto", [
    ("Missing Fixture", "Knee Injury", "lesao", "Lesão (joelho)"),
    ("Missing Fixture", "Muscle Injury", "lesao", "Lesão muscular"),
    ("Missing Fixture", "Suspended", "suspenso", "Suspenso"),
    ("Missing Fixture", "Yellow Cards", "suspenso", "Suspenso (amarelos)"),
    ("Missing Fixture", "Red Card", "suspenso", "Suspenso (vermelho)"),
    ("Questionable", "Hamstring Injury", "duvida", "Dúvida · Lesão (coxa)"),
    ("Missing Fixture", "Illness", "outro", "Doença"),
    ("Missing Fixture", "Coach's decision", "outro", "Coach's decision"),
])
def test_motivo_em_portugues(tipo, motivo, categoria, texto):
    assert esc.motivo_em_portugues(tipo, motivo) == (categoria, texto)


def test_desfalques_por_time_sem_repetir():
    resposta = [
        {"player": {"id": 5, "name": "Zagueiro", "type": "Missing Fixture", "reason": "Knee Injury"}, "team": {"id": 10}},
        {"player": {"id": 5, "name": "Zagueiro", "type": "Missing Fixture", "reason": "Knee Injury"}, "team": {"id": 10}},
        {"player": {"id": 7, "name": "Meia", "type": "Missing Fixture", "reason": "Suspended"}, "team": {"id": 20}},
    ]
    d = esc.ler_desfalques(resposta)
    assert [x["player_id"] for x in d[10]] == [5]
    assert d[20][0]["categoria"] == "suspenso"


def test_provavel_usa_ficha_do_jogador():
    p = esc.montar_provavel([1, 9, 99], "4-4-2",
                            {1: {"nome": "Goleiro", "posicao": "G"}, 9: {"nome": "Nove", "posicao": "F"}})
    assert p["formacao"] == "4-4-2"
    assert [(j["player_id"], j["posicao"]) for j in p["titulares"]] == [(1, "G"), (9, "A"), (99, None)]
    assert all(j["grid"] is None for j in p["titulares"])


class Cur:
    def __init__(self):
        self._r = []
        self.connection = type("C", (), {"rollback": lambda s: None})()

    def execute(self, sql, params=None):
        if "FROM team_lineups" in sql:
            self._r = [{"titulares": [1, 9], "formation": "4-4-2"}]
        elif "FROM player_match_stats" in sql:
            self._r = [{"player_id": 1, "player_name": "Goleiro", "position": "G"},
                       {"player_id": 9, "player_name": "Nove", "position": "F"}]

    def fetchone(self):
        return self._r[0] if self._r else None

    def fetchall(self):
        return self._r


def test_jogo_monta_oficial_de_um_lado_provavel_do_outro_e_marca_desfalque(monkeypatch):
    esc._cache.clear()
    chamadas = []

    def api(caminho, params):
        chamadas.append(caminho)
        if caminho == "fixtures/lineups":
            return [_bloco(10)]          # so' o mandante publicou
        return [{"player": {"id": 9, "name": "Nove", "type": "Missing Fixture", "reason": "Knee Injury"},
                 "team": {"id": 20}}]
    monkeypatch.setattr(esc, "_api", api)

    r = esc.escalacao_do_jogo(Cur(), 555, 10, 20)
    assert r["times"]["home"]["status"] == "oficial"
    assert r["times"]["away"]["status"] == "provavel"
    nove = next(j for j in r["times"]["away"]["titulares"] if j["player_id"] == 9)
    assert nove["desfalque"] is True, "titular provavel no boletim medico e' marcado"
    assert r["desfalques"]["away"][0]["motivo"] == "Lesão (joelho)"

    # Oficial incompleta nao fica pra sempre: volta a perguntar depois do TTL,
    # mas dentro dele usa o cache.
    esc.escalacao_do_jogo(Cur(), 555, 10, 20)
    assert chamadas.count("fixtures/lineups") == 1


def test_oficial_completa_nunca_mais_e_pedida(monkeypatch):
    esc._cache.clear()
    chamadas = []
    monkeypatch.setattr(esc, "_api", lambda c, p: chamadas.append(c) or ([_bloco(10), _bloco(20)] if c == "fixtures/lineups" else []))
    esc.escalacao_do_jogo(Cur(), 556, 10, 20)
    monkeypatch.setattr(esc, "TTL_SEM_OFICIAL", 0)
    monkeypatch.setattr(esc, "TTL_DESFALQUES", 0)
    esc.escalacao_do_jogo(Cur(), 556, 10, 20)
    assert chamadas.count("fixtures/lineups") == 1


# ── classificacao ──────────────────────────────────────────────────────────
def test_classificacao_le_a_temporada_mais_recente_da_liga_do_jogo(monkeypatch):
    import cache_publico
    import routers.fixtures as fx
    cache_publico.invalidar()
    feitas = []

    class C:
        def __init__(self):
            self._r = []

        def execute(self, sql, params=None):
            feitas.append((sql, params))
            if "FROM fixtures" in sql:
                self._r = [{"league_id": 71}]
            elif "FROM league_standings" in sql:
                self._r = [{"group_name": None, "team_id": 127, "team_name": "Flamengo", "rank": 1, "points": 60}]

        def fetchone(self):
            return self._r[0] if self._r else None

        def fetchall(self):
            return self._r

        def close(self):
            pass

    cur = C()
    monkeypatch.setattr(fx, "get_connection", lambda: type("K", (), {"cursor": lambda s: cur, "close": lambda s: None})())
    r = fx.get_classificacao(555, current_user={}, league=None)
    assert r["league_id"] == 71 and r["linhas"][0]["team_name"] == "Flamengo"
    sql, params = next(f for f in feitas if "league_standings" in f[0])
    assert "MAX(season)" in sql and params == (71, 71)
    cache_publico.invalidar()
