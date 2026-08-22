"""Motor de Picks Ao Vivo · V1 (2026-08-11).

O que esta bateria protege, em ordem de gravidade:

1. A EQUIVALENCIA DO PRE-JOGO. O Live tocou quatro arquivos compartilhados
   (staking, extractor de pernas, banca, routers/live). Os testes de
   equivalencia aqui existem pra provar que nenhum produto pre-jogo mudou de
   comportamento por causa disso.

2. A SEMANTICA DA LIQUIDACAO. Pick criado no minuto 60 e' graduado pelo TOTAL
   da partida, nao pelos eventos posteriores. Se o modelo estimar uma coisa e
   a liquidacao ler outra, o motor e' cobrado por algo que nunca previu.

3. O TETO DE API e o BLOQUEIO POR DADO VELHO. Os dois freios que impedem a V1
   de virar um problema de custo ou de decidir sobre uma partida que ja mudou.

4. O MODELO. Pressao, ritmo, tendencia, janelas, eventos, convergencia e
   projecao residual -- cada um com o caso que ele existe pra pegar.
"""
import os
from datetime import timedelta
from decimal import Decimal

import pytest

# settlement_bridge poe ApostaEsportivas/src no sys.path -- e' o mesmo caminho
# que routers/live.py usa. Sem este import o pacote do motor nao resolve.
import settlement_bridge  # noqa: F401
from settlement_bridge import settlement

from services.pick_engine.staking import calculate_stake
from services.pick_engine_live import (
    live_odds, live_state, orchestrator, pressure_model,
    residual_model as rm, rhythm_model as rit, signal_score,
)
from services.pick_engine_live.config import (
    AmbienteInvalido, LiveEngineConfig, exigir_ambiente_dev,
)
from services.pick_engine_live.live_feed import (
    LiveFeed, OrcamentoEsgotado, ler_estatisticas, total_da_familia,
)

CONFIG = LiveEngineConfig(habilitado=True, dry_run=True)


# ═════════════════════════════════════════════════════════════════════════
# Dubles
# ═════════════════════════════════════════════════════════════════════════
def folha(home_id=10, away_id=20, home=None, away=None):
    """Resposta de /fixtures/statistics no formato cru da API-Football."""
    def bloco(tid, valores):
        return {"team": {"id": tid},
                "statistics": [{"type": k, "value": v} for k, v in (valores or {}).items()]}
    return [bloco(home_id, home), bloco(away_id, away)]


def fixture_bruto(minuto=60, status="2H", hg=1, ag=1, kickoff=None, fid=999):
    return {
        "fixture": {"id": fid, "timestamp": kickoff,
                    "status": {"short": status, "elapsed": minuto}},
        "goals": {"home": hg, "away": ag},
        "teams": {"home": {"id": 10, "name": "Casa FC"},
                  "away": {"id": 20, "name": "Fora EC"}},
        "league": {"id": 71, "name": "Serie A"},
    }


def estado_de(minuto=60, status="2H", hg=1, ag=1, home=None, away=None,
              eventos=None, kickoff=None):
    padrao_home = {"Corner Kicks": 6, "Total Shots": 11, "Shots on Goal": 4,
                   "Ball Possession": 55, "Yellow Cards": 1, "Red Cards": 0,
                   "Blocked Shots": 3}
    padrao_away = {"Corner Kicks": 3, "Total Shots": 7, "Shots on Goal": 2,
                   "Ball Possession": 45, "Yellow Cards": 2, "Red Cards": 0,
                   "Blocked Shots": 1}
    casa, fora = ler_estatisticas(
        folha(home={**padrao_home, **(home or {})}, away={**padrao_away, **(away or {})}),
        10, 20)
    return live_state.montar_estado(
        fixture_bruto(minuto, status, hg, ag, kickoff), casa, fora, eventos or [])


def observacao(minuto, corners=None, goals=None, shots=None, epoch=None):
    return {"minuto": minuto, "corners_observado": corners, "goals_observado": goals,
            "shots_observado": shots, "epoch": epoch}


def mercado(nome, valores):
    return {"name": nome, "values": valores}


# ═════════════════════════════════════════════════════════════════════════
# 1 · EQUIVALENCIA DO PRE-JOGO
# ═════════════════════════════════════════════════════════════════════════
def test_stake_do_pre_jogo_nao_mudou_com_a_entrada_do_live():
    """Adicionar a chave 'live' ao dicionario de staking nao pode mexer em
    nenhum tipo que ja existia."""
    assert calculate_stake(confidence=0.85, odd=2.0, ev=0.20, pick_type="vip") == (0.05, 5)
    assert calculate_stake(confidence=0.80, odd=2.0, ev=0.15, pick_type="free") == (0.02, 2)
    # 2 unidades e nao 3 porque round(2.5) no Python arredonda pro par --
    # comportamento antigo, preservado de proposito.
    assert calculate_stake(confidence=0.70, odd=3.0, ev=0.10, pick_type="multipla") == (0.025, 2)
    assert calculate_stake(confidence=0.85, odd=2.0, ev=0.20, pick_type="qualquer") == (0.03, 3)


def test_live_tem_stake_mais_conservador_que_qualquer_produto_pre_jogo():
    pct_live, u_live = calculate_stake(confidence=0.90, odd=2.5, ev=0.30, pick_type="live")
    pct_vip, _ = calculate_stake(confidence=0.90, odd=2.5, ev=0.30, pick_type="vip")
    pct_free, _ = calculate_stake(confidence=0.90, odd=2.5, ev=0.30, pick_type="free")
    assert pct_live < pct_free < pct_vip
    assert u_live <= 4


def test_extractor_de_pernas_mantem_as_colunas_de_cada_tabela():
    from services import pick_legs_extractor as ex

    class CursorFalso:
        """`tem_market_id` simula a resposta de information_schema: picks_live
        e' a unica das cinco que nao tem a coluna, e o extractor precisa
        continuar funcionando nos dois casos."""

        def __init__(self, tem_market_id=True):
            self.sql = ""
            self.tem_market_id = tem_market_id
        def execute(self, sql, params=None):
            self.sql = sql
        def fetchall(self):
            return []
        def fetchone(self):
            return (1,) if self.tem_market_id else None

    for tabela, esperado, proibido in (
        ("picks_vip", "home_team_name AS home_team", "prob_real"),
        ("picks_live", "home_team_name AS home_team", "prob_real"),
        ("picks_free", "prob_real AS probability", "home_team_name"),
        ("picks_faltas", "prob_real AS probability", "home_team_name"),
        ("picks_goleiros", "prob_real AS probability", "home_team_name"),
    ):
        cur = CursorFalso()
        ex.fetch_vip_free_legs(cur, tabela)
        assert esperado in cur.sql, f"{tabela} perdeu a coluna certa"
        assert proibido not in cur.sql, f"{tabela} pegou a coluna da outra familia"
        # Sem market_id a perna nao recebe CLV: casar a odd de fechamento so'
        # pelo rotulo da linha traz outro mercado (ver tests/test_clv_cruzado.py
        # no pacote do motor).
        assert "market_id" in cur.sql, f"{tabela} nao trouxe market_id"

    # Tabela sem a coluna: seleciona NULL em vez de quebrar a extracao inteira.
    cur = CursorFalso(tem_market_id=False)
    ex.fetch_vip_free_legs(cur, "picks_live")
    assert "NULL::int AS market_id" in cur.sql


def test_router_do_live_nao_consulta_nenhuma_tabela_do_pre_jogo():
    """A estatistica Live e' separada por construcao, nao por disciplina."""
    import inspect
    import re
    import routers.live_picks as lp

    fonte = inspect.getsource(lp)
    # Procura a tabela em posicao de CONSULTA, nao no texto: as docstrings
    # citam os nomes justamente pra explicar por que eles NAO sao consultados.
    for tabela in ("picks_vip", "picks_free", "picks_multiplas",
                   "picks_alavancagem", "picks_faltas", "picks_goleiros"):
        padrao = re.compile(rf"\b(FROM|JOIN|UPDATE|INTO)\s+{tabela}\b", re.IGNORECASE)
        assert not padrao.search(fonte), f"live_picks.py consulta {tabela}"


def test_pick_live_nao_grava_em_tabela_de_pre_jogo():
    """_save_single_result manda pra picks_free tudo que nao e' 'vip'. Passar
    'live' por la gravaria em silencio na tabela errada -- por isso existe um
    saver proprio."""
    import inspect
    from routers import live as rl

    fonte = inspect.getsource(rl._save_live_pick_result)
    assert "UPDATE picks_live" in fonte
    assert "status = 'SETTLED'" in fonte
    fonte_branch = inspect.getsource(rl.get_live_my_picks)
    assert "_save_live_pick_result(pick_id" in fonte_branch


# ═════════════════════════════════════════════════════════════════════════
# 2 · SEMANTICA DA LIQUIDACAO
# ═════════════════════════════════════════════════════════════════════════
def test_pick_live_e_liquidado_pelo_total_da_partida():
    """Over 2.5 criado aos 60' com 1x0 e' GREEN se o jogo terminar 2x1.

    Sao 3 gols no TOTAL, e e' assim que a casa liquida. Contar so' os gols
    posteriores a' criacao (2) daria RED.
    """
    resultado, fator = settlement.settle_over_under(2 + 1, Decimal("2.5"), "over")
    assert resultado == settlement.GREEN
    assert fator == Decimal("1")


