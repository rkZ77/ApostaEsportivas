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


def test_home_mostra_lucro_e_media_por_produto():
    """O pedido: lucro acumulado em unidades e media por pick de VIP e de free."""
    banda = _front_codigo("home/StatsBand.tsx")
    assert "Lucro da IA" in banda
    assert "Média por pick VIP" in banda
    assert "Média por pick free" in banda


def test_home_nao_mostra_roi_junto_da_media_em_unidades():
    """ROI e media de unidades sao o MESMO numero.

    Toda stake do historico vale 1u, entao `roi` e' `media_de_unidades × 100`.
    Os dois lado a lado seriam o mesmo dado em roupa diferente, e quem entende
    de aposta percebe. O ROI segue vivo em /resultados e /performance, onde o
    leitor esta' comparando com fonte que publica em %.
    """
    banda = _front_codigo("home/StatsBand.tsx")
    assert "ROI" not in banda, "ROI voltou pra faixa da Home ao lado da media"


def test_premissa_de_stake_fixa_aparece_junto_do_numero():
    """O lucro publico e' flat 1u por pick, e a Banca sugere de 1u a 10u.

    Sem a premissa escrita na tela, o usuario compara com a banca dele, os
    numeros nao batem e o site parece estar mentindo.
    """
    assert "1 unidade por pick" in _front("home/StatsBand.tsx")
    for tela in ("pages/Picks.tsx", "pages/ResultadosPublicos.tsx"):
        assert "stake 1u" in _front(tela), f"{tela} mostra unidade sem dizer a stake"


def test_picks_mostra_lucro_que_o_endpoint_ja_devolvia():
    """/suggestions/stats/quick sempre devolveu `profit`; a tela ignorava."""
    assert "COALESCE(SUM(profit)" in _codigo("routers/suggestions.py", "get_quick_stats")
    tela = _front_codigo("pages/Picks.tsx")
    assert "lucroUnidades" in tela
    assert "quickStats?.profit" in tela, "lucro da tela de Picks tem que sair do endpoint"


# ─────────────────────── 2. Faixa de plano ───────────────────────


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
