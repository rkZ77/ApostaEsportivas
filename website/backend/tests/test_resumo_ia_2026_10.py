"""Resumo de IA do Raio-X (12/10/2026): gerado uma vez por jogo por dia, so'
com amostra, e nunca derrubando a tela."""
import json

import pytest

import resumo_ia


def _jogo(gp, gc, casa=True, ep=5, ec=4, ap=2, ac=2, gp1=None, gc1=None):
    return {"gols_pro": gp, "gols_contra": gc, "em_casa": casa,
            "escanteios_pro": ep, "escanteios_contra": ec,
            "amarelos_pro": ap, "amarelos_contra": ac,
            "gols_pro_1t": gp1, "gols_contra_1t": gc1, "chutes_alvo_pro": 4}


@pytest.mark.parametrize("rodada, tabela, esperado", [
    ("Regular Season - 30", True, "liga"),
    ("Regular Season - 30", False, "liga"),
    (None, True, "liga"),
    ("Group Stage - 3", True, "grupos"),
    ("Final - 1st Leg", False, "mata-mata ida e volta"),
    ("Round of 16", False, "mata-mata"),
    ("Semi-finals", False, "mata-mata"),
    (None, False, "copa"),
])
def test_formato_da_partida(rodada, tabela, esperado):
    assert resumo_ia.formato_da_partida(rodada, tabela) == esperado


def test_numeros_do_time_conta_as_linhas():
    jogos = [_jogo(2, 1), _jogo(0, 0), _jogo(3, 2, gp1=1, gc1=0), _jogo(1, 1)]
    n = resumo_ia.numeros_do_time(jogos)
    assert n["jogos"] == 4
    assert n["forma_recente_primeiro"] == "VEVE"
    assert n["pct_over_2_5_gols"] == 50          # 3 e 5 gols
    assert n["pct_ambas_marcam"] == 75
    assert n["pct_gol_no_1t"] == 100             # so' o jogo com folha do 1T conta
    assert n["escanteios_total_media"] == 9
    assert resumo_ia.numeros_do_time([]) is None


def _dados():
    return {
        "fixture": {"home_team_id": 1, "away_team_id": 2, "home_team": "Casa",
                    "away_team": "Fora", "round": "Regular Season - 7",
                    "match_datetime": "2026-10-12T16:00:00"},
        "times": {"home": {"jogos": [_jogo(2, 0, True), _jogo(1, 1, False)]},
                  "away": {"jogos": [_jogo(0, 1, False), _jogo(2, 2, True)]}},
        "h2h": [{"data": "2026-03-01T00:00:00", "home_team_id": 2, "away_team_id": 1,
                 "home_goals": 1, "away_goals": 3, "escanteios": 11}],
        "arbitro": None,
    }


def test_montar_fatos_separa_mando_e_tira_vazios():
    fatos = resumo_ia.montar_fatos(_dados(), "Serie A", "liga", {}, {}, {"mandante_em_casa": 5})
    assert fatos["jogo"]["formato"] == "liga"
    assert fatos["mandante"]["jogando_em_casa"]["jogos"] == 1
    assert fatos["visitante"]["jogando_fora"]["jogos"] == 1
    assert fatos["confronto_direto"][0]["mandante"] == "Fora"
    assert "arbitro" not in fatos and "tabela" not in fatos["mandante"]
    json.dumps(fatos)                            # vai pro modelo como JSON


