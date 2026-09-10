"""O piso de amostra virou piso de QUALIDADE DE ESTIMATIVA (2026-09-10).

Faltas e Player Stats aprovavam pick sem nunca olhar QUANTOS jogos tinham
produzido a media. Os dois motores tinham a regua no projeto e nao a cobravam
na hora de gerar o pick:

  faltas         MIN_JOGOS_TIME (=4) so' rodava em fouls_calibration
  player stats   min_atuacoes (=4) igual pra contadores com CV de 0.65 a 1.90

O que amarra os dois arquivos e' a ideia: um numero de jogos nao significa a
mesma coisa em contadores de dispersao diferente, entao piso igual em NUMERO
produz exigencia desigual em QUALIDADE. Os numeros medidos estao nos
comentarios de cada arquivo -- aqui ficam so' as consequencias.
"""
import pytest

from engine_pipelines.faltas_pipeline import erro_de_amostragem, MIN_JOGOS_PICK
from services.player_stats_engine.methods import POR_SLUG


# ────────────────────────────────── faltas ───────────────────────────────────


def test_erro_de_amostragem_cai_conforme_a_amostra_cresce():
    """A tabela medida: 1.82 falta no total com 5 jogos, 0.69 com 18."""
    assert erro_de_amostragem(5, 5) == pytest.approx(1.82)
    assert erro_de_amostragem(18, 18) == pytest.approx(0.69)
    anterior = 99.0
    for n in (5, 8, 10, 12, 15, 18):
        atual = erro_de_amostragem(n, n)
        assert atual < anterior
        anterior = atual


def test_manda_o_lado_mais_curto():
    """Um time com 30 jogos nao compensa o outro com 5: quem limita a projecao
    do TOTAL e' o lado pior."""
    assert erro_de_amostragem(30, 5) == erro_de_amostragem(5, 5)


def test_erro_interpola_entre_os_pontos_medidos():
    assert erro_de_amostragem(10, 10) < erro_de_amostragem(11, 11) + 0.2
    assert erro_de_amostragem(12, 12) < erro_de_amostragem(11, 11)


def test_fora_da_tabela_nao_extrapola():
    """Amostra gigante nao vira erro zero -- a tabela para onde foi medida."""
    assert erro_de_amostragem(200, 200) == erro_de_amostragem(18, 18)
    assert erro_de_amostragem(1, 1) == erro_de_amostragem(5, 5)


def test_o_piso_duro_existe():
    """Com 5 jogos o erro (1.82) e' maior que a margem tipica de um pick de
    faltas · a Championship abriu temporada e sairam 7 picks assim."""
    assert MIN_JOGOS_PICK == 10


# ─────────────────────────────── player stats ────────────────────────────────


def test_piso_por_metodo_segue_a_dispersao_do_contador():
    """CV 0.65 (saves), 1.37 (shots), 1.90 (shots_on) · quanto mais disperso o
    contador, mais atuacoes pra media dele valer a mesma coisa."""
    assert POR_SLUG["saves"].min_atuacoes < POR_SLUG["shots"].min_atuacoes
    assert POR_SLUG["shots"].min_atuacoes < POR_SLUG["shots_on"].min_atuacoes


def test_o_metodo_que_funciona_e_a_regua():
    """saves acerta com 4 atuacoes (2 GREEN, 0 RED em PROD) porque 4 ja' lhe
    dao ~22% de erro. Ele nao sobe -- os outros e' que vem ate' ele."""
    assert POR_SLUG["saves"].min_atuacoes == 4
    assert POR_SLUG["shots_on"].min_atuacoes == 12
    assert POR_SLUG["shots"].min_atuacoes == 8


def test_contador_nao_medido_nao_se_mexe():
    """fouls/tackles/passes nao tem oferta hoje e nao foram medidos · subir o
    piso deles seria transpor conclusao de outro contador, que e' o erro que
    esta correcao existe pra desfazer."""
    for slug in ("fouls", "tackles", "passes"):
        assert POR_SLUG[slug].min_atuacoes == 4
