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
        # AsyncFunctionDef junto: metade das rotas de acao pesada do admin e'
        # async (elas disparam asyncio.create_task), e sem isto o helper
        # respondia "funcao nao encontrada" pra uma funcao que existe.
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name == nome:
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


def test_largura_cheia_tem_teto():
    """Era `max-w-none` ate 2026-08-11, e num monitor grande a lista de jogos
    esticava de ponta a ponta: linha de 2500px pra caber nome de time e placar,
    com o olho atravessando a tela inteira entre o horario e o resultado.

    O teto e' o degrau de "aplicativo", nao de leitura -- continua bem acima do
    max-w-6xl das outras telas, e cabe lista mais painel de detalhe lado a lado.
    """
    src = _front("lib/pageWidth.ts")
    assert "full: 'max-w-none" not in src, "voltou a esticar sem teto"
    assert "full: 'max-w-[1440px]" in src
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
    """As tres coisas que o usuario NAO pediu pra apagar.

    Proibe ESCRITA, nao leitura: a guarda de mes fechado precisa consultar
    banca_monthly_closes justamente pra proteger o saldo (ver
    test_zerar_mes_recusa_mes_ja_fechado).
    """
    corpo = _codigo("routers/banca.py", "reset_current_month")
    for tabela in ("banca_monthly_closes", "banca_withdrawals", "user_banca"):
        for verbo in ("DELETE FROM", "UPDATE", "INSERT INTO"):
            assert f"{verbo} {tabela}" not in corpo, f"reset nao pode escrever em {tabela}"
    # a unica escrita permitida
    assert corpo.count("DELETE FROM") == 1
    assert "DELETE FROM user_followed_picks" in corpo


def test_zerar_mes_tem_rate_limit_e_exige_sessao():
    corpo = _codigo("routers/banca.py", "reset_current_month")
    assert "_check_banca_rate" in corpo
    assert "Depends(get_current_user)" in corpo


def test_aviso_mostra_o_que_some_antes_de_confirmar():
    """Acao sem desfazer nao pergunta "tem certeza", mostra o que vai embora."""
    src = _front("components/ResetMonthModal.tsx")
    assert "Some da sua banca" in src
    assert "Continua como está" in src


def test_zerar_mes_mora_na_tela_que_lista_as_apostas():
    """O comando apaga user_followed_picks, que e' o que Meus Picks mostra.

    Na Banca o botao ficava sobre uma pagina que, depois de zerar, nao tem mais
    nada pra exibir -- grafico sem serie, sequencia vazia, distribuicao zerada.
    """
    picks = _front("pages/MeusPicks.tsx")
    assert "ResetMonthModal" in picks
    assert "/banca/reset-month" in picks
    # o numero do aviso vem do mesmo calculo do servidor, nao da lista filtrada
    assert "/banca/monthly-close" in picks
    assert "reset-month" not in _front("pages/Banca.tsx")

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
    """Resultado e placar exato nao tem contador em match_statistics (defesas
    de goleiro tambem nao, e' prop de jogador). Melhor a secao sumir do que
    desenhar barra cinza sem significado."""
    corpo = _codigo("routers/suggestions.py", "_series_da_perna")
    assert 'if not serie["resolved"]' in corpo
    corpo_rota = _codigo("routers/suggestions.py", "get_market_form")
    assert '"available": False' in corpo_rota


def test_forma_do_mercado_exige_sessao():
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "Depends(get_current_user)" in corpo


def test_bilhete_de_varias_pernas_mostra_uma_serie_POR_PERNA():
    """Nao existe UMA serie que descreva multipla/alavancagem -- sao mercados
    diferentes. Existe a de cada perna, que e' a mesma decisao que a regra de
    mercado no modal ja seguia. Ate 2026-08-10 os dois tipos nao passavam
    pickId/pickType e a secao inteira sumia dos dois cards."""
    src = _front_codigo("pages/Picks.tsx")
    assert "pickType: 'multipla'" in src
    assert "pickType: 'alavancagem'" in src
    corpo = _codigo("routers/suggestions.py", "get_market_form")
    assert "_pernas_de_multipla" in corpo
    assert "_pernas_de_alavancagem" in corpo


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
    src = _front_codigo("pages/MeusPicks.tsx")
    # Recorta o ELEMENTO inteiro, nao uma janela de N caracteres: a primeira
    # versao usava 700 e quebrou assim que o botao ganhou `disabled` e um
    # `title` mais longo -- o teste falhava sem nada ter piorado na tela.
    i = src.index("setShowReset(true)")
    botao = src[i:src.index("</button>", i)]
    assert "Zerar mês" in botao
    assert "hidden sm:inline" not in botao, "o texto nao pode sumir no celular"


