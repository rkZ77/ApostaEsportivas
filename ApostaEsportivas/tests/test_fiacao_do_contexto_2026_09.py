"""Nenhum pipeline pode montar o contexto pela metade sem dizer por que.

O CASO QUE ORIGINOU ESTE TESTE
------------------------------
`context_gate.build_for_fixture` entrega tres coisas: agregado de mata-mata,
rivalidade medida em cartoes e pressao competitiva de tabela. As duas ultimas
so' existem se o chamador passar `convergencia_cartoes` e `league_table` -- sem
elas `rivalry_signal` devolve label "desconhecido" e a pressao sai None. O
motor nao quebra, nao avisa, e decide com menos informacao do que tem.

Em 2026-09-01 um commit corrigiu exatamente isso em dica/multipla/alavancagem
("pressao competitiva de tabela estava cega nesses tres motores") e nao passou
por faltas/boost/player_stats. A omissao sobreviveu porque nada a media: os
tres continuaram passando nos testes, gerando pick e fechando COMPLETED.

O QUE ESTE TESTE FAZ
--------------------
Le a CHAMADA de build_for_fixture em cada pipeline pelo AST e exige que cada
argumento ausente seja uma decisao declarada aqui, com motivo -- em vez de um
esquecimento que ninguem ve. Um pipeline novo entra na lista ou passa os dois.
"""
import ast
import os

import pytest

_PIPELINES = os.path.join(os.path.dirname(__file__), "..", "src", "engine_pipelines")

#: Pipelines que NAO passam `convergencia_cartoes`, e o motivo de cada um. A
#: rivalidade e' medida em pontos de cartao sobre o historico do TIME; onde
#: esse historico nao existe, ligar a camada e' trabalho de coleta e nao um
#: argumento a mais. Sair desta lista exige passar o argumento.
SEM_CONVERGENCIA_DE_CARTOES = {
    "pick_boost_pipeline.py":
        "historico do motor (goals_history) le' so' gols de FT e HT",
    "player_stats_pipeline.py":
        "le' historico de JOGADOR (player_history), nao de time",
    "live_pipeline.py":
        "caminho ao vivo, com orcamento proprio de consulta",
}

#: Pipelines que NAO passam `league_table`. Vazio de proposito: a tabela sai de
#: standings_service com league_id e season, que todo pipeline tem no fixture.
#: Nao ha' motivo tecnico pra faltar em nenhum.
SEM_TABELA_DA_LIGA: dict = {}


def _chamadas_de_build(caminho):
    """Todos os `context_gate.build_for_fixture(...)` de um arquivo."""
    with open(caminho, encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    chamadas = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        alvo = no.func
        nome = alvo.attr if isinstance(alvo, ast.Attribute) else getattr(alvo, "id", None)
        if nome == "build_for_fixture":
            chamadas.append(no)
    return chamadas


def _pipelines_com_contexto():
    for arquivo in sorted(os.listdir(_PIPELINES)):
        if not arquivo.endswith("_pipeline.py"):
            continue
        caminho = os.path.join(_PIPELINES, arquivo)
        if _chamadas_de_build(caminho):
            yield arquivo, caminho


def _passa_convergencia(chamada):
    """3o posicional ou `convergencia_cartoes=`, e nao literalmente None."""
    for kw in chamada.keywords:
        if kw.arg == "convergencia_cartoes":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    if len(chamada.args) >= 3:
        terceiro = chamada.args[2]
        return not (isinstance(terceiro, ast.Constant) and terceiro.value is None)
    return False


def _passa_tabela(chamada):
    for kw in chamada.keywords:
        if kw.arg == "league_table":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def test_existe_pipeline_montando_contexto():
    """Guarda contra o teste virar vacuo se a chamada for renomeada."""
    assert len(list(_pipelines_com_contexto())) >= 6


@pytest.mark.parametrize("arquivo,caminho", list(_pipelines_com_contexto()))
def test_contexto_completo_ou_excecao_declarada(arquivo, caminho):
    for chamada in _chamadas_de_build(caminho):
        if not _passa_convergencia(chamada):
            assert arquivo in SEM_CONVERGENCIA_DE_CARTOES, (
                f"{arquivo} nao passa convergencia_cartoes: a rivalidade nasce "
                f"'desconhecido' e o motor decide sem ela. Passe o argumento ou "
                f"declare o motivo em SEM_CONVERGENCIA_DE_CARTOES."
            )
        if not _passa_tabela(chamada):
            assert arquivo in SEM_TABELA_DA_LIGA, (
                f"{arquivo} nao passa league_table: a pressao competitiva nasce "
                f"None e o motor fica cego a 'time que precisa vencer pra nao "
                f"cair'. A tabela sai de standings_service com league_id e "
                f"season, que este pipeline ja' tem."
            )


def test_os_tres_pipelines_corrigidos_em_02_09_passam_a_tabela():
    """Trava explicita do que foi corrigido: faltas, boost e player_stats
    ficaram de fora da correcao de 01/09 e entraram em 02/09."""
    for arquivo in ("faltas_pipeline.py", "pick_boost_pipeline.py",
                    "player_stats_pipeline.py"):
        caminho = os.path.join(_PIPELINES, arquivo)
        chamadas = _chamadas_de_build(caminho)
        assert chamadas, f"{arquivo} deixou de montar contexto"
        assert all(_passa_tabela(c) for c in chamadas), arquivo


def test_faltas_passa_a_rivalidade():
    """Faltas e' o caso em que a camada mais pesa -- rivalidade e' medida em
    pontos de cartao, o proxy mais direto de jogo quente, e jogo quente e' onde
    falta se multiplica. Diferente de boost e player_stats, aqui o historico do
    time existe, entao nao ha' motivo pra ficar de fora."""
    caminho = os.path.join(_PIPELINES, "faltas_pipeline.py")
    assert all(_passa_convergencia(c) for c in _chamadas_de_build(caminho))
    assert "faltas_pipeline.py" not in SEM_CONVERGENCIA_DE_CARTOES
