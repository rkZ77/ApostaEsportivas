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
    # O SQL saiu de public_results e foi pra _resultados_publicos em 04/09: o
    # endpoint agora so agenda as varreduras e delega a parte cacheada.
    corpo = _codigo("routers/public.py", "_resultados_publicos")
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
    assert "Média por pick:" in banda, "a quebra por produto sumiu da faixa"
    assert "mediaVip" in banda and "mediaFree" in banda


def test_plano_de_stake_vive_num_lugar_so():
    """VIP 4u, free e mercados 3u, multipla 1u · escrito uma vez, lido por todos.

    Com a tabela repetida, /public/results (Home, Resultados, Performance) e
    /suggestions/stats/quick (tela de Picks) passariam a anunciar lucros
    diferentes pra mesma IA, e nada acusaria a divergencia.

    Numeros revisados em 2026-08-19 a pedido do usuario: o VIP fica um degrau
    acima do que e' vitrine (free, faltas, defesas), e a alavancagem sai do
    placar em unidades -- ela e' um caminho, e so' vira unidade na banca de
    quem apostou (alavancagem_series).
    """
    from stake_plan import STAKE_PADRAO, conta_em_unidades

    assert STAKE_PADRAO["vip"] == 4
    # Free e os mercados proprios sao a vitrine: entrada simples tambem, mas
    # um degrau abaixo do produto pago.
    assert STAKE_PADRAO["free"] == STAKE_PADRAO["faltas"] == STAKE_PADRAO["goleiros"] == 3
    assert STAKE_PADRAO["multiplas"] == 1
    # Zero = fora do placar de unidades, NAO "deu zero de lucro".
    assert STAKE_PADRAO["alavancagem"] == 0
    assert not conta_em_unidades("alavancagem")
    assert conta_em_unidades("vip") and conta_em_unidades("free")

    for arquivo in ("routers/public.py", "routers/suggestions.py"):
        assert "stake_plan import" in _fonte(arquivo), f"{arquivo} nao le o plano central"


def test_espelho_do_plano_no_front_bate_com_o_backend():
    """O card de pick precisa do plano ANTES de o backend responder.

    Ele mostra "lucro do pick" pra quem NAO apostou, e antes caia num 1u fixo
    -- entao o mesmo pick aparecia a 1u no card e a 4u no placar da mesma tela.
    A correcao foi o card ler o plano; o preco e' um espelho em TypeScript, e o
    preco do espelho e' este teste. Sem ele, mudar um lado e esquecer o outro
    reintroduz exatamente a divergencia que o plano central existe pra impedir.
    """
    import re
    from stake_plan import STAKE_PADRAO, STAKE_FALLBACK

    fonte = _front("utils/stakePlan.ts")
    bloco = fonte[fonte.index("STAKE_PADRAO"):fonte.index("STAKE_FALLBACK")]
    espelho = {m.group(1): int(m.group(2))
               for m in re.finditer(r"(\w+):\s*(\d+),", bloco)}

    for tipo, unidades in STAKE_PADRAO.items():
        assert espelho.get(tipo) == unidades, (
            f"{tipo}: backend {unidades}u, front {espelho.get(tipo)}u")

    # O front usa a forma de rota ('multipla'); o backend, o nome da tabela.
    # A chave extra tem que apontar pro mesmo peso, senao o card da multipla
    # cai no fallback sem ninguem perceber.
    assert espelho.get("multipla") == STAKE_PADRAO["multiplas"]
    assert f"STAKE_FALLBACK = {STAKE_FALLBACK}" in fonte

    # Quem calcula pergunta pro plano, nao pro literal. O defeito era o 1u
    # chutado -- so' na stake de quem NAO seguiu; `stakeSuggestion?.units ?? 1`
    # e' outra coisa (sugestao da Banca) e continua valendo.
    for tela in ("components/SuggestionCard.tsx", "pages/Picks.tsx"):
        codigo = _front_codigo(tela)
        assert "stakePlan" in codigo, f"{tela} nao le o plano"
        assert "stakeSeguida! : 1" not in codigo, f"{tela}: nao-seguiu voltou pra 1u fixo"
        for pos in [m.start() for m in re.finditer(r"calcProfitUnits\(", codigo)]:
            chamada = codigo[pos:pos + 240]
            assert "?? 1," not in chamada, f"{tela}: calcProfitUnits ainda chuta 1u"


