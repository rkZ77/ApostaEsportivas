"""Aba Jogos (06/10/2026): so' liga ativa, forma recente e o Raio-X do jogo.

O banco e' um duble que responde por trecho de SQL · o que se testa aqui e' a
montagem (lado da casa/fora, titular provavel, jogo sem linha em `fixtures`),
nao o Postgres.
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("JWT_SECRET", "teste")

import cache_publico  # noqa: E402
import routers.fixtures as fx  # noqa: E402


@pytest.fixture(autouse=True)
def _cache_limpo():
    # O Raio-X guarda o resultado por 3 min · sem isto um teste leria o
    # resultado montado pelo anterior.
    cache_publico.invalidar()
    yield
    cache_publico.invalidar()


class Cur:
    def __init__(self, respostas):
        self.respostas = respostas   # lista de (trecho do SQL, linhas)
        self.feitas = []
        self._ult = []
        self.connection = type("C", (), {"rollback": lambda s: None})()

    def execute(self, sql, params=None):
        self.feitas.append((sql, params))
        for trecho, linhas in self.respostas:
            if trecho in sql:
                self._ult = linhas(params) if callable(linhas) else linhas
                return
        self._ult = []

    def fetchall(self):
        return list(self._ult)

    def fetchone(self):
        return self._ult[0] if self._ult else None

    def close(self):
        pass


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


def _jogo(fid, data, casa, fora, gc, gf, **extra):
    base = dict(fixture_id=fid, match_date=dt.date.fromisoformat(data), league_id=71,
                home_team_id=casa, away_team_id=fora, home_goals=gc, away_goals=gf,
                home_corners=5, away_corners=4, home_yellow_cards=2, away_yellow_cards=3,
                home_red_cards=0, away_red_cards=0, home_shots_on=6, away_shots_on=2,
                home_fouls=12, away_fouls=14, home_possession=55, away_possession=45)
    base.update(extra)
    return base


# ── lista do dia ────────────────────────────────────────────────────────────
def test_lista_do_dia_so_le_liga_ativa():
    fonte = open(fx.__file__, encoding="utf-8").read()
    i = fonte.index("def get_today_fixtures")
    assert "COALESCE(ativa, TRUE)" in fonte[i:i + 3000]


def test_resultado_e_do_ponto_de_vista_do_time():
    jogo = {"home_team_id": 10, "away_team_id": 20, "home_goals": 2, "away_goals": 1}
    assert fx._resultado_do_time(jogo, 10) == "V"
    assert fx._resultado_do_time(jogo, 20) == "D"
    assert fx._resultado_do_time({**jogo, "away_goals": 2}, 20) == "E"
    assert fx._resultado_do_time({**jogo, "home_goals": None}, 10) is None


def test_forma_recente_em_uma_consulta(monkeypatch):
    cur = Cur([("CROSS JOIN LATERAL", [
        {"team_id": 10, "home_team_id": 10, "away_team_id": 30, "home_goals": 1, "away_goals": 0},
        {"team_id": 10, "home_team_id": 40, "away_team_id": 10, "home_goals": 2, "away_goals": 2},
        {"team_id": 20, "home_team_id": 20, "away_team_id": 50, "home_goals": 0, "away_goals": 3},
    ])])
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(cur))
    formas = fx._formas_recentes({10, 20}, antes_de="2026-10-06")
    assert formas == {10: ["V", "E"], 20: ["D"]}
    assert len(cur.feitas) == 1


def test_forma_que_falha_nao_derruba_a_agenda(monkeypatch):
    class Quebra(Cur):
        def execute(self, *a, **k):
            raise RuntimeError("banco fora")
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(Quebra([])))
    assert fx._formas_recentes({10}, antes_de="2026-10-06") == {}


# ── Raio-X ──────────────────────────────────────────────────────────────────
def _banco_raio_x(fixture_row, lineup=None):
    kickoff = dt.datetime(2026, 10, 6, 21, 30)

    def serie(params):
        assert params[0] == [10, 20], "os dois times numa consulta so'"
        return [{**_jogo(901, "2026-09-30", 10, 77, 2, 0), "team_id": 10},
                {**_jogo(902, "2026-09-24", 66, 10, 1, 1), "team_id": 10},
                {**_jogo(903, "2026-09-29", 20, 88, 0, 1), "team_id": 20}]

    def jogadores(params):
        fixtures, times = params
        assert sorted(times) == [10, 20], "os dois times numa consulta so'"
        if 901 in fixtures:
            return [
                dict(team_id=10, fixture_id=901, match_date=dt.date(2026, 9, 30), player_id=1, player_name="Atacante",
                     position="F", minutes=90, rating=7.4, is_substitute=False, shots_total=4, shots_on=2,
                     goals_total=1, assists=0, fouls_committed=1, fouls_drawn=3, tackles_total=0, saves=None,
                     cards_yellow=0, passes_total=20, dribbles_success=2),
                dict(team_id=10, fixture_id=902, match_date=dt.date(2026, 9, 24), player_id=1, player_name="Atacante",
                     position="F", minutes=80, rating=6.8, is_substitute=False, shots_total=2, shots_on=1,
                     goals_total=0, assists=1, fouls_committed=2, fouls_drawn=1, tackles_total=1, saves=None,
                     cards_yellow=1, passes_total=18, dribbles_success=1),
                dict(team_id=10, fixture_id=901, match_date=dt.date(2026, 9, 30), player_id=2, player_name="Reserva",
                     position="M", minutes=0, rating=None, is_substitute=True, shots_total=None, shots_on=None,
                     goals_total=None, assists=None, fouls_committed=None, fouls_drawn=None, tackles_total=None,
                     saves=None, cards_yellow=None, passes_total=None, dribbles_success=None),
            ]
        return []

    return Cur([
        ("FROM fixtures WHERE fixture_id", [fixture_row] if fixture_row else []),
        ("CROSS JOIN LATERAL", serie),
        (") h2h", [_jogo(800, "2026-05-01", 20, 10, 1, 3)]),
        ("FROM fixture_lineups", [lineup] if lineup else []),
        ("FROM team_lineups", []),
        ("FROM player_match_stats", jogadores),
        ("FROM teams", [{"team_id": 10, "name": "Casa FC"}, {"team_id": 20, "name": "Fora FC"},
                        {"team_id": 77, "name": "Rival A"}, {"team_id": 66, "name": "Rival B"}]),
        ("WHERE referee = %s", [_jogo(700, "2026-09-01", 1, 2, 0, 0)]),
    ]), kickoff


def test_raio_x_monta_series_do_ponto_de_vista_de_cada_time(monkeypatch):
    cur, kickoff = _banco_raio_x(None)
    cur.respostas[0] = ("FROM fixtures WHERE fixture_id", [dict(
        fixture_id=555, league_id=71, season=2026, home_team_id=10, away_team_id=20,
        home_team="Casa FC", away_team="Fora FC", match_datetime=kickoff,
        status="NS", referee="Fulano", round="Rodada 30")])
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(cur))

    r = fx.get_raio_x(555, current_user={}, home=None, away=None, league=None, n=10)

    casa = r["times"]["home"]["jogos"]
    assert [j["fixture_id"] for j in casa] == [901, 902]
    # 902 foi FORA de casa: o "pro" tem que ser o lado away daquele jogo.
    assert casa[1]["em_casa"] is False
    assert (casa[1]["gols_pro"], casa[1]["gols_contra"]) == (1, 1)
    assert casa[1]["adversario"] == "Rival B"
    assert r["arbitro"]["nome"] == "Fulano"
    assert r["arbitro"]["jogos"][0]["amarelos"] == 5
    assert r["h2h"][0]["escanteios"] == 9
    # So' jogos ANTES do apito entram na serie.
    sql_serie = next(p for s, p in cur.feitas if "CROSS JOIN LATERAL" in s)
    assert sql_serie[1] == kickoff and sql_serie[4] == kickoff


def test_jogador_sem_minuto_fica_de_fora_e_titular_vem_da_escalacao(monkeypatch):
    cur, kickoff = _banco_raio_x(None, lineup={"oficial": False, "titulares": [1, 999]})
    cur.respostas[0] = ("FROM fixtures WHERE fixture_id", [dict(
        fixture_id=555, league_id=71, season=2026, home_team_id=10, away_team_id=20,
        home_team="Casa FC", away_team="Fora FC", match_datetime=kickoff,
        status="NS", referee=None, round=None)])
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(cur))

    r = fx.get_raio_x(555, current_user={}, home=None, away=None, league=None, n=10)

    lista = r["jogadores"]["home"]["lista"]
    assert [j["player_id"] for j in lista] == [1]
    atacante = lista[0]
    assert atacante["titular_provavel"] is True
    assert r["jogadores"]["home"]["fonte_titulares"] == "escalacao provavel"
    assert [g["chutes_alvo"] for g in atacante["jogos"]] == [2, 1]
    assert atacante["minutos_total"] == 170
    assert r["arbitro"] is None


def test_jogo_fora_do_banco_usa_os_times_do_parametro(monkeypatch):
    cur, _ = _banco_raio_x(None)
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(cur))

    r = fx.get_raio_x(555, current_user={}, home=10, away=20, league=71, n=10)

    assert r["fixture"]["home_team"] == "Casa FC"
    assert r["fixture"]["league_id"] == 71
    assert len(r["times"]["home"]["jogos"]) == 2


def test_jogo_desconhecido_e_sem_parametro_e_404(monkeypatch):
    cur, _ = _banco_raio_x(None)
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(cur))
    with pytest.raises(fx.HTTPException) as e:
        fx.get_raio_x(555, current_user={}, home=None, away=None, league=None, n=10)
    assert e.value.status_code == 404


# ── lista do dia: a API pelo dia inteiro ────────────────────────────────────
def _item(fid, liga, quando="2026-10-06T20:00:00-03:00"):
    return {"fixture": {"id": fid, "date": quando, "status": {"short": "NS"}},
            "league": {"id": liga, "season": 2026},
            "teams": {"home": {"id": fid * 10, "name": "A"}, "away": {"id": fid * 10 + 1, "name": "B"}},
            "goals": {"home": None, "away": None}}


def _ligas_ativas(monkeypatch):
    cur = Cur([("FROM leagues", [{"league_id": 71, "name": "Brasileirao", "season": 2026}]),
               ("FROM picks_free", [])])
    monkeypatch.setattr(fx, "get_connection", lambda: Conn(cur))
    monkeypatch.setattr(fx, "_formas_recentes", lambda *a, **k: {})


def test_lista_pede_o_dia_inteiro_e_recorta_as_ligas_ativas(monkeypatch):
    _ligas_ativas(monkeypatch)
    pedidos = []
    monkeypatch.setattr(fx, "_fetch_dia_inteiro",
                        lambda d: pedidos.append(d) or [_item(1, 71), _item(2, 999)])
    monkeypatch.setattr(fx, "_fetch_by_utc_date",
                        lambda *a: pytest.fail("nao pode cair no caminho por liga"))

    jogos = fx.get_today_fixtures(current_user={}, date="2026-10-06")

    assert sorted(pedidos) == ["2026-10-06", "2026-10-07"]
    assert [j["fixture_id"] for j in jogos] == [1]   # liga 999 nao e' cadastrada
    assert jogos[0]["league_name"] == "Brasileirao"


def test_lista_cai_no_caminho_por_liga_se_o_dia_falhar(monkeypatch):
    _ligas_ativas(monkeypatch)
    monkeypatch.setattr(fx, "_fetch_dia_inteiro", lambda d: None)
    monkeypatch.setattr(fx, "_fetch_by_utc_date", lambda liga, season, d: [_item(5, liga)])

    jogos = fx.get_today_fixtures(current_user={}, date="2026-10-06")

    assert [j["fixture_id"] for j in jogos] == [5]


def test_cache_em_memoria_tem_teto(monkeypatch):
    monkeypatch.setattr(fx, "_cache", {})
    for i in range(fx._CACHE_MAX + 15):
        fx._guardar(f"k{i}", [])
    assert len(fx._cache) <= fx._CACHE_MAX
    assert f"k{fx._CACHE_MAX + 14}" in fx._cache