class _Cur:
    """Banco de mentira: responde pelo trecho do SQL."""

    def __init__(self, fixture=None, casa=5, fora=5, feitos_hoje=0):
        self.fixture = fixture if fixture is not None else {
            "league_id": 71, "season": 2026, "round": "Regular Season - 30",
            "status": "NS", "home_team_id": 1, "away_team_id": 2}
        self.casa, self.fora, self.feitos_hoje = casa, fora, feitos_hoje
        self.guardado = None
        self._r = []
        self.connection = self

    def commit(self): pass
    def rollback(self): pass

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT status, conteudo"):
            self._r = [self.guardado] if self.guardado else []
        elif s.startswith("INSERT INTO raio_x_resumo_ia"):
            _, _, status, conteudo, motivo, *_ = params
            self.guardado = {"status": status, "conteudo": conteudo, "motivo": motivo,
                             "velho": False}
            self._r = []
        elif "FROM fixtures" in s:
            self._r = [self.fixture] if self.fixture else []
        elif "FROM league_standings" in s:
            self._r = []
        elif "AS casa" in s:
            self._r = [{"casa": self.casa, "fora": self.fora}]
        elif "COUNT(*) AS n FROM raio_x_resumo_ia" in s:
            self._r = [{"n": self.feitos_hoje}]
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
        return {"resumo": "Jogo de gols.", "mercados": [], "contexto": "", "alerta": ""}, 900, 120
    monkeypatch.setattr(resumo_ia, "chamar_modelo", falso)
    return chamadas


def test_primeira_abertura_gera_e_a_segunda_le_do_banco(modelo):
    cur = _Cur()
    r1 = resumo_ia.resumo_do_jogo(cur, 10, _dados)
    r2 = resumo_ia.resumo_do_jogo(cur, 10, _dados)
    assert r1["status"] == "ok" and r1["resumo"] == "Jogo de gols."
    assert r2 == r1
    assert len(modelo) == 1                      # uma chamada so'


def test_sem_amostra_nao_chama_o_modelo_e_guarda_o_motivo(modelo):
    cur = _Cur(casa=2, fora=7)
    r = resumo_ia.resumo_do_jogo(cur, 10, _dados)
    assert r["status"] == "inelegivel" and "2 jogo" in r["motivo"]
    assert cur.guardado["status"] == "inelegivel"
    assert modelo == []


def test_jogo_encerrado_e_teto_do_dia_nao_gastam(modelo, monkeypatch):
    assert resumo_ia.resumo_do_jogo(
        _Cur(fixture={"league_id": 71, "season": 2026, "round": None, "status": "FT",
                      "home_team_id": 1, "away_team_id": 2}), 10, _dados)["status"] == "inelegivel"
    monkeypatch.setenv("RESUMO_IA_MAX_DIA", "3")
    assert resumo_ia.resumo_do_jogo(_Cur(feitos_hoje=3), 10, _dados)["status"] == "limite"
    assert modelo == []


def test_desligado_sem_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert resumo_ia.resumo_do_jogo(_Cur(), 10, _dados) == {"status": "desligado"}


def test_chamada_usa_modelo_barato_json_e_corta_em_4(monkeypatch):
    from types import SimpleNamespace as NS
    pedido = {}
    saida = {"resumo": "r", "contexto": "c", "alerta": "",
             "mercados": [{"mercado": f"m{i}", "tendencia": "over", "leitura": "l"} for i in range(6)]}

    class _Msgs:
        def create(self, **kw):
            pedido.update(kw)
            return NS(stop_reason="end_turn",
                      content=[NS(type="thinking"), NS(type="text", text=json.dumps(saida))],
                      usage=NS(input_tokens=1500, output_tokens=300))
    monkeypatch.setattr(resumo_ia, "_client", NS(messages=_Msgs()))
    conteudo, t_in, t_out = resumo_ia.chamar_modelo({"jogo": {}})
    assert pedido["model"] == "claude-haiku-5-5"
    assert pedido["output_config"]["effort"] == "low"
    assert pedido["output_config"]["format"]["type"] == "json_schema"
    assert len(conteudo["mercados"]) == 4 and (t_in, t_out) == (1500, 300)


def test_falha_do_modelo_fica_gravada_e_nao_levanta(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def quebra(fatos):
        raise RuntimeError("overloaded")
    monkeypatch.setattr(resumo_ia, "chamar_modelo", quebra)
    cur = _Cur()
    assert resumo_ia.resumo_do_jogo(cur, 10, _dados) == {"status": "falhou"}
    assert cur.guardado["status"] == "falhou"
