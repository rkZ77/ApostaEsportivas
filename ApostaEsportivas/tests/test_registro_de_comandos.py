"""O registro COMANDOS de main.py e' a fonte unica da lista de comandos.

Ate 2026-08-11 essa lista vivia copiada em cinco lugares (dispatch do main.py,
HELP, etapas do cmd_tudo, e o par OPCOES/run() de run_dev.py e run_prod.py). O
defeito nunca foi uma copia errada: era uma copia ESQUECIDA. Faltas e goleiros
rodaram semanas dentro do `tudo` sem opcao avulsa nos wrappers, `player_stats`
respondia no dispatch mas nao aparecia no HELP, e o motor Live nasceu
inalcancavel pelo run_dev -- justamente o wrapper do unico ambiente onde ele
aceita rodar.

O que estes testes protegem, entao, nao e' o conteudo da lista (ela vai crescer)
e sim a propriedade de que so existe UMA: os wrappers derivam do registro em vez
de manter a propria. Se alguem reintroduzir um if/elif paralelo, os testes de
paridade abaixo continuam passando por acidente -- por isso ha tambem os que
leem o codigo-fonte dos wrappers e cobram a derivacao.

Nenhum teste aqui toca banco nem executa comando: so' le o registro e o fonte.
"""

import io
import ast
import os

import pytest

import main
import run_dev
import run_prod


SRC = os.path.dirname(os.path.abspath(main.__file__))


def _fonte(nome_modulo: str) -> str:
    with open(os.path.join(SRC, f"{nome_modulo}.py"), encoding="utf-8") as fh:
        return fh.read()


# ── O registro em si ──────────────────────────────────────────────────────
def test_todo_comando_tem_nome_unico():
    nomes = [c.nome for c in main.COMANDOS]
    assert len(nomes) == len(set(nomes)), f"nome repetido em COMANDOS: {nomes}"


def test_indice_por_nome_cobre_o_registro_inteiro():
    assert set(main.COMANDOS_POR_NOME) == {c.nome for c in main.COMANDOS}


def test_todo_comando_declara_label_ajuda_e_ambiente():
    for c in main.COMANDOS:
        assert c.label, f"{c.nome} sem label (menu dos wrappers ficaria vazio)"
        assert c.ajuda, f"{c.nome} sem ajuda (linha do HELP ficaria vazia)"
        assert c.ambientes, f"{c.nome} sem ambiente: nao apareceria em wrapper nenhum"
        assert set(c.ambientes) <= {"dev", "prod"}, f"{c.nome}: ambiente desconhecido"


def test_setup_nao_esta_no_registro():
    """`setup` e' so' as migracoes e o dispatch trata ele antes de consultar o
    registro. Se entrasse aqui viraria opcao de menu que nao gera nada."""
    assert "setup" not in main.COMANDOS_POR_NOME


# ── O `tudo` ──────────────────────────────────────────────────────────────
def test_tudo_roda_as_etapas_do_pipeline_diario():
    """A ORDEM importa e por isso a lista e' literal: dados e odds antes dos
    geradores, e resultados por ultimo.

    PICK BOOST entrou em 2026-08-28, junto com a publicacao dele pro assinante.
    A regra que governa esta lista continua sendo a mesma: produto publicado e'
    gerado todo dia, e motor que ainda nao foi publicado (Player Stats completo,
    Live) fica fora pra nao virar custo fixo da rodada.
    """
    assert [c.etapa for c in main.COMANDOS if c.etapa] == [
        "DADOS", "ESTATISTICA DE JOGADOR", "ODDS", "PICKS VIP", "DICA DO DIA",
        "MÚLTIPLA", "ALAVANCAGEM", "FALTAS", "PICKS DE JOGADOR", "PICK BOOST",
        "RESULTADOS",
        # ESTATISTICA DE JOGADOR entrou em 28/08 e, no mesmo dia, foi movida
        # pra ANTES das odds por pedido do usuario. Ela e' a UNICA etapa com
        # teto fixo (50 fixtures); a coleta de odds pede o que o dia tiver.
        # Com o teto na frente, o custo de jogador e' conhecido antes de a
        # coleta grande comecar.
        # PICK BOOST antes de RESULTADOS nao e' detalhe: gerar depois da
        # liquidacao deixa o pick do dia pendente ate' o dia seguinte.
        #
        # "PICKS DE JOGADOR" era "DEFESAS DE GOLEIRO" ate' 28/08 -- heranca de
        # quando defesas era um motor inteiro. Virou o Player Stats com os
        # metodos marcados `diario` no catalogo (defesas, chutes no alvo,
        # chutes), e a etapa passou a chamar `playerstats-diario`.
    ]


def test_tudo_nao_e_etapa_de_si_mesmo():
    assert main.COMANDOS_POR_NOME["tudo"].etapa == ""


