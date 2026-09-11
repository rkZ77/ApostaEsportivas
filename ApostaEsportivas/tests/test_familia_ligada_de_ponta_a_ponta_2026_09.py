"""Faltas estava ligada em todo lugar, menos no lugar que conta.

O QUE ACONTECEU
---------------
Em 04/09/2026 a familia `fouls` entrou:

    config.familias              ("corners", "goals", "cards", "fouls")
    live_odds.FAMILIAS_V1        idem
    live_odds.NOMES_POR_FAMILIA  "total fouls", "fouls. total", ...
    residual_model.BASELINE_PADRAO   24.82 faltas por partida, medido
    live_state                   "fouls_total", com os dois lados

E nao entrou em `orchestrator.observado_da_familia`, que era uma cadeia de
`if familia == ...` com tres ramos. Faltas caia no `return None` final.

O efeito nao foi "faltas nao gera pick". Foi pior: `analisar` marca a familia
como indisponivel com o motivo **"estatistica nao publicada pelo provedor"** --
ou seja, o decision_log passou seis dias culpando a API-Football por um numero
que a API tinha publicado e que estava no dicionario de estado, ali do lado.

Cada teste destes existe pra prender uma metade do defeito: a fiacao, e o
motivo que o log da' quando a fiacao falta.
"""
import pytest

from services.pick_engine_live import orchestrator as orq
from services.pick_engine_live import live_odds
from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG as cfg
from services.pick_engine_live import residual_model as rm


def _estado(**extra):
    base = {
        "fixture_id": 1, "status": "2H", "minuto": 60,
        "home_team_id": 10, "away_team_id": 20, "league_id": 71,
        "corners_total": 6, "goals_total": 1, "cards_points_total": 3,
        "fouls_total": 18, "home_goals": 1, "away_goals": 0,
    }
    base.update(extra)
    return base


# ── a cobertura, que e' o teste que faltava ──────────────────────────────

def test_toda_familia_configurada_tem_chave_de_estado():
    """ESTE e' o teste que teria pego o defeito em 04/09. Familia ligada no
    config sem chave mapeada nao analisa nada, em silencio."""
    faltando = [f for f in cfg.familias if f not in orq.CHAVE_DO_ESTADO]
    assert faltando == [], f"familia sem fiacao no orchestrator: {faltando}"


def test_toda_familia_configurada_tem_baseline_padrao():
    """Sem baseline a familia cai em `None` no lambda e some do mesmo jeito."""
    faltando = [f for f in cfg.familias if f not in rm.BASELINE_PADRAO]
    assert faltando == [], f"familia sem baseline: {faltando}"


def test_toda_familia_configurada_e_cotavel():
    """Sem nome de mercado a familia nunca acha odd, e o pick morre depois de
    ja' ter gasto a requisicao."""
    faltando = [f for f in cfg.familias if f not in live_odds.NOMES_POR_FAMILIA]
    assert faltando == [], f"familia sem nome de mercado: {faltando}"


def test_o_config_e_o_catalogo_de_odds_nao_divergem():
    assert set(cfg.familias) == set(live_odds.FAMILIAS_V1)


# ── faltas, o caso concreto ──────────────────────────────────────────────

def test_faltas_chega_na_analise():
    assert orq.observado_da_familia(_estado(), "fouls") == 18
    analise = orq.analisar(_estado(), observacoes=[], config=cfg,
                           baselines={"fouls": 24.82})
    assert analise["familias"]["fouls"]["disponivel"] is True


def test_faltas_projeta_sobre_o_que_ja_foi_cometido():
    analise = orq.analisar(_estado(), observacoes=[], config=cfg,
                           baselines={"fouls": 24.82})
    lam = analise["familias"]["fouls"]["lambda"]
    assert lam["observado"] == 18
    assert lam["projecao_total"] > 18       # faltam 30 minutos de jogo


# ── o motivo que o log grava ─────────────────────────────────────────────

def test_dado_ausente_continua_culpando_o_provedor():
    """Quando o provedor realmente nao publicou, o motivo e' esse mesmo."""
    estado = _estado(fouls_total=None)
    analise = orq.analisar(estado, observacoes=[], config=cfg,
                           baselines={"fouls": 24.82})
    info = analise["familias"]["fouls"]
    assert info["disponivel"] is False
    assert "provedor" in info["motivo"]


def test_fiacao_faltando_nao_pode_ser_confundida_com_dado_faltando():
    """O defeito inteiro em um assert: uma familia sem chave mapeada tem que
    dizer que e' fiacao, nao acusar a API."""
    motivo = orq.motivo_da_indisponibilidade(_estado(), "familia_nova")
    assert "fiacao" in motivo
    assert "provedor" not in motivo


def test_chutes_tem_fiacao_mesmo_sem_estar_ligado():
    """Chutes NAO esta' em `familias` (decisao de produto, nao esquecimento).
    A chave existe pra o dia em que ligarem, e ligar passar a ser uma linha de
    config em vez de uma cacada."""
    assert "shots" in orq.CHAVE_DO_ESTADO
    assert "shots" not in cfg.familias
    assert orq.observado_da_familia(_estado(shots_total=14), "shots") == 14