def test_peso_multiplica_lucro_e_stake_juntos():
    """Se so' o lucro fosse pesado, o ROI (lucro/stake) saltaria pelo mesmo
    fator e o site anunciaria um retorno que nunca existiu."""
    from routers.public import _build_union, _SUB_BUILDERS
    import re

    # `_build_union` passou a receber os builders ATIVOS (a fonte ao vivo sai
    # do UNION onde `picks_live` nao existe). O teste passa o catalogo inteiro
    # de proposito: o que ele verifica e' o peso de CADA fonte declarada, nao
    # o que uma instancia especifica tem.
    sql = _build_union(_SUB_BUILDERS, "", None)
    # A alavancagem tem o UNION ALL do proprio caminho recursivo dentro dela,
    # entao cortar a string por "UNION ALL" parte o bloco dela no meio. Costura
    # de volta: bloco de verdade e' o que declara a fonte.
    blocos, atual = [], ""
    for pedaco in sql.split("UNION ALL"):
        atual += pedaco
        if re.search(r"'\w+' AS source", atual):
            blocos.append(atual)
            atual = ""
    for bloco in blocos:
        fonte = re.search(r"'(\w+)' AS source", bloco)
        assert fonte, bloco[:120]
        if fonte.group(1) == "alavancagem":
            # Ela nao tem peso por linha: o lucro sai do CAMINHO fechado (ver
            # alavancagem_caminho.py). A exigencia e' a mesma -- lucro e stake
            # da MESMA origem, sempre juntos --, so' que a origem e' a CTE.
            assert "cam.caminho_profit" in bloco and "cam.caminho_stake" in bloco
            continue
        lucro = re.search(r"profit \* (\d+) AS profit", bloco)
        stake = re.search(r"(\d+)(?:::numeric)? AS stake", bloco)
        assert lucro and stake, bloco[:120]
        assert lucro.group(1) == stake.group(1),             f"{fonte.group(1)}: lucro x{lucro.group(1)} mas stake {stake.group(1)}u"


def test_premissa_de_stake_aparece_junto_do_numero():
    """A Banca sugere stake variavel; sem o plano escrito na tela o usuario
    compara com a banca dele, os numeros nao batem e o site parece mentir.

    A legenda vem do backend (`stake_label`) pra nao envelhecer sozinha quando
    o plano mudar.
    """
    from stake_plan import rotulo_curto

    assert "4u" in rotulo_curto() and "1u" in rotulo_curto()
    assert '"stake_label": rotulo_curto()' in _codigo("routers/public.py", "_resultados_publicos")
    for tela in ("home/StatsBand.tsx", "pages/ResultadosPublicos.tsx", "pages/PerformanceIA.tsx"):
        assert "stake_label" in _front(tela) or "STAKE_LABEL_PADRAO" in _front(tela),             f"{tela} mostra unidade sem dizer a stake"


def test_lucro_fecha_a_fila_na_tela_de_picks():
    """Ordem pedida: volume (Picks, Green, Red), taxa (Win %) e o resultado por
    ultimo."""
    tela = _front_codigo("pages/Picks.tsx")
    inicio = tela.index("Performance geral da IA")
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


# O convite de plano deixou de ser faixa no topo do PageShell em 21/08 (pedido
# do usuario: ela custava uma linha inteira do topo em toda tela do app). Virou
# aviso de rodape + item no sino. As REGRAS abaixo nao mudaram nenhuma, so' o
# arquivo que as guarda -- por isso os testes seguiram junto em vez de sumir.


def test_convite_de_plano_so_aparece_logado():
    regra = _front_codigo("lib/planoUpsell.ts")
    assert "if (!user || isAdmin) return null" in regra, (
        "visitante deslogado e admin nao recebem convite de assinatura"
    )


