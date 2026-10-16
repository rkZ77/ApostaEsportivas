"""Folha cheia na aba Ligas (15/10/2026): finalizacao, passe, xG e o resto nas
medias da temporada e no ranking por time · jogo sem o dado fica fora da
media, e coluna ausente no banco nao derruba a aba."""
from routers import suggestions as s


def _jogo(**kw):
    base = {"home_goals": 1, "away_goals": 1, "total_goals": 2, "total_corners": 9,
            "total_yellow_cards": 4, "total_red_cards": 0, "home_shots_on": 4, "away_shots_on": 3,
            "home_fouls": 10, "away_fouls": 12, "home_goalkeeper_saves": None,
            "away_goalkeeper_saves": None, "home_team_id": 1, "away_team_id": 2}
    return {**base, **kw}


def test_medias_da_folha_so_com_os_dois_lados():
    games = [
        _jogo(home_total_shots=14, away_total_shots=8, home_xg=1.5, away_xg=0.5,
              home_passes_accuracy=86, away_passes_accuracy=78),
        _jogo(home_total_shots=10, away_total_shots=10, home_xg=None, away_xg=0.9),
    ]
    m = s.medias_da_folha(games)
    assert m["chutes"] == {"media": 21.0, "jogos": 2}
    assert m["xg"] == {"media": 2.0, "jogos": 1}            # o 2o jogo nao tem o xG da casa
    assert m["passes_certos"] == {"media": 82.0, "jogos": 1}  # percentual e' media, nao soma
    assert "passes" not in m


class _Cur:
    """Recusa a consulta com a folha cheia, como um banco sem a coluna."""

    def __init__(self, linhas):
        self.linhas, self.sqls, self.connection = linhas, [], self
        self._r = []

    def rollback(self): pass
    def close(self): pass

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        if "shots_insidebox" in sql:
            raise RuntimeError('column "home_shots_insidebox" does not exist')
        self._r = self.linhas

    def fetchall(self):
        return self._r


class _Conn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur
    def rollback(self): pass
    def close(self): pass


def test_tendencias_sem_a_coluna_cai_na_consulta_de_antes(monkeypatch):
    cur = _Cur([_jogo(fixture_id=1, match_date="2026-10-11", referee=None,
                      home_team="A", away_team="B")])
    monkeypatch.setattr(s, "get_connection", lambda: _Conn(cur))
    r = s.get_liga_tendencias(league_id=79, limit=500, current_user={})
    assert len(cur.sqls) == 2 and r["summary"]["total_games"] == 1
    assert r["summary"]["folha"] == {}


def test_ranking_por_time_com_folha_e_reserva(monkeypatch):
    linha = {"team_id": 1, "team_name": "A", "goals": 2, "corners": 5, "yellow_cards": 1,
             "red_cards": 0, "fouls": 10, "shots_on": 4,
             "f_chutes": 12, "f_posse": 61, "f_xg": None}

    class _CurOk(_Cur):
        def execute(self, sql, params=None):
            self.sqls.append(sql)
            self._r = self.linhas
    monkeypatch.setattr(s, "get_connection", lambda: _Conn(_CurOk([linha, {**linha, "f_chutes": 8}])))
    [t] = s.get_liga_ranking(league_id=79, context="home", current_user={})
    assert t["games"] == 2 and t["folha"]["chutes"] == {"media": 10.0, "jogos": 2}
    assert t["folha"]["posse"]["media"] == 61 and "xg" not in t["folha"]

    cur = _Cur([{k: v for k, v in linha.items() if not k.startswith("f_")}])
    monkeypatch.setattr(s, "get_connection", lambda: _Conn(cur))
    [t] = s.get_liga_ranking(league_id=79, context="all", current_user={})
    assert t["folha"] == {} and len(cur.sqls) == 2