def test_o_modelo_pergunta_sobre_o_que_falta_mas_responde_sobre_o_total():
    """A ponte entre modelo e liquidacao e' a subtracao do ja-observado.

    Com 7 escanteios no placar e linha 9.5, a pergunta correta pro Poisson do
    RESTANTE e' P(X > 2.5), nao P(X > 9.5). Sem a subtracao, o motor viraria
    uma maquina de Under.
    """
    lam = 3.0
    com = rm.probabilidade_da_linha(lam, 9.5, "over", ja_observado=7)
    sem = rm.probabilidade_da_linha(lam, 9.5, "over", ja_observado=0)
    assert com > 0.35
    assert sem < 0.01
    from services.pick_engine import probability_model as pm
    assert com == pytest.approx(pm.prob_over(2.5, lam), abs=1e-6)


def test_linha_ja_resolvida_nao_vira_pick():
    conv_ok = {"a_favor": 4, "contra": 0, "score": 0.8}
    for direcao, observado, linha, esperado in (
        ("over", 9, 8.5, "ja batida"),
        ("under", 3, 2.5, "ja perdida"),
    ):
        motivos = orchestrator._gates(
            {"familia": "corners", "linha": linha, "direcao": direcao,
             "odd": 1.60, "tem_par": True},
            prob=0.99, valor={"ev": 0.50, "edge": 0.40}, conf={"confidence": 0.90},
            conv=conv_ok, observado=observado, linha=linha, direcao=direcao,
            fresh={"nivel": live_state.FRESH}, config=CONFIG)
        assert any(esperado in m for m in motivos)


# ═════════════════════════════════════════════════════════════════════════
# 3 · TETO DE API
# ═════════════════════════════════════════════════════════════════════════
class RespostaFalsa:
    def __init__(self, itens=None):
        self._itens = itens if itens is not None else [{"ok": True}]
    def raise_for_status(self): pass
    def json(self): return {"response": self._itens}


def test_orcamento_bloqueia_a_chamada_seguinte(monkeypatch):
    feed = LiveFeed(limite_requisicoes=2)
    chamadas = {"n": 0}

    def get_falso(*a, **kw):
        chamadas["n"] += 1
        return RespostaFalsa()

    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")
    monkeypatch.setattr("services.pick_engine_live.live_feed.requests.get", get_falso)

    feed.estatisticas(1)
    feed.estatisticas(2)
    assert (feed.usadas, feed.restantes) == (2, 0)
    with pytest.raises(OrcamentoEsgotado):
        feed.estatisticas(3)
    assert chamadas["n"] == 2  # a terceira NAO saiu pela rede


def test_repeticao_na_mesma_rodada_nao_gasta_requisicao(monkeypatch):
    feed = LiveFeed(limite_requisicoes=5)
    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")
    monkeypatch.setattr("services.pick_engine_live.live_feed.requests.get",
                        lambda *a, **kw: RespostaFalsa([]))
    feed.estatisticas(99)
    feed.estatisticas(99)
    assert feed.usadas == 1