def test_convite_de_plano_cobre_free_trial_e_vip_vencendo():
    regra = _front_codigo("lib/planoUpsell.ts")
    assert "'free'" in regra
    assert "'trial'" in regra, "periodo de teste tambem recebe o convite"
    assert "'vip'" in regra


def test_convite_de_plano_nao_alcanca_a_home():
    """A Home nunca ve o convite, e a exclusao continua ESTRUTURAL.

    Antes era o PageShell (a Home monta a propria casca). Agora e' o
    PlanUpsellToast montado uma vez em App.tsx, dentro do <Suspense> que so'
    existe para tela logada -- e a Home segue sem PageShell.
    """
    assert "PlanUpsellBar" not in _front_codigo("components/PageShell.tsx"), (
        "a faixa saiu do PageShell; se voltou, e' regressao"
    )
    assert "PlanUpsellToast" in _front_codigo("App.tsx")
    assert "PageShell" not in _front("pages/Home.tsx")


def test_convite_de_plano_nao_aparece_em_checkout_e_planos():
    """Quem ja' esta' na tela de assinar nao precisa ser convidado a ir."""
    aviso = _front_codigo("components/PlanUpsellToast.tsx")
    assert "/checkout" in aviso and "/planos" in aviso


def test_convite_de_plano_espera_o_tour_de_boas_vindas():
    """z-[9990] contra o z-[80] do tour: sem esperar, ele pula na frente.

    Vender assinatura para quem ainda nao viu o produto funcionar e' o pior
    momento possivel, e era o que acontecia no primeiro acesso.
    """
    aviso = _front_codigo("components/PlanUpsellToast.tsx")
    assert "useOnboarding" in aviso
    assert "tourNaFrente" in aviso


def test_convite_de_plano_nao_empilha_com_o_de_confirmar_email():
    """Free que ainda pode ganhar o trial ve o convite do e-mail, nao este.

    Os dois moram na mesma faixa do rodape (bottom-24). Dois avisos pedindo
    acesso ao VIP por caminhos diferentes, empilhados, e' ruido -- e o do e-mail
    ganha porque entrega 2 dias de graca.
    """
    regra = _front_codigo("lib/planoUpsell.ts")
    assert "podeGanharTrial" in regra
    assert "if (podeGanharTrial) return null" in regra


def test_convite_de_plano_fica_guardado_no_sino():
    """Dispensar o aviso nao pode apagar o convite de vez.

    Ele nao vem do servidor (nao e' evento, e' estado permanente da conta),
    entao o item do sino e' montado no cliente com id negativo -- e o markRead
    precisa reconhecer esse id em vez de fazer POST em /notifications/-1.
    """
    ctx = _front_codigo("context/NotificationContext.tsx")
    assert "ID_NOTIFICACAO_PLANO" in ctx
    assert "id === ID_NOTIFICACAO_PLANO" in ctx, (
        "markRead tem que tratar o item sintetico antes de chamar a API"
    )
    assert "'plan_upsell'" in ctx


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


def test_por_jogo_cobre_todos_os_pipelines():
    """Faltas e defesas contavam no ROI publico desde 01/08 e nesta aba nao
    existiam: um pick de faltas resolvido nao aparecia em lugar nenhum dela.

    `player_stats` entrou em 27/08 pelo mesmo motivo -- ele e' publicado e
    liquidado como os outros. `boost` NAO entra: fase 1 dele e' so' Admin.
    """
    from routers.suggestions import FONTES_POR_JOGO

    assert set(FONTES_POR_JOGO) == {
        "vip", "free", "multipla", "alavancagem", "faltas", "goleiros",
        "player_stats",
    }
    assert "boost" not in FONTES_POR_JOGO


