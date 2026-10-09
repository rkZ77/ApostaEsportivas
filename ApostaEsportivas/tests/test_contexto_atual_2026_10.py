# -*- coding: utf-8 -*-
"""Contexto atual no motor (2026-10-08) -- ver services/pick_engine/contexto_atual.py.

O que estes testes prendem:
  * a matematica: o peso do historico antigo sai da divergencia, e nunca
    afasta a probabilidade do mercado;
  * o tecnico: corte certo pelas escalacoes e pela API, inclusive estreia;
  * desfalques POR MERCADO: gols perde os gols de quem esta' fora, escanteio
    perde so' os minutos;
  * dados atrasados: jogo ja' disputado fora da folha barra a partida em `on`;
  * o motor nos tres modos: `off`/sem contexto identico ao de antes, `shadow`
    so' grava, `on` muda a conta e passa a amostra efetiva pelo piso;
  * o contexto nunca e' o que aprova;
  * revalidacao da linha antes de publicar e reavaliacao perto do apito;
  * o mesmo fato nao pune duas vezes (news_score sai em `on`);
  * nada de futuro: replay nao consulta API e filtra pelo instante.
"""
from datetime import date, datetime

import pytest

from services.pick_engine import analyze_fixture_markets
from services.pick_engine import contexto_atual as ca
from services.pick_engine import ranking, revalidacao, reavaliacao
from services.pick_engine.config import DEFAULT_CONFIG, VIP_CONFIG

CASA, FORA = 100, 200
CALIBRACAO_VAZIA = {"by_market_league": {}, "by_market": {}}


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.delenv("MOTOR_CONTEXTO", raising=False)
    monkeypatch.delenv("MOTOR_CONTEXTO_FATORES", raising=False)
    monkeypatch.setenv("MOTOR_DESFALQUES", "shadow")
    # O teste de motor nao pode chamar a API do tecnico.
    monkeypatch.setenv("MOTOR_CONTEXTO_COACHS", "off")


# ---------------------------------------------------------------------------
# 1. Matematica
# ---------------------------------------------------------------------------
def test_trechos_que_concordam_mantem_o_historico_inteiro():
    a0, z = ca.peso_do_historico_antigo(0.60, 10, 0.62, 20)
    assert a0 == 1.0 and abs(z) < 1


def test_trechos_que_divergem_derrubam_o_peso_do_antigo():
    a0, z = ca.peso_do_historico_antigo(0.10, 10, 0.90, 20)
    assert z < -3 and a0 < 0.15


def test_peso_e_monotono_na_divergencia():
    pesos = [ca.peso_do_historico_antigo(p, 10, 0.7, 20)[0] for p in (0.7, 0.55, 0.4, 0.25)]
    assert pesos == sorted(pesos, reverse=True)


def test_trechos_sem_variancia_concordam():
    assert ca.peso_do_historico_antigo(1.0, 5, 1.0, 10)[0] == 1.0


def test_peso_por_media_detecta_mudanca_de_nivel():
    a0, z = ca.peso_por_media([10, 11, 9, 10, 10], [20, 21, 19, 22, 20, 18, 21])
    assert a0 < 0.1 and z < -5
    assert ca.peso_por_media([20, 21, 19], [20, 21, 19, 22])[0] == 1.0


# ---------------------------------------------------------------------------
# 2. Tecnico
# ---------------------------------------------------------------------------
def test_corte_e_o_dia_seguinte_ao_ultimo_jogo_do_anterior():
    esc = [(date(2026, 10, 5), 2, "Novo", "4-3-3"), (date(2026, 9, 28), 2, "Novo", "4-3-3"),
           (date(2026, 9, 20), 1, "Antigo", "4-4-2"), (date(2026, 9, 13), 1, "Antigo", "4-4-2")]
    r = ca.regime_do_tecnico(esc)
    assert r["jogos_sob_tecnico"] == 2
    assert r["inicio"] == date(2026, 9, 21)
    assert r["anterior"] == "Antigo"
    assert r["formacao"]["mais_usada"] == "4-3-3" and r["formacao_anterior"] == "4-4-2"


