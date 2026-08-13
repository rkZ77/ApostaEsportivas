"""Quem enxerga mata-mata, quem nao enxerga, e por que isso esta certo hoje.

O gate de contexto (context_gate.py) barra pick que contradiz o que a partida
vai ser: volta de mata-mata abre o jogo, entao "Under" de escanteio/cartao/gol
passa a ser a aposta perigosa. Ele esta ligado no VIP, na Dica, na Multipla e
na Alavancagem, e NAO esta em faltas nem em defesas de goleiro.

Isso parece lacuna e foi investigado como tal em 2026-08-13. Nao e', porque o
gate e DIRECIONAL: `pressao_contraria` devolve zero pra qualquer coisa que nao
seja "under" (confirmar nao gera bonus, pra nao contar a mesma evidencia duas
vezes). Faltas so' publica Over e defesas so' publica "N ou mais" -- ligar o
gate nos dois seria codigo que nunca executa.

O que estes testes fazem, entao, nao e' cobrar a ligacao: e' travar a PREMISSA.
No dia em que faltas ou goleiros ganharem um lado Under, eles falham e obrigam
a decisao a ser tomada de novo, em vez de o pick sair sem o gate em silencio.
"""
import inspect

import pytest

from services.pick_engine import context_gate


PIPELINES_COM_GATE = ["vip", "dica", "multipla", "alavancagem"]
PIPELINES_SO_OVER = ["faltas", "goleiros"]


def _fonte(nome: str) -> str:
    from importlib import import_module
    return inspect.getsource(import_module(f"engine_pipelines.{nome}_pipeline"))


@pytest.mark.parametrize("nome", PIPELINES_COM_GATE)
def test_pipeline_que_publica_under_consulta_o_gate(nome):
    """Foi a ausencia disto que deixou passar o "Under cartoes" num
    Fluminense x Vasco de volta valendo classificacao."""
    assert "context_gate.build_for_fixture" in _fonte(nome)


@pytest.mark.parametrize("nome", PIPELINES_SO_OVER)
def test_pipeline_sem_gate_nao_publica_under(nome):
    """A premissa que torna a ausencia do gate correta. Se cair, o pipeline
    passou a ter um lado que o gate protegeria e ninguem ligou."""
    fonte = _fonte(nome).lower()
    assert '"under' not in fonte and "'under" not in fonte, (
        f"{nome}_pipeline passou a publicar Under: o gate de contexto precisa "
        f"ser ligado nele (ver context_gate.FAMILIAS_DIRECIONAIS)"
    )


def test_gate_e_direcional_e_ignora_over():
    """A razao de ligar o gate num pipeline so'-Over ser codigo morto."""
    veredito = context_gate.evaluate(
        {"market_type": "fouls", "value": "over"},
        {"stakes": 0.95, "tie": {"precisa_de_resultado": "ambos"}, "rivalidade": {}},
    )
    assert veredito["penalidade"] == 0.0
    assert veredito["bloqueado"] is False


def test_mesmo_contexto_penaliza_o_under():
    """O outro lado da mesma moeda: com Under, aquele contexto age."""
    veredito = context_gate.evaluate(
        {"market_type": "fouls", "value": "under"},
        {"stakes": 0.95, "tie": {"precisa_de_resultado": "ambos"}, "rivalidade": {}},
    )
    assert veredito["pressao_total"] > 0


def test_faltas_e_familia_direcional_mesmo_sem_gate_ligado():
    """`fouls` esta na lista porque falta tatica sobe junto com o resto quando
    o jogo abre. E' o que fara o gate valer no dia em que houver um Under."""
    assert "fouls" in context_gate.FAMILIAS_DIRECIONAIS


def test_defesas_de_goleiro_nao_e_familia_direcional():
    """Defesa nao sobe junto com o volume ofensivo dos DOIS lados: ela sobe pra
    quem esta sendo pressionado e cai pro outro. Tratar como direcional seria
    afirmar um mecanismo que nao foi medido."""
    assert "saves" not in context_gate.FAMILIAS_DIRECIONAIS