def test_abas_de_resultados_tem_indicadores():
    """Por Liga, Por Jogo e Por Mes abriam direto numa lista, sem nenhuma
    leitura de conjunto.

    `statsPorMes` deixou de existir em 02/09/2026: a aba Por Mes virou o
    fechamento mensal da IA e passou a montar os proprios indicadores dentro de
    `AbaFechamento`, do mes selecionado (picks, acerto, lucro, ROI) em vez do
    historico inteiro. O teste segue o componente, nao o nome antigo -- o que
    ele protege e' "nenhuma aba abre sem leitura de conjunto".
    """
    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    for painel in ("statsPorLiga", "statsPorJogo", "AbaFechamento"):
        assert painel in tela, f"{painel} nao esta montado"
    # Uma por aba: Por Liga, Por Jogo e a de dentro do AbaFechamento (Por Mes).
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
    corpo = _codigo("routers/public.py", "_resultados_publicos")
    # `if slim` virou `if not _quer("by_source_day")` em 04/09 · a pagina pede
    # o bloco so' na aba que o usa, e `_quer` mantem o corte do slim por cima.
    assert 'by_source_day = [] if not _quer("by_source_day") else' in corpo
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


def test_ladrilho_e_numero_e_rotulo_e_mais_nada():
    """Nem subtitulo (empilhava texto miudo que ninguem le) nem icone de ajuda
    colado no numero (polui justo o que o ladrilho existe pra mostrar).

    O que precisa ser dito sobre o conjunto vai numa linha de apoio, uma vez,
    embaixo da faixa -- e o plano de stake TEM que estar la: a Banca sugere
    stake variavel, e sem a premissa o numero nao bate com o que o usuario ve
    na banca dele.
    """
    for tela in ("home/StatsBand.tsx", "pages/Picks.tsx",
                 "pages/ResultadosPublicos.tsx", "pages/PerformanceIA.tsx"):
        fonte = _front_codigo(tela)
        assert "hint=" not in fonte, f"{tela} tem subtitulo em ladrilho"
        assert "info=" not in fonte, f"{tela} tem icone de ajuda colado no numero"

    assert "info?: string" not in _front_codigo("components/ui/Card.tsx")
    assert "hint:" not in _front_codigo("home/StatsBand.tsx")

    # A premissa sobrevive na linha de apoio das telas de RESULTADO.
    assert "Plano fixo de stake" in _front("home/StatsBand.tsx")

    # Em Picks ela saiu (16/08). A tensao que esta funcao documentava era real
    # -- a Banca sugere stake variavel e o placar usa stake fixa -- mas a
    # solucao de publicar as duas premissas lado a lado nao funcionou na tela:
    # "4u em picks simples" ficava logo acima de um card mandando apostar 5u, e
    # o leitor le contradicao, nao nuance. Os dois numeros respondem perguntas
    # diferentes (placar da IA x stake pra banca DAQUELE usuario) e explicar
    # isso no rodape custava mais texto do que o numero valia.
    #
    # Nas telas de resultado a legenda fica, porque la nao existe card de Kelly
    # pra contradizer -- e' so' premissa de calculo, que e' o papel dela.
    assert "Plano fixo de stake" not in _front("pages/Picks.tsx")

    # O "i" AO LADO DO MERCADO SAIU DE TODOS OS CARDS (2026-09-02, pedido do
    # usuario). Ele abria um tooltip com a regra do mercado -- a mesma regra
    # que hoje e' a PRIMEIRA secao do "Entenda esta analise", que todo card tem
    # no rodape. No celular o icone e' um alvo de 12px que, quando acerta,
    # cobre a linha que a pessoa estava lendo.
    #
    # A regra nao se perde, e e' isso que o teste trava: sumiu do card, mas
    # continua alcancavel pelo botao de analise.
    for tela in ("pages/Picks.tsx", "components/SuggestionCard.tsx"):
        assert "<InfoTip" not in _front_codigo(tela), f"{tela} tem o 'i' de volta no card"
    assert "regraDoMercado" in _front_codigo("components/AnalysisModal.tsx")


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


# ────────────── 6. Bugs de tela achados com Playwright (15/08) ──────────────


