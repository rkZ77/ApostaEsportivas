"""Mudancas de 15/08: lucro em unidades no site, faixa de plano e odd do clique.

Tres entregas independentes, testadas pelo que cada uma garante:

1. UNIDADE NA VITRINE. O site so' comunicava performance em porcentagem (win
   rate e ROI). Quem acompanha tipster le lucro em UNIDADE, e o numero ja'
   existia no banco: a coluna `profit` das seis tabelas de picks e' lucro com
   stake fixa de 1u (settlement.py). Faltava chegar na tela.

2. FAIXA DE PLANO. Convite pra assinar/renovar, so' logado e nunca na Home.

3. ODD DO CLIQUE EM "APOSTEI". /live/pick-odd so' sabia ler odd AO VIVO e
   devolvia None pra jogo nao iniciado -- ou seja, pra quase todo clique. O
   front caia na odd salva na geracao, e o efeito pratico era "so' atualiza pra
   menos": a unica vez que a odd mudava era com o jogo rolando, quando ela
   normalmente ja' caiu.

Nada aqui abre conexao: o conftest ja bloqueia get_connection.
"""
import re

from tests.test_home_2026_08 import _codigo, _fonte, _front, _front_codigo


# ─────────────────────── 1. Lucro em unidades ───────────────────────


def test_resumo_publico_quebra_vip_e_free_na_mesma_varredura():
    """As medias por produto saem do SELECT que ja' rodava.

    A Home chama /public/results com slim=1 justamente pra cair de sete
    consultas pra tres. Um bloco `by_source` separado custaria mais uma ida ao
    banco (154ms) pra ela -- entao a quebra entra como coluna condicional no
    proprio resumo, mesmo padrao do `leagues_count`.
    """
    corpo = _codigo("routers/public.py", "public_results")
    for coluna in ("AS vip_profit", "AS vip_total", "AS free_profit", "AS free_total"):
        assert coluna in corpo, f"{coluna} sumiu do resumo"

    # A quebra tem que estar DENTRO do SELECT do sumario (o unico que roda no
    # caminho slim), nao num bloco proprio marcado com `[] if slim else`.
    sumario = corpo[corpo.index("summary = _q1"):corpo.index("by_day")]
    assert "vip_profit" in sumario, "quebra por produto ficou fora do resumo slim"


def test_unidade_tem_um_formatador_so():
    """`fmtUnits` e' o unico lugar que decide como uma unidade e' escrita.

    Sem isso o site escreveria a mesma grandeza de tres jeitos (`+42.7u`,
    `+42,7 U`, `+42.70`), como ja' acontecia entre a Banca e os cards.
    """
    fonte = _front("utils/format.ts")
    assert "export function fmtUnits" in fonte
    assert "pt-BR" in fonte, "numero de unidade tem que sair com virgula decimal"

    for tela in ("home/StatsBand.tsx", "pages/Picks.tsx",
                 "pages/ResultadosPublicos.tsx", "pages/PerformanceIA.tsx"):
        assert "fmtUnits" in _front_codigo(tela), f"{tela} escreve unidade na mao"


def test_home_troca_ligas_cobertas_pelo_lucro():
    """A faixa e' a de sempre com UMA troca: sai "Ligas cobertas", entra o
    lucro em unidades. Os outros tres tiles ficam onde estavam.

    A contagem de ligas nao se perde -- vira apoio da assertividade, e continua
    saindo de `summary.leagues_count`, nunca do tamanho de `by_league`.
    """
    banda = _front_codigo("home/StatsBand.tsx")
    for tile in ("Picks publicadas", "Assertividade", "ROI acumulado", "Lucro da IA"):
        assert f"label: '{tile}'" in banda, f"{tile} sumiu da faixa"
    assert "label: 'Ligas cobertas'" not in banda, "o lucro devia ter tomado esse lugar"
    assert "leaguesCount" in banda and "by_league" not in banda


