"""O árbitro da partida no Raio-X (16/10/2026): os números dele na temporada,
nesta liga e com cada um dos dois times, com VAR e pênalti dos eventos."""
from datetime import date

import arbitro_do_jogo as ad


def _jogo(fid, hg, ag, hy, ay, hr=0, ar=0, hf=10, af=12, home=1, away=2, liga=71, eventos=True):
    return {"fixture_id": fid, "match_date": date(2026, 10, fid % 28 + 1), "league_id": liga, "season": 2026,
            "home_team_id": home, "away_team_id": away, "home_team": f"T{home}", "away_team": f"T{away}",
            "home_goals": hg, "away_goals": ag, "home_yellow_cards": hy, "away_yellow_cards": ay,
            "home_red_cards": hr, "away_red_cards": ar, "home_fouls": hf, "away_fouls": af,
            "tem_eventos": eventos}


def test_var_em_portugues():
    assert ad.var_em_portugues("Goal Disallowed - offside") == "Gol anulado (impedimento)"
    assert ad.var_em_portugues("Penalty confirmed") == "Pênalti confirmado"
    assert ad.var_em_portugues(None) == "Revisão do VAR"
    assert ad.var_em_portugues("Algo novo") == "Algo novo"


def test_resumo_conta_cartao_falta_var_e_mando():
    jogos = [_jogo(1, 2, 0, 2, 3, ar=1), _jogo(2, 1, 1, 1, 1, eventos=False), _jogo(3, 0, 1, 3, 2, hf=None)]
    jogos[0].update(var=[{"lance": "Gol anulado"}, {"lance": "Pênalti confirmado"}], penaltis=1)
    jogos[2].update(var=[], penaltis=0)
    s = ad.resumo(jogos)
    assert s["jogos"] == 3
    assert s["amarelos"] == {"media": 4.0, "jogos": 3}          # 5, 2, 5
    assert s["pontos_de_cartao"]["media"] == round((7 + 2 + 5) / 3, 2)   # vermelho vale 2
    assert s["faltas"] == {"media": 22.0, "jogos": 2}           # o 3o nao tem a falta da casa
    assert s["var"] == {"media": 1.0, "jogos": 2}               # so' jogo com evento coletado
    assert s["penaltis"] == {"media": 0.5, "jogos": 2}
    assert (s["pct_mandante_vence"], s["pct_empate"], s["pct_visitante_vence"]) == (33, 33, 33)
    assert s["pct_mais_de_4_5_amarelos"] == 67


class _Cur:
    """Responde pelo trecho do SQL."""

    def __init__(self, fix, jogos, eventos=()):
        self.fix, self.jogos, self.eventos = fix, jogos, list(eventos)
        self.connection = self
        self.consultas = []
        self._r = []

    def rollback(self): pass

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))
        if "FROM fixtures f" in sql:
            self._r = [self.fix] if self.fix else []
        elif "FROM match_events" in sql:
            ids = set(params[0])
            self._r = [e for e in self.eventos if e["fixture_id"] in ids]
        elif "FROM match_statistics ms" in sql:
            if "ms.season = %s" in sql:
                self._r = self.jogos
            else:                                   # com um dos times
                time_ = params[1]
                self._r = [j for j in self.jogos if time_ in (j["home_team_id"], j["away_team_id"])]

    def fetchone(self):
        return self._r[0] if self._r else None

    def fetchall(self):
        return self._r


FIX = {"referee": "Raphael Claus, Brazil", "referee_ms": None, "league_id": 71, "season": 2026,
       "home_team_id": 1, "away_team_id": 2, "home_team": "Cruzeiro", "away_team": "Flamengo"}


def test_arbitro_do_jogo_monta_os_quatro_recortes():
    jogos = [_jogo(1, 2, 0, 2, 3), _jogo(2, 1, 1, 1, 1, home=3, away=1, liga=73), _jogo(3, 0, 1, 3, 2, home=4, away=5)]
    eventos = [{"fixture_id": 1, "minuto": 67, "team_id": 2, "tipo": "Var", "detalhe": "Goal cancelled"},
               {"fixture_id": 1, "minuto": 30, "team_id": 1, "tipo": "Goal", "detalhe": "Penalty"}]
    r = ad.arbitro_do_jogo(_Cur(FIX, jogos, eventos), 99)
    assert r["status"] == "ok" and r["nome"] == "Raphael Claus"
    assert r["temporada_toda"]["resumo"]["jogos"] == 3
    assert r["nesta_liga"]["resumo"]["jogos"] == 2              # o da Copa do Brasil (73) sai
    assert [j["fixture_id"] for j in r["com_mandante"]["jogos"]] == [1, 2]
    assert [j["fixture_id"] for j in r["com_visitante"]["jogos"]] == [1]
    primeiro = r["temporada_toda"]["jogos"][0]
    assert primeiro["var"] == [{"minuto": 67, "team_id": 2, "lance": "Gol anulado"}]
    assert primeiro["penaltis"] == 1 and primeiro["data"] == "2026-10-02"


def test_sem_escala_e_sem_jogo():
    assert ad.arbitro_do_jogo(_Cur({**FIX, "referee": None}, []), 99) == {"status": "sem_arbitro"}
    assert ad.arbitro_do_jogo(_Cur(None, []), 99) == {"status": "sem_jogo"}


def test_nome_vem_pela_chave_e_nao_pelo_texto():
    """'Raphael Claus' e 'Raphael Claus, Brazil' sao a mesma pessoa."""
    cur = _Cur(FIX, [])
    ad.arbitro_do_jogo(cur, 99)
    sql, params = next(c for c in cur.consultas if "ms.referee" in c[0] and "ORDER BY ms.match_date" in c[0])
    assert params[0] == "raphael claus" and "split_part" in sql
