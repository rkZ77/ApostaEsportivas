"""A página não baixa o que a aba não usa, e cancelamento não vira alerta.

O SINTOMA ERA UM ALERTA VERMELHO
--------------------------------
"O servidor demorou para responder", com o log do servidor mostrando 200 em
tudo. Ele respondeu mesmo, só que tarde: uma visita à Minha Banca disparava
`/banca/monthly-closes` 4 vezes, `/banca/monthly-close` 4, `/banca` 2,
`/notifications` 3, `/live/my-picks` 3 -- vinte e cinco requisições em poucos
segundos.

O custo aqui não é a consulta: é ABRIR A CONEXÃO. Medido no projeto, a query
roda em 0,4ms e o handshake leva perto de 1s. Concorrência vira fila, a fila
estoura o timeout de 15s do axios, e o interceptor pinta o alerta.

AS DUAS PONTAS
--------------
  1. GET idêntico e concorrente vira UM (services/dedupeGet.ts);
  2. cada aba de /resultados pede só os blocos dela (`blocos` nesta rota).

E a terceira, que é de leitura e não de volume: requisição CANCELADA (o
componente desmontou antes da resposta) chegava no mesmo ramo de "sem
response" e pintava alerta de servidor para quem só trocou de aba.
"""
import inspect
import re

from routers import public


def _front(arquivo: str) -> str:
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")
    with open(os.path.join(base, arquivo), encoding="utf-8") as fh:
        return fh.read()


# ── backend: blocos sob demanda ───────────────────────────────────────────
def test_a_rota_aceita_escolher_os_blocos():
    assert "blocos" in inspect.signature(public.public_results).parameters


def test_sem_blocos_a_resposta_continua_inteira():
    """Contrato antigo intacto: quem não pede nada recebe tudo. A Home usa
    `slim`, e nenhum chamador existente passa `blocos`."""
    fonte = inspect.getsource(public._resultados_publicos)
    assert "_pedidos = None if not blocos" in fonte
    assert "_pedidos is None or bloco in _pedidos" in fonte


def test_os_quatro_blocos_pesados_respeitam_o_pedido():
    fonte = inspect.getsource(public._resultados_publicos)
    for bloco in ("months", "by_day", "by_league", "by_source_day"):
        assert f'_quer("{bloco}")' in fonte, bloco


def test_o_slim_continua_cortando_tudo():
    """A Home depende dele, e ele é mais forte que `blocos`: slim corta mesmo
    que o chamador tenha pedido o bloco."""
    fonte = inspect.getsource(public._resultados_publicos)
    assert "return not slim and" in fonte


# ── frontend: a aba pede o que usa ────────────────────────────────────────
def test_a_pagina_pede_por_aba():
    tela = _front("pages/ResultadosPublicos.tsx")
    assert "blocosDaAba" in tela
    assert "blocos: blocosDaAba(tab)" in tela
    # `tab` tem que estar nas dependências, senão a troca de aba não refaz a
    # consulta e a aba nova abre vazia.
    assert re.search(r"\[source, month, recentPage, tab\]", tela)


def test_o_filtro_de_mes_nunca_fica_sem_dado():
    """`available_months` fica acima das abas e vale pra todas · pedir só na
    aba que o usa faria o filtro abrir vazio e se preencher sozinho."""
    tela = _front("pages/ResultadosPublicos.tsx")
    bloco = tela[tela.index("const blocosDaAba"):tela.index("useEffect(() => {\n    setLoading(true)")]
    assert "const comuns = ['months']" in bloco
    for aba in ("resumo", "por_liga", "por_mes"):
        assert "comuns" in bloco


# ── o alerta vermelho ─────────────────────────────────────────────────────
def test_cancelamento_nao_vira_alerta_de_servidor():
    api = _front("services/api.ts")
    assert "axios.isCancel(err)" in api
    # E o guard vem ANTES do ramo que mostra o toast, senão não adianta.
    assert api.index("axios.isCancel(err)") < api.index("if (!err.response) {")


def test_get_concorrente_e_compartilhado():
    api = _front("services/api.ts")
    assert "compartilhar(chave, () => _get(url, config))" in api


def test_escrita_esvazia_a_janela():
    """Depois de um POST o próximo GET tem que ver o mundo novo, mesmo que
    alguém tenha lido o antigo meio segundo antes."""
    api = _front("services/api.ts")
    assert "limparDedupe()" in api
    for metodo in ("post", "put", "patch", "delete"):
        assert f"'{metodo}'" in api


def test_a_janela_e_curta():
    """Ela cobre o remonte de componente, não "o usuário voltou depois de um
    minuto" · esse quer o número atualizado."""
    dedupe = _front("services/dedupeGet.ts")
    m = re.search(r"JANELA_MS = (\d+)", dedupe)
    assert m and int(m.group(1)) <= 3000


def test_falha_nao_fica_na_janela():
    """Se a primeira quebrou, a próxima tela tem que poder tentar na hora."""
    dedupe = _front("services/dedupeGet.ts")
    assert "promessa.catch(() => emVoo.delete(chave))" in dedupe
