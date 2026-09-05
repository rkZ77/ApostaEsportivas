# -*- coding: utf-8 -*-
"""Tres defeitos do motor ao vivo achados na rodada de 2026-09-05.

O LOG QUE ORIGINOU ESTE ARQUIVO
-------------------------------
Uma rodada real: 269 fixtures encontradas, 3 elegiveis, 0 picks. As tres
partidas morreram, e duas das tres mortes eram do motor e nao do jogo.

    [1] Fiorentina x Torino   minuto 45   STALE "18 min atras do esperado"
    [2] Hoffenheim x Dortmund minuto 34   "0 linha(s) ativa(s)"
    [3] Leverkusen x Union    minuto 34   "0 linha(s) ativa(s)"
    Requisicoes usadas: 9/15

Os tres numeros dessa ultima linha estao errados, e cada bloco abaixo prova
um deles.

1 · O INTERVALO ERA LIDO COMO FEED TRAVADO
------------------------------------------
Fiorentina estava em HT. `freshness` descontava os 15 minutos de intervalo
quando o status era 2H/ET/BT/P ou o minuto passava de 45 -- e "HT" nao estava
na lista, e `45 > 45` e' falso. Resultado: 63 minutos de relogio de parede
contra os 45 do provedor viravam 18 minutos de atraso, STALE, partida
descartada.

O intervalo e' o melhor momento do jogo pro motor (folha do 1o tempo completa,
odd ainda aberta) e estava sendo jogado fora por construcao.

2 · TODO 2o TEMPO CARREGAVA O ACRESCIMO DO 1o COMO ATRASO
---------------------------------------------------------
Aritmetica, nao suposicao: aos 80' do 2o tempo o relogio de parede marca
45 + s1 + 15 + 35, onde s1 e' o acrescimo do primeiro tempo. `esperado -
minuto` da' exatamente s1. Com `atraso_maximo_minutos = 4`, qualquer jogo com
4+ minutos de acrescimo no 1o tempo virava DELAYED sem nada ter acontecido.

3 · O H2H GASTAVA 7 REQUISICOES INVISIVEIS POR PARTIDA
-------------------------------------------------------
`Requisicoes usadas: 9/15` contava so' o que passa por `LiveFeed`. O
`[CONTEXT_GATE] H2H via API` de cada partida sai por `h2h_api_fetcher`, que
tem cliente HTTP proprio: 1 chamada de H2H mais 1 de `/fixtures/statistics`
POR JOGO devolvido (H2H_LIMIT = 6). Sao 7 por partida, 21 na rodada -- o teto
rigido de 15 nunca poderia conte-las, porque nao as enxerga.

E eram compradas pra nada: a folha de cada confronto tem UM consumidor,
`rivalry_model`, que devolve "desconhecido" antes de olhar a media quando nao
ha baseline de cartoes -- e o Live passa `convergencia_cartoes=None` de
proposito.
"""
import pytest

from services.pick_engine_live import live_state
from services.pick_engine_live.live_state import DELAYED, FRESH, STALE


# Folha completa: isola a checagem de minuto da checagem de completude, que
# senao rebaixaria tudo pra DELAYED e esconderia o que estes testes medem.
_FOLHA = {"Total Shots": 8, "Shots on Goal": 3, "Corner Kicks": 4}

_APITO = 1_757_000_000.0


def _estado(minuto, status, **kw):
    base = {"minuto": minuto, "status": status, "kickoff_epoch": _APITO,
            "_folha_home": dict(_FOLHA), "_folha_away": dict(_FOLHA)}
    base.update(kw)
    return base


# ───────────────────── 1 · o intervalo nao e' atraso ──────────────────────
def test_intervalo_no_minuto_45_nao_vira_stale():
    """O caso Fiorentina, com os numeros do log: 63 min de parede, minuto 45."""
    fresh = live_state.freshness(_estado(45, "HT"),
                                 agora_epoch=_APITO + 63 * 60)
    assert fresh["nivel"] == FRESH
    assert not fresh["motivos"]


def test_intervalo_longo_continua_fresh():
    """Intervalo esticado (VAR, protocolo medico) nao muda o diagnostico: o
    relogio do jogo esta parado por desenho, nao por falha do feed."""
    fresh = live_state.freshness(_estado(45, "HT"),
                                 agora_epoch=_APITO + 75 * 60)
    assert fresh["nivel"] == FRESH


