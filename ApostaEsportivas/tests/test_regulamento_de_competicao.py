# -*- coding: utf-8 -*-
"""Regulamento vindo do banco: onde ele entra, e onde ele NAO entra.

A camada existe pra responder a uma pergunta so' -- "esta fase e' de ida e
volta? vale gol fora?" -- em competicao que o motor nao conhece de cabeca. Ela
custa uma chamada de modelo por competicao por temporada, feita fora do
caminho do pick por scripts/descobrir_regulamento.py.

O que estes testes travam e' a HIERARQUIA. Uma tabela preenchida por modelo
nao pode passar na frente de evidencia nem de cadastro conferido, e nao pode
transformar "nao sei" em afirmacao.
"""
import pytest

from services.pick_engine import competition_profile as cp
from services.pick_engine import competition_rules_store as loja
from services.pick_engine import match_context_model as mcm


@pytest.fixture(autouse=True)
def _cache_limpo():
    loja.limpar_cache()
    yield
    loja.limpar_cache()


def _regras(**kw):
    base = {"two_legged_default": None, "fases_de_jogo_unico": frozenset(),
            "away_goals": None, "prorrogacao": None, "penaltis": None}
    base.update(kw)
    return cp.RegrasDeMataMata(**base)


def test_cadastro_a_mao_ganha_do_banco():
    """As sete linhas de _REGRAS sao regulamento conferido e versionado junto
    do codigo. A tabela e' preenchida por um modelo. Quando as duas responderem
    sobre a mesma competicao, a conferida vence."""
    loja._cache = {13: _regras(two_legged_default=False, away_goals=True)}
    regras = cp.regras_de_mata_mata(13)          # 13 = Libertadores, cadastrada
    assert regras.two_legged_default is True
    assert regras.away_goals is False


def test_banco_responde_onde_o_cadastro_nao_conhece():
    """E' o caso que a camada existe pra cobrir: sem ela o motor devolvia
    DESCONHECIDO e parava de saber o formato da fase."""
    assert cp.regras_de_mata_mata(999001).two_legged_default is None
    loja._cache = {999001: _regras(two_legged_default=True,
                                   fases_de_jogo_unico=frozenset({"FINAL"}))}
    assert cp.regras_de_mata_mata(999001).two_legged_default is True
    assert cp.formato_declarado(999001, "QUARTAS") == mcm.COPA_IDA_E_VOLTA
    assert cp.formato_declarado(999001, "FINAL") == mcm.COPA_JOGO_UNICO


def test_evidencia_do_confronto_ganha_do_regulamento():
    """Ordem de autoridade: rotulo > confronto > regulamento > DESCONHECIDO.
    Se a tabela disser "ida e volta" e o confronto disser outra coisa, quem
    manda e' o confronto -- regulamento so' e' consultado quando nao ha
    evidencia."""
    loja._cache = {999002: _regras(two_legged_default=True)}
    ida = {"match_date": None, "home_team_id": 2, "away_team_id": 1,
           "home_goals": 1, "away_goals": 0}
    formato, origem = mcm.resolver_formato(999002, "QUARTAS", None, ida)
    assert (formato, origem) == (mcm.COPA_IDA_E_VOLTA, "confronto")
    # Sem confronto, ai' sim o regulamento responde.
    assert mcm.resolver_formato(999002, "QUARTAS", None, None)[1] == "regulamento"


def test_gol_fora_continua_tri_estado_vindo_do_banco():
    """None do banco tem que continuar chegando como None, nao virar False no
    caminho -- 'nao declarado' e 'nao vale' sao coisas diferentes, e so' True
    literal autoriza qualquer conta de gol fora."""
    loja._cache = {999003: _regras(two_legged_default=True, away_goals=None)}
    tie = mcm.tie_context("Semi-finals", 1, 2, None, league_id=999003)
    assert tie["regras"]["gol_fora"] is None


def test_tabela_indisponivel_nao_derruba_o_motor():
    """Regulamento e' camada auxiliar. Sem tabela, sem modulo ou com o banco
    fora, o motor volta ao comportamento anterior em vez de quebrar."""
    loja.limpar_cache()
    assert cp.regras_de_mata_mata(999004) == cp._REGRAS_PADRAO
    assert mcm.resolver_formato(999004, "QUARTAS", None, None) == (
        mcm.FORMATO_DESCONHECIDO, None)


class _CursorQueFalha:
    """Cursor cuja primeira consulta explode, como acontece quando a tabela
    ainda nao existe naquele banco."""

    def __init__(self):
        self.rollback_chamado = False
        conn = self

        class _Conn:
            def rollback(_self):
                conn.rollback_chamado = True

        self.connection = _Conn()

    def execute(self, *a, **kw):
        raise RuntimeError("relation \"competition_rules\" does not exist")


def test_falha_na_carga_faz_rollback_e_nao_derruba_a_rodada():
    """No psycopg2 um erro deixa a transacao ABORTADA, e toda consulta
    seguinte na MESMA conexao falha com "current transaction is aborted".

    Sem o rollback, uma tabela ausente nesta camada auxiliar derrubaria a
    rodada inteira de picks -- o oposto exato do que ela promete. O teste
    trava as duas metades: nao levanta, e limpa a transacao pra quem vem
    depois."""
    cur = _CursorQueFalha()
    assert loja.carregar(cur) == {}
    assert cur.rollback_chamado is True


def test_pontos_corridos_nunca_consulta_regulamento():
    """Rodada de campeonato nao tem formato de mata-mata pra resolver, e a
    esmagadora maioria dos jogos e' isso."""
    loja._cache = {71: _regras(two_legged_default=True)}
    assert mcm.resolver_formato(71, None, None, None) == (mcm.PONTOS_CORRIDOS, "fase")
