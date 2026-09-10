"""O radar segurava jogo que ja' tinha acabado (10/09, achado do usuario).

A tela mostrava partidas com "ha 122min" e "ha 137min" como se o motor
estivesse acompanhando, com a frase "a IA entra nesta partida depois dos
primeiros minutos" embaixo -- em jogo que ja' tinha terminado fazia tempo.

Duas fontes, e as duas tinham o mesmo defeito de origem: a janela larga.

  1. A metade LIDA (live_match_observations) so' soltava o jogo quando a
     fixture virava FT ou quando o minuto passava de 90. Jogo encerrado aos
     88' com status atrasado ficava ate' uma hora na tela.

  2. A metade AGUARDANDO (jogo em campo que o motor ainda nao leu) reusava
     `_JANELA_DE_JOGO_MIN`, os 150 minutos que servem pra ACORDAR o motor.
     La' errar pra mais e' de graca; no radar, errar pra mais e' mentir.
"""
from tests.test_home_2026_08 import _codigo


def _consulta() -> str:
    return _codigo("routers/live_picks.py", "em_leitura")


def test_leitura_velha_tira_o_jogo_do_radar():
    """Observacao parada = jogo que o motor nao esta' mais lendo."""
    corpo = _consulta()
    assert "EXTRACT(EPOCH FROM (NOW() - u.observed_at)) <= 1500" in corpo


def test_jogo_sem_leitura_usa_a_janela_do_radar_e_nao_a_de_acordar():
    corpo = _consulta()
    assert "_JANELA_DO_RADAR_MIN" in corpo
    assert "_JANELA_DE_JOGO_MIN" not in corpo, (
        "a janela de acordar o motor (150min) voltou pro radar")


def test_a_janela_do_radar_acompanha_o_fim_da_janela_do_motor():
    from routers import live_picks
    # O motor le' ate' LIVE_MINUTE_END (80' por padrao). Passado isso mais o
    # intervalo, a partida nao sera lida de novo.
    assert live_picks._JANELA_DO_RADAR_MIN == live_picks._MINUTO_FINAL_DO_MOTOR + 25
    assert live_picks._JANELA_DO_RADAR_MIN < 150
