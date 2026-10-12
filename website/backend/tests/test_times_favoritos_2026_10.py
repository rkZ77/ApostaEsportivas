"""Times favoritos (12/10/2026): na conta, com teto, e leitura que nao quebra
a aba Jogos se a tabela ainda nao existir."""
import pytest
from fastapi import HTTPException

from routers import personal


class _Cur:
    def __init__(self, favoritos=None, quebra=False):
        self.favs = list(favoritos or [])
        self.quebra = quebra
        self._r = []

    def execute(self, sql, params=None):
        if self.quebra:
            raise RuntimeError("relation user_times_favoritos does not exist")
        s = " ".join(sql.split())
        if s.startswith("SELECT COUNT(*)"):
            self._r = [{"n": len(self.favs)}]
        elif s.startswith("INSERT"):
            if params[1] not in self.favs:
                self.favs.append(params[1])
        elif s.startswith("DELETE"):
            self.favs = [f for f in self.favs if f != params[1]]
        elif s.startswith("SELECT team_id"):
            self._r = [{"team_id": f} for f in self.favs]

    def fetchone(self):
        return self._r[0] if self._r else None

    def fetchall(self):
        return self._r

    def close(self): pass


class _Conn:
    def __init__(self, cur): self.cur = cur
    def cursor(self): return self.cur
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


def _usar(monkeypatch, cur):
    monkeypatch.setattr(personal, "get_connection", lambda: _Conn(cur))


def test_marca_desmarca_e_devolve_a_lista(monkeypatch):
    cur = _Cur([10])
    _usar(monkeypatch, cur)
    user = {"id": 1}
    assert personal.put_time_favorito(personal.FavoritoBody(team_id=20), user) == {"times": [10, 20]}
    assert personal.put_time_favorito(personal.FavoritoBody(team_id=10, favorito=False), user) == {"times": [20]}
    assert personal.get_times_favoritos(user) == {"times": [20]}


def test_teto_de_favoritos(monkeypatch):
    _usar(monkeypatch, _Cur(list(range(1, personal.MAX_FAVORITOS + 1))))
    with pytest.raises(HTTPException) as e:
        personal.put_time_favorito(personal.FavoritoBody(team_id=999), {"id": 1})
    assert e.value.status_code == 400


def test_sem_tabela_a_leitura_volta_vazia(monkeypatch):
    _usar(monkeypatch, _Cur(quebra=True))
    assert personal.get_times_favoritos({"id": 1}) == {"times": []}
