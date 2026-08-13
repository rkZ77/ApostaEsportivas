"""O que o motor faz com um historico MISTURADO (copa).

Abrir o historico pra todas as competicoes resolveu "amostra pequena" e criou
"amostra enviesada": 15 jogos vindos de Brasileirao, Libertadores e Copa do
Brasil pesavam todos igual, contra adversario que o banco nem sabia quem era, e
jogo decidido na prorrogacao ficava de fora justamente no mata-mata.

Estes testes travam as quatro correcoes de 2026-08-13 e, principalmente, a
propriedade que faz nenhuma delas mexer em fixture de pontos corridos.
"""
from datetime import date

import pytest

from services.pick_engine import stats_model
from services.pick_engine.competition_profile import cross_competition_weight


def jogo(**kw):
    base = {
        "match_date": "2026-08-10", "league_id": 71, "status": "FT",
        "home_team_id": 1, "away_team_id": 2,
        "home_goals": 1, "away_goals": 1, "total_goals": 2,
        "home_corners": 5, "away_corners": 4, "total_corners": 9,
        "opponent_rank": None,
    }
    base.update(kw)
    return base


# ── Peso por competicao de origem ─────────────────────────────────────────
def test_competicao_fraca_pesa_menos_na_taxa():
    """4x0 na Copa do Brasil contra time de divisao inferior nao descreve o
    mesmo time que 4x0 no Brasileirao. Com o peso ligado, o jogo de Copa do
    Brasil (0.75) puxa menos a taxa que o de Brasileirao (1.00)."""
    bateu_no_brasileirao = [jogo(league_id=71, total_corners=12),
                            jogo(league_id=73, total_corners=4)]
    bateu_na_copa = [jogo(league_id=71, total_corners=4),
                     jogo(league_id=73, total_corners=12)]

    hit = lambda m: 1 if m["total_corners"] > 9 else 0
    taxa_brasileirao = stats_model.weighted_rate(bateu_no_brasileirao, hit,
                                                 reference_date=date(2026, 8, 12))
    taxa_copa = stats_model.weighted_rate(bateu_na_copa, hit, reference_date=date(2026, 8, 12))

    assert taxa_brasileirao["taxa_ponderada"] > taxa_copa["taxa_ponderada"]
    # A taxa BRUTA e' identica nos dois (1 de 2): o que muda e' so' o peso.
    assert taxa_brasileirao["taxa_bruta"] == taxa_copa["taxa_bruta"] == 0.5


def test_historico_de_uma_liga_so_nao_muda_nada():
    """A propriedade que mantem fixture de pontos corridos intacta, e ela e'
    aritmetica, nao um `if`: peso constante em todos os jogos se cancela na
    media ponderada (soma(v*w)/soma(w))."""
    hist = [jogo(league_id=71, total_corners=12), jogo(league_id=71, total_corners=4)]
    hit = lambda m: 1 if m["total_corners"] > 9 else 0

    com_peso = stats_model.weighted_rate(hist, hit, reference_date=date(2026, 8, 12))
    assert com_peso["taxa_ponderada"] == com_peso["taxa_bruta"] == 0.5


def test_liga_desconhecida_cai_no_peso_padrao():
    """Campeonato estrangeiro nao cadastrado nao pode valer 0 nem 1."""
    assert 0 < cross_competition_weight(99999) < 1.0


# ── Prorrogacao, por familia ──────────────────────────────────────────────
def test_prorrogacao_sai_do_pool_de_escanteios():
    """A folha de um AET cobre 120 minutos e nao ha coluna de 90 pra
    escanteios: manter o jogo empurraria a taxa de Over pra cima com um jogo
    que a casa liquidou noutro placar."""
    pool = [jogo(status="FT"), jogo(status="AET"), jogo(status="PEN")]

    resultado, _ = stats_model.pool_and_field("corners", "total", pool, [],
                                              home_team_id=1, away_team_id=2)
    assert [m["status"] for m in resultado] == ["FT"]


@pytest.mark.parametrize("familia", ["goals", "btts"])
def test_prorrogacao_fica_no_pool_de_gols(familia):
    """Gols e BTTS tem placar de 90 minutos separado, entao o jogo serve -- e
    e' o jogo de mata-mata, exatamente onde a amostra e' curta."""
    pool = [jogo(status="FT"), jogo(status="AET")]

    resultado, _ = stats_model.pool_and_field(familia, "total", pool, [],
                                              home_team_id=1, away_team_id=2)
    assert len(resultado) == 2


def test_jogo_sem_status_permanece_no_pool():
    """Ausencia de campo nunca pode ENCOLHER o pool: chamador antigo e fixture
    de teste nao trazem `status`."""
    pool = [{"match_date": "2026-08-10", "home_team_id": 1, "away_team_id": 2,
             "home_corners": 5, "away_corners": 4, "total_corners": 9}]

    resultado, _ = stats_model.pool_and_field("corners", "total", pool, [],
                                              home_team_id=1, away_team_id=2)
    assert len(resultado) == 1


# ── Placar de 90 minutos ──────────────────────────────────────────────────
def test_gol_da_prorrogacao_nao_conta_no_over():
    """Caso real ja documentado no repositorio (goals 3x2 com fulltime 2x2).
    A casa liquida Over/Under pelos 90 minutos."""
    m = jogo(status="AET", home_goals=3, away_goals=2, total_goals=5,
             home_goals_90=2, away_goals_90=2)

    assert stats_model._extract_stat(m, "goals", "total") == 4


def test_placar_cheio_vale_quando_nao_ha_prorrogacao():
    """Jogo normal nao tem `_90` preenchido (a coluna nasceu depois), e ai o
    placar cheio E' o de 90 minutos."""
    m = jogo(home_goals=2, away_goals=1, total_goals=3)

    assert stats_model._extract_stat(m, "goals", "total") == 3


def test_media_de_escanteios_ignora_o_jogo_de_120_minutos():
    """scored_conceded_avg alimenta o cruzamento feitos-x-cedidos, e no caminho
    de historico cru -- que e' o caminho da COPA -- ele recebia a lista inteira,
    com o AET inflando a media."""
    so_ft = [jogo(home_corners=5, away_corners=5)]
    com_aet = so_ft + [jogo(status="AET", home_corners=15, away_corners=15)]

    assert (stats_model.scored_conceded_avg(so_ft, True, "corners", team_id=1)
            == stats_model.scored_conceded_avg(com_aet, True, "corners", team_id=1))


def test_media_de_gols_usa_os_90_minutos():
    m = [jogo(status="AET", home_goals=3, away_goals=2,
              home_goals_90=1, away_goals_90=1)]

    feitos, cedidos = stats_model.scored_conceded_avg(m, True, "goals", team_id=1)
    assert (feitos, cedidos) == (1.0, 1.0)


def test_btts_tambem_ignora_gol_de_prorrogacao():
    """0x0 nos 90 que virou 1x1 na prorrogacao nao e' 'ambas marcam' pra casa
    de aposta."""
    hit = stats_model._build_market_hit_fn("btts", "total", "yes", None)
    m = jogo(status="AET", home_goals=1, away_goals=1, home_goals_90=0, away_goals_90=0)

    assert hit(m) == 0
