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
def test_tudo_roda_as_nove_etapas_do_pipeline_diario():
    assert [c.etapa for c in main.COMANDOS if c.etapa] == [
        "DADOS", "ODDS", "PICKS VIP", "DICA DO DIA", "MÚLTIPLA",
        "ALAVANCAGEM", "FALTAS", "DEFESAS DE GOLEIRO", "RESULTADOS",
    ]


def test_tudo_nao_e_etapa_de_si_mesmo():
    assert main.COMANDOS_POR_NOME["tudo"].etapa == ""


def test_geradores_de_pick_estao_todos_no_tudo():
    """Escopo de picks: VIP, free, multipla, alavancagem, faltas e goleiros.
    Nenhum tipo pode ficar de fora do pipeline diario por esquecimento."""
    etapas = {c.nome for c in main.COMANDOS if c.etapa}
    assert {"vip", "dica", "multiplas", "alavancagem", "faltas", "goleiros"} <= etapas


@pytest.mark.parametrize("nome, porque", [
    ("player_stats", "gasta 1 requisicao da API por fixture, disputa a cota das odds"),
    ("live", "motor em validacao, so' faz sentido durante os jogos"),
    ("ligas", "chama a Anthropic, custo real por rodada"),
    ("shadow", "so' registra comparacao, nao gera pick"),
])
def test_comandos_caros_ficam_fora_do_tudo(nome, porque):
    assert main.COMANDOS_POR_NOME[nome].etapa == "", porque


# ── Live: dev-only e sem migracao ─────────────────────────────────────────
def test_live_e_shadow_sao_so_de_dev():
    """cmd_live recusa rodar sem DB_ENV=dev (pick_engine_live/config) e o
    shadow compara contra base de homologacao. Oferecer no menu de prod seria
    um botao que so' sabe recusar."""
    assert main.COMANDOS_POR_NOME["live"].ambientes == ("dev",)
    assert main.COMANDOS_POR_NOME["shadow"].ambientes == ("dev",)


def test_live_nao_dispara_as_migracoes_do_pre_jogo():
    """O motor Live provisiona o proprio esquema (live_pipeline.criar_tabelas).
    Rodar a lista de ALTER TABLE do pre-jogo a cada rodada de teste aproximaria
    o produto novo de escrever no esquema do que esta em producao."""
    assert main.COMANDOS_POR_NOME["live"].migrar is False


def test_so_o_live_pula_migracao():
    assert [c.nome for c in main.COMANDOS if not c.migrar] == ["live"]


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


def test_numeracao_conhecida_dos_menus_nao_mudou():
    """As nove etapas em 1-9 e o `tudo` no 10, nos dois wrappers -- e' a
    numeracao que ja estava na mao de quem usa. Comando novo entra no fim."""
    for wrapper in (run_dev, run_prod):
        assert wrapper.OPCOES["1"].nome == "dados", wrapper.__name__
        assert wrapper.OPCOES["9"].nome == "resultados", wrapper.__name__
        assert wrapper.OPCOES["10"].nome == "tudo", wrapper.__name__


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