def test_geradores_de_pick_estao_todos_no_tudo():
    """Escopo de picks: nenhum tipo PUBLICADO pode ficar de fora do pipeline
    diario por esquecimento.

    `goleiros` saiu desta lista em 28/08 e NAO e' regressao: defesas continua
    sendo gerada todo dia, agora como um dos metodos de `playerstats-diario`
    (ver `Metodo.diario` no catalogo). O comando `goleiros` continua existindo
    pra rodar so' aquele metodo na mao.
    """
    etapas = {c.nome for c in main.COMANDOS if c.etapa}
    assert {"vip", "dica", "multiplas", "alavancagem", "faltas",
            "playerstats-diario", "pickboost"} <= etapas


def test_defesas_continua_sendo_gerada_todo_dia():
    """A etapa mudou de nome, o produto nao · `saves` tem que continuar entre
    os metodos diarios, senao a aba Jogadores para de receber pick de defesa
    sem ninguem ter decidido isso."""
    from services.player_stats_engine import methods as cat

    diarios = {m.slug for m in cat.DIARIOS}
    assert diarios == {"saves", "shots_on", "shots"}


def test_metodo_novo_nasce_fora_do_pipeline_diario():
    """Mesmo criterio do Pick Boost e do Live: motor sem historico medido nao
    vira custo fixo da rodada. `fouls`, `tackles` e `passes` nunca geraram pick
    real."""
    from services.player_stats_engine import methods as cat

    assert not cat.Metodo.__dataclass_fields__["diario"].default


@pytest.mark.parametrize("nome, porque", [
    ("live", "motor em validacao, so' faz sentido durante os jogos"),
    ("ligas", "chama a Anthropic, custo real por rodada"),
    ("shadow", "so' registra comparacao, nao gera pick"),
])
def test_comandos_caros_ficam_fora_do_tudo(nome, porque):
    assert main.COMANDOS_POR_NOME[nome].etapa == "", porque


def test_a_coleta_de_jogador_entrou_no_tudo():
    """`player_stats` saiu da lista de "caros que ficam de fora" em 28/08.

    O CUSTO nao mudou -- continua 1 requisicao por fixture, disputando a cota
    das odds. O que mudou e' o que o custo COMPRA: enquanto nada lia
    `player_match_stats`, coletar era gasto puro; agora o motor de jogador roda
    todo dia e a aba Jogadores esta' publicada pro assinante.

    Deixar o coletor de fora era rodar o motor sobre uma tabela que so' enche
    quando alguem lembra de clicar, com o pior sintoma possivel: aba vazia, sem
    erro nenhum, indistinguivel de "hoje nao teve oportunidade".

    O custo continua limitado: teto de 50 fixtures por rodada, repartido entre
    as ligas com fila pelo rodizio de `coletar_pendentes`. E' justamente por ter
    teto que ela ficou ANTES das odds (28/08): a coleta de odds nao tem teto,
    entao nesta ordem o custo de jogador e' conhecido antes de a coleta grande
    comecar.
    """
    etapas = [c.nome for c in main.COMANDOS if c.etapa]

    assert "player_stats" in etapas
    # Antes das odds (pedido do usuario) e antes do motor que consome o que ela
    # coleta. Ver o comentario de test_tudo_roda_as_etapas_do_pipeline_diario.
    assert etapas.index("player_stats") < etapas.index("odds")
    assert etapas.index("player_stats") < etapas.index("playerstats-diario")


# ── Live: dev-only e sem migracao ─────────────────────────────────────────
def test_live_e_shadow_sao_so_de_dev():
    """cmd_live recusa rodar sem DB_ENV=dev (pick_engine_live/config) e o
    shadow compara contra base de homologacao. Oferecer no menu de prod seria
    um botao que so' sabe recusar."""
    assert main.COMANDOS_POR_NOME["live"].ambientes == ("dev",)
    assert main.COMANDOS_POR_NOME["shadow"].ambientes == ("dev",)


def test_so_o_setup_dispara_as_migracoes():
    """Nenhum comando roda a lista de ALTER TABLE antes de trabalhar (28/08).

    O `live` ja' era a unica excecao, pelo motivo que agora vale pra todos: o
    esquema esta criado ha' meses e reaplicar dezenas de DDL a cada `vip` /
    `dados` / `pickboost` so' custa. O campo `migrar` do registro saiu junto,
    que era o unico jeito de declarar a excecao.

    O preco esta assumido: coluna nova exige `python main.py setup` na mao,
    PROD inclusive.
    """
    assert not hasattr(main.Comando, "migrar")

    # O despacho e' de nivel de modulo (`if __name__ == "__main__":`), entao
    # nao ha funcao pra inspecionar -- le o arquivo.
    fonte = io.open(main.__file__, encoding="utf-8").read()
    assert 'if cmd == "setup":' in fonte
    assert "alvo.migrar" not in fonte


def test_live_chega_no_menu_do_run_dev():
    """A regressao original: `live` existia no main.py e em lugar nenhum do
    wrapper de dev."""
    assert "live" in {c.nome for c in run_dev.COMANDOS}


def test_live_nao_chega_no_menu_do_run_prod():
    assert "live" not in {c.nome for c in run_prod.COMANDOS}