def test_dica_nao_e_posicionada_por_transform():
    """A DICA COBRIA O QUE ESTAVA EXPLICANDO.

    O deslocamento pra cima era `transform: translateY(-100%)` no style do
    proprio motion.div. Só que framer-motion ESCREVE a propriedade `transform`
    inteira pra animar a escala do popIn, e apagava o translate ja' no primeiro
    quadro. Medido no navegador em 15/08: gatilho em y=651, dica renderizada em
    y=649 com 101px de altura, quando deveria comecar em y=542.

    Agora o deslocamento vai no `top`, com a altura MEDIDA, e o lado vira pra
    baixo quando nao ha espaco acima.
    """
    # Le codigo, nao prosa: o comentario do arquivo cita o transform antigo.
    codigo = _front_codigo("components/ui/Tooltip.tsx")
    fonte = _front("components/ui/Tooltip.tsx")
    assert "translateY(-100%)" not in codigo, "voltou a posicionar por transform"
    assert "useLayoutEffect" in fonte, "sem medir a altura nao da pra escolher o lado"
    assert "'abaixo'" in fonte, "faltou o caso de abrir pra baixo"


def test_rotulo_do_ladrilho_nao_tem_flex():
    """`.stat-tile` e' text-center. O flex que abria espaco pro icone tirava o
    texto do centro; sem icone, o rotulo volta a ser so' o rotulo."""
    for arquivo in ("components/ui/Card.tsx", "pages/ResultadosPublicos.tsx"):
        fonte = _front_codigo(arquivo)
        assert "stat-label flex" not in fonte, arquivo


def test_rodape_do_card_de_pick_desce_pro_fim():
    """Quatro picks lado a lado tinham "Apostei" e "Compartilhar" em quatro
    alturas diferentes: os cards ja' esticavam pra mesma altura no grid, mas o
    conteudo empilhava a partir do topo e o rodape parava onde o texto acabasse.
    """
    css = _front("index.css")
    bloco = css[css.index(".pick-card {"):]
    bloco = bloco[:bloco.index("}")]
    assert "flex flex-col h-full" in bloco, "a casca do card nao e' coluna de altura cheia"

    partes = _front_codigo("components/PickCardParts.tsx")
    assert "border-t border-line/60 mt-auto" in partes, "rodape nao desce sozinho"

    # ALGUEM PRECISA ABSORVER A FOLGA, e ate' 2026-09-02 era o bloco do "Fato"
    # (PickReasoning, `rounded-md flex-1`). O "Fato" saiu de todos os cards --
    # ele adiantava as primeiras linhas do mesmo texto que abre dentro do
    # "Entenda esta analise" --, entao o `flex-1` passou a ser um espacador
    # explicito, um por card.
    #
    # Sem ele o defeito volta inteiro: numa grade de quatro picks, o botao de
    # analise para onde o conteudo de cada card acabar.
    for tela, quantos in (("components/SuggestionCard.tsx", 1),
                          ("pages/Picks.tsx", 3)):
        fonte = _front_codigo(tela)
        assert fonte.count('<div className="flex-1" aria-hidden="true" />') >= quantos, (
            f"{tela} perdeu o espacador que segura o rodape no fim do card")


def test_serie_do_mercado_cobre_chutes_e_impedimentos():
    """"Como esse mercado vem se comportando" ficava VAZIO nos picks de chutes.

    `folha_do_jogo` so' copia as chaves de `_ADAPTADOR`, e "Total Shots" e
    "Offsides" nao estavam la' -- mesmo com as colunas existindo em
    match_statistics desde sempre. A folha saia sem a chave, `_stat_side`
    devolvia None pra todo jogo, e todo jogo caia fora da serie, enquanto
    escanteios e cartoes mostravam os ultimos jogos normalmente.
    """
    import market_form

    chaves = {c for c, _, _ in market_form._ADAPTADOR}
    assert "Total Shots" in chaves
    assert "Offsides" in chaves

    # A folha tem que sair com as duas chaves quando as colunas vem preenchidas.
    ms = {
        "home_corners": 5, "away_corners": 4,
        "home_total_shots": 12, "away_total_shots": 15,
        "home_offsides": 2, "away_offsides": 0,
        "home_shots_on": 4, "away_shots_on": 3,
    }
    casa, fora = market_form.folha_do_jogo(ms)
    assert casa["Total Shots"] == 12 and fora["Total Shots"] == 15
    assert casa["Offsides"] == 2 and fora["Offsides"] == 0