def test_zerar_mes_desabilita_em_vez_de_sumir():
    """Escondido quando o mes esta vazio, o botao sumia justamente depois de
    zerar -- que e' quando se volta pra conferir se funcionou. Controle que
    desaparece sem explicacao confunde mais que controle desabilitado."""
    src = _front_codigo("pages/MeusPicks.tsx")
    i = src.index("setShowReset(true)")
    botao = src[i:src.index("</button>", i)]
    assert "disabled={(mesAtual?.apostas ?? 0) === 0}" in botao
    assert "Nenhuma aposta registrada em" in botao


def test_banca_mantem_sacar_e_configurar():
    """Pedido do usuario: a barra da Banca fica so' com esses dois."""
    src = _front_codigo("pages/Banca.tsx")
    inicio = src.index("actions: (")
    barra = src[inicio:src.index("}}", inicio)]
    assert "Sacar" in barra
    assert "Configurar" in barra
    assert "Meus Picks" not in barra


# ────────────── Mercados: aba do dia, igual a de picks VIP ─────────────


def test_mercados_saem_do_mesmo_endpoint_do_dia():
    """A aba lia /suggestions/faltas e /goleiros com limit=50 e SEM filtro de
    data: era historico, entao a aba do dia misturava pick de semanas atras, e
    a navegacao por data no topo nao mexia nela."""
    corpo = _codigo("routers/suggestions.py", "get_today_suggestions")
    assert 'result["faltas"]' in corpo
    assert 'result["goleiros"]' in corpo

    tela = _front_codigo("pages/Picks.tsx")
    assert "today?.faltas" in tela
    assert "today?.goleiros" in tela
    # e a busca separada deixa de existir
    assert "/suggestions/faltas" not in tela
    assert "/suggestions/goleiros" not in tela


def test_mercados_usam_a_mesma_janela_dos_outros_tipos():
    """Se a janela divergisse, a aba Mercados falaria de um dia e as outras de
    outro dentro da MESMA resposta."""
    corpo = _codigo("routers/suggestions.py", "get_today_suggestions")
    assert "_merc_where" in corpo
    # mesma cauda de pendentes que vip/multipla/alavancagem usam
    assert corpo.count("INTERVAL '3 days'") >= 5


def test_mercados_sabem_se_ja_foram_apostados():
    """Sem is_followed o card nao sabe que a aposta ja foi registrada e o
    botao "Apostar" reaparece como se nada tivesse acontecido."""
    corpo = _codigo("routers/suggestions.py", "get_today_suggestions")
    assert 'for _tipo in ("faltas", "goleiros")' in corpo
    assert '_ufp_map(_tipo' in corpo


# ─────────────────────────── Favoritos, fora ───────────────────────────


def test_favoritos_sairam_do_frontend():
    """Coracao no card, no cabecalho das secoes de mercado e na agenda, mais
    filtro em dois lugares · muita superficie pra uma preferencia sem uso."""
    for arq in ("App.tsx", "pages/Picks.tsx", "components/SuggestionCard.tsx",
                "components/AgendaInteligente.tsx", "lib/mercadoFiltro.ts"):
        src = _front(arq)
        for termo in ("FavoriteButton", "useFavorites", "FavoritesProvider"):
            assert termo not in src, f"{arq} ainda usa {termo}"


def test_arquivos_de_favorito_foram_removidos():
    for arq in ("components/FavoriteButton.tsx", "context/FavoritesContext.tsx"):
        assert not os.path.exists(os.path.join(_FRONT, arq)), f"{arq} ainda existe"