def test_falha_de_rede_consome_orcamento(monkeypatch):
    """Chamada que estourou timeout gastou cota da conta do mesmo jeito."""
    feed = LiveFeed(limite_requisicoes=3)
    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")

    def explode(*a, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr("services.pick_engine_live.live_feed.requests.get", explode)
    assert feed.estatisticas(1) == []
    assert feed.usadas == 1


def test_sem_chave_de_api_nao_ha_chamada_silenciosa(monkeypatch):
    feed = LiveFeed(limite_requisicoes=3)
    monkeypatch.setenv("API_FOOTBALL_KEY", "")
    with pytest.raises(RuntimeError):
        feed._headers()


def test_trilha_registra_onde_a_cota_foi(monkeypatch):
    feed = LiveFeed(limite_requisicoes=5)
    monkeypatch.setenv("API_FOOTBALL_KEY", "k")
    monkeypatch.setattr("services.pick_engine_live.live_feed.requests.get",
                        lambda *a, **kw: RespostaFalsa([]))
    feed.partidas_ao_vivo()
    feed.eventos(1)
    endpoints = [t["endpoint"] for t in feed.trilha()]
    assert endpoints == ["fixtures", "fixtures/events"]


# ═════════════════════════════════════════════════════════════════════════
# 4 · LEITURA DA FOLHA
# ═════════════════════════════════════════════════════════════════════════
def test_lado_sai_do_team_id_nao_da_posicao():
    """A API nao garante que o indice 0 seja o mandante."""
    bruto = folha(home={"Corner Kicks": 3}, away={"Corner Kicks": 8})
    bruto.reverse()
    casa, fora = ler_estatisticas(bruto, home_id=10, away_id=20)
    assert (casa["Corner Kicks"], fora["Corner Kicks"]) == (3, 8)


def test_ausencia_nunca_vira_zero():
    """Invariante 1 do settlement. Ao vivo ela vale ainda mais: zero fabricado
    nao produz so' um resultado errado, produz um PICK errado."""
    casa, fora = ler_estatisticas(
        folha(home={"Corner Kicks": 4}, away={"Total Shots": 9}), 10, 20)
    assert "Corner Kicks" not in fora
    assert total_da_familia(casa, fora, "corners") is None


def test_cartao_vermelho_vale_dois_pontos():
    casa, fora = ler_estatisticas(
        folha(home={"Yellow Cards": 2, "Red Cards": 1},
              away={"Yellow Cards": 1, "Red Cards": 0}), 10, 20)
    assert total_da_familia(casa, fora, "cards") == 2 + 2 + 1


def test_estado_completo_carrega_tudo_que_o_modelo_usa():
    estado = estado_de(minuto=63, hg=1, ag=0)
    assert estado["fixture_id"] == 999
    assert estado["minuto"] == 63
    assert estado["periodo"] == "2o_tempo"
    assert estado["corners_total"] == 9
    assert estado["shots_total"] == 18
    assert estado["shots_on_target_total"] == 6
    assert estado["blocked_shots_total"] == 4
    assert estado["goals_total"] == 1
    assert estado["diferenca_gols"] == 1
    assert estado["possession_home"] == 55
    assert orchestrator.observado_da_familia(estado, "goals") == 1


def test_contador_ausente_deixa_o_total_da_familia_nulo():
    estado = estado_de(home={"Corner Kicks": None})
    assert estado["corners_total"] is None
    assert orchestrator.observado_da_familia(estado, "corners") is None


# ═════════════════════════════════════════════════════════════════════════
# 5 · FRESHNESS
# ═════════════════════════════════════════════════════════════════════════
def test_relogio_congelado_e_stale():
    """Se ha 8 minutos de relogio real o provedor dizia 55' e continua dizendo
    55', o feed travou. Este sinal nao depende de estimativa nenhuma."""
    agora = 1_000_000.0
    estado = estado_de(minuto=55)
    obs = [observacao(55, corners=9, epoch=agora - 8 * 60)]
    f = live_state.freshness(estado, obs, CONFIG, agora_epoch=agora)
    assert f["nivel"] == live_state.STALE
    assert any("parado" in m for m in f["motivos"])


def test_relogio_andando_e_fresh():
    agora = 1_000_000.0
    estado = estado_de(minuto=63)
    obs = [observacao(55, corners=9, epoch=agora - 8 * 60)]
    f = live_state.freshness(estado, obs, CONFIG, agora_epoch=agora)
    assert f["nivel"] == live_state.FRESH


def test_minuto_muito_atras_do_esperado_e_stale():
    """Apito ha 80 minutos de relogio real, provedor dizendo 50'."""
    agora = 1_000_000.0
    estado = estado_de(minuto=50, kickoff=agora - 80 * 60)
    f = live_state.freshness(estado, None, CONFIG, agora_epoch=agora)
    assert f["nivel"] == live_state.STALE
    assert f["atraso_estimado"] > 8


def test_atraso_pequeno_e_apenas_delayed():
    agora = 1_000_000.0
    # 71 min de parede, menos 15 de intervalo = 56 esperado contra 50 reportado
    estado = estado_de(minuto=50, kickoff=agora - 71 * 60)
    f = live_state.freshness(estado, None, CONFIG, agora_epoch=agora)
    assert f["nivel"] == live_state.DELAYED


def test_sem_minuto_a_qualidade_e_desconhecida():
    estado = estado_de(minuto=None)
    f = live_state.freshness(estado, None, CONFIG)
    assert f["nivel"] == live_state.UNKNOWN


def test_folha_vazia_e_stale():
    casa, fora = ler_estatisticas(folha(home={}, away={}), 10, 20)
    estado = live_state.montar_estado(fixture_bruto(60), casa, fora)
    f = live_state.freshness(estado, None, CONFIG)
    assert f["nivel"] == live_state.STALE
    assert f["completude"]["presentes"] == 0


def test_folha_incompleta_e_delayed():
    estado = estado_de(home={"Shots on Goal": None})
    f = live_state.freshness(estado, None, CONFIG)
    assert f["nivel"] == live_state.DELAYED
    assert "Shots on Goal" in f["completude"]["faltando"]


def test_dado_stale_bloqueia_a_analise_antes_de_qualquer_modelo():
    """Ao vivo, decidir sobre um estado que ja mudou nao produz um pick
    impreciso -- produz um pick sobre outra partida."""
    estado = estado_de(minuto=60, home={"Corner Kicks": 8})
    analise = orchestrator.analisar(estado, [], CONFIG,
                                    fresh={"nivel": live_state.STALE,
                                           "motivos": ["feed travado"]})
    tri = orchestrator.triagem(analise, CONFIG)
    assert tri["vale"] is False
    assert "STALE" in tri["motivo"]


# ═════════════════════════════════════════════════════════════════════════
# 6 · PRESSAO
# ═════════════════════════════════════════════════════════════════════════
def test_time_dominante_pontua_mais_que_o_dominado():
    """O exemplo do pedido: 11 finalizacoes, 5 no alvo e 5 escanteios contra
    3 finalizacoes, 1 no alvo e 1 escanteio."""
    casa, fora = ler_estatisticas(folha(
        home={"Total Shots": 11, "Shots on Goal": 5, "Corner Kicks": 5,
              "Ball Possession": 62, "Blocked Shots": 3},
        away={"Total Shots": 3, "Shots on Goal": 1, "Corner Kicks": 1,
              "Ball Possession": 38, "Blocked Shots": 1}), 10, 20)
    p = pressure_model.pressao(casa, fora, minuto=45)
    assert p["home"]["score"] > p["away"]["score"]
    assert p["home"]["nivel"] in (pressure_model.NIVEL_ALTA, pressure_model.NIVEL_MUITO_ALTA)
    assert p["away"]["nivel"] == pressure_model.NIVEL_BAIXA
    assert p["dominancia"] > 0.6


def test_componente_ausente_sai_da_conta_em_vez_de_entrar_como_zero():
    """Ausencia de 'Dangerous Attacks' e' o caso NORMAL na API-Football: o
    campo nao faz parte da resposta padrao de /fixtures/statistics."""
    casa, _ = ler_estatisticas(folha(
        home={"Total Shots": 10, "Shots on Goal": 4, "Corner Kicks": 5}), 10, 20)
    p = pressure_model.pressao_de_um_time(casa, minuto=45, posse=None)
    ausentes = [c["sinal"] for c in p["componentes"] if not c.get("disponivel")]
    assert "dangerous_attacks" in ausentes
    assert "possession" in ausentes
    assert p["score"] is not None
    assert p["peso_coberto"] < 1.0  # renormalizou sobre o que existe


def test_pressao_sem_nenhum_contador_e_indisponivel():
    p = pressure_model.pressao_de_um_time({}, minuto=45, posse=None)
    assert p["score"] is None
    assert "nenhum contador" in p["motivo"]


def test_posse_alta_sozinha_nao_faz_pressao_alta():
    """70% de posse nao e' 70% de pressao. Time que roda a bola atras tem posse
    alta e pressao nenhuma."""
    casa, _ = ler_estatisticas(folha(
        home={"Total Shots": 2, "Shots on Goal": 0, "Corner Kicks": 1,
              "Ball Possession": 70, "Blocked Shots": 0}), 10, 20)
    p = pressure_model.pressao_de_um_time(casa, minuto=60, posse=70)
    assert p["nivel"] == pressure_model.NIVEL_BAIXA


def test_pressao_satura_e_nao_explode_com_outlier():
    casa, _ = ler_estatisticas(folha(
        home={"Total Shots": 40, "Shots on Goal": 25, "Corner Kicks": 20,
              "Ball Possession": 90, "Blocked Shots": 15}), 10, 20)
    p = pressure_model.pressao_de_um_time(casa, minuto=20, posse=90)
    assert p["score"] <= 1.0


# ═════════════════════════════════════════════════════════════════════════
# 7 · RITMO, JANELAS E TENDENCIA
# ═════════════════════════════════════════════════════════════════════════
def test_ritmo_alto_e_baixo_sao_reconhecidos():
    quente = rit.ritmo({"corners_total": 14, "shots_total": 30,
                        "shots_on_target_total": 11, "goals_total": 4}, minuto=60)
    frio = rit.ritmo({"corners_total": 3, "shots_total": 6,
                      "shots_on_target_total": 1, "goals_total": 0}, minuto=60)
    assert quente["score"] > frio["score"]
    assert quente["nivel"] in (rit.RITMO_ALTO, rit.RITMO_MUITO_ALTO)
    assert frio["nivel"] == rit.RITMO_BAIXO


def test_ritmo_sem_contador_nenhum_e_indisponivel():
    r = rit.ritmo({}, minuto=60)
    assert r["score"] is None


def test_janela_mede_o_que_aconteceu_nos_ultimos_minutos():
    obs = [observacao(50, corners=7), observacao(40, corners=5)]
    j = rit.janela(obs, "corners", minuto_atual=60, valor_atual=11, largura=10)
    assert j["eventos"] == 4          # 11 - 7
    assert j["largura_real"] == 10
    assert j["por_minuto"] == pytest.approx(0.4)


def test_sem_leitura_anterior_nao_existe_janela():
    assert rit.janela([], "corners", 60, 11, 10) is None


def test_contador_que_regride_e_correcao_do_provedor():
    obs = [observacao(50, corners=12)]
    assert rit.janela(obs, "corners", 60, 11, 10) is None


def test_tendencia_detecta_aceleracao():
    """0-40' com 2 escanteios, 40-50' com 1, 50-60' com 4. Acelerando."""
    obs = [observacao(50, corners=3), observacao(40, corners=2), observacao(30, corners=1)]
    t = rit.tendencia(obs, "corners", 60, 7, CONFIG)
    assert t["rotulo"] == rit.ACELERANDO
    assert t["variacao"] > 0


def test_tendencia_detecta_desaceleracao():
    """Jogo que teve 6 escanteios entre 40' e 50' e apenas 1 entre 50' e 60'."""
    obs = [observacao(50, corners=10), observacao(40, corners=4), observacao(30, corners=2)]
    t = rit.tendencia(obs, "corners", 60, 11, CONFIG)
    assert t["rotulo"] == rit.DESACELERANDO
    assert t["variacao"] < 0


def test_tendencia_estavel_quando_a_variacao_e_ruido():
    obs = [observacao(50, corners=8), observacao(40, corners=5), observacao(30, corners=2)]
    t = rit.tendencia(obs, "corners", 60, 11, CONFIG)
    assert t["rotulo"] == rit.ESTAVEL


def test_tendencia_indefinida_sem_duas_janelas():
    t = rit.tendencia([observacao(50, corners=7)], "corners", 60, 11, CONFIG)
    assert t["rotulo"] == rit.INDEFINIDA


def test_poucos_eventos_nao_viram_tendencia():
    """1 escanteio de um lado e 0 do outro e' ruido com cara de sinal."""
    obs = [observacao(50, corners=2), observacao(40, corners=2), observacao(30, corners=1)]
    t = rit.tendencia(obs, "corners", 60, 3, CONFIG)
    assert t["rotulo"] == rit.ESTAVEL
    assert "poucos eventos" in t["motivo"]


def test_fator_de_ritmo_e_amortecido_e_tem_teto():
    """4 escanteios em 10 minutos contra taxa estimada de 0.11/min e' 3.6x. O
    fator nao pode ser 3.6 -- escanteio vem em rajada por natureza, e a rajada
    ja esta dentro do acumulado que produziu a taxa."""
    obs = [observacao(50, corners=7)]
    janelas = rit.janelas_recentes(obs, "corners", 60, 11, CONFIG)
    f = rit.fator_de_ritmo(janelas, {"rotulo": rit.ESTAVEL}, 0.11, CONFIG)
    assert f["fator_bruto"] > 3.0
    assert 1.0 < f["fator"] <= rit.RITMO_MAX


def test_janela_vazia_quase_nao_move_o_fator():
    """10 minutos sem escanteio nao e' evidencia de nada: com lambda tipico de
    1.2 por 10 minutos, P(zero) e' ~30% -- acontece em quase um terco das
    janelas de qualquer jogo normal."""
    obs = [observacao(50, corners=3)]
    janelas = rit.janelas_recentes(obs, "corners", 60, 3, CONFIG)
    f = rit.fator_de_ritmo(janelas, {"rotulo": rit.ESTAVEL}, 0.08, CONFIG)
    assert f["janela"]["eventos"] == 0
    assert f["peso_da_janela"] < 0.25      # janela pobre em informacao
    assert f["fator"] > 0.90               # e por isso quase nao pune


def test_janela_cheia_pesa_muito_mais_que_janela_vazia():
    cheia = rit.fator_de_ritmo(
        rit.janelas_recentes([observacao(50, corners=7)], "corners", 60, 11, CONFIG),
        {"rotulo": rit.ESTAVEL}, 0.15, CONFIG)
    vazia = rit.fator_de_ritmo(
        rit.janelas_recentes([observacao(50, corners=7)], "corners", 60, 7, CONFIG),
        {"rotulo": rit.ESTAVEL}, 0.15, CONFIG)
    assert cheia["peso_da_janela"] > vazia["peso_da_janela"] * 2


def test_tendencia_ajusta_o_fator_de_ritmo_na_margem():
    obs = [observacao(50, corners=8)]
    janelas = rit.janelas_recentes(obs, "corners", 60, 11, CONFIG)
    acelerando = rit.fator_de_ritmo(janelas, {"rotulo": rit.ACELERANDO}, 0.15, CONFIG)
    desacelerando = rit.fator_de_ritmo(janelas, {"rotulo": rit.DESACELERANDO}, 0.15, CONFIG)
    assert acelerando["fator"] > desacelerando["fator"]


def test_sem_janela_o_ritmo_e_neutro():
    f = rit.fator_de_ritmo({"principal": None}, {}, 0.15, CONFIG)
    assert f["fator"] == 1.0


# ═════════════════════════════════════════════════════════════════════════
# 8 · EVENTOS
# ═════════════════════════════════════════════════════════════════════════
def eventos_brutos():
    return [
        {"time": {"elapsed": 23}, "type": "Goal", "detail": "Normal Goal",
         "team": {"id": 10, "name": "Casa FC"}, "player": {"name": "Fulano"}},
        {"time": {"elapsed": 41}, "type": "Card", "detail": "Yellow Card",
         "team": {"id": 20, "name": "Fora EC"}, "player": {"name": "Beltrano"}},
        {"time": {"elapsed": 58}, "type": "Card", "detail": "Red Card",
         "team": {"id": 20, "name": "Fora EC"}, "player": {"name": "Sicrano"}},
    ]


def test_eventos_trazem_o_minuto_que_a_folha_nao_tem():
    lidos = live_state.ler_eventos(eventos_brutos(), minuto_atual=65)
    resumo = live_state.resumo_de_eventos(lidos, 65)
    assert resumo["gols"] == 1
    assert resumo["vermelhos"] == 1
    assert resumo["vermelho_minuto"] == 58
    assert resumo["ultimo_gol_minuto"] == 23


def test_evento_recente_e_marcado():
    lidos = live_state.ler_eventos(eventos_brutos(), minuto_atual=65, janela=15)
    recentes = [e["minuto"] for e in lidos if e["recente"]]
    assert recentes == [58]


def test_sem_eventos_o_resumo_diz_que_esta_indisponivel():
    r = live_state.resumo_de_eventos([], 60)
    assert r["disponivel"] is False
    assert r["vermelho_minuto"] is None


def test_expulsao_cedo_pesa_mais_que_expulsao_tarde():
    """Expulsao aos 20' muda 70 minutos de jogo; aos 85' quase nao muda nada.
    E' por isso que o minuto do evento e' lido."""
    estado = estado_de(minuto=86, hg=1, ag=1)
    cedo = rm.ajuste_estado("goals", estado, None, {"vermelho_minuto": 20})
    tarde = rm.ajuste_estado("goals", estado, None, {"vermelho_minuto": 85})
    assert cedo["fator"] > tarde["fator"]


def test_vermelho_sem_minuto_entra_pela_metade():
    """Sem /fixtures/events so' se sabe QUE houve. Metade da informacao falta,
    entao metade do efeito."""
    estado = estado_de(minuto=60, hg=0, ag=0, home={"Red Cards": 1})
    com_minuto = rm.ajuste_estado("goals", estado, None, {"vermelho_minuto": 30})
    sem_minuto = rm.ajuste_estado("goals", estado, None, {})
    assert com_minuto["fator"] > sem_minuto["fator"] > 1.0


# ═════════════════════════════════════════════════════════════════════════
# 9 · MODELO RESIDUAL
# ═════════════════════════════════════════════════════════════════════════
def test_minutos_restantes():
    assert rm.minutos_restantes(63, "2H") == 27
    assert rm.minutos_restantes(45, "HT") == 45
    assert rm.minutos_restantes(None, "2H") is None
    assert rm.minutos_restantes(95, "2H") == 0
    assert rm.minutos_restantes(100, "ET") == 0


def test_amostra_curta_nao_vira_conviccao():
    """Aos 15' com 3 escanteios, a taxa crua projeta 18 no jogo. O
    encolhimento contra o baseline tem que puxar isso pra perto do esperado."""
    taxa = rm.taxa_por_minuto(observado=3, minuto=15, baseline_por_partida=10.0)
    assert taxa["taxa_observada_min"] * 90 == pytest.approx(18.0)
    assert taxa["taxa_estimada_min"] * 90 < 12.5
    assert taxa["peso_observado"] == pytest.approx(15 / (15 + rm.MEIA_CONFIANCA), abs=1e-4)


def test_contagem_de_evento_regride_e_o_modelo_respeita_isso():
    """7 escanteios aos 38' nao projetam o ritmo que vinha.

    Este teste trava a decisao de calibracao de MEIA_CONFIANCA: com o valor
    antigo (30) a projecao dessa partida saia acima de 16 antes de qualquer
    multiplicador, o que e' percentil alto tratado como cenario central.
    """
    taxa = rm.taxa_por_minuto(observado=7, minuto=38, baseline_por_partida=10.4)
    projecao_sem_multiplicadores = 7 + taxa["taxa_estimada_min"] * 52
    assert projecao_sem_multiplicadores < 16.0
    assert taxa["peso_observado"] < 0.50  # o baseline ainda manda aos 38'


def test_o_jogo_pesa_mais_conforme_o_tempo_passa():
    cedo = rm.taxa_por_minuto(2, 15, 10.0)
    tarde = rm.taxa_por_minuto(10, 75, 10.0)
    assert cedo["peso_observado"] < 0.4 < 0.6 < tarde["peso_observado"]


def test_taxa_recusa_dado_ausente():
    assert rm.taxa_por_minuto(None, 60, 10.0) is None
    assert rm.taxa_por_minuto(5, None, 10.0) is None
    assert rm.taxa_por_minuto(5, 0, 10.0) is None


def test_jogo_resolvido_desacelera():
    estado = estado_de(minuto=75, hg=4, ag=0)
    assert rm.ajuste_estado("goals", estado)["fator"] < 1.0


def test_fim_de_jogo_apertado_abre_a_partida():
    estado = estado_de(minuto=78, hg=1, ag=1)
    assert rm.ajuste_estado("goals", estado)["fator"] > 1.0


def test_escanteio_se_concentra_no_fim():
    cedo = rm.ajuste_estado("corners", estado_de(minuto=40, hg=0, ag=0))
    tarde = rm.ajuste_estado("corners", estado_de(minuto=75, hg=0, ag=0))
    assert tarde["fator"] > cedo["fator"]


def test_pressao_alta_sustenta_volume_e_pressao_baixa_regride():
    """E' o termo que distingue '7 escanteios com 12 finalizacoes' de '7
    escanteios com 2 finalizacoes'."""
    estado = estado_de(minuto=60, hg=0, ag=0)
    alta = rm.ajuste_estado("corners", estado, {"total": 0.60, "nivel_total": "ALTA"})
    baixa = rm.ajuste_estado("corners", estado, {"total": 0.15, "nivel_total": "BAIXA"})
    assert alta["fator"] > baixa["fator"]


def test_ajuste_de_estado_tem_teto_dos_dois_lados():
    estado = estado_de(minuto=88, hg=1, ag=1)
    extremo = rm.ajuste_estado("goals", estado, {"total": 0.99, "nivel_total": "MUITO_ALTA"},
                               {"vermelho_minuto": 5})
    assert extremo["fator"] <= 1.35
    resolvido = rm.ajuste_estado("goals", estado_de(minuto=88, hg=5, ag=0),
                                 {"total": 0.05, "nivel_total": "BAIXA"})
    assert resolvido["fator"] >= 0.75


def test_lambda_residual_encadeia_tudo_e_deixa_rastro():
    lam = rm.lambda_residual(
        familia="corners", observado=7, minuto=60, status="2H",
        baseline_por_partida=10.0,
        fator_ritmo={"fator": 1.2}, ajuste={"fator": 1.05, "componentes": []})
    assert lam["minutos_restantes"] == 30
    assert lam["lambda_residual"] > 0
    assert lam["projecao_total"] == pytest.approx(7 + lam["lambda_residual"], abs=0.01)
    for chave in ("taxa_observada_min", "taxa_baseline_min", "peso_observado",
                  "taxa_estimada_min", "ritmo", "estado", "lambda_residual"):
        assert chave in lam


def test_lambda_nao_existe_com_o_jogo_acabado():
    assert rm.lambda_residual("goals", 2, 92, "2H", 2.7) is None


# ═════════════════════════════════════════════════════════════════════════
# 10 · CONVERGENCIA E CONFIANCA
# ═════════════════════════════════════════════════════════════════════════
def sinais_quentes():
    return {
        "estado": estado_de(minuto=75, hg=1, ag=1),
        "pressao": {"total": 0.62, "nivel_total": "MUITO_ALTA",
                    "home": {"score": 0.7}, "away": {"score": 0.54}},
        "ritmo": {"score": 1.35, "nivel": rit.RITMO_MUITO_ALTO},
        "tendencia": {"rotulo": rit.ACELERANDO, "variacao": 0.5},
        "janelas": {"principal": {"por_minuto": 0.25, "eventos": 3, "largura_real": 12}},
    }


def test_convergencia_alta_sustenta_um_over():
    s = sinais_quentes()
    c = signal_score.convergencia("over", "corners", s["estado"], s["pressao"],
                                  s["ritmo"], s["tendencia"], s["janelas"],
                                  taxa_estimada_min=0.15, config=CONFIG)
    assert c["a_favor"] >= 3
    assert c["contra"] == 0
    assert c["score"] > 0.65
    assert c["convergente"] is True


def test_os_mesmos_sinais_contradizem_um_under():
    """A leitura e' a mesma; o que muda e' o sinal. Um mercado quente sustenta
    Over e contradiz Under."""
    s = sinais_quentes()
    c = signal_score.convergencia("under", "corners", s["estado"], s["pressao"],
                                  s["ritmo"], s["tendencia"], s["janelas"],
                                  taxa_estimada_min=0.15, config=CONFIG)
    assert c["contra"] >= 3
    assert c["score"] < 0.35


def test_sinais_brigando_derrubam_o_score():
    """Ritmo alto mas tendencia desacelerando: e' um Over que ja aconteceu, nao
    um Over que esta acontecendo."""
    s = sinais_quentes()
    misto = signal_score.convergencia(
        "over", "corners", s["estado"], s["pressao"], s["ritmo"],
        {"rotulo": rit.DESACELERANDO, "variacao": -0.6},
        {"principal": {"por_minuto": 0.05, "eventos": 1, "largura_real": 12}},
        taxa_estimada_min=0.15, config=CONFIG)
    limpo = signal_score.convergencia(
        "over", "corners", s["estado"], s["pressao"], s["ritmo"],
        s["tendencia"], s["janelas"], taxa_estimada_min=0.15, config=CONFIG)
    assert misto["score"] < limpo["score"]
    assert misto["contra"] > 0


def test_sinal_indisponivel_nao_conta_como_contra():
    c = signal_score.convergencia("over", "corners", estado_de(minuto=60),
                                  pressao=None, ritmo=None, tendencia=None,
                                  janelas=None, taxa_estimada_min=None, config=CONFIG)
    indisponiveis = [s for s in c["sinais"] if not s["disponivel"]]
    assert len(indisponiveis) >= 3
    assert c["contra"] == 0


def test_xg_acima_do_placar_aponta_mais_gol():
    """xG bem acima dos gols diz que o jogo cria e nao converte, e o que nao
    converteu tende a converter."""
    estado = estado_de(minuto=60, hg=0, ag=0,
                       home={"expected_goals": 1}, away={"expected_goals": 2})
    valor = signal_score._sinal_qualidade_da_chance(estado, "goals")
    assert valor is not None and valor > 0


def test_muitos_bloqueios_apontam_mais_escanteio():
    """Bloqueio vira escanteio com frequencia alta: muitos bloqueios com poucos
    escanteios e' pressao que ainda nao virou contagem."""
    estado = estado_de(minuto=60, home={"Blocked Shots": 8, "Corner Kicks": 2},
                       away={"Blocked Shots": 4, "Corner Kicks": 1})
    valor = signal_score._sinal_qualidade_da_chance(estado, "corners")
    assert valor is not None and valor > 0


def test_divergencia_grande_do_mercado_derruba_a_confianca():
    """Ao vivo, edge enorme quase nunca e' valor encontrado -- e' quase sempre
    o nosso lado olhando uma folha atrasada."""
    conv = {"score": 0.7}
    fresh = {"nivel": live_state.FRESH}
    colado = signal_score.live_confidence(0.60, 0.58, 60, conv, fresh, 1.0)
    distante = signal_score.live_confidence(0.60, 0.30, 60, conv, fresh, 1.0)
    assert colado["confidence"] > distante["confidence"]
    assert distante["A"] == 0.0


def test_dado_atrasado_derruba_a_confianca():
    conv = {"score": 0.7}
    fresco = signal_score.live_confidence(0.62, 0.55, 60, conv,
                                          {"nivel": live_state.FRESH}, 1.0)
    atrasado = signal_score.live_confidence(0.62, 0.55, 60, conv,
                                            {"nivel": live_state.DELAYED}, 1.0)
    assert atrasado["confidence"] < fresco["confidence"]
    assert atrasado["fator_freshness"] < 1.0


def test_convergencia_alta_sobe_a_confianca():
    fresh = {"nivel": live_state.FRESH}
    forte = signal_score.live_confidence(0.62, 0.55, 60, {"score": 0.85}, fresh, 1.0)
    fraca = signal_score.live_confidence(0.62, 0.55, 60, {"score": 0.30}, fresh, 1.0)
    assert forte["confidence"] > fraca["confidence"]


def test_projecao_colada_na_linha_derruba_a_confianca():
    """Projecao colada na linha e' moeda ao ar mesmo com EV positivo: meio
    evento decide."""
    fresh = {"nivel": live_state.FRESH}
    folgada = signal_score.live_confidence(0.62, 0.55, 60, {"score": 0.7}, fresh, 2.5)
    colada = signal_score.live_confidence(0.62, 0.55, 60, {"score": 0.7}, fresh, 0.1)
    assert folgada["confidence"] > colada["confidence"]


def test_confianca_fica_no_intervalo():
    fresh = {"nivel": live_state.FRESH}
    baixa = signal_score.live_confidence(0.01, 0.99, 1, {"score": 0.0}, fresh, 0.0)
    alta = signal_score.live_confidence(0.99, 0.99, 90, {"score": 1.0}, fresh, 5.0)
    assert 0.20 <= baixa["confidence"] <= 0.92
    assert 0.20 <= alta["confidence"] <= 0.92


def test_encolhimento_puxa_o_modelo_para_o_mercado():
    r = rm.encolher_contra_mercado(0.80, 0.50, minuto=15)
    assert 0.50 < r["prob"] < 0.80
    assert r["peso_modelo"] < 0.30


def test_mais_jogo_observado_da_mais_direito_de_discordar():
    assert (rm.encolher_contra_mercado(0.80, 0.50, 75)["prob"]
            > rm.encolher_contra_mercado(0.80, 0.50, 15)["prob"])


def test_sem_mercado_o_modelo_fica_intacto():
    assert rm.encolher_contra_mercado(0.72, None, 60)["prob"] == 0.72


# ═════════════════════════════════════════════════════════════════════════
# 11 · COTACOES AO VIVO
# ═════════════════════════════════════════════════════════════════════════
def test_mercado_suspenso_nao_entra():
    bruto = [mercado("Total Corners", [
        {"value": "Over", "odd": "1.85", "handicap": "9.5", "suspended": True},
        {"value": "Under", "odd": "1.90", "handicap": "9.5", "suspended": False},
    ])]
    assert all(l["direcao"] != "over" for l in live_odds.extrair_linhas(bruto))


def test_par_completo_produz_probabilidade_sem_vig():
    bruto = [mercado("Total Corners", [
        {"value": "Over", "odd": "2.00", "handicap": "9.5", "suspended": False},
        {"value": "Under", "odd": "2.00", "handicap": "9.5", "suspended": False},
    ])]
    linhas = live_odds.extrair_linhas(bruto)
    assert len(linhas) == 2
    for l in linhas:
        assert l["origem_prob_mercado"] == "no_vig"
        assert l["prob_mercado"] == pytest.approx(0.50)
        assert l["tem_par"] is True


def test_linha_de_um_lado_so_e_marcada_como_sem_par():
    bruto = [mercado("Match Goals", [
        {"value": "Over", "odd": "1.75", "handicap": "2.5", "suspended": False}])]
    linhas = live_odds.extrair_linhas(bruto)
    assert len(linhas) == 1
    assert linhas[0]["tem_par"] is False
    assert linhas[0]["origem_prob_mercado"] == "implied"


def test_mercado_de_primeiro_tempo_fica_de_fora():
    bruto = [mercado("1st Half Goals", [
        {"value": "Over", "odd": "1.90", "handicap": "0.5", "suspended": False},
        {"value": "Under", "odd": "1.90", "handicap": "0.5", "suspended": False}])]
    assert live_odds.extrair_linhas(bruto) == []


def test_familia_fora_da_v1_e_ignorada():
    """Chutes continua fora ate' o residual estar medido nas familias atuais.

    O exemplo aqui era "Total Cards", que entrou na V1 em 2026-08-22 · cartao
    e' a unica familia cujo numero ainda chega ao vivo quando a folha de
    estatistica nao vem, e a unica com uma terceira estimativa independente do
    jogo (a media de quem apita). Trocar o exemplo mantem a regra que este
    teste existe pra proteger: familia nao declarada nao vira linha cotada.
    """
    bruto = [mercado("Total Shots", [
        {"value": "Over", "odd": "1.90", "handicap": "22.5", "suspended": False},
        {"value": "Under", "odd": "1.90", "handicap": "22.5", "suspended": False}])]
    assert live_odds.extrair_linhas(bruto) == []


def test_cartao_entrou_na_v1_e_vira_linha():
    """Contrapartida do teste acima · sem ele, tirar cartao da V1 por engano
    passaria despercebido."""
    bruto = [mercado("Total Cards", [
        {"value": "Over", "odd": "1.90", "handicap": "3.5", "suspended": False},
        {"value": "Under", "odd": "1.90", "handicap": "3.5", "suspended": False}])]
    linhas = live_odds.extrair_linhas(bruto)
    assert [l["familia"] for l in linhas] == ["cards", "cards"]


def test_melhor_odd_vence_quando_a_linha_aparece_duas_vezes():
    bruto = [
        mercado("Match Goals", [{"value": "Over", "odd": "1.70", "handicap": "2.5", "suspended": False}]),
        mercado("Over/Under Line", [{"value": "Over", "odd": "1.88", "handicap": "2.5", "suspended": False}]),
    ]
    linhas = live_odds.extrair_linhas(bruto)
    assert len(linhas) == 1 and linhas[0]["odd"] == 1.88


# ═════════════════════════════════════════════════════════════════════════
# 12 · ANALISE E TRIAGEM (a economia de API)
# ═════════════════════════════════════════════════════════════════════════
def analisar_de(minuto=60, corners_home=6, corners_away=5, observacoes=None,
                baselines=None, config=None, **kw):
    cfg = config or LiveEngineConfig(habilitado=True, familias=("corners",))
    estado = estado_de(minuto=minuto,
                       home={"Corner Kicks": corners_home},
                       away={"Corner Kicks": corners_away}, **kw)
    return estado, orchestrator.analisar(
        estado, observacoes or [], cfg,
        baselines or {"corners": 10.0},
        fresh={"nivel": live_state.FRESH, "motivos": []}), cfg


def test_jogo_na_media_nao_gasta_consulta_de_odd():
    """E' a economia central do desenho: partida sem sinal nao custa a
    requisicao mais cara da rodada."""
    _, analise, cfg = analisar_de(minuto=54, corners_home=3, corners_away=3)
    assert orchestrator.triagem(analise, cfg)["vale"] is False


def test_jogo_acelerado_vale_a_consulta():
    _, analise, cfg = analisar_de(minuto=60, corners_home=7, corners_away=4)
    tri = orchestrator.triagem(analise, cfg)
    assert tri["vale"] is True
    assert "corners" in tri["familias"]


def test_fora_da_janela_de_minutos_nao_passa():
    for minuto in (5, 88):
        _, analise, cfg = analisar_de(minuto=minuto)
        tri = orchestrator.triagem(analise, cfg)
        assert tri["vale"] is False


def test_estatistica_ausente_tira_a_familia_da_analise():
    _, analise, cfg = analisar_de(minuto=60, corners_home=None)
    assert analise["familias"]["corners"]["disponivel"] is False
    assert orchestrator.triagem(analise, cfg)["vale"] is False


def test_status_fora_do_jogo_corrente_nao_passa():
    for status in ("NS", "FT", "ET", "PEN"):
        estado = estado_de(minuto=60, status=status)
        analise = orchestrator.analisar(estado, [], CONFIG,
                                        fresh={"nivel": live_state.FRESH})
        assert orchestrator.triagem(analise, CONFIG)["vale"] is False


def test_baseline_do_confronto_tem_prioridade_sobre_o_da_liga():
    _, analise, _ = analisar_de(minuto=60, baselines={"corners": 13.5})
    info = analise["familias"]["corners"]
    assert info["baseline"] == 13.5
    assert info["baseline_origem"] == "liga"


def test_analise_registra_janela_e_tendencia_quando_ha_historico():
    obs = [observacao(50, corners=8), observacao(40, corners=6), observacao(30, corners=3)]
    _, analise, _ = analisar_de(minuto=60, corners_home=7, corners_away=5, observacoes=obs)
    info = analise["familias"]["corners"]
    assert info["janelas"]["principal"] is not None
    assert info["tendencia"]["rotulo"] in (rit.ACELERANDO, rit.DESACELERANDO, rit.ESTAVEL)


# ═════════════════════════════════════════════════════════════════════════
# 13 · GATES
# ═════════════════════════════════════════════════════════════════════════
def entrada_ok(**kw):
    base = {"familia": "corners", "linha": 9.5, "direcao": "over",
            "odd": 1.80, "tem_par": True}
    base.update(kw)
    return base


def gates(entrada, ev=0.10, conf=0.70, observado=7, conv=None, fresh=None, config=CONFIG,
          prob=0.62):
    return orchestrator._gates(
        entrada, prob=prob, valor={"ev": ev, "edge": 0.08},
        conf={"confidence": conf},
        conv=conv or {"a_favor": 4, "contra": 0, "score": 0.75},
        observado=observado, linha=entrada["linha"], direcao=entrada["direcao"],
        fresh=fresh or {"nivel": live_state.FRESH}, config=config)


def test_candidato_bom_passa_em_todos_os_gates():
    assert gates(entrada_ok()) == []


def test_ev_abaixo_do_minimo_reprova():
    assert any("EV" in m for m in gates(entrada_ok(), ev=0.01))


def test_confianca_abaixo_do_minimo_reprova():
    assert any("confianca" in m for m in gates(entrada_ok(), conf=0.30))


def test_odd_fora_da_faixa_reprova():
    assert any("abaixo do minimo" in m for m in gates(entrada_ok(odd=1.15)))
    assert any("acima do teto" in m for m in gates(entrada_ok(odd=9.00)))


def test_linha_sem_par_reprova():
    assert any("sem no-vig" in m for m in gates(entrada_ok(tem_par=False)))


def test_convergencia_fraca_reprova():
    motivos = gates(entrada_ok(), conv={"a_favor": 1, "contra": 0, "score": 0.55})
    assert any("convergencia fraca" in m for m in motivos)


def test_sinais_contraditorios_reprovam():
    motivos = gates(entrada_ok(), conv={"a_favor": 1, "contra": 3, "score": 0.3})
    assert any("contraditorios" in m for m in motivos)


def test_dado_stale_reprova_mesmo_com_ev_bom():
    motivos = gates(entrada_ok(), fresh={"nivel": live_state.STALE})
    assert any("STALE" in m for m in motivos)


def test_gates_reportam_todos_os_motivos_nao_so_o_primeiro():
    motivos = gates(entrada_ok(odd=1.10, tem_par=False), ev=0.001, conf=0.20,
                    conv={"a_favor": 0, "contra": 2, "score": 0.2})
    assert len(motivos) >= 4


def test_melhor_candidato_nao_escolhe_mais_pelo_maior_ev():
    """Ate 2026-08-20 esta funcao devolvia o de maior EV, e este teste travava
    esse comportamento. Ele foi invertido junto com a decisao.

    O motivo esta medido no pre-jogo (pick_engine/config.py, 2026-08-14): nos
    65 picks resolvidos dele, edge de 10-20% acertou 57,1% e edge abaixo de
    10% acertou 71,4%. EV maior anuncia pick PIOR contra mercado liquido,
    porque um EV grande quase sempre e' a probabilidade do modelo otimista, e
    nao a casa errada. O pre-jogo derrubou o peso do edge de 0.25 pra 0.10; o
    motor ao vivo ainda decidia 100% por EV.

    Abaixo, `leitura_boa` tem EV menor e leitura da partida melhor
    (probabilidade e confianca altas, odd baixa = mercado concordando).
    `odd_alta` tem o maior EV entre os aprovados, e o EV dele vem inteiro da
    odd 3.40. E' a forma exata do pior pick real gravado em DEV: goals Under
    1.5 @3.50 com 31% de probabilidade, aprovado por EV, RED."""
    avaliados = [
        {"aprovado": True, "ev": 0.08, "confidence": 0.90, "probability": 0.78,
         "odd": 1.55, "id": "leitura_boa"},
        {"aprovado": True, "ev": 0.15, "confidence": 0.60, "probability": 0.34,
         "odd": 3.40, "id": "odd_alta"},
        {"aprovado": False, "ev": 0.90, "confidence": 0.99, "probability": 0.95,
         "odd": 2.00, "id": "reprovado"},
    ]
    assert orchestrator.melhor_candidato(avaliados)["id"] == "leitura_boa"


def test_probabilidade_baixa_nao_vira_pick_por_causa_da_odd():
    """O piso que nao existia. Os dois picks de DEV que passariam a ser
    barrados: 31,0% @3.50 e 41,4% @2.62, os dois com EV acima do minimo."""
    motivos = gates(entrada_ok(odd=3.50), prob=0.31, ev=0.086, conf=0.62)
    assert any("probabilidade" in m for m in motivos)
    # E o mesmo candidato com leitura de partida decente segue passando.
    assert not any("probabilidade" in m
                   for m in gates(entrada_ok(odd=1.60), prob=0.70, ev=0.12, conf=0.62))


def test_sem_aprovado_nao_ha_pick():
    assert orchestrator.melhor_candidato([{"aprovado": False, "ev": 1.0, "confidence": 1.0}]) is None


# ═════════════════════════════════════════════════════════════════════════
# 14 · PONTA A PONTA (sem rede, sem banco)
# ═════════════════════════════════════════════════════════════════════════
def test_avaliacao_completa_produz_candidato_com_rastro_auditavel():
    obs = [observacao(50, corners=8), observacao(40, corners=6), observacao(30, corners=3)]
    cfg = LiveEngineConfig(habilitado=True, familias=("corners",), ev_minimo=-1.0,
                           confianca_minima=0.0, odd_minima=1.01,
                           sinais_minimos_convergentes=0)
    estado = estado_de(minuto=60, hg=1, ag=1,
                       home={"Corner Kicks": 7}, away={"Corner Kicks": 4})
    analise = orchestrator.analisar(estado, obs, cfg, {"corners": 10.0},
                                    fresh={"nivel": live_state.FRESH})
    tri = orchestrator.triagem(analise, cfg)
    assert tri["vale"]

    cotacoes = live_odds.extrair_linhas([mercado("Total Corners", [
        {"value": "Over", "odd": "1.85", "handicap": "13.5", "suspended": False},
        {"value": "Under", "odd": "1.95", "handicap": "13.5", "suspended": False},
    ])], ("corners",))

    avaliados = orchestrator.avaliar(analise, cotacoes, cfg)
    assert len(avaliados) == 2
    for c in avaliados:
        assert c["observado_na_criacao"] == 11
        assert 0.0 <= c["probability"] <= 1.0
        assert c["live_signal_score"] is not None
        assert c["debug"]["faltam_para_a_linha"] == pytest.approx(2.5)
        assert c["engine_version"] == "live_v1.0.0"
        for bloco in ("lambda", "janelas", "tendencia", "fator_ritmo",
                      "ajuste_estado", "convergencia", "confianca"):
            assert bloco in c["debug"], f"rastro sem {bloco}"


def test_familia_que_nao_passou_na_triagem_nao_gera_candidato():
    cfg = LiveEngineConfig(habilitado=True, familias=("corners",))
    estado, analise, _ = analisar_de(minuto=60, config=cfg)
    cotacoes = live_odds.extrair_linhas([mercado("Match Goals", [
        {"value": "Over", "odd": "1.85", "handicap": "2.5", "suspended": False},
        {"value": "Under", "odd": "1.95", "handicap": "2.5", "suspended": False},
    ])], ("goals",))
    assert orchestrator.avaliar(analise, cotacoes, cfg) == []


def test_engine_debug_responde_por_que_o_motor_criou_o_pick():
    from engine_pipelines import live_pipeline as lp

    obs = [observacao(50, corners=8), observacao(40, corners=6), observacao(30, corners=3)]
    cfg = LiveEngineConfig(habilitado=True, familias=("corners",), ev_minimo=-1.0,
                           confianca_minima=0.0, odd_minima=1.01,
                           sinais_minimos_convergentes=0)
    estado = estado_de(minuto=60, hg=1, ag=1,
                       home={"Corner Kicks": 7}, away={"Corner Kicks": 4})
    analise = orchestrator.analisar(estado, obs, cfg, {"corners": 10.0},
                                    fresh={"nivel": live_state.FRESH})
    tri = orchestrator.triagem(analise, cfg)
    cotacoes = live_odds.extrair_linhas([mercado("Total Corners", [
        {"value": "Over", "odd": "1.85", "handicap": "13.5", "suspended": False},
        {"value": "Under", "odd": "1.95", "handicap": "13.5", "suspended": False},
    ])], ("corners",))
    candidato = orchestrator.avaliar(analise, cotacoes, cfg)[0]

    debug = lp.montar_engine_debug(analise, candidato, cfg)
    for chave in ("baseline", "current_state", "freshness", "pressure", "rhythm",
                  "recent_windows", "trend", "events", "projection", "market",
                  "convergence", "probability", "ev", "confidence", "decision"):
        assert chave in debug, f"engine_debug sem {chave}"
    assert debug["engine_version"] == "live_v1.0.0"

    texto = lp.montar_explicacao(analise, candidato)
    assert "Aos 60'" in texto
    # ACENTUADO: este texto vai pro card, na frente do assinante, num produto
    # 100% em portugues -- e o unico bloco acentuado de live_pipeline.py, que
    # no resto e' comentario e log de terminal. Escrever "Pressao" aqui seria
    # erro de ortografia publicado, nao economia de caractere.
    assert "Pressão ofensiva" in texto
    assert "projeção" in texto.lower()
    # E o nivel vem traduzido, nao a chave crua do motor: "MUITO_ALTA" e' dado,
    # "muito alta" e' prosa (live_pipeline._nivel_pt).
    assert "_" not in texto.split("Pressão ofensiva")[1].split(".")[0]


# ═════════════════════════════════════════════════════════════════════════
# 15 · ANTI-SPAM
# ═════════════════════════════════════════════════════════════════════════
def test_linha_identica_ja_publicada_nao_repete():
    from engine_pipelines import live_pipeline as lp

    anteriores = [{"market_type": "corners", "line": "Over 9.5", "minuto": 40, "status": "ACTIVE"}]
    motivo = lp.ja_existe_pick_equivalente(
        anteriores, {"market_type": "corners", "line": "Over 9.5", "linha": 9.5}, CONFIG)
    assert motivo and "identica" in motivo


def test_linha_vizinha_e_a_mesma_tese_com_outra_roupa():
    from engine_pipelines import live_pipeline as lp

    anteriores = [{"market_type": "corners", "line": "Over 9.5", "minuto": 40, "status": "ACTIVE"}]
    motivo = lp.ja_existe_pick_equivalente(
        anteriores, {"market_type": "corners", "line": "Over 10.5", "linha": 10.5}, CONFIG)
    assert motivo and "vizinha" in motivo


def test_mercado_diferente_no_mesmo_jogo_e_permitido():
    from engine_pipelines import live_pipeline as lp

    anteriores = [{"market_type": "corners", "line": "Over 9.5", "minuto": 40, "status": "ACTIVE"}]
    assert lp.ja_existe_pick_equivalente(
        anteriores, {"market_type": "goals", "line": "Over 2.5", "linha": 2.5}, CONFIG) is None


def test_a_trava_de_duplicata_esta_no_banco_e_no_insert():
    """Check em Python e' select-then-insert e nao pega duas execucoes
    concorrentes -- foi assim que a multipla duplicou em 2026-07-25."""
    import inspect
    from engine_pipelines import live_pipeline

    fonte = inspect.getsource(live_pipeline)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_picks_live_unico" in fonte
    assert "ON CONFLICT (fixture_id, market_type, line, minute_at_creation) DO NOTHING" in fonte


def test_indices_pedidos_existem():
    import inspect
    from engine_pipelines import live_pipeline

    fonte = inspect.getsource(live_pipeline.criar_tabelas)
    for indice in ("idx_picks_live_fixture", "idx_picks_live_status",
                   "idx_picks_live_criacao", "idx_picks_live_pendentes",
                   "idx_picks_live_mercado"):
        assert indice in fonte, f"falta o indice {indice}"


# ═════════════════════════════════════════════════════════════════════════
# 16 · EXPIRACAO E ESTATISTICA SEPARADA
# ═════════════════════════════════════════════════════════════════════════
def test_expiracao_nunca_toca_pick_que_alguem_seguiu():
    """Pick seguido virou aposta real, e aposta real e' liquidada pelo jogo,
    nao pelo relogio da odd."""
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp.expirar_vencidos)
    assert "NOT EXISTS" in fonte
    assert "user_followed_picks" in fonte
    assert "result IS NULL" in fonte