def test_sem_troca_nao_ha_corte():
    esc = [(date(2026, 10, d), 1, "Mesmo", None) for d in (5, 1)]
    assert "inicio" not in ca.regime_do_tecnico(esc)


def test_tecnico_que_estreia_hoje_vem_da_api():
    esc = [(date(2026, 10, 5), 1, "Antigo", None), (date(2026, 9, 28), 1, "Antigo", None)]
    r = ca.regime_do_tecnico(esc, {"coach_id": 9, "coach_name": "Novo", "inicio": "2026-10-06"})
    assert r["tecnico"] == "Novo" and r["jogos_sob_tecnico"] == 0 and r["fonte"] == "api"
    assert r["inicio"] == date(2026, 10, 6)


def test_api_do_mesmo_tecnico_so_aperta_o_corte():
    esc = [(date(2026, 10, 5), 2, "Novo", None), (date(2026, 9, 20), 1, "Antigo", None)]
    r = ca.regime_do_tecnico(esc, {"coach_id": 2, "coach_name": "Novo", "inicio": "2020-01-01"})
    assert r["inicio"] == date(2026, 9, 21)     # data velha da API nao recua o corte


def test_tecnico_da_api_pega_a_passagem_aberta_mais_recente():
    resp = [{"id": 1, "name": "Velho", "career": [{"team": {"id": 7}, "start": "2019-01-01", "end": None}]},
            {"id": 2, "name": "Atual", "career": [{"team": {"id": 7}, "start": "2026-09-01", "end": None},
                                                  {"team": {"id": 8}, "start": "2024-01-01", "end": "2026-08-01"}]}]
    assert ca.tecnico_da_api(resp, 7)["coach_name"] == "Atual"


# ---------------------------------------------------------------------------
# 3. Desfalques por mercado
# ---------------------------------------------------------------------------
LINHAS = [  # fixture, jogador, minutos, gols, chutes, no_alvo, cartoes, faltas
    (1, 9, 90, 2, 5, 3, 0, 1), (1, 2, 90, 0, 1, 0, 1, 3), (1, 3, 90, 0, 0, 0, 0, 2),
    (2, 9, 90, 1, 4, 2, 0, 1), (2, 2, 90, 0, 1, 0, 1, 2), (2, 3, 90, 1, 1, 1, 0, 1),
]


def test_gols_perde_os_gols_do_artilheiro_e_escanteio_so_os_minutos():
    prod = ca.producao_perdida(LINHAS, {9})
    gols = ca.fracao_perdida([prod], "goals")
    escanteio = ca.fracao_perdida([prod], "corners")
    assert gols["producao"] == "gols" and gols["fracao"] == pytest.approx(0.75)
    assert escanteio["producao"] == "minutos" and escanteio["fracao"] == pytest.approx(1 / 3, abs=1e-3)


def test_cartao_de_quem_nao_faz_cartao_cai_pros_minutos():
    prod = ca.producao_perdida(LINHAS, {9})
    assert ca.fracao_perdida([prod], "cards")["producao"] == "minutos"


def test_mercado_total_soma_os_dois_times():
    prod_casa = ca.producao_perdida(LINHAS, {9})
    prod_fora = ca.producao_perdida(LINHAS, set())
    total = ca.fracao_perdida([prod_casa, prod_fora], "goals")
    assert total["fracao"] == pytest.approx(3 / 8)


# ---------------------------------------------------------------------------
# 4. Dados atrasados e fatores da partida
# ---------------------------------------------------------------------------
HIST = [{"match_date": date(2026, 9, d), "league_id": 71} for d in (10, 17, 24)]


def test_jogo_disputado_fora_da_folha_e_contado():
    concluidos = [("2026-09-28 16:00:00", 71), ("2026-10-02 16:00:00", 71),
                  ("2026-10-01 21:00:00", 13)]   # copa fora do historico de liga
    assert ca.jogos_faltando(HIST, concluidos) == ["2026-09-28", "2026-10-02"]


