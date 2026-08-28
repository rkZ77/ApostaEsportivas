# -*- coding: utf-8 -*-
"""A media agregada do time nao pode contar jogo sem folha como jogo com zero.

O DEFEITO, E POR QUE ELE SOBREVIVEU A DUAS CORRECOES
------------------------------------------------------------
O `or 0` que transforma "a API nao publicou" em "aconteceu zero" ja' tinha sido
corrigido em duas camadas:

    2026-08-20  stats_model._tem_folha_da_familia    derruba do pool o jogo de
                                                     folha parcial
    2026-08-26  utils/stat_sheet                     o coletor grava NULL em vez
                (e 27, 28)                           de zero

As duas passaram longe de `MatchStatsServiceMedia._aggregate_games`, que e' a
funcao que alimenta `team_statistics` -- e desde 2026-08-03 essa tabela e' a
fonte PREFERIDA do cruzamento feitos-x-cedidos, sendo o historico cru so' o
fallback. Ou seja: a correcao foi toda pro caminho de reserva, e o caminho
principal continuou somando `g.get(coluna) or 0` e dividindo pelo total de
jogos.

Medido em PROD em 2026-08-28: 145 das 1.490 fatias (time, liga, temporada,
mando) tinham pelo menos um jogo assim, e nelas a media saia 1,23 escanteio e
4,06 faltas ABAIXO da real -- sempre pra baixo, ou seja sempre inflando Under.
"""
import pytest

from services.match_stats_service_media import MatchStatsServiceMedia
from services.pick_engine import stats_model
from services.pick_engine.team_profile_model import tactical_patterns


TIME = 100
ADV = 200


def _jogo(**kw):
    base = {
        "home_team_id": TIME, "away_team_id": ADV,
        "home_goals": 1, "away_goals": 1,
        "home_corners": 6, "away_corners": 4,
        "home_fouls": 14, "away_fouls": 12,
        "home_yellow_cards": 2, "away_yellow_cards": 1,
        "home_red_cards": 0, "away_red_cards": 0,
        "home_goalkeeper_saves": 3, "away_goalkeeper_saves": 4,
        "home_possession": 55, "away_possession": 45,
        "home_total_shots": 12, "away_total_shots": 9,
        "home_shots_on": 5, "away_shots_on": 3,
    }
    base.update(kw)
    return base


def _medias(jogos, team_id=TIME):
    return {m["context_type"]: m
            for m in MatchStatsServiceMedia()._aggregate_games(jogos, team_id)}


def test_jogo_sem_escanteio_publicado_sai_da_media_de_escanteio():
    """Dois jogos com 6 escanteios e um sem folha: a media e' 6, nao 4."""
    jogos = [_jogo(), _jogo(), _jogo(home_corners=None, away_corners=None)]
    casa = _medias(jogos)["HOME"]

    assert casa["avg_corners_for"] == 6.0
    assert casa["games_count"] == 3           # o jogo aconteceu
    assert casa["games_by_stat"]["corners"] == 2   # mas nao sustenta escanteio


def test_metrica_que_nenhum_jogo_publicou_fica_vazia_e_nao_zero():
    """NULL manda o motor pro historico cru · zero seria numero inventado."""
    jogos = [_jogo(home_fouls=None, away_fouls=None),
             _jogo(home_fouls=None, away_fouls=None)]
    casa = _medias(jogos)["HOME"]

    assert casa["avg_fouls_for"] is None
    assert casa["avg_fouls_against"] is None
    assert casa["games_by_stat"]["fouls"] == 0
    # a familia vizinha, publicada nos dois jogos, nao e' afetada
    assert casa["avg_corners_for"] == 6.0


def test_uma_metrica_faltando_nao_contamina_as_outras():
    jogos = [_jogo(), _jogo(home_possession=None, away_possession=None)]
    casa = _medias(jogos)["HOME"]

    assert casa["avg_possession_for"] == 55.0
    assert casa["avg_corners_for"] == 6.0
    assert casa["games_by_stat"] == {**casa["games_by_stat"], "possession": 1, "corners": 2}