def test_expirado_entra_no_denominador_de_acerto():
    """DECISAO REVISADA EM 2026-08-13, e o motivo importa.

    A versao anterior deste teste travava o contrario ("EXPIRED fica FORA do
    denominador"), com o argumento de que EXPIRED nao e' RED e conta-lo como
    derrota inventaria erro que nunca existiu. O argumento partia de uma
    premissa que o codigo nao sustenta: pick expirado NAO fica sem resultado.
    `liquidar_pendentes` busca ACTIVE **e** EXPIRED (STATUS_ATIVO,
    STATUS_EXPIRADO na consulta), entao ele e' liquidado pelo jogo como
    qualquer outro e ganha um GREEN ou RED de verdade.

    O que expirou foi o PRECO, nao o pick. Deixar de fora o que ninguem seguiu
    mediria a taxa de acerto so' no que o usuario teve tempo de pegar, que e'
    outra coisa -- e sempre mais bonita que a do motor.

    Ver o comentario longo em routers/live_picks.py::estatisticas.
    """
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp.estatisticas)
    assert "FILTER (WHERE result IS NOT NULL) AS resolvidos" in fonte
    assert "FILTER (WHERE status = 'EXPIRED')" not in fonte, \
        "voltou a filtrar acerto por status: pick nao seguido sumiria da conta"


