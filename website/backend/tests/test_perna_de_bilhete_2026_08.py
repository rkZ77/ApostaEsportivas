"""Perna de multipla/alavancagem guarda o resultado DELA (16/08).

O usuario abriu uma multipla marcada RED, foi conferir as duas pernas e nenhuma
tinha perdido. O bilhete estava certo; as pernas, nao.

Origem: quatro call sites escreviam `legs_results = ["RED"] * len(legs_out)`
como atalho pra fechar o bilhete sem esperar as outras pernas. O atalho e'
valido PRO BILHETE (uma perna RED mata a multipla), mas ele era passado adiante
pra funcao que grava, e ela carimbava RED em toda perna do JSONB `games` --
inclusive nas que ganharam e nas que nem tinham jogado.

Vale notar por que nao foi pego antes: o commit ffffbf31 ja tinha corrigido a
TELA (a perna passou a ler o resultado dela em vez do resultado do bilhete).
Isso nao consertou nada -- so trocou "a tela inventa o X" por "a tela mostra
fielmente o X errado que foi gravado". Quem escreve era o problema.

Nada aqui abre conexao: o conftest ja bloqueia get_connection.
"""
import inspect

import pytest

from routers import live


# ─────────────────── 1. O atalho nao vaza mais pras pernas ───────────────────
def test_nenhum_call_site_carimba_red_em_todas_as_pernas():
    """A forma exata do bug: `["RED"] * len(...)`.

    Olha a arvore sintatica, e nao o texto do arquivo, porque o proprio
    docstring de `_bilhete_morto` cita o trecho errado pra explicar o que
    aconteceu · varredura por regex reprovaria a documentacao do bug junto
    com o bug.
    """
    import ast

    arvore = ast.parse(inspect.getsource(live))
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.BinOp) and isinstance(no.op, ast.Mult)):
            continue
        lado = no.left if isinstance(no.left, ast.List) else no.right
        if not isinstance(lado, ast.List) or len(lado.elts) != 1:
            continue
        item = lado.elts[0]
        assert not (isinstance(item, ast.Constant) and item.value == "RED"), (
            f"linha {no.lineno}: voltou o carimbo de RED em todas as pernas · "
            "feche o bilhete com forced_result e preserve leg_results"
        )


def test_bilhete_morto_e_uma_funcao_so():
    """Estava escrito a mao em quatro lugares, e nos quatro do mesmo jeito
    errado. Uma copia divergente e' como o bug nasceu."""
    src = inspect.getsource(live)
    assert src.count("def _bilhete_morto") == 1
    # Os quatro call sites (2 multipla + 2 alavancagem) passaram a usar.
    assert src.count("_bilhete_morto(") >= 5   # 1 def + 4 usos


@pytest.mark.parametrize("fn", ["_save_multipla_result", "_save_alavancagem_result"])
def test_forced_result_fecha_o_bilhete_sem_tocar_nas_pernas(fn):
    src = inspect.getsource(getattr(live, fn))
    assert "forced_result" in src
    # O lucro do bilhete morto sai da tabela por resultado, nao de combine_legs:
    # com perna em aberto nao da pra recompor a odd efetiva.
    assert "_profit_for_result" in src


# ─────────────────── 2. A regra do bilhete continua a mesma ───────────────────
def test_uma_perna_red_mata_o_bilhete():
    assert live._bilhete_morto(["GREEN", "RED"]) is True
    assert live._bilhete_morto(["RED", None]) is True       # sem esperar o resto
    assert live._bilhete_morto([None, "GREEN"]) is False
    assert live._bilhete_morto(["GREEN", "GREEN"]) is False


def test_perna_em_aberto_nao_fecha_bilhete_sozinha():
    """Sem RED e sem todas encerradas, o bilhete continua pendente."""
    assert live._multipla_combined_result(["GREEN", None], [1.5, 2.0], 3.0) is None


# ─────────────────── 3. A gravacao preserva None ───────────────────
def test_perna_nao_jogada_fica_nula_no_jsonb():
    """None tem que sobreviver ate o JSONB · e' o que diferencia "nao jogou" de
    "perdeu". Carimbar RED aqui foi exatamente o bug."""
    import json

    class Cur:
        def __init__(self): self._r = None
        def execute(self, sql, params=()):
            self._r = {"games": json.dumps([{"market": "A"}, {"market": "B"}])}
        def fetchone(self): return self._r

    saida = live._gravar_resultado_das_pernas(Cur(), "picks_multiplas", 1, ["RED", None])
    pernas = json.loads(saida)
    assert pernas[0]["result"] == "RED"
    assert pernas[1]["result"] is None


def test_tamanho_divergente_nao_anota_nada():
    """Anotar por indice com listas de tamanhos diferentes poria o resultado de
    uma perna em cima de outra."""
    import json

    class Cur:
        def __init__(self): self._r = None
        def execute(self, sql, params=()):
            self._r = {"games": json.dumps([{"market": "A"}, {"market": "B"}])}
        def fetchone(self): return self._r

    assert live._gravar_resultado_das_pernas(Cur(), "picks_multiplas", 1, ["RED"]) is None
