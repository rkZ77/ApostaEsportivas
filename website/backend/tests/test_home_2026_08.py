"""Home: fila de jogos publica, Dica do Dia com reserva e peso da pagina.

Como o resto da suite, nada aqui toca banco: o que se verifica e a forma do
SQL e o acoplamento entre tela e rota, que e onde os tres bugs desta leva
moravam.
"""

import ast
import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _fonte(caminho: str) -> str:
    with open(os.path.join(_BACKEND, caminho), encoding="utf-8") as f:
        return f.read()


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


def _front_codigo(caminho: str) -> str:
    """Fonte do componente SEM comentario.

    Mesma armadilha que _codigo resolve do lado do Python: uma asserção de
    ausência ("nao pode ter max-w-6xl") passa a falhar quando o comentario
    EXPLICA que aquilo foi removido. O teste tem que ler codigo, nao prosa.
    """
    src = _front(caminho)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)   # bloco e JSX {/* */}
    return re.sub(r"(?<!:)//[^\n]*", "", src)              # linha, poupando URL


def _codigo(caminho: str, nome: str) -> str:
    """Fonte de uma funcao, SEM a docstring.

    Recortar por texto ("do def ate o proximo @router") mordia o que viesse
    depois e, pior, deixava a prosa dentro da amostra: a primeira versao destes
    testes passava a ler os proprios comentarios e dava tanto falso positivo
    quanto falso negativo. Aqui o recorte e sintatico.
    """
    fonte = _fonte(caminho)
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            bruto = ast.get_source_segment(fonte, no) or ""
            doc = ast.get_docstring(no, clean=False)
            return bruto.replace(doc, "") if doc else bruto
    raise AssertionError(f"funcao {nome} nao encontrada em {caminho}")


# ─────────────────────── Fila de jogos na Home ─────────────────────────


def test_fila_da_home_nao_depende_de_sessao():
    """A faixa e' pra visitante anonimo, entao a rota tem que ser publica.

    Ela lia GET /api/fixtures/today, que exige login: pro publico da Home o
    resultado era sempre 401, e a faixa nunca aparecia pra ninguem deslogado.
    """
    src = _front_codigo("home/NextGames.tsx")
    assert "/public/next-fixtures" in src
    assert "/fixtures/today" not in src

    # e a rota nova precisa mesmo ser publica -- sem Depends de usuario
    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "current_user" not in corpo
    assert "Depends" not in corpo


def test_fila_corta_pelo_relogio_de_brasilia():
    """`fixtures.match_datetime` esta gravado em horario de Brasilia sem fuso.

    Comparar com NOW() puro (o banco roda em UTC) adiantaria o corte em 3
    horas e esconderia justamente os jogos da tarde.
    """
    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "NOW() AT TIME ZONE '{TZ_BR}'" in corpo
    assert re.search(r"NOW\(\)\s*[<>=]", corpo) is None


def test_fila_e_daqui_pra_frente_e_nao_do_dia():
    """A queixa era "quando acabam os jogos de hoje, mostrar os de amanha".

    Filtrar por data presa a hoje devolve partida que ja rolou e deixa a faixa
    vazia no fim do dia; o corte tem que ser por horario, sem travar no dia.
    """
    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "match_datetime >=" in corpo
    assert "::date =" not in corpo
    assert "ORDER BY f.match_datetime" in corpo


def test_fila_tem_indice_pra_nao_varrer_a_tabela():
    src = _fonte("migrations.py")
    assert "idx_fixtures_proximos" in src
    idx = src[src.index("idx_fixtures_proximos") - 40:]
    assert "IF NOT EXISTS" in idx[:120]


# ─────────────────── Dica do Dia: hoje, ou a anterior ──────────────────


def test_dica_do_dia_usa_data_brasileira():
    """CURRENT_DATE e' a data UTC: entre 21h e meia-noite de Brasilia o banco
    ja virou o dia e o Brasil nao, e a dica sumia da Home no horario de pico."""
    corpo = _codigo("routers/public.py", "public_free_pick_today")
    assert "HOJE_BR" in corpo
    assert "CURRENT_DATE" not in corpo


def test_dica_cai_na_anterior_quando_o_dia_ainda_nao_tem_pick():
    """Sem pick de hoje a rota devolvia None e a Home ficava com um buraco.

    Nao existe horario fixo de publicacao desde 01/08, entao esse buraco podia
    durar o dia inteiro.
    """
    corpo = _codigo("routers/public.py", "public_free_pick_today")
    assert "match_date <" in corpo, "falta a consulta de reserva"
    assert 'd["is_previous"] = is_previous' in corpo
    # a reserva tem que ser a MAIS RECENTE das antigas
    assert "ORDER BY pf.match_date DESC" in corpo