def test_favoritos_sairam_da_api_mas_a_tabela_fica():
    """DROP TABLE nao tem volta; tabela parada nao custa nada."""
    src = _fonte("routers/personal.py")
    codigo = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "/favorites" not in codigo
    assert "user_favorites" not in codigo.split('"""', 2)[-1]
    assert "user_favorites" in _fonte("migrations.py"), "a tabela nao devia ser dropada"


# ─────────────────────────── Filtros do site ───────────────────────────


def test_periodo_tem_um_vocabulario_so():
    """Banca e Meus Picks filtram a MESMA lista de apostas (/banca) e diziam
    coisas diferentes: "Tudo" contra "Todos", "7 dias" contra "Semana", e um
    recorte de 30 dias que so' existia num lado."""
    lib = _front("lib/periodo.ts")
    for rotulo in ("Tudo", "Hoje", "7 dias", "30 dias", "Este mês", "Mês passado"):
        assert f"'{rotulo}'" in lib, f"falta {rotulo} no vocabulario"

    for pagina in ("pages/Banca.tsx", "pages/MeusPicks.tsx"):
        src = _front(pagina)
        assert "lib/periodo" in src, f"{pagina} nao usa o vocabulario compartilhado"
        # e nenhuma das duas pode ter a propria regua de novo
        codigo = _front_codigo(pagina)
        assert "'thismonth'" not in codigo, f"{pagina} voltou a ter regua propria"
        assert "'lastmonth'" not in codigo, f"{pagina} voltou a ter regua propria"


def test_periodo_fica_a_vista_nas_duas_telas():
    """Era painel dobravel com UM grupo dentro na Banca (tres cliques pro
    filtro principal da tela) e fila aberta em Meus Picks."""
    for pagina in ("pages/Banca.tsx", "pages/MeusPicks.tsx"):
        src = _front_codigo(pagina)
        assert "<PillGroup" in src, f"{pagina} devia mostrar o periodo em fila"
    assert "FilterPanel" not in _front_codigo("pages/Banca.tsx")


def test_janela_de_periodo_e_calculada_num_lugar_so():
    """Com "7 dias" solto, cada tela fazia a propria conta de fuso e as duas
    divergiam na virada da meia-noite."""
    banca = _front_codigo("pages/Banca.tsx")
    picks = _front_codigo("pages/MeusPicks.tsx")
    assert "janelaDoPeriodo(" in banca
    assert "dentroDoPeriodo(" in picks
    for src, pagina in ((banca, "Banca"), (picks, "MeusPicks")):
        assert "function monthBounds" not in src, f"{pagina} refez a conta local"
        assert "function monthRange" not in src, f"{pagina} refez a conta local"


def test_botao_do_painel_nao_promete_aplicar_o_que_ja_esta_aplicado():
    """Dizia "Aplicar" e so' fechava o painel · cada opcao ja chama onChange no
    clique. O rotulo prometia um estado pendente que nunca existiu."""
    src = _front_codigo("components/FilterPanel.tsx")
    assert ">\n              Aplicar\n" not in src
    assert "Ver ${resultado} resultados" in src or "resultados`" in src


def test_painel_de_filtro_diz_quantos_sobraram():
    """Lista vazia por filtro apertado fica igualzinha a lista vazia por nao
    existir dado. So' a aba Mercados respondia isso."""
    assert "resultado?: number" in _front("components/FilterPanel.tsx")
    for pagina in ("pages/Picks.tsx", "pages/ResultadosPublicos.tsx"):
        assert "resultado={" in _front(pagina), f"{pagina} nao passa a contagem"


def test_um_painel_de_filtro_pro_site_inteiro():
    """A aba Mercados tinha controles proprios (busca inline, tres filas de
    pill, um select de ordenacao) e parecia outra ferramenta dentro da mesma
    pagina · a aba VIP, logo acima, filtrava com o painel dobravel."""
    assert not os.path.exists(os.path.join(_FRONT, "components/MercadosControls.tsx")), \
        "os controles proprios deviam ter sumido"
    # o modulo que sobrou e' so' regra, sem casca
    regras = _front("lib/mercadoFiltro.ts")
    assert "aplicarFiltro" in regras
    assert "import" not in regras, "regra de filtro nao devia importar componente"

    src = _front_codigo("pages/Picks.tsx")
    assert "MercadosControls" not in src
    # e a aba passa a usar o mesmo painel, com busca e ordenacao
    assert "busca={{" in src
    assert "ordem={{" in src