def test_relogio_parado_no_intervalo_nao_acusa_feed_travado():
    """A outra metade da correcao. Corrigir so' o minuto esperado nao bastava:
    a checagem 1 procura exatamente a assinatura do intervalo -- minuto que
    nao avanca enquanto o relogio de parede anda -- e reprovaria a partida
    pelo mesmo motivo, com outra frase."""
    anterior = [{"minuto": 45, "epoch": _APITO + 47 * 60}]
    fresh = live_state.freshness(_estado(45, "HT"), observacoes=anterior,
                                 agora_epoch=_APITO + 58 * 60)
    assert fresh["nivel"] == FRESH
    assert fresh["relogio_congelado_min"] is None


def test_feed_travado_no_1o_tempo_continua_sendo_stale():
    """A guarda vale so' pros status de relogio parado. Em jogo correndo, o
    minuto que nao anda continua sendo o sinal mais forte que existe."""
    anterior = [{"minuto": 30, "epoch": _APITO + 30 * 60}]
    fresh = live_state.freshness(_estado(30, "1H"), observacoes=anterior,
                                 agora_epoch=_APITO + 39 * 60)
    assert fresh["nivel"] == STALE
    assert fresh["relogio_congelado_min"] == 9.0


# ───────────────── 2 · o acrescimo do 1o tempo nao e' atraso ───────────────
def test_acrescimo_do_primeiro_tempo_nao_rebaixa_o_segundo():
    """Aos 60' do 2o tempo com 3 minutos de acrescimo no 1o, o relogio de
    parede marca 45+3+15+15 = 78. O atraso aparente e' 3 e nao ha nada de
    errado com o feed."""
    fresh = live_state.freshness(_estado(60, "2H"),
                                 agora_epoch=_APITO + 78 * 60)
    assert fresh["nivel"] == FRESH
    # O numero cru continua no rastro -- e' ele que permite calibrar a
    # tolerancia contra jogo real depois.
    assert fresh["atraso_estimado"] == 3.0


def test_segundo_tempo_realmente_atrasado_ainda_e_stale():
    """A tolerancia nao pode virar cegueira: 20 minutos de defasagem sao
    outra partida, com ou sem acrescimo."""
    fresh = live_state.freshness(_estado(50, "2H"),
                                 agora_epoch=_APITO + 85 * 60)
    assert fresh["nivel"] == STALE


def test_atraso_intermediario_no_segundo_tempo_e_delayed():
    """Entre a tolerancia e o dobro dela: nao bloqueia, mas entra na
    confianca."""
    fresh = live_state.freshness(_estado(50, "2H"),
                                 agora_epoch=_APITO + 75 * 60)
    assert fresh["nivel"] == DELAYED


def test_primeiro_tempo_nao_ganha_tolerancia():
    """A tolerancia existe por causa do intervalo que ja' passou. No 1o tempo
    nao ha acrescimo anterior nenhum, e o limiar continua sendo o de sempre."""
    fresh = live_state.freshness(_estado(30, "1H"),
                                 agora_epoch=_APITO + 36 * 60)
    assert fresh["nivel"] == DELAYED


# ─────────────── 3 · a folha do H2H so' e' comprada com consumidor ──────────
class _Resposta:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _um_confronto(fid):
    return {
        "fixture": {"id": fid, "date": "2026-03-01T20:00:00+00:00",
                    "status": {"short": "FT"}},
        "league": {"id": 39},
        "teams": {"home": {"id": 1}, "away": {"id": 2}},
        "goals": {"home": 2, "away": 1},
    }