def test_reserva_nao_derruba_o_bloqueio_de_mercado():
    """O ramo do anonimo continua sendo o primeiro `else` da funcao.

    E' o mesmo invariante do test_deploy_prod_2026_08; repetido aqui porque a
    consulta de reserva entrou logo acima dele e um `else` novo no caminho
    quebraria o corte sem quebrar nenhum teste de la.
    """
    corpo = _codigo("routers/public.py", "public_free_pick_today")
    ramo_anon = corpo[corpo.index("else:"):]
    assert 'd.pop("market", None)' in ramo_anon
    assert 'd["locked"] = True' in ramo_anon


def test_tela_trata_a_dica_anterior_como_historico():
    """Card antigo tem que dizer que e' antigo -- com data e resultado --
    em vez de se passar pela dica de hoje."""
    src = _front("home/FreePickHero.tsx")
    assert "is_previous" in src
    assert "Última dica publicada" in src


# ──────────────────────── Peso da pagina ───────────────────────────────


def test_home_nao_pede_mais_recentes_do_que_mostra():
    """Pedia 50 e renderizava 10: o backend roda uma sub-query por tipo de
    pick, entao o excesso multiplicava por seis do lado do banco."""
    src = _front("pages/Home.tsx")
    pedido = re.search(r"recent_limit:\s*(\d+)", src)
    mostrado = re.search(r"\.recent\s*\?\?\s*\[\]\)\.slice\(0,\s*(\d+)\)", src)
    assert pedido and mostrado
    assert int(pedido.group(1)) == int(mostrado.group(1))


def test_resposta_da_api_sai_comprimida():
    """O dist/ e servido pelo proprio FastAPI, sem nginx na frente: sem este
    middleware nada no site era comprimido, nem JSON nem bundle."""
    src = _fonte("main.py")
    assert "GZipMiddleware" in src
    # registrado antes do CORS pra que o CORS seja a camada de fora
    assert src.index("add_middleware(GZipMiddleware") < src.index("CORSMiddleware,")


def test_bundle_com_hash_nao_revalida_a_cada_carregamento():
    src = _fonte("main.py")
    assert "immutable" in src
    # e o index.html tem que ser o oposto, senao o deploy novo nao chega
    assert '"Cache-Control": "no-cache"' in src


def test_ligas_da_home_sao_buscadas_uma_vez_so():
    """A Home montava duas fitas de ligas; cada uma disparava a sua propria
    chamada pra mesma lista."""
    src = _front("components/LeagueMarquee.tsx")
    assert "_leaguesPromise" in src
    assert src.count("api.get(") == 1


# ──────────────────────── Fitas que passam sozinhas ────────────────────


def test_fita_nao_repete_item_pra_encher_o_trilho():
    """A lista era duplicada ate passar de 12 itens, entao com 8 ligas a mesma
    liga saia quatro vezes -- as vezes duas delas visiveis juntas."""
    src = _front_codigo("components/LeagueMarquee.tsx")
    assert "Math.ceil(12" not in src
    assert ".flat()" not in src
    # cada liga entra uma vez: o map e' direto sobre a lista da API
    assert "leagues.map(" in src


def test_home_tem_uma_fita_de_ligas_so():
    """Duas fitas cruzadas rodando a MESMA lista poem toda liga duas vezes na
    tela ao mesmo tempo, uma indo e outra voltando."""
    src = _front_codigo("home/Leagues.tsx")
    assert src.count("<LeagueMarquee") == 1
    assert "reverse" not in src


def test_fita_decide_sozinha_se_anda():
    """Quem chamava e' que resolvia encher o trilho. A decisao passa a ser do
    Marquee, que mede: nao coube, anda; coube, fica parado e centralizado."""
    src = _front("components/ui/Marquee.tsx")
    assert "ResizeObserver" in src
    assert "scrollWidth" in src
    assert "prefers-reduced-motion" in src


def test_fita_usa_padding_e_nao_gap_entre_itens():
    """Com `gap`, o ultimo item de cada copia nao ganha vao depois dele e o
    -50% da animacao cai meio espacamento fora -- a emenda salta a cada volta.
    """
    src = _front_codigo("components/ui/Marquee.tsx")
    assert "spacing = 'pr-8'" in src
    assert "gap-8" not in src