def test_busca_aparece_no_rastro_de_filtros():
    """Digitada e painel fechado, ela sumia da vista e o usuario ficava sem
    entender por que a lista estava curta."""
    src = _front_codigo("components/FilterPanel.tsx")
    assert "__busca" in src
    # e limpar tudo tem que limpar a busca junto
    assert "busca?.onChange('')" in src




# ─────────── Entenda esta analise: mesmo padrao em todo pipeline ───────


def test_regra_do_mercado_fala_em_numero_inteiro():
    """A linha vem com meio ponto ("Menos de 10.5") por motivo tecnico: meio
    escanteio nao existe, a fracao so' impede empate. Mas quem le isso pela
    primeira vez trava, porque o jogo nunca vai ter 10.5 escanteios."""
    src = _front("utils/marketTranslate.ts")
    assert "export function regraDoMercado" in src
    assert "ou menos" in src and "ou mais" in src
    # os tres desfechos, nao so' o GREEN
    for campo in ("green", "red", "devolve"):
        assert f"{campo}:" in src


def test_linha_cheia_e_quarto_de_linha_avisam_do_meio_termo():
    """Linha cheia devolve a aposta no numero exato; quarto de linha resolve
    metade. Quem descobre isso so' quando acontece acha que foi erro."""
    src = _front("utils/marketTranslate.ts")
    assert "a aposta volta pra você" in src
    assert "metade da aposta ganha" in src
    assert "metade da aposta perde" in src


def test_sujeito_do_mercado_nao_e_raspado_por_regex():
    """A primeira versao raspava o sujeito do texto pronto e trazia junto o
    "for maior que 0" do exemplo."""
    src = _front("utils/marketTranslate.ts")
    assert "fn.sujeito = subject" in src
    assert "_SUJEITO_RE" not in src


def test_entenda_a_analise_cobre_os_seis_pipelines():
    """VIP, free, faltas e goleiros tinham regra e forma recente; multipla e
    alavancagem recebiam um modal degradado, sem explicacao nenhuma -- e sao
    justamente os tipos em que se entende menos o que precisa acontecer."""
    modal = _front_codigo("components/AnalysisModal.tsx")
    assert "legs?:" in _front("components/AnalysisModal.tsx")
    assert "O que precisa acontecer em cada jogo" in modal

    picks = _front_codigo("pages/Picks.tsx")
    assert picks.count("legs:") >= 2, "multipla e alavancagem precisam passar as pernas"
    # e os de mercado unico continuam mandando o cru
    assert "marketRaw:" in picks


def test_botao_de_detalhes_saiu_do_card():
    """O detalhe do jogo mora na aba Jogos (FixtureStatsModal). No card fica so'
    "Entenda esta analise"."""
    assert "onDetails" not in _front("components/PickCardParts.tsx")
    assert "onDetails" not in _front("components/SuggestionCard.tsx")
    assert "FixtureStatsModal" in _front("pages/Fixtures.tsx")


def test_zerar_mes_recusa_mes_ja_fechado():
    """Fechar rola o lucro do mes pra dentro de bankroll_start. Apagar as
    apostas depois disso conta o mesmo dinheiro duas vezes."""
    corpo = _codigo("routers/banca.py", "reset_current_month")
    assert "FROM banca_monthly_closes" in corpo
    assert "ja foi fechado" in corpo
    # e a checagem tem que vir ANTES do DELETE
    assert corpo.index("banca_monthly_closes") < corpo.index("DELETE FROM user_followed_picks")


# ───────── Faltas e defesas: integracao ponta a ponta no site ──────────


def _uniao_de_picks(sql: str) -> set:
    """Tabelas de pick citadas num UNION."""
    return set(re.findall(r"FROM (picks_\w+)", sql))


_SEIS = {"picks_vip", "picks_free", "picks_multiplas", "picks_alavancagem",
         "picks_faltas", "picks_goleiros"}


