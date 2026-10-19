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
    # 3 e 5 gols: 50% fica entre 36 e 64, nao vira mercado e nao vai pro modelo
    assert "2.5" not in n["jogo"]["gols"]["pct_mais_de"] and n["jogo"]["gols"]["pct_mais_de"]["1.5"] == 75
    assert n["pct_marcou"] == 75 and n["pct_sofreu"] == 75
    assert n["jogo"]["pct_ambas_marcam"] == 75
    # so' o jogo com folha do 1T conta
    assert n["jogo"]["gols_1t"] == {"media": 1, "jogos": 1, "pct_mais_de": {"0.5": 100, "1.5": 0, "2.5": 0}}
    assert n["jogo"]["escanteios"]["media"] == 9
    assert n["time"]["gols_feitos"]["pct_mais_de"]["0.5"] == 75
    assert n["time"]["gols_sofridos"]["pct_mais_de"]["0.5"] == 75
    assert n["time"]["escanteios_a_favor"]["media"] == 5
    assert n["time"]["escanteios_a_favor"]["pct_mais_de"]["4.5"] == 100
    assert n["resultado"] == {"pct_vitoria": 50, "pct_empate": 50, "pct_derrota": 0}
    assert n["time"]["faltas_cometidas"] is None                 # sem o numero, sem mercado
    assert resumo_ia.numeros_do_time([]) is None


def test_todos_os_mercados_da_aba_entram():
    j = {**_jogo(1, 0), "faltas_pro": 14, "faltas_contra": 10, "chutes_pro": 12, "chutes_contra": 9,
         "impedimentos_pro": 2, "impedimentos_contra": 1, "defesas_pro": 3, "defesas_contra": 4,
         "escanteios_pro_1t": 2, "escanteios_contra_1t": 3, "vermelhos_pro": 1, "vermelhos_contra": 0}
    n = resumo_ia.numeros_do_time([j, j])
    assert n["time"]["faltas_cometidas"]["pct_mais_de"]["13.5"] == 100
    assert n["jogo"]["faltas"]["media"] == 24 and n["jogo"]["chutes"]["media"] == 21
    assert n["time"]["impedimentos"]["media"] == 2 and n["time"]["defesas_do_goleiro"]["media"] == 3
    assert n["jogo"]["escanteios_1t"]["media"] == 5 and n["jogo"]["escanteios_2t"]["media"] == 4
    assert n["jogo"]["pct_teve_vermelho"] == 100 and n["jogo"]["pct_ambos_recebem_cartao"] == 100


def test_jogadores_so_no_mando_e_so_linhas_fortes():
    def g(fid, chutes_alvo, faltas=0):
        return {"fixture_id": fid, "minutos": 90, "chutes_alvo": chutes_alvo, "faltas": faltas,
                "chutes": chutes_alvo, "gols": 0}
    lista = [
        {"nome": "Pedro", "posicao": "F", "titular_provavel": True,
         "jogos": [g(1, 2), g(2, 1), g(3, 1), g(4, 0), g(99, 0)]},
        {"nome": "Banco", "posicao": "M", "jogos": [g(1, 1), g(2, 1)]},       # 2 jogos: fora
        {"nome": "Goleiro", "posicao": "G", "jogos": [{**g(f, 0), "defesas": 4} for f in (1, 2, 3, 4)]},
    ]
    saida = resumo_ia.numeros_dos_jogadores(lista, {1, 2, 3, 4})
    assert [p["nome"] for p in saida] == ["Pedro", "Goleiro"]
    pedro = saida[0]
    assert pedro["jogos"] == 4                                   # o jogo 99 e' do outro mando
    assert pedro["mercados"]["chutes_alvo"]["pct_jogos_com"] == {"1+": 75}   # 2+ (25%) nao vai
    assert "faltas" not in pedro["mercados"]                     # 0% em tudo
    assert set(saida[1]["mercados"]) == {"defesas"}              # goleiro so' defesas


def test_media_da_liga_e_a_regua_e_so_com_amostra():
    j = {**_jogo(1, 1), "faltas_pro": 11, "faltas_contra": 12}
    assert resumo_ia.media_da_liga([j] * 10) is None              # 5 jogos: pouco
    m = resumo_ia.media_da_liga([j] * 40)
    assert m["jogos"] == 20
    assert m["media_de_um_time"]["faltas_cometidas"] == 11 and m["media_do_jogo"]["faltas"] == 23
    dados = {**_dados(), "liga_jogos": [j] * 40}
    fatos = resumo_ia.montar_fatos(dados, "Serie A", "liga", {}, {}, {})
    assert fatos["media_da_liga"]["media_do_jogo"]["gols"] == 2


