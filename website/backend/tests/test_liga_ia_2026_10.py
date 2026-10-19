"""Leitura da IA da liga (15/10/2026): uma vez por liga por dia, so' com
amostra, e a MESMA geracao alimenta o perfil de liga do motor."""
import json

import pytest

import liga_ia


def _j(hg, ag, hc=5, ac=4, hy=2, ay=2, home=1, away=2, hht=None, aht=None, hr=0, ar=0):
    return {"home_team_id": home, "away_team_id": away,
            "home_team": f"T{home}", "away_team": f"T{away}",
            "home_goals": hg, "away_goals": ag, "home_goals_ht": hht, "away_goals_ht": aht,
            "home_corners": hc, "away_corners": ac,
            "home_yellow_cards": hy, "away_yellow_cards": ay,
            "home_red_cards": hr, "away_red_cards": ar}


def test_numeros_da_liga_contam_linhas_mando_e_volatilidade():
    jogos = [_j(2, 1), _j(0, 0), _j(3, 2, hht=1, aht=0), _j(1, 1)]
    n = liga_ia.numeros_da_liga(jogos)
    assert n["jogos"] == 4
    assert n["gols_media"] == 2.5
    assert n["pct_over_2_5_gols"] == 50 and n["pct_ambas_marcam"] == 75
    assert n["pct_0x0"] == 25
    assert n["pct_vitoria_mandante"] == 50 and n["pct_empate"] == 50
    assert n["pct_gol_no_1t"] == 100            # so' o jogo com o 1T conta
    assert n["escanteios_media"] == 9 and n["pct_over_8_5_escanteios"] == 100
    assert n["gols_desvio_padrao"] > 1.5
    assert liga_ia.numeros_da_liga([]) is None


def test_liga_le_todos_os_mercados_do_raio_x():
    j = {**_j(2, 1, hht=1, aht=0), "home_fouls": 12, "away_fouls": 13, "home_shots_on": 5,
         "away_shots_on": 3, "home_offsides": 2, "away_offsides": 1,
         "home_corners_1h": 3, "away_corners_1h": 1}
    m = liga_ia.numeros_da_liga([j, j])["mercados"]
    assert m["faltas"]["media"] == 25 and m["faltas"]["pct_mais_de"]["24.5"] == 100
    assert m["chutes_no_alvo"]["media"] == 8 and m["impedimentos"]["media"] == 3
    assert m["escanteios_1t"]["media"] == 4 and m["gols_2t"]["media"] == 2
    # a liga manda a linha inteira, inclusive o meio (corte 40/60 e' do SYSTEM)
    assert set(m["gols"]["pct_mais_de"]) == {"0.5", "1.5", "2.5", "3.5", "4.5"}
    assert m["chutes"] is None                                  # sem o numero
    t = liga_ia.numeros_por_time([j] * 4)[0]
    assert t["faltas_jogo_media"] == 25 and t["chutes_no_alvo_jogo_media"] == 8


def test_time_com_poucos_jogos_fica_fora():
    jogos = [_j(2, 1, home=1, away=2)] * 4 + [_j(1, 0, home=3, away=1)]
    times = {t["team_id"]: t for t in liga_ia.numeros_por_time(jogos)}
    assert set(times) == {1, 2}                  # o 3 tem 1 jogo
    assert times[1]["jogos"] == 5 and times[2]["gols_pro_media"] == 1


def test_recorte_recente_so_com_temporada_longa():
    curta = liga_ia.montar_fatos("L", 2026, [_j(1, 1)] * 40, [], None)
    assert not any(k.startswith("numeros_dos_ultimos") for k in curta)
    longa = liga_ia.montar_fatos("L", 2026, [_j(3, 1)] * 30 + [_j(0, 0)] * 30, [], None)
    assert longa[f"numeros_dos_ultimos_{liga_ia.RECENTES}_jogos"]["gols_media"] == 4
    json.dumps(longa)


def test_texto_do_motor_nao_cita_time_e_traz_os_numeros():
    conteudo = {"resumo": "Liga de gols.", "mando": "Mandante vence 48%.", "momento": "",
                "tendencias": [{"mercado": "Mais de 1,5 gol", "tendencia": "over", "pct": 81,
                                "leitura": "8 de 10 jogos."}],
                "times_over": [{"time": "Hertha", "leitura": "x", "team_id": 1}], "alerta": ""}
    n = liga_ia.numeros_da_liga([_j(2, 1), _j(1, 1)])
    t = liga_ia.texto_pro_motor("2. Bundesliga", 2026, 105, conteudo, n)
    assert t.startswith("2. Bundesliga (105 jogos) · Season 2026")
    assert "Hertha" not in t
    assert "Mais de 1,5 gol: 81% a favor" in t and "gols 2,5/jogo" in t


