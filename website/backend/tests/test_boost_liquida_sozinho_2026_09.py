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