def test_expirados_conta_por_motivo_e_nao_por_status():
    """`expirados` e' metrica de OPERACAO (quantas janelas de odd fecharam
    antes de alguem pegar), e por isso conta `expiration_reason`.

    Contar por `status` fazia o numero DIMINUIR sozinho ao longo da noite: a
    liquidacao troca o status pra SETTLED, entao um pick que de fato expirou
    parava de ser contado assim que o jogo acabava. O motivo da expiracao fica
    gravado pra sempre; o status, nao.
    """
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp.estatisticas)
    assert "expiration_reason IS NOT NULL" in fonte


def test_liquidacao_alcanca_o_pick_expirado():
    """A premissa do teste acima, verificada na fonte em vez de assumida: se
    a liquidacao parar de buscar EXPIRED, o pick nao seguido volta a ficar sem
    `result` e some do denominador pela porta dos fundos, sem ninguem mexer em
    estatisticas()."""
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp.liquidar_pendentes)
    assert "STATUS_ATIVO, STATUS_EXPIRADO" in fonte


def test_vocabulario_de_resultado_e_o_do_settlement():
    """Nao inventar VOID nem CANCELLED: `status` fala de ciclo de vida e
    `result` fala a lingua do settlement."""
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp)
    assert "VOID" not in fonte and "CANCELLED" not in fonte
    assert lp.STATUS_ATIVO == "ACTIVE"
    assert lp.STATUS_EXPIRADO == "EXPIRED"
    assert lp.STATUS_LIQUIDADO == "SETTLED"


