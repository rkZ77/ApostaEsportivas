"""O "Rodar Tudo" do admin tem que cobrir o mesmo que o `main.py tudo`.

`_TUDO_STEPS` nasceu junto com o scheduler das 00:10 (9cdeb70e) sem
`atualizar_resultados`, e o scheduler foi removido em 2026-08-01 sem que
ninguem revisitasse a lista. Resultado: o botao que o usuario usa pra "rodar o
dia" era o unico caminho que nunca liquidava pick -- o CLI liquidava, o botao
avulso liquidava, o "Rodar Tudo" nao.

Nao ha banco nem subprocesso aqui: le-se a lista de passos e o mapa de scripts.
"""

import ast
import os

import pytest


BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN = os.path.join(BACKEND, "routers", "admin.py")


def _avaliar(no):
    """literal_eval que tambem resolve os.path.join -- e' assim que
    _PIPELINE_SCRIPTS monta os caminhos ("engine_pipelines/vip_pipeline.py")."""
    if isinstance(no, ast.Call):
        alvo = ast.unparse(no.func)
        if alvo.endswith("path.join"):
            return os.path.join(*[_avaliar(a) for a in no.args])
        raise AssertionError(f"chamada nao suportada no literal: {alvo}")
    if isinstance(no, ast.Dict):
        return {_avaliar(k): _avaliar(v) for k, v in zip(no.keys, no.values)}
    if isinstance(no, (ast.List, ast.Tuple)):
        return [_avaliar(e) for e in no.elts]
    return ast.literal_eval(no)


def _literal(nome: str):
    """Valor de uma atribuicao de modulo em admin.py, sem importar o router
    (que puxaria FastAPI, banco e o resto do backend)."""
    with open(ADMIN, encoding="utf-8") as fh:
        arvore = ast.parse(fh.read())
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(
            isinstance(a, ast.Name) and a.id == nome for a in no.targets
        ):
            return _avaliar(no.value)
    raise AssertionError(f"{nome} nao encontrado em admin.py")


@pytest.fixture(scope="module")
def passos():
    return _literal("_TUDO_STEPS")


@pytest.fixture(scope="module")
def rotulos():
    return _literal("_STEP_LABELS")


def test_rodar_tudo_atualiza_resultados(passos):
    """A regressao. Sem esta etapa o pick fica 'Pendente' pra todo mundo ate
    alguem clicar no botao avulso."""
    assert "atualizar_resultados" in passos


def test_resultados_e_a_ultima_etapa(passos):
    """Liquidar antes de gerar resolveria o dia anterior e ignoraria o de hoje."""
    assert passos[-1] == "atualizar_resultados"


def test_coleta_vem_antes_da_geracao(passos):
    """Gerar pick antes de coletar odds do dia usa cotacao da vespera."""
    assert passos.index("atualizar_jogos") < passos.index("capturar_odds")
    assert passos.index("capturar_odds") < passos.index("gerar_vip")


def test_todo_tipo_de_pick_entra_no_rodar_tudo(passos):
    """VIP, free, multipla, alavancagem, faltas e defesas de goleiro."""
    assert {"gerar_vip", "gerar_free", "gerar_multipla",
            "gerar_alavancagem", "gerar_faltas", "gerar_goleiros"} <= set(passos)


def test_todo_passo_tem_rotulo(passos, rotulos):
    """A tela de espera do usuario mostra `_STEP_LABELS[key]` direto: passo sem
    rotulo levanta KeyError em pipeline_status_public."""
    faltando = [p for p in passos if p not in rotulos]
    assert not faltando, f"passos sem rotulo em _STEP_LABELS: {faltando}"


def test_nao_ha_rotulo_orfao(passos, rotulos):
    """Rotulo tem que corresponder a um passo que existe de verdade -- os de
    _TUDO_STEPS ou os de _DEV_PIPELINE_STEPS (tela de homologacao). Um rotulo
    solto e' passo que foi renomeado ou removido sem limpar aqui."""
    conhecidos = set(passos) | set(_literal("_DEV_PIPELINE_STEPS"))
    orfaos = set(rotulos) - conhecidos
    assert not orfaos, f"rotulos sem passo correspondente: {sorted(orfaos)}"


def test_todo_passo_tem_script(passos):
    scripts = _literal("_PIPELINE_SCRIPTS")
    faltando = [p for p in passos if p not in scripts]
    assert not faltando, f"passos sem script em _PIPELINE_SCRIPTS: {faltando}"


def test_player_stats_fica_fora_do_rodar_tudo(passos):
    """1 requisicao da API por fixture, disputando a cota diaria da coleta de
    odds. Botao separado, sob demanda."""
    assert "player_stats" not in passos


def test_rodar_tudo_nao_dispara_passo_de_homologacao(passos):
    """Os `dev_*` rodam contra a base de DEV e alguns chamam IA."""
    assert not [p for p in passos if p.startswith("dev_")]


def test_geradores_apontam_pro_motor_e_nao_pra_ia(passos):
    """Ja aconteceu duas vezes de um botao continuar ligado no pipeline de IA
    depois do corte de 2026-07-17 (custo real por clique)."""
    scripts = _literal("_PIPELINE_SCRIPTS")
    for passo in passos:
        if passo.startswith("gerar_"):
            assert "engine_pipelines" in scripts[passo], passo
            assert not scripts[passo].startswith("ai"), passo