# ────────────── 7. Graficos de lucro por mes, liga e na Home ──────────────


def test_curva_da_home_tem_rota_propria():
    """A Home chama /public/results com slim=1 justamente pra cair de sete
    consultas pra tres, e e' essa chamada que desenha o topo da pagina.
    Pendurar a serie la' devolveria o custo que o slim tirou.

    Rota separada, uma consulta, chamada depois do topo: se demorar, o que
    atrasa e' um grafico abaixo da dobra.
    """
    corpo = _codigo("routers/public.py", "public_profit_curve")
    assert "GROUP BY match_date, source" in corpo
    assert corpo.count("_q(cur") == 1, "a rota da curva tem que ser UMA consulta"

    # A curva e o grafico moram em home/RecentResults.tsx desde 04/09 (a secao
    # saiu do Home.tsx para poder ser lazy).
    home = _front_codigo("home/RecentResults.tsx")
    assert "/public/profit-curve" in home
    assert "PipelineProfitChart" in home


def test_lucro_por_mes_e_por_liga_sai_do_que_a_pagina_ja_tem():
    """Nenhuma consulta nova pros dois graficos novos.

    E o do mes sai de `by_source_day`, que ja' vem com o peso do plano de
    stake, e NAO de /results/monthly, que soma na base de 1u -- dois numeros da
    mesma tela discordando e' pior que um numero a menos.
    """
    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    assert "lucroPorMes" in tela and "lucroPorLiga" in tela
    assert "bySourceDay" in tela[tela.index("const lucroPorMes"):tela.index("const lucroPorLiga")]
    assert tela.count("<LucroBarChart") == 2


def test_barra_de_mes_e_vertical_e_a_de_liga_e_horizontal():
    """Sao duas perguntas diferentes: mes e' tempo (balde fechado, barra
    separada), liga e' comparacao entre categorias de nome comprido (de lado o
    rotulo cabe inteiro)."""
    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    mes = tela[tela.index("Lucro por mês"):]
    assert 'orientation="vertical"' in mes[:400]
    liga = tela[tela.index("Lucro por liga"):]
    assert 'orientation="horizontal"' in liga[:400]


# ────────────── 8. Historico aberto sem login (15/08) ──────────────


def test_por_jogo_e_por_mes_abertos_sem_login():
    """Sao o HISTORICO da IA, e pick encerrado nao e' produto: mercado, linha e
    odd dele ja' valeram. Exigir conta so' escondia a prova de quem ainda
    estava decidindo criar conta."""
    for rota in ("get_results_games", "get_results_monthly"):
        assinatura = _fonte("routers/suggestions.py")
        assinatura = assinatura[assinatura.index(f"def {rota}("):]
        assinatura = assinatura[:assinatura.index(")")]
        assert "get_current_user_optional" in assinatura, f"{rota} ainda exige sessao"

    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    assert "{tab === 'por_jogo' && (" in tela, "a aba ainda checa user"
    assert "{tab === 'por_mes' && (" in tela, "a aba ainda checa user"


def test_pendente_continua_exigindo_sessao():
    """`resultado=pending` inverte o filtro pra `result IS NULL` e devolveria os
    picks de HOJE com mercado, linha e odd -- o produto inteiro, de graca,
    trocando um parametro na URL."""
    corpo = _codigo("routers/suggestions.py", "get_results_games")
    assert "pode_ver_pendente = current_user is not None" in corpo
    assert 'resultado == "pending" and pode_ver_pendente' in corpo

    # E a tela nem oferece a opcao pra quem nao tem sessao.
    tela = _front_codigo("pages/ResultadosPublicos.tsx")
    assert "RESULTADO_OPTIONS.filter(o => o.value !== 'pending')" in tela


