"""O Pick Boost tem que fechar sozinho, como os outros tipos.

O QUE ACONTECIA
---------------
Ele era o UNICO tipo cuja liquidacao automatica dependia de `match_statistics`,
e por JOIN obrigatorio: sem linha na folha, sem resultado, ponto. VIP, free,
mercados proprios e ao vivo leem o fixture da API e fecham assim que o jogo
aparece como FT.

`match_statistics` nao e' preenchida pela varredura de resultado. Ela vem do
`stats_sweep`, que tem freios proprios, ou do botao "Atualizar Jogos" do
/admin. O Boost entao ficava pendente horas depois de o VIP do MESMO dia ja'
ter fechado, e a saida era resolver na mao.

Medido em PROD em 04/09: o pick #6 estava GREEN sem nenhuma linha em
`match_statistics` -- alguem fechou a mao.

O QUE OS CASOS DAQUI PROTEGEM
-----------------------------
  1. o fixture e' a fonte primaria, igual aos outros tipos;
  2. a folha continua valendo como SEGUNDA chance, nao como unica;
  3. sem o placar do intervalo nos dois caminhos, o pick fica PENDENTE. Nunca
     zero. Foi violar isso que gravou RED num pick GREEN em 05/08;
  4. AET/PEN liquida pelos 90 minutos, como o resto do site.
"""
import inspect

from routers import live


def _bloco_do_boost() -> str:
    fonte = inspect.getsource(live.resolve_all_pending)
    inicio = fonte.index("PICK BOOST")
    fim = fonte.index("ANULACAO POR FALTA DE ESTATISTICA")
    return fonte[inicio:fim]


def test_le_o_fixture_como_os_outros_tipos():
    bloco = _bloco_do_boost()
    assert "_fetch_fixtures_bulk" in bloco
    assert "_fetch_fixture(" in bloco
    assert "FT_STATUSES" in bloco


def test_a_folha_virou_segunda_chance_e_nao_exigencia():
    """JOIN obrigatorio era o defeito. LEFT deixa o pick chegar na conta mesmo
    sem folha, e o fixture responde."""
    bloco = _bloco_do_boost()
    assert "LEFT JOIN match_statistics" in bloco
    assert "\n                  JOIN match_statistics" not in bloco


def test_sem_placar_do_intervalo_fica_pendente():
    """A primeira invariante do settlement: ausencia nunca vira zero."""
    bloco = _bloco_do_boost()
    assert "if gols_ft is None or gols_ht is None:" in bloco
    assert "continue" in bloco.split("if gols_ft is None or gols_ht is None:")[1][:120]


def test_prorrogacao_liquida_pelos_90():
    bloco = _bloco_do_boost()
    assert '("AET", "PEN")' in bloco
    assert 'score.get("fulltime")' in bloco


def test_respeita_a_janela_da_varredura():
    """Os outros tipos filtram por `_janela`; o Boost ignorava e varria o
    historico inteiro em toda passada."""
    bloco = _bloco_do_boost()
    assert "{_janela}" in bloco or "_janela" in bloco
    assert "_args()" in bloco


def test_nao_liquida_jogo_que_nao_comecou():
    bloco = _bloco_do_boost()
    assert "nao_iniciados" in bloco


def test_a_janela_vem_qualificada_por_causa_do_join():
    """`_janela` nasce sem tabela ("AND match_date >= %s"), porque os outros
    blocos consultam UMA tabela e ali não há ambiguidade.

    Este passou a fazer LEFT JOIN em `match_statistics`, que também tem
    `match_date`. Sem prefixo o Postgres recusa a consulta inteira com "column
    reference match_date is ambiguous" -- e o erro ABORTA A TRANSAÇÃO, então os
    dois blocos de anulação que vêm depois morrem junto com "current transaction
    is aborted". Um JOIN derrubou três blocos, em produção, no mesmo dia em que
    o JOIN entrou.
    """
    bloco = _bloco_do_boost()
    assert "_janela_pb = _janela.replace" in bloco
    assert "{_janela_pb}" in bloco
    # E o `{_janela}` cru não pode ter sobrado neste bloco.
    corpo_sem_definicao = bloco.replace("_janela_pb = _janela.replace", "")
    assert "{_janela}" not in corpo_sem_definicao


def test_todo_bloco_com_join_qualifica_a_janela():
    """A regra, e não só o caso: bloco que faz JOIN e usa a janela tem que
    qualificar a coluna. É a varredura que pega o próximo JOIN adicionado."""
    fonte = inspect.getsource(live.resolve_all_pending)
    # Cada `cur.execute(f"""...` que contenha JOIN e a janela crua é suspeito.
    import re
    for consulta in re.findall(r'cur\.execute\(f"""(.*?)"""', fonte, re.S):
        if "JOIN" in consulta.upper() and "{_janela}" in consulta:
            raise AssertionError(
                "consulta com JOIN usando a janela sem prefixo de tabela:\n"
                + consulta[:300])
