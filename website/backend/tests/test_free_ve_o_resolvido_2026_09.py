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


# ── os outros produtos, no mesmo método (14/09/2026, pedido dele) ─────────
def _suggestions() -> str:
    return (_BACKEND / "routers" / "suggestions.py").read_text(encoding="utf-8")


def test_todo_produto_com_teaser_tem_resolvido():
    """Ele pediu o mesmo método em todos. Se um produto ganhar teaser e não
    ganhar resolvido, a aba dele volta a ser só cadeado."""
    src = _suggestions()
    for chave in ("resolvidos", "resolvidos_mercados",
                  "resolvidos_cartelas", "resolvidos_alavancagem"):
        assert f'"{chave}":' in src, chave


def test_a_cartela_resolvida_nao_entrega_as_pernas():
    """`/public/results` publica a múltipla resolvida como "Múltipla, 3 sel."
    com a odd do bilhete, e as pernas NÃO saem. O que cada perna é continua
    sendo a análise, resolvida ou não."""
    src = _suggestions()
    ini = src.index("def _cartela_resolvida(")
    corpo = src[ini:src.index("resolvidos_cartelas = (", ini)]
    assert 'd.pop("games", None)' in corpo, "o games tem que sair da resposta"
    assert '"titulo"' in corpo


def test_o_mercado_resolvido_traz_o_que_foi_apostado():
    """Faltas, goleiros, jogador e Boost têm a forma de picks_free, e é assim
    que `_sub_mercado` já os publica."""
    src = _suggestions()
    ini = src.index("resolvidos_mercados = []")
    trecho = src[ini:src.index("def _cartela_resolvida", ini)]
    for coluna in ("p.market", "p.line", "p.odd", "p.result"):
        assert coluna in trecho, coluna
    assert "reasoning" not in trecho


def test_a_aba_de_um_mercado_nao_mostra_o_de_outro():
    """Os quatro mercados próprios chegam na mesma lista: sem o filtro, a aba
    Pick Falta mostraria pick de jogador."""
    tela = (_FRONT / "pages" / "Picks.tsx").read_text(encoding="utf-8")
    assert "function soDoTipo(" in tela
    for tipo in ("'faltas'", "'player_stats'", "'boost'"):
        assert f"soDoTipo(today?.bloqueados?.resolvidos_mercados, {tipo})" in tela, tipo


def test_o_resolvido_usa_o_card_do_produto():
    """Lista de texto fazia a seção parecer extrato. A pessoa precisa
    reconhecer que aquilo é o mesmo produto que está trancado acima."""
    tela = (_FRONT / "pages" / "Picks.tsx").read_text(encoding="utf-8")
    assert "function CardResolvido(" in tela
    card = tela[tela.index("function CardResolvido("):tela.index("function CardTrancado(")]
    # Mesma casca e mesmo cabeçalho do card trancado. A borda passou a sair de
    # `cascaDoPick` (14/09): o pick que fechou em GREEN veste a borda verde,
    # como todo card resolvido do site, e no resto continua a borda neutra.
    assert "pick-card" in card and "cascaDoPick(" in card
    assert '"pick-head"' in card
    assert "<PickTypeBadge" in card and "<LeagueLogo" in card
    # A faixa de números e a caixa do jogo são as MESMAS dos cards abertos · a
    # odd saía como uma linha de texto no pé, e mercado e linha vinham grudados
    # num parágrafo só, sem rótulo.
    assert '"pick-hero"' in card
    assert "caixaDoPick(" in card and "<CampoDoPick" in card
    # e o que muda: mercado no lugar da tarja, resultado no lugar do cadeado
    assert "<SeloDeResultado" in card
    # `<TarjaDeAnalise`, com o sinal de menor: sem ele o teste reprovava o
    # COMENTÁRIO que explica a troca ("no lugar exato da TarjaDeAnalise").
    assert "<TarjaDeAnalise" not in card