def test_dois_faltando_bloqueia_um_so_vira_incerteza(monkeypatch):
    dois = {"home": {"concluidos_recentes": [("2026-09-28", 71), ("2026-10-02", 71)]}}
    um = {"home": {"concluidos_recentes": [("2026-09-28", 71)]}}
    assert "bloqueio" in ca.avaliar_partida(dois, HIST, HIST, DEFAULT_CONFIG)
    assert "bloqueio" not in ca.avaliar_partida(um, HIST, HIST, DEFAULT_CONFIG)
    monkeypatch.setenv("MOTOR_CONTEXTO_FATORES", "tecnico,forma,desfalques")
    assert "bloqueio" not in ca.avaliar_partida(dois, HIST, HIST, DEFAULT_CONFIG)


def test_calendario_e_viagem_sao_rotulos_de_incerteza():
    ctx = {"home": {"calendario": {"dias_desde_o_ultimo": 2.5, "jogos_ultimos_14_dias": 4,
                                   "dias_ate_o_proximo": 3}},
           "away": {"viagem_km": 2100, "calendario": {"dias_desde_o_ultimo": 20}}}
    f = ca.avaliar_partida(ctx, HIST, HIST, DEFAULT_CONFIG)["fatores_de_incerteza"]
    assert {"home:descanso_curto", "home:sequencia_apertada", "home:proximo_jogo_perto",
            "away:pausa_longa", "away:viagem_longa"} <= set(f)


def test_distancia_haversine():
    assert ca.distancia_km((-23.55, -46.63), (-22.91, -43.17)) == pytest.approx(361, abs=5)


# ---------------------------------------------------------------------------
# 5. O motor nos tres modos
# ---------------------------------------------------------------------------
def _jogo(dia, mes, gols_casa, gols_fora):
    return {"match_date": date(2026, mes, dia), "league_id": 71,
            "home_team_id": CASA, "away_team_id": FORA,
            "home_goals": gols_casa, "away_goals": gols_fora,
            "total_goals": gols_casa + gols_fora,
            "home_corners": 6, "away_corners": 4, "total_corners": 10,
            "home_yellow_cards": 2, "away_yellow_cards": 2, "total_yellow_cards": 4,
            "home_red_cards": 0, "away_red_cards": 0}


# 14 jogos do tecnico antigo com 4 gols, 6 do novo com 1 gol.
HISTORICO = ([_jogo(d, 7, 3, 1) for d in range(1, 15)]
             + [_jogo(d, 9, 1, 0) for d in range(1, 7)])
CONTEXTO = {"home": {"regime": {"inicio": "2026-08-15", "tecnico": "Novo"}}, "away": {}}


def _odd(value, line, odd):
    return {"market_id": 5, "market_name": "Goals Over/Under", "value": value, "line": line,
            "best_odd": odd, "bookmakers_count": 6, "value_label": f"{value} {line}"}


ODDS = [_odd("Over", "2.5", 1.80), _odd("Under", "2.5", 2.00)]


def _rodar(contexto=CONTEXTO, config=VIP_CONFIG):
    return analyze_fixture_markets(
        ODDS, HISTORICO, HISTORICO, reference_date=date(2026, 10, 8), config=config,
        calibration_data=CALIBRACAO_VAZIA, home_team_id=CASA, away_team_id=FORA,
        contexto_partida=contexto)


def _over(cands):
    return next((c for c in cands if c["market_type"] == "goals"
                 and c["value"] == "Over"), None)


def _linha(cands, valor):
    return next((c for c in cands if c["market_type"] == "goals" and c["value"] == valor), None)


def test_sem_contexto_o_motor_e_o_de_antes():
    a = _rodar(contexto=None)
    b = analyze_fixture_markets(
        ODDS, HISTORICO, HISTORICO, reference_date=date(2026, 10, 8), config=VIP_CONFIG,
        calibration_data=CALIBRACAO_VAZIA, home_team_id=CASA, away_team_id=FORA)
    chave = lambda cs: [(c["value_label"], c["taxa_real"], c["ev"], c["confidence"]) for c in cs]
    assert chave(a) == chave(b)
    assert all("contexto_sombra" not in c for c in a)