@pytest.fixture
def api(monkeypatch):
    """Substitui a rede e registra CADA url chamada, que e' o que estes testes
    medem -- o numero de requisicoes, nao o conteudo delas."""
    from services import h2h_api_fetcher

    chamadas = []

    def _get(url, headers=None, params=None, timeout=None):
        chamadas.append(url)
        if "headtohead" in url:
            return _Resposta({"response": [_um_confronto(100 + i) for i in range(6)]})
        return _Resposta({"response": [
            {"team": {"id": 1}, "statistics": [{"type": "Yellow Cards", "value": 2}]},
            {"team": {"id": 2}, "statistics": [{"type": "Yellow Cards", "value": 3}]},
        ]})

    monkeypatch.setattr(h2h_api_fetcher.requests, "get", _get)
    monkeypatch.setattr(h2h_api_fetcher, "_API_KEY", "chave-de-teste")
    monkeypatch.setattr(h2h_api_fetcher, "_cache", {})
    h2h_api_fetcher.zerar_contador()
    return chamadas


def test_sem_folha_o_h2h_custa_uma_requisicao(api):
    """Era 7. O caminho ao vivo passa por aqui uma vez por partida
    analisada."""
    from services import h2h_api_fetcher

    jogos = h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=False)
    assert len(jogos) == 6
    assert len(api) == 1
    assert h2h_api_fetcher.requisicoes_feitas() == 1


def test_sem_folha_os_campos_de_estatistica_ficam_none(api):
    """None e' ausencia de leitura, nunca zero. Um 0 fabricado aqui viraria
    'confronto friissimo' no rivalry_model."""
    from services import h2h_api_fetcher

    jogos = h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=False)
    assert jogos[0]["total_yellow_cards"] is None
    assert jogos[0]["total_corners"] is None
    # O que NAO depende da folha continua vindo: e' disto que o
    # match_context_model precisa pra achar o jogo de ida.
    assert jogos[0]["total_goals"] == 3
    assert jogos[0]["match_date"] == "2026-03-01"


def test_com_folha_o_custo_continua_sendo_um_por_jogo(api):
    """Quem precisa da folha continua recebendo tudo -- os pipelines de
    pre-jogo passam `convergencia_cartoes` e dependem disso."""
    from services import h2h_api_fetcher

    jogos = h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=True)
    assert h2h_api_fetcher.requisicoes_feitas() == 7
    assert jogos[0]["total_yellow_cards"] == 5


def test_o_par_repetido_nao_paga_de_novo(api):
    """H2H e' fato do passado: nao muda enquanto os dois nao se enfrentarem de
    novo. O `live_watch` roda em laco e repagava o par a cada passada."""
    from services import h2h_api_fetcher

    h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=False)
    h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=False)
    assert h2h_api_fetcher.requisicoes_feitas() == 1


def test_cache_sem_folha_nao_atende_quem_pede_folha(api):
    """A direcao importa: a lista completa serve pra quem quer a magra, o
    contrario devolveria None onde ha numero."""
    from services import h2h_api_fetcher

    h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=False)
    jogos = h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=True)
    assert jogos[0]["total_yellow_cards"] == 5
    assert h2h_api_fetcher.requisicoes_feitas() == 8


def test_cache_com_folha_atende_quem_nao_pede(api):
    from services import h2h_api_fetcher

    h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=True)
    h2h_api_fetcher.get_h2h(1, 2, com_estatisticas=False)
    assert h2h_api_fetcher.requisicoes_feitas() == 7


class _MatchStats:
    """Banco sem H2H, que e' a condicao que dispara a busca na API."""

    def get_h2h_matches(self, a, b, before_date=None):
        return []


_FIXTURE = {"fixture_id": 999, "home_team_id": 1, "away_team_id": 2,
            "league_id": 39, "season": 2026, "round": "Regular Season - 5",
            "match_datetime": "2026-09-05"}


@pytest.fixture
def pedidos(monkeypatch):
    """Registra COMO o context_gate pede o H2H, sem tocar a rede."""
    from services import h2h_api_fetcher

    vistos = []

    def _falso(a, b, before_date=None, com_estatisticas=True):
        vistos.append(com_estatisticas)
        return [dict(_um_confronto(1)["goals"], match_date="2026-03-01",
                     league_id=39, home_team_id=1, away_team_id=2,
                     home_goals=2, away_goals=1, total_goals=3)]

    monkeypatch.setattr(h2h_api_fetcher, "get_h2h", _falso)
    return vistos