def test_nome_inventado_pelo_modelo_sai_da_lista():
    c = {"times_over": [{"time": "T1", "leitura": "a"}, {"time": "Inventado FC", "leitura": "b"}],
         "times_under": []}
    liga_ia._com_escudo(c, [{"team_id": 1, "nome": "T1"}])
    assert c["times_over"] == [{"time": "T1", "leitura": "a", "team_id": 1}]


class _Cur:
    def __init__(self, jogos=25, feitas_hoje=0):
        self.jogos, self.feitas_hoje = jogos, feitas_hoje
        self.guardado = None
        self.perfil_motor = None
        self._r = []
        self.connection = self

    def commit(self): pass
    def rollback(self): pass

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT status, conteudo"):
            self._r = [self.guardado] if self.guardado else []
        elif s.startswith("INSERT INTO liga_resumo_ia"):
            _, _, status, conteudo, motivo, *_ = params
            self.guardado = {"status": status, "conteudo": conteudo, "motivo": motivo, "velho": False}
        elif s.startswith("INSERT INTO league_analysis"):
            self.perfil_motor = params
        elif "MAX(season) AS s" in s:
            self._r = [{"s": 2026}]
        elif "FROM match_statistics ms WHERE ms.league_id" in s:
            self._r = [_j(2, 1)] * self.jogos
        elif "COUNT(*) AS n FROM liga_resumo_ia" in s:
            self._r = [{"n": self.feitas_hoje}]
        elif "FROM leagues" in s:
            self._r = [{"name": "Serie A"}]
        else:
            self._r = []

    def fetchone(self):
        return self._r[0] if self._r else None

    def fetchall(self):
        return self._r


@pytest.fixture
def modelo(monkeypatch):
    chamadas = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("RESUMO_IA", raising=False)

    def falso(fatos):
        chamadas.append(fatos)
        return {"resumo": "Liga de gols.", "tendencias": [], "mando": "", "momento": "",
                "times_over": [{"time": "T1", "leitura": "puxa"}], "times_under": [],
                "alerta": ""}, 2000, 300
    monkeypatch.setattr(liga_ia, "chamar_modelo", falso)
    return chamadas


def test_gera_uma_vez_e_grava_tambem_o_perfil_do_motor(modelo):
    cur = _Cur()
    r1 = liga_ia.leitura_da_liga(cur, 71)
    r2 = liga_ia.leitura_da_liga(cur, 71)
    assert r1["status"] == "ok" and r1["resumo"] == "Liga de gols."
    assert r1["times_over"][0]["team_id"] == 1
    assert r2 == r1 and len(modelo) == 1
    liga, nome, season, texto = cur.perfil_motor
    assert (liga, nome, season) == (71, "Serie A", 2026) and "Liga de gols." in texto


def test_sem_amostra_e_teto_nao_gastam(modelo, monkeypatch):
    r = liga_ia.leitura_da_liga(_Cur(jogos=5), 71)
    assert r["status"] == "inelegivel" and "5 jogo" in r["motivo"]
    monkeypatch.setenv("LIGA_IA_MAX_DIA", "2")
    assert liga_ia.leitura_da_liga(_Cur(feitas_hoje=2), 71)["status"] == "limite"
    assert modelo == []


def test_desligado_sem_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert liga_ia.leitura_da_liga(_Cur(), 71) == {"status": "desligado"}


def test_falha_do_modelo_fica_gravada(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(liga_ia, "chamar_modelo", lambda f: (_ for _ in ()).throw(RuntimeError("x")))
    cur = _Cur()
    assert liga_ia.leitura_da_liga(cur, 71) == {"status": "falhou"}
    assert cur.guardado["status"] == "falhou" and cur.perfil_motor is None


def test_chamada_usa_modelo_barato_e_corta_as_listas(monkeypatch):
    from types import SimpleNamespace as NS
    pedido = {}
    t = [{"time": f"t{i}", "leitura": "l"} for i in range(6)]
    m = [{"mercado": "m", "tendencia": "over", "pct": 70, "leitura": "l"}] * 6
    saida = {"resumo": "r", "tendencias": m, "mando": "", "momento": "", "alerta": "",
             "times_over": t, "times_under": t}

    class _Msgs:
        def create(self, **kw):
            pedido.update(kw)
            return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(saida))],
                      usage=NS(input_tokens=10, output_tokens=5))
    import resumo_ia
    monkeypatch.setattr(resumo_ia, "_client", NS(messages=_Msgs()))
    conteudo, _, _ = liga_ia.chamar_modelo({})
    assert pedido["model"] == resumo_ia.MODELO and pedido["output_config"]["effort"] == "low"
    assert len(conteudo["tendencias"]) == 4 and len(conteudo["times_over"]) == 3