def test_shadow_grava_mas_nao_mexe_na_conta():
    sem = _rodar(contexto=None)
    com = _rodar()
    assert [(c["taxa_real"], c["ev"]) for c in sem] == [(c["taxa_real"], c["ev"]) for c in com]
    c = com[0]
    assert c["modo_contexto"] == "shadow"
    assert "contexto_sombra" in c and "amostra_efetiva" not in c
    s = c["contexto_sombra"]
    assert s["amostra_efetiva"] < c["amostra"]
    assert s["fatores"][0]["fator"] == "tecnico"


def test_on_puxa_pro_mercado_e_reduz_a_amostra(monkeypatch):
    monkeypatch.setenv("MOTOR_CONTEXTO", "on")
    com = _rodar()
    c = com[0]
    assert c["modo_contexto"] == "on"
    assert c["amostra_efetiva"] < c["amostra"]
    assert c["taxa_real_sem_regime"] is not None
    assert c["delta_regime"] == round(c["contexto_sombra"]["taxa"]
                                      - c["contexto_sombra"]["taxa_sem_contexto"], 4)
    # A versao com contexto e' a sombra registrada.
    assert c["contexto_sombra"]["taxa"] != c["contexto_sombra"]["taxa_sem_contexto"]
    assert c["avaliacao"]["incerteza_contextual"]["aplicada_na_conta"] is True


def test_on_derruba_o_over_que_o_tecnico_novo_desmentiu(monkeypatch):
    """O historico antigo (4 gols) sustentava o Over; o tecnico novo (1 gol)
    nao. Com o contexto, o Over deixa de ser o candidato -- ou deixa de
    passar no ranking."""
    sem = ranking.rank_all_candidates(_rodar(contexto=None), config=VIP_CONFIG)
    monkeypatch.setenv("MOTOR_CONTEXTO", "on")
    com = ranking.rank_all_candidates(_rodar(), config=VIP_CONFIG)
    over_sem = [c for c in sem if c["value"] == "Over"]
    over_com = [c for c in com if c["value"] == "Over"]
    assert len(over_com) <= len(over_sem)
    for c in over_com:
        assert c["taxa_real"] <= next(x for x in over_sem)["taxa_real"]


def test_tecnico_que_estreia_hoje_desconta_mesmo_em_mercado_total():
    """Regressao achada rodando o motor (08/10): num mercado total o trecho
    atual tem os jogos do OUTRO time, e a rampa contava esses jogos como se
    fossem do tecnico novo -- a estreia passava sem desconto nenhum."""
    estreia = {"home": {"regime": {"inicio": "2026-10-07"}}, "away": {}}
    c = _rodar(contexto=estreia)[0]
    s = c["contexto_sombra"]
    assert s["amostra_efetiva"] < c["amostra"]
    assert s["fatores"][0]["a0_rampa"] == DEFAULT_CONFIG.contexto_peso_tecnico_sem_jogos


def test_explicacao_so_fala_do_contexto_quando_ele_decidiu(monkeypatch):
    from services.pick_engine import explain
    assert "Técnico novo" not in explain(_rodar()[0])          # shadow
    monkeypatch.setenv("MOTOR_CONTEXTO", "on")
    texto = explain(_rodar()[0])
    assert "Técnico novo desde 15/08" in texto and "Amostra efetiva" in texto


def test_avaliacao_separa_as_quatro_respostas():
    c = _rodar()[0]
    av = c["avaliacao"]
    assert set(av) == {"probabilidade", "qualidade_da_estimativa", "valor",
                       "incerteza_contextual"}
    assert av["probabilidade"]["estimada"] == c["taxa_real"]
    assert av["valor"]["ev"] == c["ev"]
    assert 0 < av["incerteza_contextual"]["indice"] < 1


def test_historico_atrasado_barra_a_partida_so_em_on(monkeypatch):
    atrasado = {**CONTEXTO, "away": {"concluidos_recentes": [("2026-09-20", 71),
                                                             ("2026-09-27", 71)]}}
    assert _rodar(contexto=atrasado)          # shadow: segue
    monkeypatch.setenv("MOTOR_CONTEXTO", "on")
    rastro: list = []
    assert analyze_fixture_markets(
        ODDS, HISTORICO, HISTORICO, reference_date=date(2026, 10, 8), config=VIP_CONFIG,
        calibration_data=CALIBRACAO_VAZIA, home_team_id=CASA, away_team_id=FORA,
        contexto_partida=atrasado, rastro=rastro) == []
    assert "historico desatualizado" in rastro[0]["motivo"]