def test_stake_pessoal_nao_vaza_sem_sessao():
    corpo = _codigo("routers/suggestions.py", "get_results_games")
    assert "if current_user is None:" in corpo


def test_pagina_publica_tem_barra_com_logo_e_duas_saidas():
    """A barra do deslogado tinha o nome em texto, sem logotipo, e um unico
    "Entrar" fantasma: quem chegava por busca nao tinha como voltar pra home
    nem um caminho obvio pra criar conta."""
    barra = _front_codigo("components/PublicNav.tsx")
    # Nome do arquivo generico: o logotipo virou /logo-64.webp em 03/09 (o PNG
    # de 320 px pesava 9,3 KB pra aparecer em 32). O que o teste guarda e' que a
    # barra tem logotipo, nao qual arquivo.
    assert "/logo" in barra
    assert '/login?mode=register' in barra
    for tela in ("pages/ResultadosPublicos.tsx", "pages/PerformanceIA.tsx"):
        assert "PublicNav" in _front_codigo(tela), tela


def test_login_tem_volta_pro_site_e_topo_enxuto_no_mobile():
    """A tela de login nao tinha navegacao nenhuma, e a marca no mobile era
    logo de 96px empilhada com o nome em 30px: so' o cabecalho comia quase
    metade da tela antes do primeiro campo."""
    tela = _front_codigo("pages/Login.tsx")
    assert "Voltar para o site" in tela
    assert "w-24 h-24" not in tela, "logo gigante voltou pro mobile"
    # O painel de oferta so' aparece em cadastro · quem vai entrar ja' e cliente.
    # A tela dividida saiu em 01/09/2026: o painel virou uma faixa acima do
    # formulario, entao a condicao deixou de ser um ternario. O que o teste
    # guarda nao e' a forma, e' que a oferta continue presa ao modo `register`.
    assert "{mode === 'register' && (" in tela
    # E a barra agora e a mesma das outras publicas, em vez de um cabecalho
    # so' desta tela.
    assert "PublicNav" in tela, "o login voltou a montar cabecalho proprio"


def test_win_rate_do_login_nao_puxa_a_rota_inteira():
    """Sem slim a rota monta os sete blocos e a tela de login pagava seis
    consultas ao banco pra estampar uma porcentagem."""
    tela = _front_codigo("pages/Login.tsx")
    trecho = tela[tela.index("function RealWinRate"):]
    trecho = trecho[:trecho.index("export ")] if "export " in trecho else trecho[:1200]
    assert "slim: 1" in trecho


# ────────────── 9. Lucro pessoal, suporte e paginas publicas ──────────────


def test_lucro_em_reais_so_pra_quem_apostou():
    """O CARD ANUNCIAVA GANHO QUE O USUARIO NUNCA TEVE.

    A stake caia pra `stakeSuggestion?.units ?? 1` quando ele NAO tinha seguido
    o pick, e o card estampava "Lucro +3,75u · Em reais +R$38" usando o valor
    da unidade da banca DELE -- numa aposta em que ele nao entrou.

    Seguiu: a conta e' a dele. Nao seguiu: mostra o resultado do PICK em 1u, e
    nada de reais -- real depende de stake, e stake que nao houve nao vira
    dinheiro.
    """
    for tela in ("components/SuggestionCard.tsx", "pages/Picks.tsx"):
        fonte = _front_codigo(tela)
        assert "user_stake_units ?? stakeSuggestion?.units ?? 1" not in fonte, \
            f"{tela} ainda cai na stake sugerida pra calcular lucro"
        assert "const seguiu =" in fonte, tela
        assert "seguiu && banca" in fonte, f"{tela} calcula reais sem checar se apostou"
        assert "Não registrada" in _front(tela), f"{tela} nao diz que o usuario ficou de fora"


