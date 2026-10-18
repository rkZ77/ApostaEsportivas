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

    def __init__(self, fix, jogos, eventos=(), extras=(), grafias=()):
        self.fix, self.jogos, self.eventos, self.extras = fix, jogos, list(eventos), list(extras)
        self.grafias = list(grafias)
        self.connection = self
        self.consultas = []
        self._r = []

    def rollback(self): pass

    def execute(self, sql, params=None):
        self.consultas.append((sql, params))
        if "SELECT DISTINCT" in sql:
            self._r = [{"k": g} for g in self.grafias if g[:1] == params[0]]
        elif "FROM fixtures f" in sql:
            self._r = [self.fix] if self.fix else []
        elif "FROM arbitro_partidas" in sql:
            if "ap.season = %s" in sql:
                self._r = [dict(e) for e in self.extras]
            else:
                time_ = params[1]
                self._r = [dict(e) for e in self.extras if time_ in (e["home_team_id"], e["away_team_id"])]
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
    # Mais recente primeiro (o jogo 2 e' de 03/10, o 1 de 02/10), como o ORDER BY.
    assert [j["fixture_id"] for j in r["com_mandante"]["jogos"]] == [2, 1]
    assert [j["fixture_id"] for j in r["com_visitante"]["jogos"]] == [1]
    primeiro = next(j for j in r["temporada_toda"]["jogos"] if j["fixture_id"] == 1)
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
    assert params[0] == ["raphael claus"] and "split_part" in sql


# ── temporada inteira (18/10/2026): jogos de fora da base, em arbitro_partidas ──

def _extra(fid, liga=72, home=1, away=9, hy=2, ay=2, cartao=True):
    j = _jogo(fid, 1, 0, hy if cartao else None, ay if cartao else None, home=home, away=away, liga=liga)
    j.update(liga_nome="Serie B", tem_eventos=True, penaltis=1,
             var_lances=[{"minuto": 50, "team_id": 9, "detalhe": "Penalty confirmed"}])
    return j


def test_jogo_de_liga_nao_cadastrada_entra_na_temporada_e_nao_na_liga():
    jogos = [_jogo(1, 2, 0, 2, 3)]
    r = ad.arbitro_do_jogo(_Cur(FIX, jogos, extras=[_extra(5)]), 99)
    assert r["temporada_toda"]["resumo"]["jogos"] == 2
    assert r["nesta_liga"]["resumo"]["jogos"] == 1            # Série B (72) não é esta liga
    assert r["de_outras_competicoes"] == 1
    extra = next(j for j in r["temporada_toda"]["jogos"] if j["fixture_id"] == 5)
    assert extra["extra"] and extra["liga_nome"] == "Serie B"
    assert extra["var"] == [{"minuto": 50, "team_id": 9, "lance": "Pênalti confirmado"}]
    assert extra["penaltis"] == 1
    assert [j["fixture_id"] for j in r["com_mandante"]["jogos"]] == [5, 1] or \
           sorted(j["fixture_id"] for j in r["com_mandante"]["jogos"]) == [1, 5]


def test_mesmo_jogo_nas_duas_tabelas_conta_uma_vez():
    """Com folha em match_statistics, vale ela. Sem folha lá, vale a de fora."""
    com_folha = _jogo(1, 2, 0, 2, 3)
    sem_folha = _jogo(2, 1, 1, None, None)
    extras = [_extra(1, liga=71, hy=9, ay=9), _extra(2, liga=71, hy=4, ay=1)]
    r = ad.arbitro_do_jogo(_Cur(FIX, [com_folha, sem_folha], extras=extras), 99)
    por_id = {j["fixture_id"]: j for j in r["temporada_toda"]["jogos"]}
    assert len(por_id) == 2
    assert por_id[1]["amarelos"] == 5 and not por_id[1]["extra"]
    assert por_id[2]["amarelos"] == 5 and por_id[2]["extra"]


def test_nome_curto_e_nome_completo_sao_a_mesma_pessoa():
    """18/10/2026: o Raio-X do Ramon Abatti mostrava 4 jogos de 16. A API
    escreveu "Ramon Abatti Abel" ate' agosto e "Ramon Abatti" depois."""
    fix = {**FIX, "referee": "Ramon Abatti, Brazil"}
    # PROD: o grosso do Brasileirao dele estava em "R. Abatti" (11 de 16).
    cur = _Cur(fix, [], grafias=["r abatti", "ramon abatti", "ramon abatti abel", "ramon souza"])
    ad.arbitro_do_jogo(cur, 99)
    sql, params = next(c for c in cur.consultas if "ORDER BY ms.match_date" in c[0])
    assert params[0] == ["r abatti", "ramon abatti", "ramon abatti abel"]