def test_media_por_produto_nao_vira_tile_ao_lado_do_roi():
    """Media por pick e ROI sao o MESMO numero em escalas diferentes.

    Como toda stake vale 1u na base, `roi` e' `media × 100`. Lado a lado como
    tiles seriam o mesmo dado em duas roupas, e quem entende de aposta percebe
    -- entao a quebra de VIP e free vai pra linha de apoio, onde informa sem
    competir com o ROI. Lucro TOTAL e ROI podem conviver: um e' quanto rendeu,
    o outro e' quanto rendeu por unidade arriscada.
    """
    banda = _front_codigo("home/StatsBand.tsx")
    assert "label: 'Média por pick" not in banda, "media voltou a ser tile"
    assert "Média por pick ·" in banda, "a quebra por produto sumiu da faixa"
    assert "mediaVip" in banda and "mediaFree" in banda


def test_plano_de_stake_vive_num_lugar_so():
    """4u em pick simples, 1u em bilhete · escrito uma vez, lido por todos.

    Com a tabela repetida, /public/results (Home, Resultados, Performance) e
    /suggestions/stats/quick (tela de Picks) passariam a anunciar lucros
    diferentes pra mesma IA, e nada acusaria a divergencia.
    """
    from stake_plan import STAKE_PADRAO

    assert STAKE_PADRAO["vip"] == STAKE_PADRAO["free"] == 4
    assert STAKE_PADRAO["multiplas"] == STAKE_PADRAO["alavancagem"] == 1
    # Faltas e defesas sao pick simples (um jogo, um mercado): seguem o simples.
    assert STAKE_PADRAO["faltas"] == STAKE_PADRAO["goleiros"] == 4

    for arquivo in ("routers/public.py", "routers/suggestions.py"):
        assert "stake_plan import" in _fonte(arquivo), f"{arquivo} nao le o plano central"


def test_peso_multiplica_lucro_e_stake_juntos():
    """Se so' o lucro fosse pesado, o ROI (lucro/stake) saltaria pelo mesmo
    fator e o site anunciaria um retorno que nunca existiu."""
    from routers.public import _build_union
    import re

    sql = _build_union("", None)
    for bloco in sql.split("UNION ALL"):
        fonte = re.search(r"'(\w+)' AS source", bloco)
        lucro = re.search(r"profit \* (\d+) AS profit", bloco)
        stake = re.search(r"(\d+)(?:::numeric)? AS stake", bloco)
        assert fonte and lucro and stake, bloco[:120]
        assert lucro.group(1) == stake.group(1),             f"{fonte.group(1)}: lucro x{lucro.group(1)} mas stake {stake.group(1)}u"


def test_premissa_de_stake_aparece_junto_do_numero():
    """A Banca sugere stake variavel; sem o plano escrito na tela o usuario
    compara com a banca dele, os numeros nao batem e o site parece mentir.

    A legenda vem do backend (`stake_label`) pra nao envelhecer sozinha quando
    o plano mudar.
    """
    from stake_plan import rotulo_curto

    assert "4u" in rotulo_curto() and "1u" in rotulo_curto()
    assert '"stake_label": rotulo_curto()' in _codigo("routers/public.py", "public_results")
    for tela in ("home/StatsBand.tsx", "pages/ResultadosPublicos.tsx", "pages/PerformanceIA.tsx"):
        assert "stake_label" in _front(tela) or "STAKE_LABEL_PADRAO" in _front(tela),             f"{tela} mostra unidade sem dizer a stake"


def test_lucro_fecha_a_fila_na_tela_de_picks():
    """Ordem pedida: volume (Picks, Green, Red), taxa (Win %) e o resultado por
    ultimo."""
    tela = _front_codigo("pages/Picks.tsx")
    inicio = tela.index("Performance da IA · Geral")
    bloco = tela[inicio:inicio + 1500]
    rotulos = ["'Picks'", "'Green'", "'Red'", "'Win %'", "'Lucro'"]
    posicoes = [bloco.find(r) for r in rotulos]
    assert all(p >= 0 for p in posicoes), dict(zip(rotulos, posicoes))
    assert posicoes == sorted(posicoes), dict(zip(rotulos, posicoes))