def test_performance_da_ia_conta_os_seis_pipelines():
    """E' o numero que a tela de Picks estampa como "Performance da IA · Geral".

    Faltas e goleiros ficavam de fora: o site publicava os dois, liquidava os
    dois, contava os dois na banca do usuario e no historico publico -- so' a
    porcentagem do topo os ignorava. O percentual anunciado nao descrevia o
    produto vendido logo abaixo dele.
    """
    corpo = _codigo("routers/suggestions.py", "get_quick_stats")
    assert _uniao_de_picks(corpo) == _SEIS, "stats/quick nao soma os seis"


def test_sequencia_atual_usa_a_mesma_base_do_total():
    """Lia so' picks_vip: "5 greens seguidos" descrevia um pipeline e aparecia
    colado num total que somava todos."""
    corpo = _codigo("routers/suggestions.py", "get_quick_stats")
    trecho = corpo[corpo.index("Sequ"):]
    assert _uniao_de_picks(trecho) == _SEIS


def test_ranking_conta_aposta_em_faltas_e_defesas():
    """Os dois entravam no CASE como NULL, entao a aposta era descartada pelo
    FILTER (WHERE result IS NOT NULL): contava na banca do usuario e sumia do
    ranking. Quem apostasse so' nesses dois nem aparecia na lista."""
    corpo = _codigo("routers/public.py", "public_leaderboard")
    assert "picks_faltas" in corpo and "picks_goleiros" in corpo
    for tipo in ("'faltas'", "'goleiros'"):
        assert corpo.count(tipo) >= 2, f"{tipo} precisa do CASE de result E de profit"


def test_banca_do_usuario_conta_os_dois_mercados():
    """Apostar num pick de faltas tem que mexer no saldo, nao so' aparecer na
    lista."""
    src = _fonte("routers/banca.py")
    assert '_TABELAS_MERCADO = {"faltas": "picks_faltas", "goleiros": "picks_goleiros"}' in src
    for fn in ("_compute_bankroll_current", "_compute_month_stats"):
        assert "_mercado_maps(cur, followed)" in _codigo("routers/banca.py", fn), \
            f"{fn} ignora os mercados"


def test_liquidacao_cobre_faltas_e_defesas():
    """Sem isso o pick ficaria pendente pra sempre: nunca entraria em nenhuma
    estatistica (todas filtram result IS NOT NULL) e a aposta do usuario nunca
    sairia de "pendente"."""
    corpo = _codigo("routers/live.py", "resolve_all_pending")
    assert "FROM picks_faltas" in corpo
    assert "FROM picks_goleiros" in corpo
    # defesa e' prop de JOGADOR: tem que ler player_match_stats, nao o total do time
    assert "player_match_stats" in corpo


def test_resultado_liquidado_chega_na_aposta_do_usuario():
    """user_followed_picks.result precisa acompanhar, senao a tela mostra
    pendente com o pick ja resolvido."""
    corpo = _codigo("routers/live.py", "_save_market_pick_result")
    assert "_sync_followed_result" in corpo


# ─────────────── Fechamentos mensais em pagina propria ─────────────────


def test_historico_de_fechamentos_saiu_do_rodape_da_banca():
    """A lista cresce um item por mes e nunca para: empurrava a pagina pra
    baixo sem limite, misturada com o que e' do MES CORRENTE."""
    secao = _front_codigo("components/MonthlyCloseSection.tsx")
    assert "/banca/fechamentos" in secao
    # o pendente FICA: e' acao, tem prazo e muda a banca
    assert "openMonthlyClose" in secao
    # o historico nao e' mais desenhado aqui
    assert "bankroll_start" not in secao


def test_pagina_de_fechamentos_existe_e_e_privada():
    app = _front("App.tsx")
    assert 'path="/banca/fechamentos"' in app
    assert "<PrivateRoute><BancaFechamentos />" in app
    pagina = _front("pages/BancaFechamentos.tsx")
    assert "noindex" in pagina, "tela de conta nao deve indexar"
    assert "/banca/monthly-closes" in pagina


def test_pagina_de_fechamentos_tem_volta_e_estado_vazio():
    """Sem o `back` o usuario cai numa tela sem saida; sem o vazio, quem nunca
    fechou um mes ve uma pagina em branco."""
    pagina = _front("pages/BancaFechamentos.tsx")
    assert "back: '/banca'" in pagina
    assert "Nenhum fechamento ainda" in pagina