def test_ranking_da_liga_junta_grafias_e_nao_inventa_falta():
    """Aba Árbitros das Estatísticas (18/10/2026): uma linha por pessoa, e a
    média de faltas só sobre os jogos que têm a falta."""
    from routers import suggestions as sg

    class _C:
        def execute(self, sql, params=None): pass
        def fetchall(self):
            return [
                {"chave": "ramon abatti", "referee": "Ramon Abatti", "jogos": 4, "soma_amarelo": 24,
                 "soma_vermelho": 1, "soma_faltas": 120, "jogos_faltas": 4},
                {"chave": "ramon abatti abel", "referee": "Ramon Abatti Abel", "jogos": 12, "soma_amarelo": 60,
                 "soma_vermelho": 1, "soma_faltas": 250, "jogos_faltas": 10},
                {"chave": "outro nome", "referee": "Outro Nome", "jogos": 1, "soma_amarelo": 3,
                 "soma_vermelho": 0, "soma_faltas": None, "jogos_faltas": 0},
            ]
        def close(self): pass

    class _Conn:
        def cursor(self): return _C()
        def close(self): pass

    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(sg, "get_connection", lambda: _Conn())
    mp.setattr(sg, "_safe_query", lambda cur, sql, params: cur.fetchall())
    try:
        r = sg.get_liga_arbitros(league_id=71, min_jogos=2, current_user={})
    finally:
        mp.undo()
    (ramon,) = r["arbitros"]                       # o de 1 jogo fica abaixo do mínimo
    assert ramon["referee"] == "Ramon Abatti Abel" and ramon["jogos"] == 16
    assert ramon["avg_yellow"] == round(84 / 16, 2)
    assert ramon["avg_fouls"] == round(370 / 14, 1)   # 14 jogos com falta, não 16


# ── o arbitro no contexto (18/10/2026) ───────────────────────────────────────

def test_copia_do_contexto_e_igual_a_do_motor():
    import os
    aqui = os.path.join(os.path.dirname(__file__), "..", "arbitro_no_contexto.py")
    motor = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ApostaEsportivas", "src",
                         "services", "pick_engine", "arbitro_no_contexto.py")
    assert open(aqui, encoding="utf-8").read() == open(motor, encoding="utf-8").read()


class _CurCtx:
    """Media da liga 4,9; times 5,0 e 5,2; confrontos com 7,5 pontos."""

    def __init__(self):
        self.connection, self._r = self, []

    def rollback(self): pass

    def execute(self, sql, params=None):
        if "AVG(total_yellow_cards" in sql:
            alvo = params[-1]
            self._r = [{"pontos": 4.9 if "league_id" in sql else (5.0 if alvo == 1 else 5.2),
                        "faltas": 24.0, "n": 300}]
        elif "LIMIT 6" in sql:
            self._r = [{"pontos": 7.5}] * 5

    def fetchone(self):
        return self._r[0] if self._r else None

    def fetchall(self):
        return self._r


def test_contexto_classico_com_arbitro_rigoroso():
    fix = {"league_id": 71, "season": 2026, "home_team_id": 1, "away_team_id": 2}
    ctx = ad.contexto(_CurCtx(), fix, {"pontos_de_cartao": {"media": 6.2, "jogos": 16}})
    assert ctx["perfil"] == "rigoroso" and ctx["pontos_de_cartao_da_liga"] == 4.9
    assert ctx["confronto"]["label"] == "rivalidade_alta" and ctx["confronto"]["baseline"] == 5.1
    assert ctx["temperatura"] == "confronto_quente_com_arbitro_rigoroso"


def test_ia_do_raio_x_recebe_o_arbitro_contra_a_liga():
    import resumo_ia
    arb = {"status": "ok", "nome": "Ramon Abatti",
           "temporada_toda": {"resumo": {"jogos": 20, "pontos_de_cartao": {"media": 6.2, "jogos": 20},
                                         "faltas": {"media": 28.0, "jogos": 18}, "pct_mais_de_4_5_amarelos": 70}},
           "contexto": {"perfil": "rigoroso", "pontos_de_cartao_da_liga": 4.9, "temperatura": "arbitro_rigoroso"}}
    f = resumo_ia.fato_do_arbitro(arb)
    assert f["pontos_de_cartao_por_jogo"] == 6.2 and f["pontos_de_cartao_da_liga"] == 4.9
    assert f["perfil"] == "rigoroso" and f["jogos_na_temporada"] == 20
    assert resumo_ia.fato_do_arbitro({"status": "sem_arbitro"}) is None
    assert "pesa SÓ em cartões e faltas" in resumo_ia.SYSTEM and resumo_ia.VERSAO >= 5


def test_contexto_traz_o_perfil_de_faltas():
    fix = {"league_id": 71, "season": 2026, "home_team_id": 1, "away_team_id": 2}
    ctx = ad.contexto(_CurCtx(), fix, {"pontos_de_cartao": {"media": 5.0, "jogos": 28},
                                       "faltas": {"media": 31.7, "jogos": 28}})
    assert ctx["perfil"] == "na_media_da_liga" and ctx["perfil_de_faltas"] == "marca_muita_falta"
