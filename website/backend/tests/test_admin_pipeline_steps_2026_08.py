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
    """Valor de uma constante de modulo do admin.py.

    LE O MODULO IMPORTADO desde 2026-08-28, e nao mais o fonte por AST.

    A leitura por AST existia pra nao puxar FastAPI e banco no import -- um
    cuidado que deixou de valer (o resto da suite importa `routers.admin` sem
    problema) e que passou a MENTIR: `_TUDO_STEPS` deixou de ser literal e
    virou derivacao do registro do motor, entao "avaliar a atribuicao" nao
    responde mais qual sequencia o botao roda de verdade.

    Ler o valor real e' o que o teste sempre quis dizer.
    """
    import routers.admin as admin

    try:
        return getattr(admin, nome)
    except AttributeError:
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
    """Nenhum produto PUBLICADO pode ficar de fora do "Rodar Tudo".

    `gerar_goleiros` saiu da lista em 28/08 e nao e' regressao: defesas
    continua sendo gerada todo dia, dentro de `gerar_playerstats` (que roda os
    metodos marcados `diario` no catalogo do motor -- defesas, chutes no alvo e
    chutes). O botao avulso de Defesas continua existindo.
    """
    assert {"gerar_vip", "gerar_free", "gerar_multipla", "gerar_alavancagem",
            "gerar_faltas", "gerar_playerstats", "gerar_pickboost"} <= set(passos)


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


def test_produto_publicado_e_gerado_todo_dia(passos):
    """Pick Boost ENTROU no "Rodar Tudo" em 2026-08-28.

    Ele nasceu fora, pelo criterio que ainda vale pro Player Stats completo e
    pro Live: motor sem historico medido nao vira custo fixo da rodada diaria.
    O que mudou foi o produto, nao o criterio -- ele foi publicado pro
    assinante, com um pick gratuito por dia, e produto publicado TEM que ser
    gerado todo dia: senao a aba abre vazia e ninguem sabe por que.

    As duas coisas andam juntas, e este teste e' o que trava isso: se alguem
    tirar o Boost do `tudo` sem despublicar, a aba comeca a mentir.
    """
    assert "gerar_pickboost" in passos, "produto publicado tem que rodar no dia"


def test_o_passo_de_jogador_roda_so_os_metodos_diarios(passos):
    """Tres dos seis metodos rodam todo dia (defesas, chutes no alvo, chutes).

    `fouls`, `tackles` e `passes` nunca geraram pick real e continuam de fora --
    mesmo criterio que segurou o Pick Boost ate' ele ser publicado. Sem o
    argumento, o passo rodaria os SEIS e publicaria prop de desarme e passe sem
    ninguem ter pedido.

    A lista sai do CATALOGO do motor (`Metodo.diario`), e nao de uma copia
    aqui: promover um metodo tem que ser uma linha so'.
    """
    args = _literal("_PIPELINE_ARGS")

    assert "gerar_playerstats" in passos
    assert set(args["gerar_playerstats"]) == {"saves", "shots_on", "shots"}


def test_todo_passo_tem_script(passos):
    scripts = _literal("_PIPELINE_SCRIPTS")
    faltando = [p for p in passos if p not in scripts]
    assert not faltando, f"passos sem script em _PIPELINE_SCRIPTS: {faltando}"


def test_a_coleta_de_jogador_entrou_no_rodar_tudo(passos):
    """ENTROU em 2026-08-28, e a razao que a mantinha fora se inverteu.

    O motivo antigo -- "1 requisicao por fixture, disputa a cota das odds" --
    continua verdade sobre o CUSTO. O que mudou e' o que o custo compra:
    enquanto nada lia `player_match_stats`, coletar era gasto puro. Agora o
    motor de jogador roda todo dia e a aba Jogadores esta' publicada, entao
    deixar o coletor de fora seria rodar o motor sobre uma tabela que so' enche
    quando alguem lembra de clicar -- com o pior sintoma possivel: aba vazia,
    sem erro, indistinguivel de "hoje nao teve oportunidade".

    ANTES DAS ODDS desde 28/08, por pedido do usuario. Ela nasceu depois, com o
    argumento de que odd alimenta TODOS os motores e estatistica de jogador
    alimenta um. A inversao tem razao propria: esta etapa e' a UNICA com teto
    fixo (50 fixtures) e fila que so' cresce, enquanto a coleta de odds pede o
    que o dia tiver -- com o teto na frente, o custo de jogador e' conhecido
    antes de a coleta grande comecar.
    """
    assert "player_stats" in passos
    assert passos.index("player_stats") < passos.index("capturar_odds")
    assert passos.index("player_stats") < passos.index("gerar_playerstats")


def test_a_sequencia_do_site_e_a_MESMA_do_motor():
    """E' o que o usuario pediu: "um unico modo onde roda uma coisa e ele roda
    todos os motores, e espelha na aba pipeline".

    `_TUDO_STEPS` era uma lista literal aqui, paralela ao registro do main.py, e
    as duas divergiram DUAS vezes so' nesta semana -- o botao "Gerar Defesas"
    chamando o pipeline de rollback, e a coleta de jogador entrando no `tudo` do
    motor sem entrar no do site.

    Agora ela e' DERIVADA. Este teste compara com a fonte.
    """
    import importlib.util
    import os as _os

    import routers.admin as admin

    if not admin._PIPELINE_DIR:
        pytest.skip("motor fora do path neste ambiente")

    # Carregado por CAMINHO, com nome proprio · `import main` resolveria pro
    # main.py do SITE, que ja' esta' em sys.modules quando a suite roda. Foi
    # exatamente essa colisao que derrubou 30 testes de outros arquivos.
    with admin._motor_no_path():
        spec = importlib.util.spec_from_file_location(
            "_motor_main_teste", _os.path.join(admin._PIPELINE_DIR, "main.py"))
        motor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(motor)

    do_motor = [admin._PASSO_DO_COMANDO[c.nome] for c in motor.COMANDOS
                if c.etapa and c.nome in admin._PASSO_DO_COMANDO]
    assert admin._TUDO_STEPS == do_motor

    # E nenhuma etapa do motor pode ficar SEM traducao · ela sumiria do botao.
    sem_traducao = [c.nome for c in motor.COMANDOS
                    if c.etapa and c.nome not in admin._PASSO_DO_COMANDO]
    assert not sem_traducao, f"etapas do motor que o /admin nao sabe rodar: {sem_traducao}"


def test_a_lista_congelada_descreve_o_mesmo_que_o_motor():
    """O fallback existe pra o painel nao ficar sem passo nenhum num ambiente
    sem PIPELINE_SRC_PATH · nao pra ser mantido em paralelo."""
    import routers.admin as admin

    assert admin._TUDO_STEPS_FALLBACK == admin._TUDO_STEPS


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