def test_picks_mostra_lucro_que_o_endpoint_ja_devolvia():
    """/suggestions/stats/quick sempre devolveu `profit`; a tela ignorava."""
    assert "COALESCE(SUM(profit)" in _codigo("routers/suggestions.py", "get_quick_stats")
    tela = _front_codigo("pages/Picks.tsx")
    assert "lucroUnidades" in tela
    assert "quickStats?.profit" in tela, "lucro da tela de Picks tem que sair do endpoint"


# ─────────────────────── 2. Faixa de plano ───────────────────────


def test_performance_da_ia_so_ganhou_o_tile():
    """A tela nao foi reorganizada: os quatro indicadores originais seguem, na
    ordem original, e o lucro entra como quinto."""
    tela = _front_codigo("pages/PerformanceIA.tsx")
    for original in ("Assertividade", "Picks resolvidos", "ROI acumulado", "Ligas cobertas"):
        assert original in tela, f"{original} sumiu da Performance da IA"
    assert tela.index("Assertividade") < tela.index("Lucro da IA")


def test_faixa_de_plano_so_aparece_logada():
    barra = _front_codigo("components/PlanUpsellBar.tsx")
    assert "if (!user" in barra, "faixa tem que sumir pra visitante deslogado"
    assert "isAdmin" in barra, "admin nao recebe convite de assinatura"


def test_faixa_de_plano_cobre_free_trial_e_vip_vencendo():
    barra = _front_codigo("components/PlanUpsellBar.tsx")
    assert "'free'" in barra
    assert "'trial'" in barra, "periodo de teste tambem recebe o convite"
    assert "'vip'" in barra


def test_faixa_de_plano_nao_alcanca_a_home():
    """A exclusao e' estrutural, nao um `if` que alguem esquece de atualizar:
    a faixa mora no PageShell e a Home monta a propria casca."""
    assert "PlanUpsellBar" in _front_codigo("components/PageShell.tsx")
    assert "PageShell" not in _front("pages/Home.tsx")


def test_faixa_de_plano_nao_aparece_em_checkout_e_planos():
    """Quem ja' esta' na tela de assinar nao precisa ser convidado a ir."""
    barra = _front_codigo("components/PlanUpsellBar.tsx")
    assert "/checkout" in barra and "/planos" in barra


# ─────────────────────── 3. Odd do clique em "Apostei" ───────────────────────


def test_pick_odd_responde_para_jogo_nao_iniciado():
    """Era ESTE o bug por tras de "so' atualiza pra menos".

    A versao anterior cortava fora tudo que nao estivesse ao vivo
    (`if status not in LIVE_STATUSES: return {"odd": None}`), e jogo nao
    iniciado e' o caso normal de quem clica em Apostei.
    """
    corpo = _codigo("routers/live.py", "get_current_pick_odd")
    assert "odd_atual(" in corpo
    assert "return {\"odd\": None, \"is_live\": False" not in corpo, \
        "voltou a recusar jogo nao iniciado"

    atual = _codigo("routers/live.py", "odd_atual")
    assert "_fetch_prematch_odds" in atual, "caminho pre-jogo sumiu"
    assert "_find_live_odd" in atual, "caminho ao vivo sumiu"


def test_odd_nao_tem_trava_de_direcao():
    """O pedido foi explicito: atualizar pra cima tambem.

    Nenhum dos caminhos pode comparar a odd nova com a do pick pra decidir se
    aceita -- o que a casa estiver pagando e' o que vale.
    """
    fonte = _fonte("routers/live.py")
    corpo = _codigo("routers/live.py", "_find_prematch_odd")
    # O unico `>` de comparacao entre odds aqui e' o "melhor odd entre casas".
    assert "odd > melhor" in corpo
    assert "min(" not in corpo, "apareceu um teto de odd"
    assert re.search(r"odd\s*<\s*(pick|salva|original)", fonte) is None, \
        "apareceu comparacao com a odd do pick"