def test_total_da_partida_exige_os_dois_lados():
    """Com um lado so', 'total de escanteios do jogo' seria metade dele."""
    jogos = [_jogo(), _jogo(away_corners=None)]
    casa = _medias(jogos)["HOME"]

    assert casa["avg_total_corners"] == 10.0   # so' o jogo completo
    assert casa["avg_corners_for"] == 6.0      # os feitos usam os dois jogos
    assert casa["games_by_stat"]["corners"] == 2


def test_mando_continua_separado():
    jogos = [_jogo(), _jogo(home_team_id=ADV, away_team_id=TIME, away_corners=8)]
    medias = _medias(jogos)

    assert medias["HOME"]["avg_corners_for"] == 6.0
    assert medias["AWAY"]["avg_corners_for"] == 8.0


##############################################################################
# O encolhimento tem que pesar a amostra DA FAMILIA
##############################################################################

@pytest.mark.parametrize("familia,chave", [
    ("corners", "corners"), ("fouls", "fouls"), ("goals", "goals"), ("saves", "saves"),
])
def test_amostra_do_encolhimento_sai_da_familia_e_nao_do_total(familia, chave):
    """`games_count` conta jogos do time no mando; a familia pode ter menos.

    Usar o primeiro faz `shrink_to_baseline` acreditar numa amostra maior do
    que a que ele tem -- encolhendo de menos justamente a media que merecia
    encolher mais.
    """
    linha = {
        "games_count": 10,
        "games_by_stat": {"goals": 10, "yellow": 10, "red": 10,
                          "corners": 10, "fouls": 10, "saves": 10, chave: 3},
        "avg_goals_for": 1.5, "avg_goals_against": 1.2,
        "avg_corners_for": 6.0, "avg_corners_against": 4.0,
        "avg_fouls_for": 14.0, "avg_fouls_against": 12.0,
        "avg_saves_for": 3.0, "avg_saves_against": 4.0,
    }
    _feitos, _cedidos, n = stats_model.scored_conceded_from_team_stats(linha, familia)
    assert n == 3


def test_familia_sem_amostra_devolve_vazio_e_cai_no_historico_cru():
    linha = {"games_count": 10, "games_by_stat": {"corners": 0},
             "avg_corners_for": None, "avg_corners_against": None}
    assert stats_model.scored_conceded_from_team_stats(linha, "corners") == (None, None, 0)


def test_cartao_usa_a_menor_das_duas_contagens():
    """Ponto de cartao e' amarelo + 2*vermelho: so' vale o jogo com os dois."""
    linha = {"games_count": 10, "games_by_stat": {"yellow": 10, "red": 4},
             "avg_yellow_for": 2.0, "avg_red_for": 0.1,
             "avg_yellow_against": 1.8, "avg_red_against": 0.1}
    _f, _c, n = stats_model.scored_conceded_from_team_stats(linha, "cards")
    assert n == 4


def test_linha_antiga_sem_games_by_stat_mantem_o_comportamento_de_antes():
    """Gravada antes de 2026-08-28 · fallback em `games_count`, sem piorar."""
    linha = {"games_count": 7, "avg_corners_for": 6.0, "avg_corners_against": 4.0}
    _f, _c, n = stats_model.scored_conceded_from_team_stats(linha, "corners")
    assert n == 7


##############################################################################
# Perfil tatico · posse zero rotulava o time errado
##############################################################################

def test_posse_ausente_nao_derruba_o_estilo_do_time():
    """Posse 0% e' impossivel; um jogo sem folha rotulava o time de
    'Contra-ataque rapido' por causa da media derrubada."""
    jogos = [_jogo(home_possession=58), _jogo(home_possession=57),
             _jogo(home_possession=None)]
    perfil = tactical_patterns(jogos, TIME)

    assert perfil["avg_possession"] == 57.5
    assert perfil["style"] != "Contra-ataque rápido"
    assert perfil["amostra_por_campo"]["possession"] == 2


def test_perfil_sem_nenhuma_posse_publicada_nao_chuta_estilo():
    jogos = [_jogo(home_possession=None), _jogo(home_possession=None)]
    perfil = tactical_patterns(jogos, TIME)

    assert perfil["style"] == "Dados insuficientes"
    assert perfil["pressing_intensity"] == "Desconhecida"