def test_sem_baseline_de_cartoes_o_gate_nao_compra_a_folha(pedidos):
    """O caminho do motor ao vivo: ele passa `convergencia_cartoes=None` de
    proposito, e nesse caso `rivalry_signal` responde "desconhecido" antes de
    olhar a media do confronto. Comprar seis folhas ali era comprar pra
    descartar."""
    from services.pick_engine import context_gate

    context_gate.build_for_fixture(_MatchStats(), _FIXTURE,
                                   convergencia_cartoes=None)
    assert pedidos == [False]


def test_com_baseline_de_cartoes_a_folha_continua_vindo(pedidos):
    """O caminho do pre-jogo. A rivalidade e' medida contra este baseline, e
    sem a folha do confronto ela nao existe."""
    from services.pick_engine import context_gate

    context_gate.build_for_fixture(_MatchStats(), _FIXTURE,
                                   convergencia_cartoes={"expected_value": 4.1})
    assert pedidos == [True]


# ────────── 4 · falha de chamada nao pode virar "a casa nao cotou" ──────────
def test_o_feed_devolve_o_erro_da_ultima_chamada_do_endpoint():
    """`_get` engole rede, HTTP e JSON e devolve []. Sem isto o log acusava o
    provedor de nao cotar tanto num 429 quanto numa casa sem mercado -- dois
    diagnosticos com acoes opostas, no unico descarte do motor que gasta
    requisicao."""
    from services.pick_engine_live.live_feed import LiveFeed

    feed = LiveFeed(limite_requisicoes=5)
    feed._trilha.append({"endpoint": "fixtures/statistics", "erro": None})
    feed._trilha.append({"endpoint": "odds/live", "erro": "429 Too Many Requests"})
    assert feed.ultimo_erro("odds/live") == "429 Too Many Requests"
    assert feed.ultimo_erro("fixtures/statistics") is None
    assert feed.ultimo_erro("fixtures/events") is None


def test_chamada_de_odd_bem_sucedida_e_vazia_nao_reporta_erro():
    """A outra metade: mercado realmente nao cotado continua sendo diagnostico
    valido, e nao pode virar alarme de falha."""
    from services.pick_engine_live.live_feed import LiveFeed

    feed = LiveFeed(limite_requisicoes=5)
    feed._trilha.append({"endpoint": "odds/live", "itens": 0, "erro": None})
    assert feed.ultimo_erro("odds/live") is None


# ───── 5 · a divergencia com o mercado e' medida depois do encolhimento ─────
#
# NAO E' UM BUG CORRIGIDO -- e' um vies estrutural MEDIDO e deixado ligado de
# proposito, porque o piso de confianca esta' calibrado contra ele. Estes
# testes prendem as duas coisas: que o vies existe e tem a forma que a nota
# descreve, e que o numero honesto passou a ser gravado.
#
# Ver a nota longa em signal_score.live_confidence e em
# config.confianca_minima. Nos 7 picks de DEV, tres discordavam do mercado em
# ~30 pontos e receberam de 0.39 a 0.55 no termo que existe pra punir isso;
# trocar o termo sozinho derruba 6 dos 7 abaixo do piso.

_CONV = {"score": 0.6, "a_favor": 3, "contra": 0}
_FRESH_OK = {"nivel": FRESH}


def test_a_divergencia_que_pontua_e_a_encolhida():
    """O pick #1 de DEV, com os numeros dele: modelo 0.821, mercado 0.554,
    final 0.645 aos 23'."""
    from services.pick_engine_live import signal_score

    c = signal_score.live_confidence(
        prob_final=0.6447, prob_mercado=0.5544, minuto=23, conv=_CONV,
        fresh=_FRESH_OK, distancia_da_linha=1.0, prob_modelo_puro=0.8214)
    assert c["divergencia_mercado"] == pytest.approx(0.0903, abs=1e-4)
    assert c["A"] == pytest.approx(0.5485, abs=1e-3)


def test_a_divergencia_real_e_gravada_mesmo_sem_pontuar():
    """Sem este numero no rastro, "quanto o modelo discordava de verdade?" nao
    tem resposta, e a recalibracao do piso nunca sai do lugar."""
    from services.pick_engine_live import signal_score

    c = signal_score.live_confidence(
        prob_final=0.6447, prob_mercado=0.5544, minuto=23, conv=_CONV,
        fresh=_FRESH_OK, distancia_da_linha=1.0, prob_modelo_puro=0.8214)
    assert c["divergencia_modelo"] == pytest.approx(0.2670, abs=1e-4)
    # ~30 pontos de desacordo zeram o termo, contra os 0.55 que ele recebeu.
    assert c["A_com_divergencia_real"] == 0.0


