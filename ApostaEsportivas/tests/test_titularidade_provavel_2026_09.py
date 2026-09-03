"""O pick de jogador so' sai pra quem tem chance de COMECAR."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.player_stats_engine.player_history import (
    e_titular_provavel, MIN_TAXA_TITULARIDADE)


def _j(taxa, partidas=15):
    return {"taxa_titularidade": taxa, "partidas_do_time": partidas}


def test_titular_fixo_passa():
    assert e_titular_provavel(_j(1.0))
    assert e_titular_provavel(_j(0.8))


def test_reserva_nao_passa():
    """Medido em PROD: 4 atuacoes de 60+ minutos bastavam pro corte antigo,
    mesmo espalhadas em 15 rodadas. Um jogador 4/15 nao e' titular provavel."""
    assert not e_titular_provavel(_j(0.267))
    assert not e_titular_provavel(_j(0.154))


def test_a_fronteira_e_o_limiar_declarado():
    assert e_titular_provavel(_j(MIN_TAXA_TITULARIDADE))
    assert not e_titular_provavel(_j(MIN_TAXA_TITULARIDADE - 0.01))


def test_sem_dado_nao_vira_veto():
    """Time recem-cadastrado, janela vazia: ausencia de dado nao pode barrar
    pick. O motor volta ao comportamento anterior e a varredura de escalacao
    oficial continua sendo a rede de baixo."""
    assert e_titular_provavel(_j(None, partidas=0))
    assert e_titular_provavel(_j(0.1, partidas=3))
    assert e_titular_provavel({})


def test_poucos_jogos_do_time_nao_condena():
    """Com menos de 4 partidas na janela, a fracao e' ruido: 0 de 2 nao quer
    dizer reserva."""
    assert e_titular_provavel(_j(0.0, partidas=2))
