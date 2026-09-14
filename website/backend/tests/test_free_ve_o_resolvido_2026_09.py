"""O pick que já terminou deixa de ser invisível pra quem não assina.

Pedido dele: o free não pode ver o pick enquanto a odd vale, mas depois que ele
resolveu, deveria ver. O motivo é de conversão: é o argumento que responde
"funciona?" no lugar onde a pessoa decide.

O ACHADO QUE MUDOU O DESENHO: isso já era público. `/public/results` entrega
market, line, odd e result de todo pick resolvido, VIP inclusive, sem login
nenhum, porque a página de Resultados sempre foi aberta. O que havia era uma
incoerência: o mesmo pick aparecia ABERTO em /resultados e em LUGAR NENHUM na
aba de Picks, já que todo teaser filtra `result IS NULL`.

Então aqui não se abriu nada novo. Trouxe-se pro lugar que convence o que já
estava aberto no lugar que ninguém olhava.

O LIMITE, e é o que estes testes guardam: o `reasoning` não vai junto. O pick
resolvido diz O QUE foi apostado e como terminou. POR QUE o motor escolheu
aquilo continua sendo a análise, e a análise é o que se paga.
"""
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"


def _consulta_dos_resolvidos() -> str:
    src = (_BACKEND / "routers" / "suggestions.py").read_text(encoding="utf-8")
    ini = src.index("resolvidos_vip = _safe_query(")
    return src[ini:src.index('""", _d)', ini)]


def _colunas_de(consulta: str) -> str:
    """Só a lista do SELECT, até o FROM.

    O que expõe dado é a COLUNA SELECIONADA. `ORDER BY s.confidence` ordena e
    não devolve nada, e olhar a consulta inteira reprovava justamente o teaser
    que está certo."""
    return consulta[consulta.index("SELECT"):consulta.index("FROM")]


def test_o_resolvido_traz_o_mercado_e_o_resultado():
    """Sem isso a seção não diria nada: "Flamengo x Palmeiras, GREEN" sem o
    mercado não é prova de método, é placar."""
    sql = _consulta_dos_resolvidos()
    for coluna in ("s.market", "s.line", "s.odd", "s.result", "s.profit"):
        assert coluna in sql, coluna


def test_o_resolvido_nunca_traz_a_analise():
    """A coluna não é selecionada, então não há o que esquecer de remover
    depois. Este teste existe pro dia em que alguém "só acrescentar um campo"."""
    colunas = _colunas_de(_consulta_dos_resolvidos())
    for proibido in ("reasoning", "confidence", "ev", "probability", "stake_pct"):
        assert proibido not in colunas, f"{proibido} vazou pro pick resolvido do free"


def test_so_entra_pick_que_ja_terminou():
    """O de hoje fica fechado enquanto a odd vale: é o produto."""
    sql = _consulta_dos_resolvidos()
    assert "s.result IS NOT NULL" in sql


def test_o_corte_e_o_mesmo_que_a_rota_publica_ja_usa():
    """Se um dia /public/results parar de mostrar o mercado do pick resolvido,
    esta seção passa a ser mais aberta que a página pública, e aí ela é que
    está errada."""
    pub = (_BACKEND / "routers" / "public.py").read_text(encoding="utf-8")
    trecho = pub[pub.index("def _sub_vip"):]
    trecho = trecho[:trecho.index("def _sub_free")]
    for coluna in ("pv.market", "pv.line", "pv.odd", "pv.result"):
        assert coluna in trecho, f"{coluna} saiu da rota pública"
    assert "reasoning" not in trecho


def test_o_teaser_do_pendente_continua_sem_mercado():
    """A regressão que importa: abrir o resolvido não pode ter afrouxado o
    trancado, que é o produto de hoje."""
    src = (_BACKEND / "routers" / "suggestions.py").read_text(encoding="utf-8")
    ini = src.index("teaser_vip = _safe_query(")
    teaser = src[ini:src.index('""", _d)', ini)]
    assert "s.result IS NULL" in teaser
    colunas = _colunas_de(teaser)
    for proibido in ("s.market", "s.line", "reasoning", "confidence", "s.ev"):
        assert proibido not in colunas, f"{proibido} vazou pro teaser do pendente"


def test_a_tela_separa_o_aberto_do_trancado():
    """Desenhar cadeado em cima do que já é público faria a seção mentir."""
    tela = (_FRONT / "pages" / "Picks.tsx").read_text(encoding="utf-8")
    assert "resolvidos" in tela
    assert "Os últimos que já fecharam" in tela
    assert "today?.bloqueados?.resolvidos" in tela


def test_a_tela_explica_por_que_uns_abrem_e_outros_nao():
    """Sem a frase, a seção parece defeito: uns picks abertos e outros
    fechados, na mesma tela, sem critério visível."""
    tela = (_FRONT / "pages" / "Picks.tsx").read_text(encoding="utf-8")
    assert "enquanto a odd ainda vale" in tela
