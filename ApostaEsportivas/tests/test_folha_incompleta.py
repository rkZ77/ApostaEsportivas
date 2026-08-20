# -*- coding: utf-8 -*-
"""Folha de estatistica incompleta nao pode virar zero.

O DEFEITO, E POR QUE ELE SOBREVIVEU A UMA CORRECAO ANTERIOR
------------------------------------------------------------
Em 2026-07-25 o motor passou a LER cartao vermelho: `_FAMILY_STAT_FIELDS`
apontava so' pra amarelo e a taxa de "Under cartoes" saia inflada. Aquela
correcao resolveu metade do problema.

A outra metade e' a coluna estar VAZIA. `_extract_stat` faz `m.get(campo) or 0`
em toda familia, e `or 0` nao distingue "a API publicou zero" de "a API nao
publicou". O erro tem direcao fixa: conta menos evento do que houve, entao
sempre infla o Under.

Medido em PROD em 2026-08-20, nos 1.646 jogos FT:

    cobertura de vermelho             68,7%
    jogos com amarelo e sem vermelho  498
    o inverso                         3
    media onde HA dado                0,391 vermelho = 0,78 ponto de cartao
    ignorar o vermelho vira o lado    11,5% dos jogos numa linha 5.5

E ficou provado que NULL nao e' zero: entre as linhas preenchidas de 2026,
66% sao zeros EXPLICITOS. A API publica o zero quando sabe.

Custo do filtro, medido nos 119 times com 10+ jogos: o pool de cartoes cai de
14,2 pra 10,5 jogos e 20% dos times ficam abaixo de `min_amostra`. Esses 20%
param de gerar pick de cartao, que e' o resultado certo -- a historia deles nao
sustentava a estimativa, ela so' parecia sustentar.
"""
import pytest

from services.pick_engine import stats_model


def _jogo(**kw):
    base = {"status": "FT", "home_team_id": 1, "away_team_id": 2,
            "home_goals": 1, "away_goals": 1}
    base.update(kw)
    return base


# ─────────────────────────── cartoes ──────────────────────────────────────
def test_jogo_com_amarelo_e_sem_vermelho_sai_do_pool():
    """Os 498 jogos reais. Antes entravam contando vermelho=0."""
    pool = [
        _jogo(home_yellow_cards=2, away_yellow_cards=1,
              home_red_cards=0, away_red_cards=0),
        _jogo(home_yellow_cards=3, away_yellow_cards=2,
              home_red_cards=None, away_red_cards=None),
    ]
    assert len(stats_model.comparavel_em_90(pool, "cards")) == 1


def test_zero_explicito_de_vermelho_continua_valendo():
    """66% das linhas preenchidas sao zero de verdade. Confundir "zero
    publicado" com "nao publicado" na direcao contraria destruiria dois tercos
    da amostra boa."""
    pool = [_jogo(home_yellow_cards=2, away_yellow_cards=1,
                  home_red_cards=0, away_red_cards=0)]
    assert len(stats_model.comparavel_em_90(pool, "cards")) == 1


def test_folha_inteira_ausente_nao_encolhe_o_pool():
    """Chamador antigo e fixture de teste nao trazem os campos. Ausencia
    TOTAL nao e' folha parcial -- mesma regra que `status` ja seguia."""
    pool = [_jogo()]
    assert len(stats_model.comparavel_em_90(pool, "cards")) == 1


# ─────────────────────────── as outras familias ───────────────────────────
@pytest.mark.parametrize("familia,campo_home,campo_away", [
    ("corners", "home_corners", "away_corners"),
    ("fouls", "home_fouls", "away_fouls"),
    ("shots", "home_total_shots", "away_total_shots"),
    ("shots_on_target", "home_shots_on", "away_shots_on"),
    ("offsides", "home_offsides", "away_offsides"),
    ("saves", "home_goalkeeper_saves", "away_goalkeeper_saves"),
])
def test_folha_parcial_sai_do_pool_em_toda_familia(familia, campo_home, campo_away):
    """96-99% de cobertura quer dizer 1 a 4% de jogos entrando como zero. E'
    pequeno o bastante pra nunca ser notado e grande o bastante pra deslocar
    uma taxa -- e o defeito e' o mesmo do vermelho, so' menor."""
    pool = [
        _jogo(**{campo_home: 5, campo_away: 4}),
        _jogo(**{campo_home: 5, campo_away: None}),
    ]
    assert len(stats_model.comparavel_em_90(pool, familia)) == 1


def test_gols_nao_sao_filtrados_por_folha():
    """Placar tem 100% de cobertura e ja' tem tratamento proprio (gols_90 e o
    filtro de prorrogacao). Passar gols por esta checagem so' criaria risco de
    encolher o pool da familia mais importante sem motivo."""
    pool = [_jogo(home_goals=2, away_goals=0), _jogo(home_goals=1, away_goals=1)]
    assert len(stats_model.comparavel_em_90(pool, "goals")) == 2


def test_prorrogacao_continua_saindo():
    """A regra que ja existia nao pode ter sido perdida na generalizacao."""
    pool = [
        _jogo(home_corners=5, away_corners=4),
        _jogo(status="AET", home_corners=7, away_corners=6),
    ]
    assert len(stats_model.comparavel_em_90(pool, "corners")) == 1