def test_jogo_encerrado_nao_gasta_chamada_de_api():
    """Odd de jogo que ja' acabou nao existe; insistir so' queima quota."""
    atual = _codigo("routers/live.py", "odd_atual")
    assert "FT_STATUSES" in atual


def test_bilhete_recombina_as_pernas():
    """Multipla e alavancagem eram os unicos tipos em que Apostei nunca
    conferia a odd: o modal abria com o numero da geracao.

    Bilhete nao tem odd propria numa casa -- ele e' o produto das pernas, entao
    cada perna e' reconsultada e o produto refeito.
    """
    corpo = _codigo("routers/live.py", "get_current_ticket_odd")
    assert "combinada *=" in corpo
    assert "partial" in corpo, "bilhete com perna nao atualizada tem que se declarar parcial"

    pernas = _codigo("routers/live.py", "_pernas_do_bilhete")
    assert "picks_multiplas" in pernas
    assert "picks_alavancagem" in pernas


def test_casas_ativas_em_cache():
    """Tres pernas chamariam a leitura de casas tres vezes, e cada conexao nova
    custa ~998ms de abertura mais 154ms de consulta."""
    corpo = _codigo("routers/live.py", "_casas_ativas")
    assert "_casas_cache" in corpo
    assert "_TTL_CASAS" in corpo


def test_busca_de_odd_e_um_hook_so():
    """A busca vivia copiada no card VIP e no card free, e nao existia nos de
    multipla e alavancagem."""
    hook = _front("hooks/useOddAtualizada.ts")
    assert "/live/pick-odd" in hook
    assert "/live/ticket-odd" in hook

    for tela in ("components/SuggestionCard.tsx", "pages/Picks.tsx"):
        fonte = _front_codigo(tela)
        assert "useOddAtualizada" in fonte
        assert "'/live/pick-odd'" not in fonte, f"{tela} voltou a chamar a rota na mao"


def test_modal_nao_chama_a_odd_nova_de_odd_do_pick():
    """`pickOdd` passou a ser a odd ATUALIZADA. Sem `originalOdd`, o rotulo
    "(pick: X)" passaria a exibir a odd nova como se fosse a publicada, e a
    mudanca que acabou de acontecer ficaria invisivel."""
    modal = _front_codigo("components/ApostaModal.tsx")
    assert "originalOdd" in modal
    assert "(pick: {oddPick})" in modal
    assert "subiu" in modal and "caiu" in modal, "o modal tem que dizer os dois sentidos"


# ────────────── 4. Correcoes de 15/08 (Por Jogo, cashout, fila de jogos) ──────────────


def test_por_jogo_conta_as_pernas_do_proprio_union():
    """A ABA ESTAVA VAZIA POR ERRO DE CONTAGEM, nao por falta de dado.

    `get_results_games` fazia `n_legs = 1 if source != "all" else 5` enquanto o
    UNION tinha quatro pernas. Com o filtro em "all" -- o estado inicial da aba
    -- o numero de parametros nao batia com o de placeholders, psycopg2
    levantava, `_safe_query` engolia e a tela dizia "Nenhum pick encontrado"
    para um historico de centenas de picks.
    """
    from routers.suggestions import _build_combined_sql, FONTES_POR_JOGO

    date_cond = " AND match_date >= CURRENT_DATE - (%s * INTERVAL '1 day')"
    sql, n = _build_combined_sql("all", date_cond)
    assert n == sql.count("%s") == len(FONTES_POR_JOGO)

    for fonte in FONTES_POR_JOGO:
        sql_1, n_1 = _build_combined_sql(fonte, date_cond)
        assert n_1 == sql_1.count("%s") == 1, fonte

    corpo = _codigo("routers/suggestions.py", "get_results_games")
    assert "n_legs = 1 if source" not in corpo, "contagem escrita a mao voltou"


