"""Todo produto que da' pra SEGUIR tem que ser CONTADO em todo lugar.

O defeito que estes testes travam nao aparece como erro em lugar nenhum. Ele
tem sempre a mesma forma: uma lista de tipos de pick escrita a mao, num modulo
que ninguem lembra de abrir quando nasce um produto novo. O tipo que falta
naquela lista nao levanta excecao, nao aparece zerado -- ele SOME. A aposta
conta na banca e nao conta no ranking; o green conta no placar e nao conta na
conquista; o pick e' liquidado e o freio da varredura nao sabe que ele existe.

Ja' aconteceu quatro vezes: faltas e defesas (08/2026), Player Stats (27/08),
Pick Boost (28/08) e ao vivo (29/08). Em 29/08 o ranking do /api contava 4
tipos, o ranking publico 8, a banca 9 e o ledger de auditoria 7 -- quatro
respostas diferentes sobre o mesmo usuario e o mesmo motor.

A regra que estes testes impoem: `banca.STAKE_LIMITS` e' a lista de produtos
que o site aceita seguir, e TUDO que agrega pick tem que cobrir essa lista.
Produto novo = uma linha em cada lugar que o teste aponta, no mesmo commit.
"""
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _codigo(rel: str) -> str:
    with open(os.path.join(_BACKEND, rel), encoding="utf-8") as fh:
        return fh.read()


def _tipos_seguiveis() -> set:
    import routers.banca as banca
    return set(banca.STAKE_LIMITS)


def test_a_banca_soma_todo_tipo_que_ela_deixa_seguir():
    """`_resolve_pick` aceitar o tipo nao basta: o follow entra no banco e o
    somatorio ignora o pick.

    Alavancagem e multipla sao as duas excecoes DECLARADAS: a alavancagem sai
    por `pick_type != 'alavancagem'` (caminho em andamento nao e' dinheiro, ver
    _quebra_por_pipeline) e a multipla tem mapa proprio no corpo da rota,
    porque le `games` alem de result/odd.
    """
    import routers.banca as banca

    cobertos = set(banca._TABELAS_MERCADO) | {"vip", "free", "multipla", "alavancagem"}
    faltando = _tipos_seguiveis() - cobertos
    assert not faltando, (
        f"{faltando} pode ser seguido e some do saldo: type_map.get devolve "
        "{} e o laco faz continue, sem erro nenhum")


def test_o_mapa_da_banca_declara_a_coluna_de_time_de_cada_tabela():
    """As tabelas nao concordam no nome (`home_team` x `home_team_name`), e o
    alias fixo no SQL do chamador foi o que impediu picks_live de entrar por
    meses."""
    import routers.banca as banca

    for tipo, valor in banca._TABELAS_MERCADO.items():
        assert isinstance(valor, tuple) and len(valor) == 3, tipo
        tabela, casa, fora = valor
        assert tabela.startswith("picks_")
        assert casa.startswith("home_team") and fora.startswith("away_team")


def test_o_ranking_conta_todo_tipo_seguivel():
    """Tipo fora do CASE vira NULL e o `FILTER (WHERE result IS NOT NULL)`
    descarta a aposta · ela conta na banca do usuario e some do ranking."""
    import pick_sources

    tipos = {f[0] for f in pick_sources._FONTES}
    assert _tipos_seguiveis() <= tipos, _tipos_seguiveis() - tipos


def test_os_dois_rankings_leem_a_mesma_lista():
    """Havia dois: /api/leaderboard e /public/leaderboard. Escritos a mao, um
    contava 4 tipos e o outro 8 -- duas telas discordando sobre o mesmo
    usuario."""
    for rel in ("routers/leaderboard.py", "routers/public.py"):
        fonte = _codigo(rel)
        assert "from pick_sources import" in fonte, rel
        assert "joins_sql(" in fonte and "case_sql(" in fonte, rel


def test_as_conquistas_contam_green_de_todo_tipo():
    import routers.personal as personal

    faltando = _tipos_seguiveis() - set(personal.PICK_TABLES) - {"multipla"}
    assert not faltando, f"{faltando} nao conta pra conquista"