def test_entrada_cabe_no_custo():
    """Todos os mercados so' no bloco do mando: ultimos 5 e geral vao so' com
    as medias. A entrada inteira tem que ficar bem abaixo de ~6 mil tokens."""
    j = {**_jogo(1, 0), "faltas_pro": 14, "faltas_contra": 10, "chutes_pro": 12, "chutes_contra": 9,
         "impedimentos_pro": 2, "impedimentos_contra": 1, "defesas_pro": 3, "defesas_contra": 4,
         "escanteios_pro_1t": 2, "escanteios_contra_1t": 3, "amarelos_pro_1t": 1, "amarelos_contra_1t": 0,
         "chutes_alvo_pro_1t": 2, "chutes_alvo_contra_1t": 1, "gols_pro_1t": 1, "gols_contra_1t": 0,
         "fixture_id": 1}
    serie = [j] * 16
    curto = resumo_ia.numeros_curtos(serie)
    assert "time" not in curto and curto["medias_do_time"]["faltas_cometidas"] == 14
    fatos = resumo_ia.montar_fatos(_dados(), "Serie A", "liga", {}, {}, {}, serie, serie)
    texto = json.dumps(fatos, ensure_ascii=False, separators=(",", ":"))
    assert len(texto) < 14000                     # ~4 caracteres por token


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
    assert fatos["mandante"]["EM_CASA_na_temporada"]["jogos"] == 1
    assert fatos["visitante"]["FORA_na_temporada"]["jogos"] == 1
    serie = [_jogo(1, 0), _jogo(2, 0), _jogo(0, 0)]
    com_mando = resumo_ia.montar_fatos(_dados(), "Serie A", "liga", {}, {}, {}, serie, serie)
    assert com_mando["mandante"]["EM_CASA_na_temporada"]["jogos"] == 3
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
    m = [{"mercado": f"m{i}", "tendencia": "over", "leitura": "l"} for i in range(6)]
    saida = {"resumo": "r", "contexto": "c", "alerta": "", "mercados_do_jogo": m,
             "times": [{"lado": "mandante", "perfil": "dominante", "leitura": "l", "mercados": m,
                        "jogadores": m}] * 3}

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
    # 3500 cortava a leitura no meio em PROD (max_tokens, 13/10/2026).
    assert pedido["max_tokens"] >= 8000
    assert len(conteudo["mercados_do_jogo"]) == 3 and len(conteudo["times"]) == 2
    assert len(conteudo["times"][0]["mercados"]) == 3 and (t_in, t_out) == (1500, 300)
    assert len(conteudo["times"][0]["jogadores"]) == 3
    # o atalho pra aba Mercados e' obrigatorio nos mercados de time e de jogo
    esquema = pedido["output_config"]["format"]["schema"]
    item = esquema["properties"]["mercados_do_jogo"]["items"]
    assert "atalho" in item["required"]
    assert "outro" in item["properties"]["atalho"]["properties"]["mercado"]["enum"]


def test_falha_do_modelo_fica_gravada_e_nao_levanta(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def quebra(fatos):
        raise RuntimeError("overloaded")
    monkeypatch.setattr(resumo_ia, "chamar_modelo", quebra)
    cur = _Cur()
    assert resumo_ia.resumo_do_jogo(cur, 10, _dados) == {"status": "falhou"}
    assert cur.guardado["status"] == "falhou"


def test_leitura_de_formato_antigo_e_gerada_de_novo_uma_vez(modelo):
    cur = _Cur()
    cur.guardado = {"status": "ok", "conteudo": json.dumps({"resumo": "velha", "mercados": []}),
                    "motivo": None, "velho": False}
    r = resumo_ia.resumo_do_jogo(cur, 10, _dados)
    assert r["resumo"] == "Jogo de gols." and r["versao"] == resumo_ia.VERSAO
    resumo_ia.resumo_do_jogo(cur, 10, _dados)
    assert len(modelo) == 1


def test_serie_por_mando_le_so_o_lado_do_mando():
    class C:
        def execute(self, sql, params):
            self.sql, self.params = sql, params
        def fetchall(self):
            return [{"fixture_id": 5, "match_date": None, "home_team_id": 3, "away_team_id": 7,
                     "home_goals": 2, "away_goals": 1, "home_goals_ht": 1, "away_goals_ht": 0,
                     "home_corners": 6, "away_corners": 3, "home_yellow_cards": 1, "away_yellow_cards": 3,
                     "home_red_cards": 0, "away_red_cards": 1, "home_fouls": 10, "away_fouls": 15,
                     "home_shots_on": 5, "away_shots_on": 2, "home_possession": "58%", "away_possession": "42%"}]
    c = C()
    fora = resumo_ia.serie_por_mando(c, 7, False, 2026, 71, True, None)
    assert "away_team_id = %s" in c.sql and c.params[0] == 7
    assert fora[0]["gols_pro"] == 1 and fora[0]["escanteios_pro"] == 3 and fora[0]["posse"] == "42%"
    assert fora[0]["em_casa"] is False and fora[0]["faltas_pro"] == 15
    assert resumo_ia.numeros_do_time(fora)["posse_media"] == 42

def test_numeros_da_tela_saem_da_conta_e_nao_da_ia(modelo):
    serie = [_jogo(2, 1, ep=6), _jogo(0, 0, ep=4), _jogo(1, 2, ep=5)]
    fatos = resumo_ia.montar_fatos(_dados(), "Serie A", "liga", {}, {}, {}, serie, serie)
    n = resumo_ia.numeros_da_tela(fatos)
    assert n["mandante"]["jogos"] == 3 and n["mandante"]["gols_pro"] == 1
    assert n["mandante"]["pct_marcou"] == 67 and n["visitante"]["escanteios_pro"] == 5
    r = resumo_ia.resumo_do_jogo(_Cur(), 10, _dados)
    assert set(r["numeros"]) == {"mandante", "visitante"}