def test_por_jogo_cobre_os_seis_pipelines():
    """Faltas e defesas contavam no ROI publico desde 01/08 e nesta aba nao
    existiam: um pick de faltas resolvido nao aparecia em lugar nenhum dela."""
    from routers.suggestions import FONTES_POR_JOGO

    assert set(FONTES_POR_JOGO) == {
        "vip", "free", "multipla", "alavancagem", "faltas", "goleiros",
    }


def test_abas_de_resultados_tem_indicadores():
    """Por Liga, Por Jogo e Por Mes abriam direto numa lista, sem nenhuma
    leitura de conjunto."""
    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    for painel in ("statsPorLiga", "statsPorJogo", "statsPorMes"):
        assert painel in tela, f"{painel} nao esta montado"
    assert tela.count("<AbaStats") == 3


def test_cashout_conta_como_green_red_ou_push():
    """Cashout devolvia a etiqueta "CASHOUT", que nao existe em nenhum outro
    lugar do sistema -- nem no `getResultStyle` do front, nem nos
    `COUNT(*) FILTER (WHERE result = 'GREEN')`. O pick encerrado por cashout
    entrava no saldo em reais e sumia do placar: numa banca de dois picks (um
    green e um cashout positivo) a tela mostrava "1G / 0R de 2".
    """
    from routers.banca import _compute_follow_pnl

    pick = {"result": "GREEN", "odd": 1.72}
    base = {"stake_units": 5.0, "actual_odd": 1.72}
    unidade = 10.0  # stake de R$ 50,00

    for valor, esperado in [(81.29, "GREEN"), (30.00, "RED"), (50.00, "PUSH")]:
        label, _u, pnl = _compute_follow_pnl(pick, {**base, "cashout_amount": valor}, unidade)
        assert label == esperado, f"cashout de R${valor} virou {label}"

    # O sinal do P&L e o que manda, nao o resultado oficial do pick: cashout
    # feito no prejuizo continua RED mesmo que o jogo termine GREEN depois.
    label, _u, _p = _compute_follow_pnl(pick, {**base, "cashout_amount": 10.0}, unidade)
    assert label == "RED"

    # Le codigo, nao prosa: a docstring da funcao explica a etiqueta antiga.
    assert 'return "CASHOUT"' not in _fonte("routers/banca.py"), "etiqueta orfa voltou"


def test_fila_de_jogos_sai_da_tabela_local():
    """A lista "jogos sendo analisados hoje" varria a API-Football liga por
    liga, duas datas cada: 20 requisicoes em rajada com 10 ligas cadastradas.
    As que estouravam o teto do plano voltavam vazias em silencio, entao so' as
    primeiras ligas do ORDER BY league_id apareciam -- em 15/08/2026 o banco
    tinha 12 jogos em 4 ligas e a tela mostrava 3, todos da Serie A.
    """
    tela = _front_codigo("components/PicksPendingCard.tsx")
    assert "/public/next-fixtures" in tela
    assert "/fixtures/today" not in tela, "voltou a varrer a API liga por liga"

    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "match_datetime::date = %s::date" in corpo, "filtro de dia inteiro sumiu"


def test_hora_do_jogo_sai_por_fatia_de_string():
    """`match_datetime` e' horario de Brasilia SEM fuso: `new Date` sobre ele
    reinterpreta no fuso do navegador e desloca a hora pra quem esta fora do
    Brasil."""
    tela = _front_codigo("components/PicksPendingCard.tsx")
    assert "horaBR" in tela
    assert "toLocaleTimeString" not in tela


# ────────────── 5. Comparativo por produto, info e traducao de mercado ──────────────


def test_quebra_por_produto_sai_de_uma_consulta_so():
    """A aba "Por Jogo" mostra o lucro de cada produto e a curva de cada um no
    tempo. As duas coisas saem da MESMA varredura: o agregado por fonte e'
    somado em Python a partir da serie, em vez de custar uma segunda ida ao
    banco (154ms) pra refazer uma soma que ja' esta na mao.

    E fica fora do caminho slim -- a Home nao usa nada disto.
    """
    corpo = _codigo("routers/public.py", "public_results")
    assert "by_source_day = [] if slim else" in corpo
    assert "GROUP BY match_date, source" in corpo
    # O agregado nao pode ser uma segunda consulta.
    assert corpo.count("GROUP BY match_date, source") == 1
    assert "por_fonte" in corpo, "agregado por fonte deveria ser somado em Python"