def test_carrossel_de_jogos_nao_repete_jogo():
    src = _front("home/NextGames.tsx")
    assert "games.map(" in src
    assert "Marquee" in src


# ──────────────────────── Largura de aplicativo ────────────────────────


def test_existe_degrau_de_largura_cheia():
    src = _front("lib/pageWidth.ts")
    assert "full: 'max-w-none" in src
    # o padding vem junto da largura, senao o conteudo encosta na borda do monitor
    assert "lg:px-8" in src


def test_telas_de_dado_usam_a_largura_cheia():
    for pagina in ("Picks", "Banca", "MeusPicks", "Estatisticas", "Admin"):
        src = _front(f"pages/{pagina}.tsx")
        assert 'width="full"' in src, f"{pagina} ficou preso na largura antiga"


def test_grade_de_picks_ganha_coluna_em_tela_larga():
    """Largura cheia sem coluna nova so' faz o card inchar: em 1900px, duas
    colunas dariam 900px por card."""
    src = _front("pages/Picks.tsx")
    assert "xl:grid-cols-3" in src
    assert "md:grid-cols-2" in src


def test_barra_do_app_acompanha_a_largura_do_conteudo():
    """O FUNDO da barra e' sempre cheio; o CONTEUDO segue a largura da pagina.

    Fixa em max-w-6xl a barra ficava desalinhada nos dois sentidos: sobrando
    nas telas estreitas e boiando no meio das largas.
    """
    src = _front_codigo("components/Navbar.tsx")
    assert "max-w-6xl" not in src
    assert "PAGE_WIDTH[width]" in src

    casca = _front_codigo("components/PageShell.tsx")
    assert "<Navbar width={width} />" in casca


def test_texto_para_ler_nao_vai_pra_largura_cheia():
    """A medida de leitura e' o unico teto que nao se negocia: 45 a 75
    caracteres por linha. Estas telas sao texto corrido ou formulario."""
    for pagina, largura in (
        ("Termos", "prose"), ("Privacidade", "prose"), ("ComoFunciona", "prose"),
        ("Blog", "prose"), ("BlogPost", "narrow"),
        ("Checkout", "narrow"), ("Agente", "narrow"),
    ):
        src = _front(f"pages/{pagina}.tsx")
        assert f'width="{largura}"' in src, f"{pagina} devia seguir em {largura}"


def test_grade_e_tabela_vao_pra_largura_cheia():
    for pagina in ("Fixtures", "ResultadosPublicos", "PerformanceIA"):
        src = _front(f"pages/{pagina}.tsx")
        assert 'width="full"' in src, f"{pagina} ficou preso na largura antiga"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ─────────────────── Zerar o mes corrente na banca ─────────────────────


def test_zerar_mes_so_alcanca_o_mes_corrente():
    """A rota nao aceita parametro de mes, de proposito.

    Com um `month` no corpo ou na query, um cliente qualquer apagaria mes
    fechado -- e fechamento mensal e' historico assinado.
    """
    corpo = _codigo("routers/banca.py", "reset_current_month")
    assert "_current_month_key()" in corpo
    assert "month" not in corpo.split("def reset_current_month(")[1].split(")")[0], \
        "a assinatura nao pode receber mes"
    assert "DELETE FROM user_followed_picks" in corpo


def test_zerar_mes_usa_o_mesmo_recorte_que_a_tela_soma():
    """Se o filtro daqui divergisse de _compute_month_stats, o aviso mostraria
    um numero de apostas e o comando apagaria outro conjunto."""
    corpo = _codigo("routers/banca.py", "reset_current_month")
    soma  = _codigo("routers/banca.py", "_compute_month_stats")
    for regra in ("followed_at AT TIME ZONE 'America/Sao_Paulo'",
                  "pick_type != 'alavancagem'"):
        assert regra in corpo, f"reset sem: {regra}"
        assert regra in soma,  f"soma sem: {regra}"


def test_zerar_mes_nao_toca_fechamento_saque_nem_banca_inicial():
    """As tres coisas que o usuario NAO pediu pra apagar."""
    corpo = _codigo("routers/banca.py", "reset_current_month")
    for tabela in ("banca_monthly_closes", "banca_withdrawals", "user_banca"):
        assert tabela not in corpo, f"reset nao pode tocar {tabela}"


def test_zerar_mes_tem_rate_limit_e_exige_sessao():
    corpo = _codigo("routers/banca.py", "reset_current_month")
    assert "_check_banca_rate" in corpo
    assert "Depends(get_current_user)" in corpo


