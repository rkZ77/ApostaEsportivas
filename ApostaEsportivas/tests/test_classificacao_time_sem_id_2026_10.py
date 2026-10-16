"""Time sem id na classificacao (2026-10-16).

A API devolveu a tabela da Liga MX (262) com o Club Leon sem `team.id` e sem
logo. O insert e' em lote por liga, entao o NOT NULL de team_id derrubava a
liga inteira: nenhum time do Mexico ficava com rank.

A regra que fica: time sem id recupera o id pelo nome nos jogos da mesma
liga; se nem assim achar, pula so' aquele time.
"""
from collectors import standings_collector_service as mod


def _time(team_id, nome, rank):
    gols = {"for": 1, "against": 1}
    lado = {"played": 1, "win": 0, "draw": 1, "lose": 0, "goals": gols}
    return {
        "group": "Liga MX: Apertura",
        "team": {"id": team_id, "name": nome, "logo": None},
        "rank": rank, "points": 1, "goalsDiff": 0, "form": "D",
        "status": "same", "description": None,
        "all": lado, "home": lado, "away": lado, "update": "2026-10-15",
    }


class _Cursor:
    def __init__(self, ids_por_nome):
        self.ids_por_nome = ids_por_nome
        self._ultimo = None
        self.comandos = []

    def execute(self, sql, params):
        self.comandos.append(sql.split()[0])
        if "FROM fixtures" in sql:
            self._ultimo = self.ids_por_nome.get(params[2].lower())

    def fetchone(self):
        return (self._ultimo,) if self._ultimo is not None else None

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur
        self.fim = None

    def cursor(self):
        return self.cur

    def commit(self):
        self.fim = "commit"

    def rollback(self):
        self.fim = "rollback"

    def close(self):
        pass


_LIGA = {"id": 262, "name": "Liga MX", "country": "Mexico", "season": 2026}


def _salvar(monkeypatch, times, ids_por_nome):
    gravadas = []
    cur = _Cursor(ids_por_nome)
    monkeypatch.setattr(mod, "get_connection", lambda: _Conn(cur))
    monkeypatch.setattr(mod, "execute_batch",
                        lambda _c, _sql, rows: gravadas.extend(rows))
    mod.StandingsCollectorService().save_standings({**_LIGA, "standings": [times]})
    return gravadas


def test_time_sem_id_usa_o_id_dos_jogos_da_liga(monkeypatch):
    linhas = _salvar(monkeypatch,
                     [_time(2282, "Monterrey", 1), _time(None, "Club Leon", 5)],
                     {"club leon": 2289})
    assert [l[5] for l in linhas] == [2282, 2289]


def test_time_sem_id_e_sem_jogo_e_pulado_sem_derrubar_a_liga(monkeypatch):
    linhas = _salvar(monkeypatch,
                     [_time(2282, "Monterrey", 1), _time(None, "Club Leon", 5)],
                     {})
    assert [l[5] for l in linhas] == [2282]


def test_falha_no_insert_devolve_a_tabela_anterior_da_liga(monkeypatch):
    """Sem TRUNCATE global: a liga apaga a propria tabela e insere a nova na
    MESMA transacao. Se o insert quebra, o rollback desfaz o DELETE."""
    import pytest
    cur = _Cursor({})
    conn = _Conn(cur)
    monkeypatch.setattr(mod, "get_connection", lambda: conn)

    def _quebra(*_a):
        raise RuntimeError("not-null")
    monkeypatch.setattr(mod, "execute_batch", _quebra)

    with pytest.raises(RuntimeError):
        mod.StandingsCollectorService().save_standings(
            {**_LIGA, "standings": [[_time(2282, "Monterrey", 1)]]})
    assert cur.comandos == ["DELETE"]
    assert conn.fim == "rollback"


def test_coleta_nao_trunca_mais_a_tabela_inteira():
    import inspect
    fonte = inspect.getsource(mod)
    assert "TRUNCATE TABLE" not in fonte