def test_por_jogo_mostra_numero_geral_e_nao_da_pagina():
    """Lucro de dez linhas nao diz nada sobre a IA · diz sobre quais dez linhas
    calharam de estar na pagina 1."""
    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    assert "Lucro geral" in tela
    assert "Lucro da página" not in tela, "o indicador voltou a ser da pagina"
    assert "bySource" in tela and "bySourceDay" in tela
    assert "PipelineProfitChart" in tela


def test_curva_por_produto_e_acumulada_e_na_mesma_grade():
    """Lucro diario e' serrilhado e vira ruido com seis series; a curva
    acumulada mostra a inclinacao, que e' a leitura que importa.

    E toda serie anda sobre a MESMA grade de dias -- sem isso, um pipeline que
    publicou em menos dias apareceria esticado e pareceria subir mais rapido.
    """
    grafico = _front_codigo("components/PipelineProfitChart.tsx")
    assert "acc +=" in grafico, "a curva tem que ser acumulada"
    assert "Array.from(new Set(data.map(p => p.match_date))).sort()" in grafico


def test_cards_explicam_no_icone_em_vez_de_subtitulo():
    """A linha miuda embaixo de cada numero roubava a atencao do valor e quase
    ninguem lia. Quem quer saber o que a metrica significa clica no info."""
    # Ou o InfoTip direto (ladrilho escrito na tela), ou o `info` do StatTile,
    # que monta o mesmo icone por dentro.
    for tela in ("home/StatsBand.tsx", "pages/Picks.tsx",
                 "pages/ResultadosPublicos.tsx", "pages/PerformanceIA.tsx"):
        fonte = _front_codigo(tela)
        assert "InfoTip" in fonte or "info=" in fonte, f"{tela} nao tem explicacao no icone"
        assert "hint=" not in fonte, f"{tela} ainda tem subtitulo em ladrilho"

    # O primitivo aceita `info`, e a Home nao usa mais `hint` nenhum.
    assert "info?: string" in _front_codigo("components/ui/Card.tsx")
    assert "hint:" not in _front_codigo("home/StatsBand.tsx")


def test_mercado_em_portugues_encontra_a_propria_explicacao():
    """A CAUSA DA INFO GENERICA.

    O motor grava `picks.market` ja' traduzido, entao o pick chega como
    "Escanteios Mais/Menos" e nao como "Corners Over Under". MARKET_EXPLAIN e
    regraDoMercado sao indexados pela chave em ingles, entao NENHUM desses
    picks casava e todos caiam em "Da GREEN conforme as condicoes do mercado
    X" -- 232 dos 312 picks do historico em 15/08/2026.
    """
    fonte = _front("utils/marketTranslate.ts")
    assert "PT_PARA_CHAVE" in fonte
    assert "export function chaveCanonica" in fonte
    # Os dois consumidores tem que canonizar antes de consultar o mapa.
    for fn in ("export function regraDoMercado", "export function explainMarket"):
        corpo = fonte[fonte.index(fn):]
        corpo = corpo[:corpo.index("\n}")]
        assert "chaveCanonica(market)" in corpo, f"{fn} nao canoniza"


def test_mercados_que_vazavam_em_ingles_tem_traducao():
    """"Total Shots Over 23.5" aparecia cru na Dica do Dia da Home."""
    fonte = _front("utils/marketTranslate.ts")
    for cru in ("'total shots'", "'total shotongoal'", "'offsides home total'"):
        assert cru in fonte, f"{cru} continua sem traducao"


def test_regra_do_mercado_concorda_em_numero():
    """Saia "sairem 1 gols ou menos"."""
    fonte = _front("utils/marketTranslate.ts")
    assert "Math.abs(n) === 1 ? singular : plural" in fonte
