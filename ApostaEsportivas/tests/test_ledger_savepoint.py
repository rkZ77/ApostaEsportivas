"""Uma perna ruim não pode apagar as pernas boas do mesmo sync.

REGRESSÃO REAL, encontrada em produção (2026-08-29). `sync()` tem UM commit,
no fim. O tratamento de erro por perna chamava `conn.rollback()` -- que no
Postgres desfaz tudo desde o último commit, não só a perna que falhou.

Não era hipotético. `picks_live` gravava `id` NULO (ver
`live_pipeline._reparar_id_de_picks_live`), então 28 pernas estouravam o NOT
NULL de `source_id` no meio da fila. A ordem de `fetch_all_legs` é

    vip -> free -> faltas -> goleiros -> LIVE -> player_stats -> boost
        -> multipla -> alavancagem

e o rollback na primeira falha de `live` desfazia todo o pré-jogo. Só o que
vinha depois do último erro sobrevivia, e o resumo seguia anunciando "476
atualizadas". As linhas de VIP no ledger de PROD ficaram congeladas em 25/08 --
carregando o resultado errado de chute no alvo enquanto a tabela de origem já
tinha sido corrigida.

O sintoma é traiçoeiro porque nada falha: o processo termina em 0, imprime um
resumo com números altos, e o banco não muda.
"""
import inspect

from services import picks_ledger_sync_service as ledger


def _fonte_do_sync() -> str:
    return inspect.getsource(ledger.sync)


def _sem_comentarios(texto: str) -> str:
    """Só o código. O comentário que explica o bug cita `conn.rollback()` pelo
    nome, e sem isto o teste reprovaria a própria documentação da correção."""
    return "\n".join(l for l in texto.splitlines()
                     if not l.lstrip().startswith("#"))


def test_erro_de_perna_nao_desfaz_a_transacao_inteira():
    """`conn.rollback()` dentro do laço é o bug · o certo é voltar ao savepoint."""
    fonte = _sem_comentarios(_fonte_do_sync())
    corpo_do_laco = fonte[fonte.index("for leg in legs:"):]
    assert "ROLLBACK TO SAVEPOINT perna" in corpo_do_laco
    assert "conn.rollback()" not in corpo_do_laco


def test_abre_um_savepoint_por_perna():
    """Sem o SAVEPOINT, o ROLLBACK TO não tem a que voltar e a perna boa
    seguinte herda uma transação abortada."""
    fonte = _fonte_do_sync()
    abertura = fonte.index("SAVEPOINT perna")
    laco = fonte.index("for leg in legs:")
    assert abertura > laco, "o savepoint precisa ser aberto DENTRO do laço"


def test_libera_o_savepoint_em_todo_caminho():
    """Savepoint não liberado se acumula na transação · com ~520 pernas isso
    vira consumo de memória no servidor por sync."""
    fonte = _fonte_do_sync()
    assert "RELEASE SAVEPOINT perna" in fonte
    assert "finally:" in fonte[fonte.index("for leg in legs:"):]


def test_o_commit_continua_sendo_um_so_no_fim():
    """Commit por perna resolveria o mesmo problema e custaria ~520 round-trips
    num banco remoto. A escolha aqui é savepoint; se alguém trocar, que seja
    de propósito."""
    fonte = _fonte_do_sync()
    assert fonte.count("conn.commit()") == 2  # _create_table_if_needed + o final