# ═════════════════════════════════════════════════════════════════════════
# 17 · SEGURANCA E AMBIENTE
# ═════════════════════════════════════════════════════════════════════════
def test_motor_recusa_rodar_fora_de_dev(monkeypatch):
    monkeypatch.delenv("LIVE_ENGINE_ALLOW_PROD", raising=False)
    for valor in ("prod", "", "producao"):
        monkeypatch.setenv("DB_ENV", valor)
        with pytest.raises(AmbienteInvalido):
            exigir_ambiente_dev()


def test_motor_aceita_dev(monkeypatch):
    monkeypatch.delenv("LIVE_ENGINE_ALLOW_PROD", raising=False)
    monkeypatch.setenv("DB_ENV", "dev")
    exigir_ambiente_dev()


def test_valvula_de_escape_e_explicita(monkeypatch):
    monkeypatch.setenv("DB_ENV", "prod")
    monkeypatch.setenv("LIVE_ENGINE_ALLOW_PROD", "true")
    exigir_ambiente_dev()


def test_defaults_sao_o_lado_seguro(monkeypatch):
    for var in ("LIVE_ENGINE_ENABLED", "LIVE_ENGINE_DRY_RUN", "LIVE_AI_REVIEW",
                "LIVE_MAX_MATCHES", "LIVE_MAX_API_REQUESTS_PER_RUN", "LIVE_LEAGUES",
                "LIVE_FETCH_EVENTS"):
        monkeypatch.delenv(var, raising=False)
    c = LiveEngineConfig.do_ambiente()
    assert c.habilitado is False   # nao gera pick sem alguem ligar
    assert c.dry_run is True       # nao grava sem alguem desligar o dry run
    assert c.ai_review is False    # nao gasta token na V1
    assert (c.max_partidas, c.max_requisicoes) == (3, 15)