def test_off_desliga_tudo(monkeypatch):
    monkeypatch.setenv("MOTOR_CONTEXTO", "off")
    assert all("contexto_sombra" not in c for c in _rodar())


def test_o_mesmo_fato_nao_pune_duas_vezes(monkeypatch):
    news = {"home": {"titulares_desfalcados": ["X"], "outros_desfalcados": [],
                     "tecnico_mudou": True},
            "away": {"titulares_desfalcados": [], "outros_desfalcados": []}}
    monkeypatch.setenv("MOTOR_DESFALQUES", "on")
    kw = dict(reference_date=date(2026, 10, 8), config=VIP_CONFIG,
              calibration_data=CALIBRACAO_VAZIA, home_team_id=CASA, away_team_id=FORA,
              news_data=news, contexto_partida=CONTEXTO)
    assert analyze_fixture_markets(ODDS, HISTORICO, HISTORICO, **kw)[0]["news_score"] is not None
    monkeypatch.setenv("MOTOR_CONTEXTO", "on")
    assert analyze_fixture_markets(ODDS, HISTORICO, HISTORICO, **kw)[0]["news_score"] is None


# ---------------------------------------------------------------------------
# 6. Ranking: o contexto reprova, nunca aprova
# ---------------------------------------------------------------------------
def test_aprovacao_desconta_o_regime_do_numero_final():
    # Regime subiu 0.06; depois a camada probabilistica tirou 0.02 (0.70 -> 0.68).
    c = {"taxa_real": 0.68, "ev": 0.156, "odd": 1.70, "delta_regime": 0.06}
    assert ranking._valores_de_aprovacao(c) == (0.62, round(0.62 * 1.70 - 1, 4))
    # Regime que derrubou: vale o numero com contexto.
    c = {"taxa_real": 0.60, "ev": -0.01, "odd": 1.65, "delta_regime": -0.06}
    assert ranking._valores_de_aprovacao(c) == (0.60, -0.01)


def test_amostra_efetiva_passa_pelo_mesmo_piso():
    assert ranking._amostra_de_aprovacao({"amostra": 15, "amostra_efetiva": 6.2}) == 6.2
    assert ranking._amostra_de_aprovacao({"amostra": 15}) == 15


# ---------------------------------------------------------------------------
# 7. Motores de modelo proprio
# ---------------------------------------------------------------------------
SERIE = {"home": [(date(2026, 9, d), 10) for d in (20, 27)]
         + [(date(2026, 8, d), 22) for d in range(1, 12)]}
CTX_PROPRIO = {"home": {"regime": {"inicio": "2026-09-15"}}, "away": {}}


def test_modelo_proprio_shadow_nao_muda_a_probabilidade():
    p, reg = ca.probabilidade_para_modelo_proprio(
        CTX_PROPRIO, "fouls", "home", 0.72, 13, 1.70, SERIE, DEFAULT_CONFIG)
    assert p == 0.72 and reg["aplicado"] is False and reg["taxa"] < 0.72


def test_modelo_proprio_on_nunca_afasta_do_mercado(monkeypatch):
    monkeypatch.setenv("MOTOR_CONTEXTO", "on")
    prior = 1 / 1.70
    p, reg = ca.probabilidade_para_modelo_proprio(
        CTX_PROPRIO, "fouls", "home", 0.72, 13, 1.70, SERIE, DEFAULT_CONFIG)
    assert prior <= p < 0.72 and reg["aplicado"]
    # pick abaixo do mercado tambem so' anda pro mercado
    p2, _ = ca.probabilidade_para_modelo_proprio(
        CTX_PROPRIO, "fouls", "home", 0.40, 13, 1.70, SERIE, DEFAULT_CONFIG)
    assert 0.40 < p2 <= prior


# ---------------------------------------------------------------------------
# 8. Revalidacao antes de publicar
# ---------------------------------------------------------------------------
class _Odds:
    def __init__(self, linhas):
        self.linhas, self.pedidas = linhas, []

    def load_odds_structured(self, fixture_id, max_idade_seg=None):
        self.pedidas.append(max_idade_seg)
        return self.linhas