def test_o_vies_cresce_quanto_mais_cedo_e_o_minuto():
    """A forma do defeito: a divergencia medida e' a real vezes
    w = minuto/(minuto+45), entao a penalidade e' mais fraca justamente cedo --
    onde a folha e' curta e o mercado esta' mais afiado que o modelo."""
    from services.pick_engine_live import signal_score
    from services.pick_engine_live import residual_model as rm

    for minuto, w_esperado in ((20, 0.308), (75, 0.625)):
        enc = rm.encolher_contra_mercado(0.85, 0.55, minuto)
        c = signal_score.live_confidence(
            prob_final=enc["prob"], prob_mercado=0.55, minuto=minuto,
            conv=_CONV, fresh=_FRESH_OK, prob_modelo_puro=0.85)
        assert enc["peso_modelo"] == pytest.approx(w_esperado, abs=1e-3)
        # A divergencia medida e' exatamente a real encolhida pelo mesmo peso.
        assert c["divergencia_mercado"] == pytest.approx(
            c["divergencia_modelo"] * enc["peso_modelo"], abs=1e-3)


def test_sem_mercado_nao_ha_divergencia_de_nenhum_tipo():
    """Linha sem par nao tem no-vig. O termo cai no neutro e os dois numeros
    ficam nulos -- nenhum deles pode virar 0.0, que seria "concorda em cheio"."""
    from services.pick_engine_live import signal_score

    c = signal_score.live_confidence(
        prob_final=0.7, prob_mercado=None, minuto=40, conv=_CONV,
        fresh=_FRESH_OK, prob_modelo_puro=0.7)
    assert c["A"] == 0.5
    assert c["divergencia_mercado"] is None
    assert c["divergencia_modelo"] is None


# ─────────── 6 · a escolha entre aprovados e' 100% estatistica ─────────────
#
# O pre-jogo removeu o preco do `ranking.final_score` na Fase 5 e deixou a odd
# so' escolhendo a LINHA dentro do mercado ja' decidido. O motor ao vivo fez
# metade do caminho em 20/08 (de 100% EV pra 30% preco) e o resto em 05/09.
#
# 30% nao e' "quase zero": com prob e conf empatadas, 0.20 de seguranca da odd
# mais 0.10 de EV bastavam pra a odd decidir sozinha qual pick sai.

def _aprovado(**kw):
    base = {"aprovado": True, "probability": 0.70, "confidence": 0.70,
            "ev": 0.08, "odd": 2.00}
    base.update(kw)
    return base


def test_odd_nao_desempata_leitura_igual():
    """A prova direta: mesma leitura da partida, odds opostas dentro da faixa.
    Com o score antigo o de odd 1.55 vencia por 0.20 de "seguranca"; agora os
    dois empatam e nenhum preco decide."""
    from services.pick_engine_live import orchestrator as orc

    barato = _aprovado(odd=1.55, id="odd_baixa")
    caro = _aprovado(odd=3.90, ev=0.19, id="odd_alta")
    assert orc.score_de_selecao(barato) == orc.score_de_selecao(caro)


def test_leitura_melhor_vence_mesmo_com_odd_pior():
    """O sentido que importa: quem lê melhor a partida ganha, e a odd nao
    compra posicao."""
    from services.pick_engine_live import orchestrator as orc

    leitura_boa = _aprovado(probability=0.78, confidence=0.88, ev=0.06, odd=3.90)
    leitura_fraca = _aprovado(probability=0.60, confidence=0.62, ev=0.19, odd=1.50)
    escolhido = orc.melhor_candidato([leitura_boa, leitura_fraca])
    assert escolhido is leitura_boa


