"""Todo motor usa o contexto atual e revalida a linha antes de publicar (2026-10-08).

Pedido do usuario: "todos os motores tem que utilizar o que voce esta'
criando". A fiacao de um motor novo e' exatamente o tipo de coisa que some em
silencio (ver test_todos_os_motores_2026_10: Multipla e Bingo ja' ficaram de
fora de uma correcao por lerem fixture por outro caminho). Estes testes
prendem a fiacao, motor por motor, e importam cada pipeline pra pegar nome
indefinido antes da producao.
"""
import importlib
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _fonte(caminho: str) -> str:
    with open(os.path.join(SRC, caminho), encoding="utf-8") as fh:
        return fh.read()


#: Motores que passam por analyze_fixture_markets.
GENERICOS = ("vip", "dica", "multipla", "bingo", "alavancagem")
#: Motores de modelo proprio.
PROPRIOS = ("faltas", "pick_boost", "player_stats")


@pytest.mark.parametrize("motor", GENERICOS)
def test_motor_generico_passa_o_contexto(motor):
    fonte = _fonte(f"engine_pipelines/{motor}_pipeline.py")
    assert "contexto_partida=dossie_da_partida.contexto_do_motor(" in fonte


@pytest.mark.parametrize("motor", PROPRIOS)
def test_motor_de_modelo_proprio_usa_o_contexto(motor):
    fonte = _fonte(f"engine_pipelines/{motor}_pipeline.py")
    assert "contexto_atual.probabilidade_para_modelo_proprio(" in fonte
    assert "dossie_da_partida.contexto_do_motor(" in fonte


@pytest.mark.parametrize("motor,chamada", [
    ("vip", "revalidacao.aplicar("), ("dica", "revalidacao.aplicar("),
    ("multipla", "revalidacao.pernas_ok("), ("bingo", "revalidacao.pernas_ok("),
    ("alavancagem", "revalidacao.pernas_ok("),
    ("faltas", "_revalidar_linha("), ("pick_boost", "_revalidar_pernas("),
    ("player_stats", "_revalidar_oferta("),
])
def test_todo_motor_pre_jogo_revalida_antes_da_ia(motor, chamada):
    fonte = _fonte(f"engine_pipelines/{motor}_pipeline.py")
    i_reval = fonte.index(chamada, fonte.index("def ") if chamada.startswith("revalidacao") else 0)
    # A revalidacao vem ANTES da chamada de IA que publica: nao se paga parecer
    # de linha que saiu do ar. (Procura a ultima chamada de revalidacao e o
    # `.apply(` do gate que vem depois dela.)
    ultimo = fonte.rindex(chamada)
    assert ".apply(" in fonte[ultimo:], motor
    assert i_reval > 0


def test_motores_com_historico_de_time_barram_historico_atrasado():
    for motor in ("faltas", "pick_boost"):
        assert "contexto_atual.bloqueio_da_partida(" in _fonte(f"engine_pipelines/{motor}_pipeline.py")


def test_player_stats_nao_publica_jogador_listado_fora():
    fonte = _fonte("engine_pipelines/player_stats_pipeline.py")
    assert 'jogador["player_id"] in fora' in fonte


def test_ao_vivo_grava_o_contexto_de_antes_do_apito():
    fonte = _fonte("engine_pipelines/live_pipeline.py")
    assert '"contexto_pre_jogo": candidato.get("contexto_pre_jogo")' in fonte
    assert "contexto_atual.resumo_para_ia(" in fonte


def test_fechamento_reavalia_os_picks():
    assert "_reavaliar(fixture_id)" in _fonte("capturar_fechamento.py")


@pytest.mark.parametrize("modulo", [
    "engine_pipelines.vip_pipeline", "engine_pipelines.dica_pipeline",
    "engine_pipelines.multipla_pipeline", "engine_pipelines.bingo_pipeline",
    "engine_pipelines.alavancagem_pipeline", "engine_pipelines.faltas_pipeline",
    "engine_pipelines.pick_boost_pipeline", "engine_pipelines.player_stats_pipeline",
    "engine_pipelines.live_pipeline", "capturar_fechamento",
    "services.pick_engine.contexto_atual", "services.pick_engine.revalidacao",
    "services.pick_engine.reavaliacao", "scripts.medir_contexto_atual",
])
def test_todo_modulo_tocado_importa(modulo, monkeypatch):
    # O coletor de odds exige a chave ja' no import; nenhuma chamada sai daqui.
    monkeypatch.setenv("API_FOOTBALL_KEY", os.getenv("API_FOOTBALL_KEY") or "teste-de-import")
    importlib.import_module(modulo)


def test_medicao_esta_no_agendador():
    caminho = os.path.join(os.path.dirname(os.path.dirname(SRC)), "website", "backend",
                           "agendador.py")
    if not os.path.exists(caminho):
        pytest.skip("site fora deste checkout")
    with open(caminho, encoding="utf-8") as fh:
        assert "scripts/medir_contexto_atual.py" in fh.read()