class _Coletor:
    def __init__(self, falha=None):
        self.falha, self.chamadas = falha, 0

    def process_fixture_odds(self, fixture_id):
        self.chamadas += 1
        if self.falha:
            raise RuntimeError(self.falha)


PICK = {"market_id": 5, "value_label": "Under 2.5", "taxa_real": 0.62, "odd": 1.75, "ev": 0.085}


def _entrada(odd, casas=4):
    return {"market_id": 5, "value_label": "Under 2.5", "value": "Under", "line": "2.5",
            "best_odd": odd + 0.05, "consensus_odd": odd, "best_bookmaker": "Casa",
            "bookmakers_count": casas}


@pytest.fixture
def _sem_memo():
    revalidacao._ATUALIZADAS.clear()
    yield
    revalidacao._ATUALIZADAS.clear()


def test_linha_que_saiu_do_ar_nao_publica(_sem_memo):
    r = revalidacao.revalidar(PICK, 1, VIP_CONFIG, odds_service=_Odds([]), coletor=_Coletor())
    assert r["ok"] is False and "nao esta' mais cotada" in r["motivo"]


def test_odd_que_caiu_e_matou_o_ev_nao_publica(_sem_memo):
    r = revalidacao.revalidar(PICK, 1, VIP_CONFIG, odds_service=_Odds([_entrada(1.55)]),
                              coletor=_Coletor())
    assert r["ok"] is False and "EV" in r["motivo"]


def test_revalidada_publica_com_os_numeros_de_agora(_sem_memo):
    novo = revalidacao.aplicar(PICK, 1, VIP_CONFIG, odds_service=_Odds([_entrada(1.80)]),
                               coletor=_Coletor())
    assert novo["odd"] == 1.80 and novo["ev"] == round(0.62 * 1.80 - 1, 4)
    assert novo["revalidacao"]["fonte"] == "api"


def test_api_fora_cai_pro_banco_com_idade_maxima(_sem_memo):
    odds = _Odds([_entrada(1.80)])
    r = revalidacao.revalidar(PICK, 1, VIP_CONFIG, odds_service=odds,
                              coletor=_Coletor(falha="timeout"))
    assert r["ok"] and r["fonte"] == "banco" and "timeout" in r["falha_api"]
    assert odds.pedidas == [VIP_CONFIG.max_idade_odd_publicacao_seg]


def test_api_e_chamada_uma_vez_por_partida_na_rodada(_sem_memo):
    col = _Coletor()
    for _ in range(3):
        revalidacao.revalidar(PICK, 7, VIP_CONFIG, odds_service=_Odds([_entrada(1.80)]),
                              coletor=col)
    assert col.chamadas == 1


def test_bilhete_cai_inteiro_se_uma_perna_morre(_sem_memo, monkeypatch):
    monkeypatch.setattr(revalidacao, "revalidar",
                        lambda p, fid, cfg, **kw: {"ok": fid != 2, "motivo": "x"})
    pernas = [{"fixture_id": 1}, {"_fixture": {"fixture_id": 2}}]
    assert revalidacao.pernas_ok(pernas, VIP_CONFIG) is None


def test_revalidacao_desligada_nao_toca(monkeypatch):
    monkeypatch.setenv("MOTOR_REVALIDAR_ODD", "off")
    assert revalidacao.revalidar(PICK, 1, VIP_CONFIG)["ok"]


# ---------------------------------------------------------------------------
# 9. Reavaliacao perto do apito
# ---------------------------------------------------------------------------
def test_reavaliacao_sem_noticia_so_reprecifica():
    r = reavaliacao.reavaliar_pick({"prob": 0.62, "odd": 1.75, "ev": 0.085,
                                    "market_type": "goals", "scope": "total", "amostra": 14},
                                   1.70, {"home": set(), "away": set()}, {})
    assert r["prob_reavaliada"] == 0.62 and r["ev_agora"] == round(0.62 * 1.70 - 1, 4)
    assert "alerta" not in r


