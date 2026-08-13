"""Cadastro de competicoes (services/pick_engine/competition_profile.py).

POR QUE ESTE ARQUIVO EXISTE
---------------------------
Este cadastro ja errou duas vezes pelo mesmo motivo: id herdado de uma lista
antiga sem conferir item a item. Em 2026-08-01 descobriu-se que a liga 39
(Premier League) estava marcada como eliminatoria de SELECAO. Em 2026-08-13, que
a 11 (CONMEBOL Sul-Americana) tambem estava -- competicao de clube tratada como
selecao, com historico e grupo de peso de selecao.

Nenhum dos dois quebrou nada visivel. O primeiro nao mordeu porque nao havia
jogo da liga 39 no banco; o segundo produzia pick com a amostra errada em
silencio. Erro de cadastro nao levanta excecao, entao o teste e' o unico lugar
onde ele aparece.

O que se protege aqui e' a CLASSE de cada competicao que o motor avalia, nao a
lista inteira (ela cresce). Nenhum teste toca banco nem API.
"""
import pytest

from services.pick_engine import competition_profile as cp


# Competicoes de clube em que o time nao acumula jogo suficiente DENTRO da
# propria competicao: fase de grupos da 6 no teto, mata-mata da 1 a 4.
COPAS_DE_CLUBE = [
    (13, "CONMEBOL Libertadores"),
    (11, "CONMEBOL Sul-Americana"),
    (73, "Copa do Brasil"),
    (2, "UEFA Champions League"),
    (3, "UEFA Europa League"),
    (848, "UEFA Conference League"),
]

# Pontos corridos: o time joga 20+ vezes na propria competicao.
LIGAS_DE_PONTOS_CORRIDOS = [
    (71, "Brasileirao Serie A"),
    (72, "Brasileirao Serie B"),
    (39, "Premier League"),
    (140, "La Liga"),
    (135, "Serie A (Italia)"),
    (78, "Bundesliga"),
    (61, "Ligue 1"),
    (94, "Primeira Liga"),
    (88, "Eredivisie"),
]


@pytest.mark.parametrize("league_id, nome", COPAS_DE_CLUBE)
def test_copa_de_clube_le_historico_de_todas_as_competicoes(league_id, nome):
    """Sem isso, validate_history reprova a fixture inteira em silencio: o
    minimo e' 5 jogos e a competicao nao entrega 5."""
    assert cp.uses_all_competitions_history(league_id), nome


@pytest.mark.parametrize("league_id, nome", COPAS_DE_CLUBE)
def test_copa_de_clube_nao_e_selecao(league_id, nome):
    """A 11 estava aqui. is_national_team liga o perfil de selecao nacional e
    o grupo de peso 'Eliminatorias' -- vocabulario de selecao aplicado a
    clube."""
    assert not cp.is_national_team_league(league_id), nome
    assert cp.get_profile(league_id).type == "CLUB_CUP", nome


@pytest.mark.parametrize("league_id, nome", LIGAS_DE_PONTOS_CORRIDOS)
def test_pontos_corridos_le_historico_da_propria_liga(league_id, nome):
    """Abrir o historico de uma liga trocaria amostra suficiente por amostra
    misturada, sem ganho nenhum: o time ja tem 20 jogos ali."""
    assert not cp.uses_all_competitions_history(league_id), nome


@pytest.mark.parametrize("league_id, nome", LIGAS_DE_PONTOS_CORRIDOS)
def test_pontos_corridos_nao_e_selecao_nem_copa(league_id, nome):
    perfil = cp.get_profile(league_id)
    assert perfil.type == "LEAGUE", nome
    assert not perfil.is_national_team, nome


def test_selecao_continua_lendo_todas_as_competicoes():
    """A regra de selecao e' anterior a de copa de clube e nao pode ter sido
    perdida no caminho: selecao joga pouco por natureza."""
    for league_id in (1, 9, 4, 10, 31, 32):
        assert cp.uses_all_competitions_history(league_id), league_id


def test_toda_copa_de_clube_tem_peso_de_competicao_declarado():
    """cross_competition_weight tem fallback, entao competicao sem peso nao
    quebra -- ela silenciosamente vale 0.80. Para as competicoes que o motor
    avalia todo dia, o peso e' decisao, nao fallback."""
    for league_id, nome in COPAS_DE_CLUBE:
        assert league_id in cp._CROSS_COMPETITION_WEIGHT, nome


def test_copa_de_clube_nao_entra_no_vocabulario_de_peso_de_selecao():
    """competition_weight_group indexa national_team_profile_service.WEIGHTS
    direto (WEIGHTS[grupo]); string nova ali vira KeyError no fluxo de
    selecao. Copa de clube tem que ficar None."""
    for league_id, nome in COPAS_DE_CLUBE:
        assert cp.get_profile(league_id).competition_weight_group is None, nome


def test_mando_de_copa_de_clube_e_normal():
    """Sede neutra so' vale pra competicao que joga em sede unica (Copa do
    Mundo). Libertadores e Champions tem mandante de verdade, e e' o mando que
    o filtro de pool_and_field usa."""
    for league_id, nome in COPAS_DE_CLUBE:
        assert not cp.is_neutral_venue(league_id), nome


# ── Fase da partida (o `round` da API) ────────────────────────────────────
@pytest.mark.parametrize("texto, esperado", [
    ("Group Stage - 3", "GROUP_STAGE"),
    ("Round of 16", "KNOCKOUT_SINGLE"),
    ("Quarter-finals", "KNOCKOUT_SINGLE"),
    ("Semi-finals", "KNOCKOUT_SINGLE"),
    ("Final - 1st Leg", "KNOCKOUT_TWO_LEGS"),
    ("Semi-finals - 2nd Leg", "KNOCKOUT_TWO_LEGS"),
    ("Regular Season - 12", None),
    (None, None),
])
def test_fase_sai_do_texto_do_round(texto, esperado):
    """'leg' e checado antes de knockout-single: 'Final - 1st Leg' nao pode
    cair em jogo unico."""
    assert cp.classify_round_phase(texto) == esperado