def test_config_le_o_ambiente(monkeypatch):
    monkeypatch.setenv("LIVE_ENGINE_ENABLED", "true")
    monkeypatch.setenv("LIVE_ENGINE_DRY_RUN", "false")
    monkeypatch.setenv("LIVE_MAX_MATCHES", "5")
    monkeypatch.setenv("LIVE_MAX_API_REQUESTS_PER_RUN", "40")
    monkeypatch.setenv("LIVE_MINUTE_START", "20")
    monkeypatch.setenv("LIVE_MINUTE_END", "75")
    monkeypatch.setenv("LIVE_LEAGUES", "71,72")
    monkeypatch.setenv("LIVE_FETCH_EVENTS", "false")
    c = LiveEngineConfig.do_ambiente()
    assert (c.habilitado, c.dry_run) == (True, False)
    assert (c.max_partidas, c.max_requisicoes) == (5, 40)
    assert (c.minuto_inicial, c.minuto_final) == (20, 75)
    assert c.ligas_permitidas == (71, 72)
    assert c.buscar_eventos is False


def test_ia_generativa_esta_desligada_na_v1():
    assert LiveEngineConfig().ai_review is False


# ═════════════════════════════════════════════════════════════════════════
# 18 · AUTORIZACAO DE DISPARO (o botao do /admin)
# ═════════════════════════════════════════════════════════════════════════
def test_disparo_nao_exige_baixar_app_env(monkeypatch):
    """APP_ENV controla a flag `Secure` do cookie de sessao (auth_utils.py:59
    e :86). Se a autorizacao do motor dependesse dele, liberar o botao num
    servico exposto na internet tiraria o Secure do cookie de autenticacao de
    todo mundo naquele dominio.

    Por isso a autorizacao e' flag PROPRIA -- mesmo padrao de SIDE_EFFECTS=off,
    que separa staging de producao sem mexer em APP_ENV.
    """
    import routers.live_picks as lp

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("LIVE_ENGINE_ALLOW_RUN", raising=False)
    autorizado, motivo = lp._pode_disparar()
    assert autorizado is False
    assert "LIVE_ENGINE_ALLOW_RUN" in motivo
    assert "APP_ENV" in motivo  # o motivo avisa pra NAO baixar APP_ENV

    monkeypatch.setenv("LIVE_ENGINE_ALLOW_RUN", "true")
    assert lp._pode_disparar()[0] is True