def test_ev_maior_nao_vence_sozinho():
    """A forma do pior pick real de DEV: goals Under 1.5 @3.50 com 31% de
    probabilidade, aprovado por EV, RED. Hoje ele nem seria aprovado (piso de
    probabilidade), mas a ORDENACAO tambem nao pode preferi-lo."""
    from services.pick_engine_live import orchestrator as orc

    solido = _aprovado(probability=0.76, confidence=0.80, ev=0.07, odd=1.60)
    caro = _aprovado(probability=0.56, confidence=0.60, ev=0.35, odd=3.60)
    assert orc.melhor_candidato([solido, caro]) is solido


def test_o_score_nao_le_odd_nem_ev():
    """Trava estrutural: se alguem reintroduzir um termo de preco, o score
    passa a mudar quando so' a odd muda, e este teste cai."""
    from services.pick_engine_live import orchestrator as orc

    base = _aprovado()
    for odd, ev in ((1.49, 0.05), (2.50, 0.12), (4.00, 0.40)):
        assert orc.score_de_selecao(dict(base, odd=odd, ev=ev)) == \
            orc.score_de_selecao(base)


def test_os_pesos_estatisticos_somam_um():
    """Sem isto, tirar um termo no futuro reescala o score em silencio e o
    piso de qualquer comparacao historica deixa de valer."""
    from services.pick_engine_live import orchestrator as orc

    assert orc.PESO_PROBABILIDADE + orc.PESO_CONFIANCA == pytest.approx(1.0)
    assert not hasattr(orc, "PESO_EV")
    assert not hasattr(orc, "PESO_SEGURANCA_DA_ODD")


# ────────── 7 · a API-Football recusa com HTTP 200 ──────────────────────────
#
# O caso de PROD em 05/09: 211 descartes por "sem linha ativa" e ZERO
# candidatos avaliados no dia inteiro. Os campos do descarte diziam `erro_odd`
# nulo e zero mercados no retorno -- ou seja, exatamente o que uma casa que
# fechou o mercado tambem diria. A diferenca estava em `errors`, no corpo da
# resposta 200, e o motor descartava esse campo.

class _RespostaRecusada:
    status_code = 200
    headers: dict = {}

    def __init__(self, errors):
        self._errors = errors

    def raise_for_status(self):
        return None

    def json(self):
        return {"errors": self._errors, "results": 0, "response": []}


@pytest.fixture
def feed_com_resposta(monkeypatch):
    from services.pick_engine_live import live_feed as lf

    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")

    def montar(payload):
        monkeypatch.setattr(lf.requests, "get",
                            lambda *a, **k: _RespostaRecusada(payload))
        return lf.LiveFeed(limite_requisicoes=5)

    return montar


def test_cota_estourada_vira_erro_e_nao_mercado_vazio(feed_com_resposta):
    """A recusa mais provavel, e a que nao levanta excecao nenhuma."""
    feed = feed_com_resposta(
        {"requests": "You have reached the request limit for the day"})
    assert feed.odds_ao_vivo(123) == []
    erro = feed.ultimo_erro("odds/live")
    assert erro is not None
    assert "HTTP 200" in erro and "request limit" in erro


def test_chave_invalida_tambem_e_recusa(feed_com_resposta):
    feed = feed_com_resposta({"token": "Missing application key"})
    feed.odds_ao_vivo(123)
    assert "Missing application key" in feed.ultimo_erro("odds/live")


def test_resposta_sadia_e_vazia_continua_sem_erro(feed_com_resposta):
    """A outra metade: `errors` vem como LISTA vazia quando esta tudo bem, e
    mercado realmente fechado continua sendo diagnostico valido. Confundir os
    dois na direcao oposta seria trocar um alarme mudo por um alarme falso."""
    feed = feed_com_resposta([])
    assert feed.odds_ao_vivo(123) == []
    assert feed.ultimo_erro("odds/live") is None


# ─────── 8 · odd ao vivo em UMA chamada, como o coletor de pre-jogo ─────────
#
# O coletor de pre-jogo pergunta por (fixture, casa) e mantem `_cobertura`
# pra saber quem respondeu e quem veio vazio -- e' o que faz "a Betano parou de
# cotar" ser uma frase possivel la'. O caminho ao vivo perguntava por fixture e
# nao guardava nada, entao 211 respostas vazias num dia so' nao produziram
# nenhuma conclusao.
#
# `/odds/live` sem `fixture` devolve o mundo inteiro, do mesmo jeito que
# `/fixtures?live=all`. Uma requisicao no lugar de N, e a cobertura vira um
# numero em vez de uma suposicao.

