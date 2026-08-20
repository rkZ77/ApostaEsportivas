# -*- coding: utf-8 -*-
"""O CLV estava comparando o pick com OUTRO mercado.

O DEFEITO
---------
`_closing_odd_for` procurava a odd de fechamento em `odds_snapshots` filtrando
so' por (fixture_id, value_name). `value_name` e' um rotulo generico: medido em
PROD em 2026-08-20, 'Over 4.5' aparece em ate' 19 mercados DIFERENTES da mesma
partida. Sem filtrar o mercado, a consulta devolvia a primeira linha que
ordenasse -- e o padrao do que ela devolvia era inconfundivel:

    pick real (PROD)              odd pega   "fechamento"   CLV gravado
    Escanteios Over 4.5              1.67        10.00          -83%
    Escanteios Over 5.5              1.80        19.00          -90%
    Finalizacoes no gol Over 6.5     1.30        51.00          -97%

10.00, 19.00 e 51.00 sao as odds de Over 4.5, Over 5.5 e Over 6.5 de GOLS.

POR QUE ISSO IMPORTA MAIS QUE UM CAMPO ERRADO NUM PAINEL
--------------------------------------------------------
CLV e' o insumo de `market_anchor.peso_por_clv`: CLV negativo empurra o peso do
modelo pro piso, ou seja, faz o motor se render ao mercado naquele mercado. Com
o dado corrompido, ligar a ancoragem teria feito o motor abrir mao da propria
opiniao em escanteios com base numa comparacao que nunca aconteceu.

E o defeito era invisivel justamente onde mais se olha: gols escapou por
coincidencia (o 'Over 1.5' de gols casava com gols), entao o mercado de maior
volume parecia saudavel enquanto os outros pareciam catastroficos.
"""
import pytest

from services import picks_ledger_sync_service as sync


_CONTROLE = ("SAVEPOINT", "RELEASE", "ROLLBACK")


class _CursorFalso:
    """Devolve linhas por consulta, na ordem em que forem pedidas.

    `explode_em` faz a n-esima consulta de DADOS levantar excecao, pra
    exercitar o caminho de savepoint sem precisar de banco."""

    def __init__(self, respostas, explode_em=None):
        self.respostas = list(respostas)
        self.consultas = []
        self.controle = []
        self.explodiu = False
        self.rollbacks_de_conexao = 0
        self.explode_em = explode_em
        self.connection = self

    def execute(self, sql, params=None):
        limpo = " ".join(sql.split())
        if limpo.split(" ")[0].upper() in _CONTROLE:
            self.controle.append(limpo)
            return
        self.consultas.append((limpo, params))
        if self.explode_em is not None and len(self.consultas) == self.explode_em:
            self.explodiu = True
            raise RuntimeError('relation "closing_odds" does not exist')

    def fetchone(self):
        return self.respostas.pop(0) if self.respostas else None

    def rollback(self):
        # E' a conexao INTEIRA. Contar e' o teste: chamar isto no meio da
        # sincronizacao descartaria todas as pernas ja' processadas.
        self.rollbacks_de_conexao += 1


def test_sem_market_id_nao_inventa_fechamento():
    """A regra central. Multipla e alavancagem nao guardam market_id, entao a
    perna fica sem CLV -- que e' o resultado certo. Antes elas recebiam o
    fechamento de um mercado qualquer."""
    cur = _CursorFalso([(10.00,)])
    assert sync._closing_odd_for(cur, 123, "Over 4.5", None) is None
    assert cur.consultas == [], "nao deveria nem consultar o banco"


def test_fechamento_filtra_pelo_mercado_da_perna():
    cur = _CursorFalso([None, (1.72,)])
    assert sync._closing_odd_for(cur, 123, "Over 4.5", 45) == 1.72
    for sql, params in cur.consultas:
        assert "market_id = %s" in sql, sql
        assert 45 in params


def test_closing_odds_tem_prioridade_sobre_o_snapshot():
    """A tabela dedicada e' captura perto do apito; o snapshot e' aproximacao."""
    cur = _CursorFalso([(1.65,)])
    assert sync._closing_odd_for(cur, 123, "Over 4.5", 45) == 1.65
    assert len(cur.consultas) == 1, "achou na primeira, nao consulta o snapshot"


def test_consulta_que_falha_nao_derruba_a_sincronizacao():
    """O risco real: `sync()` faz UM commit no fim de todas as pernas.

    Sem savepoint restariam duas saidas, as duas ruins -- deixar a transacao
    abortada (e ai NENHUMA perna e' gravada) ou chamar conn.rollback() (e ai
    todas as pernas ja' processadas nesta rodada sao perdidas, sem erro).

    Nao e' hipotetico: `closing_odds` e `odds_snapshots` sao criadas por
    run_migrations(), que NAO roda quando o pipeline e' disparado pelo site."""
    # so' uma resposta: a consulta que explode nem chega no fetchone, entao o
    # snapshot (a segunda) e' quem consome ela.
    cur = _CursorFalso([(1.72,)], explode_em=1)
    assert sync._closing_odd_for(cur, 123, "Over 4.5", 45) == 1.72
    assert cur.explodiu, "o teste precisa ter exercitado a falha"
    assert cur.rollbacks_de_conexao == 0, (
        "rollback na conexao inteira descartaria as pernas ja' sincronizadas")
    assert any(c.startswith("ROLLBACK TO SAVEPOINT") for c in cur.controle)


def test_falha_nas_duas_consultas_devolve_none_sem_estourar():
    cur = _CursorFalso([], explode_em=1)
    assert sync._closing_odd_for(cur, 123, "Over 4.5", 45) is None
    assert cur.rollbacks_de_conexao == 0


def test_fixture_ausente_devolve_none():
    cur = _CursorFalso([(1.65,)])
    assert sync._closing_odd_for(cur, None, "Over 4.5", 45) is None


@pytest.mark.parametrize("rotulo,esperado", [
    ("Over 4.5", "4.5"),
    ("Under 10", "10"),
    ("Over 2.25", "2.25"),
    ("Yes", None),
    ("Home", None),
    ("", None),
])
def test_numero_da_linha(rotulo, esperado):
    """O outro lado do mesmo defeito, em scripts/capture_closing_odds.py: la'
    a consulta agrupava por linha e pegava a de MAIOR odd, que num 'Over' e'
    sempre a linha mais distante. Precisa comparar o numero."""
    captura = pytest.importorskip("scripts.capture_closing_odds")
    assert captura._line_number(rotulo) == esperado


def test_market_id_chega_ao_ledger():
    """Sem esta dimensao gravada, nao da' pra auditar CLV depois -- foi a
    ausencia dela que deixou o defeito passar tres semanas."""
    import inspect
    fonte = inspect.getsource(sync)
    assert '"market_id": leg.get("market_id")' in fonte
    assert "market_id, closing_odd, clv" in fonte


def test_fechamento_nao_e_preservado_por_coalesce():
    """closing_odd e clv sao os UNICOS campos sem COALESCE no DO UPDATE. Com
    COALESCE, o valor falso ja' gravado sobreviveria pra sempre, porque o
    caminho corrigido devolve NULL quando nao identifica o mercado."""
    import inspect
    fonte = inspect.getsource(sync)
    assert "closing_odd = EXCLUDED.closing_odd," in fonte
    assert "clv = EXCLUDED.clv," in fonte
    assert "COALESCE(EXCLUDED.closing_odd" not in fonte