# ────────────────── Coleta de liga pelo /admin (2026-08-11) ──────────────────


def test_cadastrar_liga_nao_coleta_sozinho_mas_a_tela_avisa():
    """Cadastrar so' coloca a liga na fila. A dependencia que faz isso doer e'
    invisivel: FixtureCollectorService filtra por `SELECT team_id FROM teams`,
    entao liga sem time nunca salva jogo, por mais que a API tenha. Estado real
    em 2026-08-11: Sul-Americana cadastrada, 56 times e as oitavas em andamento
    na API, zero linha no banco -- e nada na tela dizia isso."""
    tela = _front_codigo("pages/Admin.tsx")
    assert "l.times === 0" in tela, "linha de liga sem time tem que avisar"
    assert "/coletar" in tela


def test_coletar_liga_e_escopado_e_nao_apaga_nada():
    """`new_league` do script faz TRUNCATE em match_statistics/teams/fixtures/
    standings. O botao do admin NAO pode cair nesse caminho -- ele existe pra
    coletar uma liga sem perder a base historica, que sustenta a calibracao."""
    corpo = _codigo("routers/admin.py", "coletar_liga")
    assert '"liga", str(league_id)' in corpo
    assert "new_league" not in corpo
    assert "TRUNCATE" not in corpo
    # e roda em segundo plano: backfill de temporada nao cabe num request HTTP
    assert "asyncio.create_task" in corpo


def test_coleta_de_liga_nao_roda_duas_de_uma_vez():
    corpo = _codigo("routers/admin.py", "coletar_liga")
    assert '_pipeline_status.get("coletar_liga"' in corpo
    assert "409" in corpo


def test_timeout_de_script_e_de_30_minutos():
    """Era 5 min no padrao e matava coleta no meio -- capturar_odds em dia cheio
    passa disso (uma requisicao por fixture), e o sintoma nao era "demorou": era
    script morto na metade, com odd faltando e sem erro obvio."""
    src = _fonte("routers/admin.py")
    assert '"default":         1800.0' in src
    assert '"coletar_liga":    2700.0' in src


# ───────── Liga sai da coleta sem sair da tabela (2026-08-11) ─────────


def test_tirar_liga_da_coleta_nao_apaga_a_linha():
    """DELETE quebrava o NOME em todo lugar que resolve liga por JOIN.

    A Copa do Mundo 2026 saiu da tabela (competicao encerrada, so' volta em
    2030) e os picks dela viraram "LIGA 1" nos Resultados da IA -- os 104 jogos
    seguiam em match_statistics sustentando 77% do ledger de calibracao, o que
    sumiu foi so' o nome, e nao ha de onde recupera-lo depois do DELETE."""
    corpo = _codigo("routers/admin.py", "remover_liga")
    assert "DELETE FROM leagues" not in corpo
    assert "UPDATE leagues SET ativa = FALSE" in corpo


def test_coletores_param_na_liga_inativa():
    """Marcar so' resolve se quem coleta respeitar a marca -- senao a liga
    continuaria gastando cota."""
    import os as _os
    # _BACKEND = .../website/backend, entao dois niveis acima e' a raiz do repo
    raiz = _os.path.join(_os.path.dirname(_os.path.dirname(_BACKEND)),
                         "ApostaEsportivas", "src")
    for arquivo in ("collectors/fixture_collector_service.py",
                    "collectors/match_statistics_sync_service.py",
                    "collectors/team_statistics_sync_service.py",
                    "collectors/standings_collector_service.py"):
        with open(_os.path.join(raiz, arquivo), encoding="utf-8") as f:
            assert "COALESCE(ativa, TRUE)" in f.read(), arquivo


def test_copa_do_mundo_volta_como_historico():
    """Restaura o nome pra quem ja tinha deletado a linha."""
    src = _fonte("migrations.py")
    assert "ADD COLUMN IF NOT EXISTS ativa BOOLEAN" in src
    assert "'Copa do Mundo', 2026, FALSE" in src
    assert "ON CONFLICT (league_id) DO NOTHING" in src
