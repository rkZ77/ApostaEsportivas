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
    """Rotulo tem que corresponder a um COMANDO que existe de verdade.

    Ate' 27/08 o universo eram so' _TUDO_STEPS e _DEV_PIPELINE_STEPS. Passaram
    a existir comandos com script e rotulo que NAO sao etapa da rodada diaria
    (gerar_playerstats, gerar_pickboost), pelo mesmo criterio que main.py usa:
    motor sem historico medido nao vira custo fixo do `tudo`. Eles tem botao
    proprio no /admin e precisam de rotulo.

    A garantia que importa continua de pe' e ficou ate' mais forte: rotulo sem
    COMANDO e' passo renomeado ou removido sem limpar aqui, e agora a checagem
    e' contra _PIPELINE_SCRIPTS, que e' quem de fato define o que existe.
    """
    conhecidos = (set(passos)
                  | set(_literal("_DEV_PIPELINE_STEPS"))
                  | set(_literal("_PIPELINE_SCRIPTS")))
    orfaos = set(rotulos) - conhecidos
    assert not orfaos, f"rotulos sem comando correspondente: {sorted(orfaos)}"


def test_defesas_aponta_pro_motor_que_a_rodada_diaria_usa():
    """O botao "Gerar Defesas" rodava o pipeline ERRADO ate' 27/08.

    Na arquitetura de motores, defesa de goleiro deixou de ser motor e virou o
    metodo `saves` do Player Stats. `main.py tudo` ja' chamava o novo; este
    botao continuou apontando pro goleiros_pipeline.py, que so' existe no disco
    como rollback. Os dois gravam em TABELAS DIFERENTES (picks_goleiros contra
    picks_player_stats), entao clicar no admin produzia um pick que a rodada
    diaria nao produziria -- e vice-versa.
    """
    scripts = _literal("_PIPELINE_SCRIPTS")
    args = _literal("_PIPELINE_ARGS")

    assert scripts["gerar_goleiros"].endswith("player_stats_pipeline.py")
    # E so' o metodo `saves`: sem o argumento, o botao rodaria os seis metodos
    # e publicaria prop de chute/desarme/passe sem ninguem ter pedido.
    assert args.get("gerar_goleiros") == ["saves"]


def test_os_motores_novos_tem_botao_e_ficam_fora_do_tudo(passos):
    """Fora do "Rodar Tudo" e' decisao, nao esquecimento (ver main.py: motor
    sem historico medido nao vira custo fixo da rodada diaria). Mas sem botao
    a unica forma de roda-los era a linha de comando."""
    scripts = _literal("_PIPELINE_SCRIPTS")

    for cmd in ("gerar_playerstats", "gerar_pickboost"):
        assert cmd in scripts, f"{cmd} sem script"
        assert cmd not in passos, f"{cmd} nao pode ser etapa do Rodar Tudo"


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
