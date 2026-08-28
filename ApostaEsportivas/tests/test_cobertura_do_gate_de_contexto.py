"""Quem enxerga mata-mata, quem nao enxerga, e por que isso esta certo hoje.

O gate de contexto (context_gate.py) barra pick que contradiz o que a partida
vai ser: volta de mata-mata abre o jogo, entao "Under" de escanteio/cartao/gol
passa a ser a aposta perigosa. Ele esta ligado no VIP, na Dica, na Multipla e
na Alavancagem.

FALTAS E GOLEIROS: A PREMISSA MUDOU EM 2026-08-20
--------------------------------------------------
Ate aqui este arquivo defendia que a ausencia de contexto nos dois era
correta, porque o GATE e' direcional (so' age em "under") e os dois pipelines
so' publicam Over -- liga-lo ali seria codigo que nunca executa. Isso continua
verdade sobre o GATE, e continua testado abaixo.

O que estava errado era a conclusao mais ampla que se tirava disso: que os dois
nao precisavam de contexto nenhum. Precisavam, e por dois caminhos que o gate
nao cobre:

  FALTAS   e' a familia com o efeito medido mais forte de todos -- o lado que
           precisa reverter comete 2.48 faltas A MENOS por jogo (3.9
           erros-padrao) e o que administra tambem cai. Como o pipeline so'
           publica Over, o agregado aberto joga direto contra o pick, e o gate
           (que so' olha Under) nunca veria isso.

  GOLEIROS nao tem efeito de direcao medido (defesas deram +0.79 ep 1.22 e
           +0.01 ep 0.89, zero nos dois papeis). Mas a media de chutes no alvo
           do adversario sai dos jogos NORMAIS dele, e uma volta com 5 gols de
           diferenca no agregado nao pertence aquela distribuicao -- e isso e'
           incerteza, que custa probabilidade.

Os dois passaram a chamar tie_effect.aplicar_em_analise(), que e' a camada
certa: ela age nos dois sentidos e nao depende de existir um lado "under".
"""
import inspect

import pytest

from services.pick_engine import context_gate


PIPELINES_COM_GATE = ["vip", "dica", "multipla", "alavancagem"]
# `goleiros` SAIU DESTA LISTA em 2026-08-28, e nao porque o mercado acabou.
#
# O goleiros_pipeline foi apagado e defesas passou a ser o metodo `saves` do
# Player Stats desde 27/08. Ao apontar as assercoes pro sucessor, elas FALHAM:
# `player_stats_pipeline.py` nao chama `context_gate.build_for_fixture` nem
# `tie_effect.aplicar_em_analise`.
#
# Ou seja: a camada de contexto de competicao que este arquivo protege existe
# em faltas, existia no pipeline que gerava defesas, e NAO existe no motor que
# gera defesas hoje. E' uma lacuna real, aberta na migracao de 27/08, que so'
# ficou visivel quando o arquivo morto saiu do caminho -- o teste vinha
# passando por ler um pipeline que nao roda mais.
#
# Ela fica registrada no xfail logo abaixo em vez de sumir daqui. Ligar a
# camada no Player Stats e' decisao de motor (o efeito medido do agregado
# contraria a intuicao em varios contadores) e nao cabe numa limpeza de
# comando.
PIPELINES_SO_OVER = ["faltas"]


def _fonte(nome: str) -> str:
    from importlib import import_module
    return inspect.getsource(import_module(f"engine_pipelines.{nome}_pipeline"))


@pytest.mark.parametrize("nome", PIPELINES_COM_GATE)
def test_pipeline_que_publica_under_consulta_o_gate(nome):
    """Foi a ausencia disto que deixou passar o "Under cartoes" num
    Fluminense x Vasco de volta valendo classificacao."""
    assert "context_gate.build_for_fixture" in _fonte(nome)