class _RespostaComOdds:
    status_code = 200
    headers: dict = {}

    def __init__(self, paginas: dict, chamadas: list):
        self._paginas = paginas
        self._chamadas = chamadas

    def raise_for_status(self):
        return None


def _feed_do_mundo(monkeypatch, paginas):
    """`paginas` = {numero_da_pagina: [itens]}. Registra cada params usado."""
    from services.pick_engine_live import live_feed as lf

    monkeypatch.setenv("API_FOOTBALL_KEY", "chave-de-teste")
    chamadas = []

    class _R:
        status_code = 200
        headers: dict = {}

        def __init__(self, pagina):
            self.pagina = pagina

        def raise_for_status(self):
            return None

        def json(self):
            return {"errors": [], "response": paginas.get(self.pagina, []),
                    "paging": {"current": self.pagina, "total": len(paginas)}}

    def _get(url, headers=None, params=None, timeout=None):
        chamadas.append(dict(params or {}))
        return _R(int((params or {}).get("page", 1)))

    monkeypatch.setattr(lf.requests, "get", _get)
    return lf.LiveFeed(limite_requisicoes=15), chamadas


def _item(fid, mercados):
    return {"fixture": {"id": fid}, "odds": mercados}


def test_uma_chamada_atende_todas_as_partidas(monkeypatch):
    """O ganho direto: tres partidas, uma requisicao. Antes eram tres."""
    feed, chamadas = _feed_do_mundo(monkeypatch, {1: [
        _item(10, [{"name": "Match Goals"}]),
        _item(20, [{"name": "Total Corners"}]),
        _item(30, []),
    ]})
    assert feed.odds_ao_vivo(10) == [{"name": "Match Goals"}]
    assert feed.odds_ao_vivo(20) == [{"name": "Total Corners"}]
    assert feed.odds_ao_vivo(30) == []
    assert feed.usadas == 1
    assert len(chamadas) == 1


def test_partida_fora_do_mundo_devolve_vazio(monkeypatch):
    """Sem custo extra: se o provedor nao serve aquela partida, a resposta ja'
    esta em memoria."""
    feed, _ = _feed_do_mundo(monkeypatch, {1: [_item(10, [{"name": "Match Goals"}])]})
    assert feed.odds_ao_vivo(999) == []
    assert feed.usadas == 1


def test_a_busca_so_acontece_quando_alguem_pede_preco(monkeypatch):
    """A economia central do motor continua de pe': partida sem sinal nao
    dispara requisicao nenhuma, porque a triagem roda antes."""
    feed, chamadas = _feed_do_mundo(monkeypatch, {1: [_item(10, [])]})
    assert feed.usadas == 0
    assert chamadas == []
    assert feed.cobertura_de_odd_ao_vivo() is None


def test_paginacao_e_seguida_ate_o_total(monkeypatch):
    """O mundo inteiro pode nao caber numa pagina, e parar na primeira faria o
    motor concluir que a partida nao tem mercado."""
    feed, chamadas = _feed_do_mundo(monkeypatch, {
        1: [_item(10, [{"name": "Match Goals"}])],
        2: [_item(20, [{"name": "Total Corners"}])],
    })
    assert feed.odds_ao_vivo(20) == [{"name": "Total Corners"}]
    assert feed.usadas == 2
    assert chamadas[1]["page"] == 2


def test_cobertura_conta_o_que_o_provedor_serve(monkeypatch):
    """O numero que faltava em 05/09: mundo vazio e dia sem oportunidade
    deixam de ser a mesma frase."""
    feed, _ = _feed_do_mundo(monkeypatch, {1: [_item(10, []), _item(20, [])]})
    feed.odds_ao_vivo(10)
    assert feed.cobertura_de_odd_ao_vivo() == {"partidas_com_odd": 2, "erro": None}


def test_mundo_vazio_e_distinguivel_de_partida_sem_mercado(monkeypatch):
    feed, _ = _feed_do_mundo(monkeypatch, {1: []})
    feed.odds_ao_vivo(10)
    assert feed.cobertura_de_odd_ao_vivo()["partidas_com_odd"] == 0