# ── HELP ──────────────────────────────────────────────────────────────────
def test_help_lista_todo_comando_do_registro():
    """A regressao do `player_stats`: respondia no dispatch e nunca apareceu no
    HELP, entao so' quem ja sabia que ele existia conseguia rodar."""
    for c in main.COMANDOS:
        assert f"  {c.uso or c.nome}" in main.HELP, f"{c.nome} sumiu do HELP"
        assert c.ajuda in main.HELP, f"descricao de {c.nome} sumiu do HELP"


def test_help_menciona_setup():
    assert "setup" in main.HELP


def test_help_traz_os_exemplos_do_live():
    for exemplo in ("live gravar", "live fixture 123456"):
        assert exemplo in main.HELP


# ── Paridade dos wrappers ─────────────────────────────────────────────────
def test_cada_wrapper_expoe_exatamente_os_comandos_do_seu_ambiente():
    assert [c.nome for c in run_dev.COMANDOS] == \
        [c.nome for c in main.COMANDOS if "dev" in c.ambientes]
    assert [c.nome for c in run_prod.COMANDOS] == \
        [c.nome for c in main.COMANDOS if "prod" in c.ambientes]


def test_menus_numeram_a_partir_de_1_sem_buraco():
    for wrapper in (run_dev, run_prod):
        chaves = list(wrapper.OPCOES)
        assert chaves == [str(i) for i in range(1, len(wrapper.COMANDOS) + 1)], wrapper.__name__


def test_a_ordem_conhecida_dos_menus_nao_mudou():
    """O que a mao de quem usa decorou e' a SEQUENCIA, e ela continua:
    `dados` abre, `resultados` fecha as etapas e `tudo` vem logo depois.

    A NUMERACAO ABSOLUTA MUDOU UMA VEZ, em 2026-08-28: `pickboost` virou etapa
    e entrou ANTES de `resultados` -- tinha que ser antes, senao o pick do dia
    nasce depois da liquidacao. Com isso `resultados` foi de 9 pra 10 e `tudo`
    de 10 pra 11.

    O teste passou a cobrar a ordem e nao os numeros de propósito: cravar "9 e'
    resultados" fazia ele reprovar uma etapa nova legitima, que e' exatamente o
    tipo de mudanca que a lista existe pra acomodar. A promessa que fica de pe'
    e' a util: nenhuma etapa se enfia DEPOIS de `resultados`, e `tudo` nunca
    deixa de ser o proximo item.
    """
    for wrapper in (run_dev, run_prod):
        nomes = [c.nome for c in wrapper.COMANDOS]
        assert nomes[0] == "dados", wrapper.__name__

        etapas = [c.nome for c in wrapper.COMANDOS if c.etapa]
        assert etapas[-1] == "resultados", \
            f"{wrapper.__name__}: alguma etapa entrou depois da liquidacao"

        assert nomes[nomes.index("resultados") + 1] == "tudo", wrapper.__name__


def test_run_prod_nao_oferece_comando_de_outro_ambiente():
    for c in run_prod.COMANDOS:
        assert "prod" in c.ambientes, c.nome


# ── A derivacao (o que impede a copia voltar) ─────────────────────────────
@pytest.mark.parametrize("wrapper", ["run_dev", "run_prod"])
def test_wrapper_deriva_do_registro_em_vez_de_manter_lista(wrapper):
    """OPCOES tem que ser construido a partir de main_module.COMANDOS. Um dict
    literal aqui e' exatamente a copia que os cinco lugares tinham."""
    fonte = _fonte(wrapper)
    assert "main_module.COMANDOS" in fonte, \
        f"{wrapper}.py voltou a manter a propria lista de comandos"


@pytest.mark.parametrize("wrapper", ["run_dev", "run_prod"])
def test_wrapper_nao_reintroduziu_dispatch_por_if_elif(wrapper):
    """Cada `elif cmd == "..."` de volta no run() e' uma etapa a mais pra
    esquecer na proxima."""
    arvore = ast.parse(_fonte(wrapper))
    run = next(n for n in ast.walk(arvore)
               if isinstance(n, ast.FunctionDef) and n.name == "run")
    comparacoes = [n for n in ast.walk(run)
                   if isinstance(n, ast.Compare)
                   and isinstance(n.left, ast.Name) and n.left.id == "cmd"]
    assert not comparacoes, \
        f"{wrapper}.run() voltou a comparar `cmd` contra nome de comando"


def test_main_despacha_pelo_indice_e_nao_por_cadeia_de_elif():
    fonte = _fonte("main")
    entrypoint = fonte.split('if __name__ == "__main__":', 1)[1]
    assert "COMANDOS_POR_NOME" in entrypoint
    assert 'elif cmd == "' not in entrypoint


def test_cmd_tudo_monta_as_etapas_a_partir_do_registro():
    fonte = _fonte("main")
    corpo = fonte.split("def cmd_tudo", 1)[1].split("\ndef ", 1)[0]
    assert "for c in COMANDOS if c.etapa" in corpo, \
        "cmd_tudo voltou a escrever a lista de etapas na mao"