def test_suporte_tem_um_link_so():
    """O numero estava copiado em cinco arquivos, cada um com um texto
    diferente: trocar de numero exigia cacar as cinco copias, e esquecer uma
    mandaria o cliente pra um telefone que ninguem atende."""
    assert "wa.me/message/" in _front("lib/support.ts")
    for tela in ("components/Footer.tsx", "components/Navbar.tsx",
                 "pages/Checkout.tsx", "pages/Planos.tsx"):
        fonte = _front(tela)
        assert "from '../lib/support'" in fonte, f"{tela} nao usa o link central"
        assert "wa.me/55" not in fonte, f"{tela} ficou com numero cru"


def test_promessa_de_sem_cartao_saiu_do_site():
    """Pedido explicito: essa frase nao volta."""
    import os
    raiz = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "frontend", "src")
    achados = []
    for pasta, _, arquivos in os.walk(raiz):
        for a in arquivos:
            if not a.endswith((".tsx", ".ts")):
                continue
            caminho = os.path.join(pasta, a)
            with open(caminho, encoding="utf-8") as f:
                texto = f.read()
            if "sem cartão" in texto.lower():
                achados.append(os.path.relpath(caminho, raiz))
    assert not achados, f"a frase do cartao voltou em: {achados}"


def test_planos_mostra_planos_sem_login():
    """Todos os blocos exigiam `user`, entao deslogado a pagina ficava com o
    card de suporte e mais nada -- uma pagina chamada "Planos" que nao mostrava
    plano nenhum, justo pra quem esta decidindo se assina."""
    tela = _front_codigo("pages/Planos.tsx")
    assert "{!user && (" in tela
    assert "fmtPlanPrice(pl.price)" in tela, "os precos tem que sair de usePlans"
    assert "PublicNav" in tela, "faltou a barra publica"


def test_blog_saiu_da_navegacao():
    for tela in ("components/SiteHeader.tsx", "components/Footer.tsx"):
        assert "/blog" not in _front_codigo(tela), f"{tela} ainda linka o blog"


def test_rodape_cabe_numa_fita():
    """Eram quatro colunas com quatorze links mais a coluna da marca: um bloco
    mais alto que o conteudo de algumas paginas."""
    rodape = _front_codigo("components/Footer.tsx")
    assert "GROUPS" not in rodape, "as colunas voltaram"
    assert "const LINKS" in rodape


# ────────────── 10. Perna de multipla mostra o resultado dela ──────────────


def test_resolucao_automatica_grava_resultado_de_cada_perna():
    """O caminho que roda de fato (resolucao por visita) gravava so' o
    resultado do BILHETE, e a lista de pernas ficava com `result: null` pra
    sempre. O job em lote sempre gravou; este nasceu sem."""
    corpo = _codigo("routers/live.py", "_save_multipla_result")
    assert "_gravar_resultado_das_pernas" in corpo
    assert "games=%s" in corpo, "o UPDATE nao leva o JSONB das pernas"

    grava = _codigo("routers/live.py", "_gravar_resultado_das_pernas")
    # Anotar pelo indice com tamanhos diferentes poria o resultado de uma perna
    # em cima de outra.
    assert "len(pernas) != len(legs_results)" in grava


def test_perna_nao_herda_o_vermelho_do_bilhete():
    """Bilhete RED pintava TODA perna sem GREEN explicito de vermelho · e como
    o resultado por perna nunca era gravado, "sem GREEN explicito" era SEMPRE.
    Numa multipla de duas em que uma bateu, o usuario via duas derrotas.

    GREEN no bilhete continua implicando pernas GREEN: combinada so' paga com
    todas de pe, entao isso e' deducao. RED nao diz qual caiu.
    """
    tela = _front_codigo("pages/Picks.tsx")
    assert "m.result === 'RED'   ? (leg.result === 'GREEN' ? 'GREEN' : 'RED')" not in tela, \
        "a perna voltou a herdar o vermelho do bilhete"
    assert "leg.result ?? (m.result === 'GREEN' ? 'GREEN' : undefined)" in tela

    # Alavancagem nao tem coluna de resultado por perna: verde ou neutro.
    assert "const lr: 'GREEN' | undefined = pick.result === 'GREEN'" in tela