def test_todo_tipo_tem_peso_declarado_no_plano_de_stake():
    """Sem chave, `stake_de` cai no STAKE_FALLBACK de 1u · o produto entra no
    placar com um peso que ninguem escolheu."""
    from stake_plan import STAKE_PADRAO

    esperado = {t if t != "multipla" else "multiplas" for t in _tipos_seguiveis()}
    faltando = esperado - set(STAKE_PADRAO)
    assert not faltando, f"{faltando} sem peso declarado"


def test_o_plano_de_stake_do_front_espelha_o_do_back():
    """Ja' existe um teste que compara os dois; aqui a checagem e' so' de que
    nenhum produto novo entre num lado so'."""
    from stake_plan import STAKE_PADRAO

    front = os.path.join(os.path.dirname(_BACKEND), "frontend", "src", "utils", "stakePlan.ts")
    with open(front, encoding="utf-8") as fh:
        codigo = fh.read()
    for chave in STAKE_PADRAO:
        assert f"{chave}:" in codigo, f"{chave} nao existe no espelho do front"


def test_o_placar_publico_oferece_toda_fonte_que_ele_soma():
    """Fonte no UNION sem entrada no filtro da tela = historico que existe e
    ninguem alcanca."""
    import routers.public as public

    front = os.path.join(os.path.dirname(_BACKEND), "frontend", "src", "pages",
                         "ResultadosPublicos.tsx")
    with open(front, encoding="utf-8") as fh:
        tela = fh.read()
    # A SUPERFICIE MUDOU EM 04/09, a garantia nao. O filtro de Fonte saiu da
    # tela (pedido do usuario: so' o seletor de mes fica no topo), e quem
    # responde "como foi o produto X" passou a ser a quebra por produto da aba
    # Por Mes -- que sai do MESMO union e lista todos, sem obrigar a escolher um
    # e recarregar. `SOURCE_LABELS` e' o mapa que ela usa pra nomear cada um,
    # entao fonte que soma e nao esta' ali continua sendo historico inalcancavel.
    for chave in public._SUB_BUILDERS:
        assert f"{chave}:" in tela or f"'{chave}'" in tela,             f"{chave} soma no placar e nao aparece em lugar nenhum da tela"


def test_o_seletor_de_mes_deriva_do_mesmo_union_da_tela():
    """A lista a mao parou em quatro tabelas: um mes so' com pick de mercado
    proprio nao aparecia no seletor, e os picks daquele mes ficavam
    inalcancaveis por uma tela que os TINHA."""
    fonte = _codigo("routers/public.py")
    assert "meses_union = _build_union(" in fonte
    assert "FROM picks_vip WHERE result IS NOT NULL GROUP BY 1" not in fonte


def test_o_freio_da_varredura_pergunta_por_todas_as_tabelas():
    """`maybe_resolve_pending` so' gasta uma thread quando ha' o que resolver.
    Tabela fora do freio = pick que fica pendente ate' alguem abrir outra
    pendencia por acaso."""
    import re

    fonte = _codigo("routers/live.py")
    corpo = fonte[fonte.index("def _ha_pendente_em_jogo"):]
    corpo = corpo[:corpo.index("def _sweep_now")]
    for tabela in ("picks_vip", "picks_free", "picks_faltas", "picks_goleiros",
                   "picks_multiplas", "picks_alavancagem", "picks_player_stats",
                   "picks_boost", "picks_live"):
        assert re.search(rf"\b{tabela}\b", corpo), f"{tabela} fora do freio"


def test_o_agente_conhece_todos_os_produtos():
    """Ele e' exclusivo de assinante e respondia "que picks sairam hoje?" por
    dois dos nove produtos · a pessoa conclui que os outros nao existem."""
    import futebol_agent.tools.pickia_db as db

    tipos = {p[0] for p in db._PRODUTOS}
    assert _tipos_seguiveis() <= tipos, _tipos_seguiveis() - tipos


def test_o_admin_conta_os_picks_de_hoje_de_todos_os_motores():
    fonte = _codigo("routers/admin.py")
    corpo = fonte[fonte.index("AS vip_picks"):]
    corpo = corpo[:corpo.index("picks_row = dict")]
    for tabela in ("picks_faltas", "picks_goleiros", "picks_player_stats",
                   "picks_boost", "picks_multiplas", "picks_alavancagem"):
        assert tabela in corpo, f"{tabela} fora do painel do dia"