def test_fora_de_producao_o_disparo_e_liberado_sem_flag(monkeypatch):
    import routers.live_picks as lp

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("LIVE_ENGINE_ALLOW_RUN", raising=False)
    assert lp._pode_disparar()[0] is True


def test_credenciais_dev_nunca_sao_fabricadas_a_partir_de_db_host(monkeypatch):
    """Mesma decisao de routers/admin.py::_dev_env, e pelo mesmo motivo:
    DB_HOST neste processo pode apontar pra producao. Fabricar credencial
    "de dev" a partir dele criaria o caminho em que o motor grava pick na base
    errada acreditando que e' DEV."""
    import routers.live_picks as lp

    monkeypatch.setenv("DB_HOST", "host-de-producao")
    for chave in lp._CHAVES_DEV:
        monkeypatch.delenv(chave, raising=False)
    faltando = lp._dev_configurado()
    assert set(faltando) == set(lp._CHAVES_DEV)

    for chave in lp._CHAVES_DEV:
        monkeypatch.setenv(chave, "valor")
    assert lp._dev_configurado() == []


def test_diagnostico_lista_todas_as_precondicoes():
    """Seis condicoes independentes. Sem o diagnostico, descobrir qual falhou
    num ambiente remoto exige ler log de subprocesso."""
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp.diagnostico)
    for item in ("motor habilitado", "disparo autorizado", "credenciais _DEV",
                 "codigo do motor", "chave da API-Football", "tabela picks_live"):
        assert item in fonte, f"diagnostico nao cobre: {item}"


# ═════════════════════════════════════════════════════════════════════════
# 19 · ACOMPANHAMENTO AO VIVO (engine_pipelines/live_watch.py)
# ═════════════════════════════════════════════════════════════════════════
def _live_watch(monkeypatch):
    """Importa o supervisor com o ambiente limpo.

    O modulo crava DB_ENV=dev no IMPORT, de proposito -- e' o que garante que
    nenhuma rodada do laco alcance producao. Limpar as variaveis antes do
    primeiro import mantem a coleta do pytest previsivel numa maquina que por
    acaso tenha DB_ENV=prod exportado.
    """
    monkeypatch.delenv("DB_ENV", raising=False)
    monkeypatch.delenv("LIVE_ENGINE_ALLOW_PROD", raising=False)
    import engine_pipelines.live_watch as lw
    return lw


def test_acompanhamento_recusa_banco_que_nao_seja_dev(monkeypatch):
    """Uma rodada manual apontada pro lugar errado e' um erro; um LACO apontado
    pro lugar errado e' o mesmo erro se repetindo a cada 7 minutos sem ninguem
    olhando. Por isso a recusa e' mais dura aqui que em live_pipeline."""
    lw = _live_watch(monkeypatch)

    monkeypatch.setenv("DB_ENV", "prod")
    with pytest.raises(SystemExit) as erro:
        lw._cravar_dev()
    assert "DEV" in str(erro.value)


def test_acompanhamento_recusa_a_valvula_de_producao(monkeypatch):
    """LIVE_ENGINE_ALLOW_PROD existe pra uma rodada unica consciente
    (config.exigir_ambiente_dev). O laco nao aceita: decisao consciente nao se
    repete sozinha trinta vezes."""
    lw = _live_watch(monkeypatch)

    monkeypatch.setenv("LIVE_ENGINE_ALLOW_PROD", "true")
    with pytest.raises(SystemExit) as erro:
        lw._cravar_dev()
    assert "ALLOW_PROD" in str(erro.value)


def test_acompanhamento_crava_dev_quando_o_ambiente_esta_vazio(monkeypatch):
    """DB_ENV vazia faz get_connection cair no .env.prod. Cravar (em vez de so'
    exigir) e' o que impede a sessao inteira de nascer apontada pra producao
    por uma variavel esquecida."""
    lw = _live_watch(monkeypatch)

    monkeypatch.delenv("DB_ENV", raising=False)
    lw._cravar_dev()
    assert os.environ["DB_ENV"] == "dev"


def test_sessao_para_quando_o_orcamento_acaba(monkeypatch):
    lw = _live_watch(monkeypatch)
    sessao = {"rodadas": 3, "requisicoes": 120}

    assert lw._motivo_de_parada(sessao, 120, None, 40) is not None
    assert lw._motivo_de_parada(sessao, 200, None, 40) is None
    assert lw._motivo_de_parada(sessao, 200, None, 3) is not None


def test_sessao_para_antes_de_dormir_quando_a_espera_passaria_do_horario(monkeypatch):
    """A parada e' avaliada com a espera INCLUIDA. Sem isso a sessao dorme 7
    minutos pra so' entao descobrir que ja tinha acabado, e o resumo chega
    depois do apito final."""
    lw = _live_watch(monkeypatch)
    sessao = {"rodadas": 1, "requisicoes": 10}
    ate = lw._agora() + timedelta(minutes=5)

    assert lw._motivo_de_parada(sessao, 300, ate, 40, espera_min=0) is None
    assert lw._motivo_de_parada(sessao, 300, ate, 40, espera_min=7) is not None


def test_horario_de_parada_no_passado_significa_amanha(monkeypatch):
    """`--ate 00:30` num jogo que comeca 22:00 tem que significar a madrugada
    seguinte, nao uma sessao que encerra antes de comecar."""
    lw = _live_watch(monkeypatch)

    agora = lw._agora()
    passado = (agora - timedelta(hours=1)).strftime("%H:%M")
    assert lw._hora(passado) > agora
    assert lw._hora(None) is None


# ═════════════════════════════════════════════════════════════════════════
# 5 · JANELA DO FEED (2026-08-16)
# ═════════════════════════════════════════════════════════════════════════
def test_feed_tem_janela_parametrizavel_com_default_de_um_dia():
    """O painel do admin e a aba publica fazem perguntas diferentes ao mesmo
    endpoint.

    Publica: "o que esta acontecendo" -- hoje e ontem basta, e por isso o
    default NAO pode mudar. Admin: "o motor esta acertando" -- e essa nao cabe
    em dois dias.

    O sintoma que motivou isto: /stats nao tem filtro de data nenhum, entao o
    painel dizia "5 resolvidos, 2 greens" com uma lista de 2 picks logo abaixo,
    escondendo as 3 que formaram o numero.
    """
    import inspect
    import routers.live_picks as lp

    assinatura = inspect.signature(lp.feed)
    assert "dias" in assinatura.parameters, "feed precisa aceitar a janela"
    assert assinatura.parameters["dias"].default.default == 1, (
        "o default do feed e' o comportamento da aba publica e nao pode mudar")

    fonte = inspect.getsource(lp.feed)
    assert "INTERVAL '1 day'" in fonte
    assert "- (%s * INTERVAL '1 day')" in fonte, (
        "a janela tem que ser parametrizada; hardcoded volta a esconder historico")


def test_stats_do_live_nao_tem_filtro_de_data():
    """A contraparte do teste acima: as estatisticas descrevem o historico
    INTEIRO de proposito. Se um filtro de data entrar aqui sem entrar no feed
    (ou vice-versa), o painel volta a se contradizer na mesma tela."""
    import inspect
    import routers.live_picks as lp

    fonte = inspect.getsource(lp.estatisticas)
    assert "INTERVAL" not in fonte
    assert "match_date >=" not in fonte