def test_aviso_mostra_o_que_some_antes_de_confirmar():
    """Acao sem desfazer nao pergunta "tem certeza", mostra o que vai embora."""
    src = _front("pages/Banca.tsx")
    assert "ResetMonthModal" in src
    assert "Some da sua banca" in src
    assert "Continua como está" in src
    # o numero do aviso vem do mesmo calculo do servidor, nao da lista filtrada
    assert "/banca/monthly-close" in src

# ─────────────── Forma recente do mercado (Entenda esta analise) ───────


def test_forma_do_mercado_nao_inventa_mapeamento_de_familia():
    """Qual contador cada familia observa e' pergunta ja respondida em
    routers/live.py::_stat_for_market -- e mal respondida custou dois bugs de
    producao (chutes totais somados como chutes no alvo, mercado de time
    resolvido pelo total). Reusar, nao reescrever."""
    src = _fonte("routers/suggestions.py")
    assert "from routers.live import _stat_for_market" in src
    forma = _fonte("market_form.py")
    # o modulo recebe a funcao, nao reimplementa o dispatch
    assert "stat_para_mercado" in forma
    for palavra in ("Corner Kicks", "Shots on Goal"):
        assert palavra in forma, "adaptador precisa falar o nome da API"


def test_forma_do_mercado_liquida_pelo_settlement():
    """`valor > linha` pareceria inofensivo e erraria em meia-linha asiatica e
    em PUSH de linha cheia -- as duas ja resolvidas no settlement."""
    src = _fonte("market_form.py")
    assert "settlement.settle_over_under" in src
    assert "settlement.parse_line" in src


def test_forma_do_mercado_nao_transforma_ausencia_em_zero():
    """O RED de 05/08 nasceu de tratar "nao sei" como "zero"."""
    src = _fonte("market_form.py")
    assert '.get(col_casa, 0)' not in src
    assert '.get(col_fora, 0)' not in src
    assert "is not None" in src
    # jogo sem dado nao pode entrar na taxa
    assert 'i["result"] is not None' in src


def test_forma_some_quando_o_mercado_nao_tem_serie_por_jogo():
    """Resultado, BTTS e placar exato nao tem contador em match_statistics.
    Melhor a secao sumir do que desenhar barra cinza sem significado."""
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert 'if not serie["resolved"]' in corpo
    assert '"available": False' in corpo


def test_forma_do_mercado_exige_sessao():
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "Depends(get_current_user)" in corpo


def test_modal_esconde_a_forma_em_multipla_e_alavancagem():
    """Bilhete de varias pernas nao tem UMA serie que o descreva."""
    src = _front("components/AnalysisModal.tsx")
    assert "data.pickId != null && data.pickType" in src


# ────────────────────── Meta de banca removida ─────────────────────────


def test_meta_de_banca_saiu_da_api():
    """Era opcional, quase ninguem preenchia, e a tela ficava com um card
    tracejado convidando pra isso. Decisao do usuario em 07/08."""
    src = _fonte("routers/banca.py")
    # so' pode sobrar na explicacao de por que ela saiu
    codigo = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "bankroll_goal" not in codigo


def test_meta_saiu_da_tela_mas_a_coluna_fica():
    """DROP COLUMN nao tem volta e a coluna parada nao custa nada."""
    assert "bankroll_goal" not in _front("pages/Banca.tsx")
    assert "bankroll_goal" not in _front("components/MonthlyCloseModal.tsx")
    assert "bankroll_goal" in _fonte("migrations.py"), "a coluna nao devia ser dropada"


def test_barra_da_pagina_quebra_antes_de_espremer_o_titulo():
    """A fila de acoes e' shrink-0: sem quebra, quem cede e' o titulo, que tem
    min-w-0. Em 360px com tres botoes "Minha Banca" virava "Minha B..."."""
    src = _front_codigo("components/PageShell.tsx")
    assert "flex flex-wrap items-center justify-between" in src
    assert "ml-auto" in src


def test_zerar_mes_mantem_o_texto_no_celular():
    """Seta circular sozinha le como "recarregar" -- ambiguidade dessas num
    botao sem volta e' armadilha, e o publico e' mobile."""
    src = _front_codigo("pages/Banca.tsx")
    i = src.index("setShowReset(true)")
    trecho = src[i:i + 700]
    assert "Zerar mês" in trecho
    assert "hidden sm:inline" not in trecho, "o texto nao pode sumir no celular"