def test_desfalque_novo_puxa_pro_preco_de_agora_e_alerta():
    prod = ca.producao_perdida(LINHAS, {9})
    pick = {"prob": 0.62, "odd": 1.75, "ev": 0.085,
            "market_type": "goals", "scope": "home", "amostra": 14}
    r = reavaliacao.reavaliar_pick(pick, 1.62, {"home": {9}, "away": set()}, {"home": prod},
                                   prob_justa=0.59)
    assert 0.59 <= r["prob_reavaliada"] < 0.62
    assert r["alerta"] and r["novos_ausentes"] == {"home": [9]}
    assert r["detalhe"]["alvo"] == "sem margem"
    # Sem o par no retrato o alvo e' 1/odd: o EV encosta em zero mas nao fica
    # negativo -- por isso o motor procura o preco justo primeiro.
    sem_par = reavaliacao.reavaliar_pick(pick, 1.62, {"home": {9}, "away": set()},
                                         {"home": prod})
    assert sem_par["prob_reavaliada"] >= 1 / 1.62 - 1e-4


def test_linha_sem_cotacao_no_fechamento_alerta():
    r = reavaliacao.reavaliar_pick({"prob": 0.62, "odd": 1.75, "market_type": "goals"},
                                   None, {}, {})
    assert "sem cotacao" in r["alerta"]


def test_segunda_passada_so_quando_o_xi_saiu_depois_e_o_jogo_nao_comecou():
    cur = _Cur()
    reavaliacao.esperando_escalacao(cur, {1, 2})
    sql = cur.sqls[-1][0]
    assert "fl.oficial" in sql and "f.status IN ('NS', 'TBD')" in sql
    assert "fl.atualizado_em > MAX(r.reavaliado_em)" in sql
    assert "xi_oficial" in sql
    assert reavaliacao.esperando_escalacao(_Cur(), set()) == []


# ---------------------------------------------------------------------------
# 10. Nada de futuro
# ---------------------------------------------------------------------------
class _Cur:
    def __init__(self, linhas=None):
        self.sqls, self.linhas = [], linhas or []
        self.connection = self

    def execute(self, sql, params=None):
        self.sqls.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return self.linhas

    def rollback(self):
        pass

    def commit(self):
        pass


def test_replay_nao_consulta_a_api_do_tecnico(monkeypatch):
    monkeypatch.setenv("MOTOR_CONTEXTO_COACHS", "on")
    chamou = []
    import utils.api_client as api
    monkeypatch.setattr(api, "buscar", lambda *a, **k: chamou.append(a) or [])
    tec, falha = ca.tecnico_atual(_Cur(), 7, instante=datetime(2026, 9, 1, 12))
    assert chamou == [] and tec is None and falha is None


def test_escalacao_filtra_pelo_apito_e_pelo_instante():
    cur = _Cur()
    ca._escalacoes_longas(cur, 7, datetime(2026, 10, 8, 16), datetime(2026, 10, 8, 9))
    sql, params = cur.sqls[-1]
    assert "match_date < %s" in sql and "coletado_em <= %s" in sql
    assert params[1] == datetime(2026, 10, 8, 16) and params[3] == datetime(2026, 10, 8, 9)


def test_calendario_so_le_jogo_terminado_antes_do_apito():
    cur = _Cur()
    ca._concluidos_recentes(cur, 7, datetime(2026, 10, 8, 16))
    sql, params = cur.sqls[-1]
    assert "status IN ('FT', 'AET', 'PEN')" in sql
    assert params[-1] < datetime(2026, 10, 8, 16)


# ---------------------------------------------------------------------------
# 11. Medicao
# ---------------------------------------------------------------------------
def test_medicao_pede_melhora_nas_duas_metades():
    from scripts import medir_contexto_atual as m
    boa = [{"p_sem": 0.7, "p_com": 0.6, "o": 0}] * 30 + [{"p_sem": 0.7, "p_com": 0.65, "o": 1}] * 30
    r = m.pareado(boa)
    assert r["d_brier"] < 0
    curta = m.pareado(boa[:10])
    assert "INSUFICIENTE" in m.veredito(curta, curta)
    assert "MELHORA" in m.veredito(r, r)