@pytest.mark.parametrize("nome", PIPELINES_SO_OVER)
def test_pipeline_de_mercado_proprio_consulta_o_contexto(nome):
    """A lacuna real, fechada em 2026-08-20. Nao e' o gate (aquele so' olha
    Under e aqui so' ha Over) -- e' o efeito medido do agregado."""
    fonte = _fonte(nome)
    assert "context_gate.build_for_fixture" in fonte
    assert "tie_effect.aplicar_em_analise" in fonte


@pytest.mark.parametrize("nome", PIPELINES_SO_OVER)
def test_pipeline_sem_gate_nao_publica_under(nome):
    """A premissa que torna a ausencia do gate correta. Se cair, o pipeline
    passou a ter um lado que o gate protegeria e ninguem ligou."""
    fonte = _fonte(nome).lower()
    assert '"under' not in fonte and "'under" not in fonte, (
        f"{nome}_pipeline passou a publicar Under: o gate de contexto precisa "
        f"ser ligado nele (ver context_gate.FAMILIAS_DIRECIONAIS)"
    )


@pytest.mark.xfail(strict=True, reason=(
    "lacuna aberta na migracao de 27/08: defesas virou metodo do Player Stats "
    "e o motor novo nao herdou a camada de contexto de competicao. Quando "
    "alguem ligar, este teste passa e o strict avisa pra promove-lo a assercao "
    "normal e devolver 'player_stats' a PIPELINES_SO_OVER."))
def test_o_motor_de_jogador_deveria_olhar_o_contexto_da_competicao():
    """O que faltas faz e o Player Stats nao.

    A media de chutes no alvo do adversario sai dos jogos NORMAIS dele, e uma
    volta de mata-mata com 5 gols de diferenca no agregado nao pertence aquela
    distribuicao. Valia pro goleiros_pipeline e vale igual pro sucessor.
    """
    fonte = _fonte("player_stats")
    assert "context_gate.build_for_fixture" in fonte
    assert "tie_effect.aplicar_em_analise" in fonte


def test_gate_e_direcional_e_ignora_over():
    """A razao de ligar o gate num pipeline so'-Over ser codigo morto."""
    veredito = context_gate.evaluate(
        {"market_type": "corners", "value": "over"},
        {"stakes": 0.95, "tie": {"precisa_de_resultado": "ambos"}, "rivalidade": {}},
    )
    assert veredito["penalidade"] == 0.0
    assert veredito["bloqueado"] is False


def test_mesmo_contexto_penaliza_o_under():
    """O outro lado da mesma moeda: com Under, aquele contexto age."""
    veredito = context_gate.evaluate(
        {"market_type": "corners", "value": "under"},
        {"stakes": 0.95, "tie": {"precisa_de_resultado": "ambos"}, "rivalidade": {}},
    )
    assert veredito["pressao_total"] > 0


def test_faltas_saiu_da_lista_direcional_por_medicao():
    """A linha anterior deste teste afirmava o oposto: que `fouls` estava na
    lista "porque falta tatica sobe junto com o resto quando o jogo abre".

    Isso nunca tinha sido medido, e quando foi (2026-08-19, jogos de volta
    reais da base) saiu invertido: o lado que precisa reverter comete 2.48
    faltas A MENOS por jogo, o sinal mais forte de toda a medicao. Quem
    persegue o resultado tem a bola, e quem tem a bola nao comete falta.

    Com `fouls` na lista, este gate e tie_effect empurravam o mesmo Under em
    sentidos opostos. O teste inverte junto pra a premissa continuar escrita
    onde ela vale -- e pra que voltar a incluir `fouls` exija desfazer a
    medicao, nao so' editar uma tupla."""
    assert "fouls" not in context_gate.FAMILIAS_DIRECIONAIS


def test_defesas_de_goleiro_nao_e_familia_direcional():
    """Defesa nao sobe junto com o volume ofensivo dos DOIS lados: ela sobe pra
    quem esta sendo pressionado e cai pro outro. Tratar como direcional seria
    afirmar um mecanismo que nao foi medido."""
    assert "saves" not in context_gate.FAMILIAS_DIRECIONAIS
