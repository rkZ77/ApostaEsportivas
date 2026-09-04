"""Correcoes de latencia de 2026-08-14.

A REGUA (medida contra producao em 13/08, anotada em database.py:71-82):

    abrir conexao:   998ms
    cada consulta:   154ms

Com esse numero, "quantas idas ao banco esta rota faz" e' a metrica que importa,
e foi por ela que a auditoria ordenou tudo. A tela de Picks disparava 10
requisicoes quase simultaneas contra um pool de 10 conexoes, e uma delas
(/suggestions/today) sozinha fazia cerca de 18 consultas.

Estes testes prendem as correcoes pelo que elas garantem, nao pela forma como
foram escritas -- as que assertam sobre o codigo-fonte dizem no nome que fazem
isso, e existem porque o alvo e' justamente "nao voltar a consultar duas vezes",
que nenhum teste de resposta pegaria.

Nada aqui abre conexao: o conftest ja bloqueia get_connection.
"""
import gzip
import time

import pytest

import auth_utils
from tests.test_home_2026_08 import _codigo, _fonte, _front


# ─────────────────── Cache da checagem de sessao ────────────────────
#
# get_current_user rodava um SELECT em `users` antes de TODO handler protegido.
# Eram 154ms somados a cada endpoint, dez vezes por carga da tela de Picks, e
# dez slots do pool gastos antes de qualquer trabalho util.


@pytest.fixture(autouse=True)
def _cache_limpo():
    """Cache e' estado de modulo: sem isto um teste contamina o proximo."""
    auth_utils._sessao_cache.clear()
    yield
    auth_utils._sessao_cache.clear()


class _CursorFake:
    def __init__(self, linha, contador):
        self._linha, self._contador = linha, contador

    def execute(self, *_a, **_k):
        self._contador[0] += 1

    def fetchone(self):
        return self._linha

    def close(self):
        pass


class _ConnFake:
    def __init__(self, linha, contador):
        self._linha, self._contador = linha, contador

    def cursor(self):
        return _CursorFake(self._linha, self._contador)

    def close(self):
        pass


def _fingir_banco(monkeypatch, linha):
    contador = [0]
    monkeypatch.setattr(auth_utils, "get_connection",
                        lambda: _ConnFake(linha, contador))
    return contador


_LINHA_FREE = {
    "id": 7, "active": True, "session_token": None, "last_login_device": None,
    "last_login_at": None, "plan": "free", "expires_at": None,
}


def test_segunda_chamada_nao_vai_ao_banco(monkeypatch):
    """O ganho todo esta aqui: 10 requisicoes por tela, 1 consulta."""
    contador = _fingir_banco(monkeypatch, _LINHA_FREE)

    for _ in range(10):
        assert auth_utils._linha_de_sessao(7)["plan"] == "free"

    assert contador[0] == 1


def test_cache_expira(monkeypatch):
    """A janela e' o atraso maximo pra pagamento aprovado virar VIP na tela,
    sessao derrubada em outro aparelho, e conta desativada pelo admin."""
    contador = _fingir_banco(monkeypatch, _LINHA_FREE)

    auth_utils._linha_de_sessao(7)
    envelhecido = time.time() - auth_utils._SESSAO_TTL - 1
    auth_utils._sessao_cache[7] = (envelhecido, _LINHA_FREE)
    auth_utils._linha_de_sessao(7)

    assert contador[0] == 2


def test_ttl_curto_o_bastante_pra_quem_acabou_de_pagar():
    assert auth_utils._SESSAO_TTL <= 60


def test_admin_nunca_entra_no_cache(monkeypatch):
    """Admin e' quem muda plano dos outros e precisa ver o efeito na hora."""
    linha = dict(_LINHA_FREE, plan="admin")
    contador = _fingir_banco(monkeypatch, linha)

    auth_utils._linha_de_sessao(7)
    auth_utils._linha_de_sessao(7)

    assert contador[0] == 2
    assert 7 not in auth_utils._sessao_cache


def test_invalidar_derruba_a_linha(monkeypatch):
    contador = _fingir_banco(monkeypatch, _LINHA_FREE)

    auth_utils._linha_de_sessao(7)
    auth_utils.invalidar_cache_usuario(7)
    auth_utils._linha_de_sessao(7)

    assert contador[0] == 2


def test_invalidar_aceita_lixo_sem_levantar():
    """E' chamada em caminho de escrita (login, pagamento, admin). Se levantar,
    derruba a operacao que de fato importava."""
    for valor in (None, "", "abc", object()):
        auth_utils.invalidar_cache_usuario(valor)


def test_usuario_inexistente_nao_e_cacheado(monkeypatch):
    """Cachear o None deixaria uma conta recem-criada invisivel pelo TTL."""
    contador = _fingir_banco(monkeypatch, None)

    assert auth_utils._linha_de_sessao(7) is None
    assert auth_utils._linha_de_sessao(7) is None
    assert contador[0] == 2


def test_quem_muda_sessao_ou_plano_invalida_o_cache():
    """FONTE. Esquecer uma dessas chamadas nao vira bug permanente (o TTL cobre),
    mas vira atraso visivel justo nos tres momentos que o usuario percebe."""
    for arquivo, quantas in (("routers/auth.py", 5),
                             ("routers/admin.py", 2),
                             ("routers/payments.py", 2)):
        fonte = _fonte(arquivo)
        assert fonte.count("invalidar_cache_usuario(") >= quantas, arquivo


# ─────────────────── /suggestions/today ────────────────────


def test_pernas_de_multipla_saem_numa_consulta_so():
    """FONTE. Era uma consulta POR PERNA, dentro de dois lacos aninhados: tres
    multiplas de tres pernas viravam nove idas ao banco pra buscar nome de time."""
    corpo = _codigo("routers/suggestions.py", "_enrich_multipla_legs")
    assert "fixture_id = ANY(%s)" in corpo
    assert "WHERE fixture_id = %s" not in corpo


def test_is_followed_de_todos_os_tipos_numa_consulta_so():
    """FONTE. Eram seis: vip, faltas, goleiros, multipla, dica do dia e
    alavancagem, cada uma uma ida ao banco."""
    corpo = _codigo("routers/suggestions.py", "get_today_suggestions")
    assert corpo.count("FROM user_followed_picks") == 1


def test_marcacao_de_seguido_e_chaveada_pelo_par_tipo_e_id():
    """O filtro e' `pick_type = ANY(...) AND pick_id = ANY(...)`, que casa tipo
    de um pick com id de outro. So' nao vira bug porque o dicionario e' chaveado
    pelo PAR -- trocar isso por chave so' de id devolveria pick seguido errado."""
    corpo = _codigo("routers/suggestions.py", "get_today_suggestions")
    assert '(r["pick_type"], r["pick_id"])' in corpo
    assert 'seguidos.get((tipo, p.get("id")))' in corpo


# ─────────────────── /public/results ────────────────────


def test_home_pede_a_versao_enxuta():
    """A resposta tinha sete blocos e a Home le tres. `by_day` era o pior: uma
    linha por dia desde o lancamento, baixada inteira pra nao ser usada."""
    assert "slim: 1" in _front("pages/Home.tsx")


def test_slim_pula_os_blocos_que_a_home_nao_usa():
    # O SQL saiu de public_results e foi pra _resultados_publicos em 04/09: o
    # endpoint agora so agenda as varreduras e delega a parte cacheada.
    corpo = _codigo("routers/public.py", "_resultados_publicos")
    for bloco in ("months_rows", "by_day", "by_league", "counts_row"):
        assert f"{bloco} = [] if slim" in corpo or f"{bloco} = None if slim" in corpo \
            or f"{bloco} = [] if slim else" in corpo, bloco


def test_contagem_de_ligas_sai_do_proprio_resumo():
    """A Home lia `by_league.length`, e so' por esse numero a rota tinha que
    montar a quebra por liga inteira: mais uma varredura do historico e mais uma
    consulta pros nomes das ligas."""
    corpo = _codigo("routers/public.py", "_resultados_publicos")
    assert "AS leagues_count" in corpo
    assert "summary?.leagues_count" in _front("pages/Home.tsx")


def test_nome_da_liga_vem_por_join_e_nao_por_segunda_consulta():
    corpo = _codigo("routers/public.py", "_resultados_publicos")
    assert "LEFT JOIN leagues l ON l.league_id = t.league_id" in corpo
    assert "SELECT league_id, name FROM leagues" not in corpo


# ─────────────────── Chamadas externas e event loop ────────────────────


def test_fixtures_do_dia_nao_seguram_conexao_durante_a_api_football():
    """FONTE. Eram `nº de ligas x 2` chamadas HTTP sequenciais de ate' 10s cada,
    com um dos 10 slots do pool preso o tempo todo."""
    corpo = _codigo("routers/fixtures.py", "get_today_fixtures")
    assert "ThreadPoolExecutor" in corpo
    # a conexao das ligas fecha ANTES do bloco de chamadas externas
    assert corpo.index("cur.close(); conn.close()") < corpo.index("ThreadPoolExecutor")


def test_reducao_de_escudo_nao_roda_no_event_loop():
    """FONTE. `_reduzir_logo` e' LANCZOS + quantize do Pillow, CPU pura, e rodava
    dentro de um handler async. Com um worker so', isso e' o site inteiro parado
    enquanto os ~20 escudos de uma tela de Picks sao processados."""
    corpo = _codigo("main.py", "_serve_logo")
    assert "run_in_threadpool(_reduzir_logo" in corpo
    assert "run_in_threadpool(_ler_cache_logo" in corpo


def test_cache_de_escudo_pode_sair_do_tmp():
    """/tmp some a cada deploy no Railway, entao o primeiro visitante depois de
    cada deploy pagava 20 downloads mais 20 reducoes."""
    assert 'os.getenv("LOGO_CACHE_DIR"' in _fonte("main.py")


def test_live_stats_tem_versao_em_lote():
    """A tela de Jogos abria UMA requisicao por partida ao vivo a cada 30s."""
    fonte = _fonte("routers/live.py")
    assert "def get_live_stats_bulk" in fonte
    assert "_fetch_fixtures_bulk(fids)" in fonte
    assert "/live/live-stats" in _front("pages/Fixtures.tsx")


# ─────────────────── Front: polls e caminho critico ────────────────────


def test_polls_param_com_a_aba_escondida():
    """Aba aberta em segundo plano gastava tres requisicoes por minuto no sino,
    mais dez por minuto no status do pipeline, a noite inteira."""
    for arquivo in ("context/NotificationContext.tsx", "pages/Picks.tsx",
                    "pages/Fixtures.tsx"):
        assert "document.hidden" in _front(arquivo), arquivo


def test_status_do_pipeline_desacelera_quando_nao_esta_rodando():
    src = _front("pages/Picks.tsx")
    assert "60_000" in src and "10_000" in src
    assert "setInterval(poll, 6000)" not in src


def test_jsx_runtime_fica_com_o_react_e_nao_com_o_framer():
    """A causa real de o framer-motion estar no caminho critico de TODA pagina.
    `react/jsx-runtime` caia dentro de vendor-motion porque o framer era quem o
    importava primeiro, entao qualquer chunk que renderiza JSX arrastava os
    43,8 KB comprimidos do framer -- Termos, Privacidade, Badge, Skeleton."""
    src = _front("../vite.config.ts")
    assert "manualChunks(id)" in src, "a forma de objeto nao resolve react/jsx-runtime"
    assert "scheduler" in src


def test_sobreposicoes_saem_do_chunk_de_entrada():
    """Banner de cookie, toast de erro e popup mensal nao participam da primeira
    pintura, e todos usam framer-motion."""
    src = _front("App.tsx")
    # o nome aparece em comentario explicando a mudanca; o que nao pode voltar
    # e' o IMPORT, que e' o que prende o chunk de entrada ao vendor-motion.
    assert "from 'framer-motion'" not in src
    for comp in ("CookieBanner", "ErrorToast", "GlobalModals", "PushPromptBanner"):
        assert f"lazy(() => import('./components/{comp}'))" in src, comp


# ─────────────────── Brotli pre-comprimido ────────────────────


def _cliente_spa(tmp_path, monkeypatch):
    """App com um dist de mentira, so' pra exercitar o catch-all do SPA."""
    import importlib
    from fastapi.testclient import TestClient

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>real</html>", encoding="utf-8")
    js = dist / "assets" / "app-abc123.js"
    corpo = "console.log('x')" * 200
    js.write_text(corpo, encoding="utf-8")
    # O .gz precisa ser gzip DE VERDADE: o cliente de teste descomprime sozinho
    # ao ler a resposta, e bytes falsos falhariam no cliente, nao no servidor.
    js.with_name(js.name + ".gz").write_bytes(gzip.compress(corpo.encode()))
    # O .br fica com conteudo qualquer de proposito: aqui so' interessa QUAL
    # arquivo o servidor escolheu e com que cabecalhos, e o httpx deste
    # ambiente nao decodifica brotli.
    js.with_name(js.name + ".br").write_bytes(b"CORPO-BROTLI")

    import main
    monkeypatch.setattr(main, "_dist", dist)
    monkeypatch.setattr(main, "_resposta_de_arquivo", main._resposta_de_arquivo)
    return TestClient(main.app), js


def test_brotli_servido_quando_o_navegador_aceita(tmp_path, monkeypatch):
    cliente, _ = _cliente_spa(tmp_path, monkeypatch)
    r = cliente.get("/assets/app-abc123.js",
                    headers={"Accept-Encoding": "br, gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "br"
    # o tipo vem do nome ORIGINAL; do .br o FileResponse chutaria octet-stream
    # e o navegador nao executaria o script
    assert "javascript" in r.headers["content-type"]
    assert "Accept-Encoding" in r.headers.get("vary", "")


def test_gzip_quando_nao_ha_brotli(tmp_path, monkeypatch):
    cliente, _ = _cliente_spa(tmp_path, monkeypatch)
    r = cliente.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"


def test_sem_accept_encoding_serve_o_arquivo_cru(tmp_path, monkeypatch):
    """Cliente velho nao pode receber bytes comprimidos sem pedir."""
    cliente, _ = _cliente_spa(tmp_path, monkeypatch)
    r = cliente.get("/assets/app-abc123.js", headers={"Accept-Encoding": "identity"})
    assert r.headers.get("content-encoding") in (None, "")
    assert "console.log" in r.text


def test_br_nao_casa_por_substring(tmp_path, monkeypatch):
    """`"br" in cabecalho` casaria dentro de outra palavra e mandaria brotli pra
    quem nao pediu · isso vira pagina em branco, nao erro visivel."""
    cliente, _ = _cliente_spa(tmp_path, monkeypatch)
    r = cliente.get("/assets/app-abc123.js", headers={"Accept-Encoding": "brotli-falso"})
    assert r.headers.get("content-encoding") in (None, "")


def test_pedido_direto_ao_br_nao_vaza_bytes_comprimidos(tmp_path, monkeypatch):
    """O .br existe so' como variante. Servido direto, iria sem o cabecalho que
    diz que esta comprimido."""
    cliente, _ = _cliente_spa(tmp_path, monkeypatch)
    r = cliente.get("/assets/app-abc123.js.br", headers={"Accept-Encoding": "br"})
    assert b"CORPO-BROTLI" not in r.content


def test_script_de_precompressao_nao_traz_dependencia():
    """zlib do proprio Node · nada novo no package.json."""
    script = _front("../scripts/precomprimir.mjs")
    assert "node:zlib" in script
    for pacote in ("brotli", "compression-webpack", "vite-plugin-compression"):
        assert pacote not in _front("../package.json")


# ─────────────────── Revelacao coletiva do topo ────────────────────


def test_topo_da_home_revela_de_uma_vez():
    """Cada bloco revelava o seu assim que a SUA resposta chegava, e dois deles
    somem quando nao tem dado: a altura da pagina mudava embaixo do dedo."""
    src = _front("pages/Home.tsx")
    assert "topoPronto" in src
    assert "revelar={topoPronto}" in src
    assert src.count("onCarregou={marcarPronto}") == 2
    assert "loaded={topoPronto}" in src


def test_pedidos_do_topo_continuam_saindo_juntos():
    """A revelacao e' que e' coletiva; os requests nao viraram fila. Se algum
    bloco passasse a so' pedir depois do vizinho, o ganho de latencia iria
    embora junto."""
    for arquivo in ("home/FreePickHero.tsx", "home/NextGames.tsx"):
        src = _front(arquivo)
        # o useEffect que busca nao depende de `revelar`
        assert "revelar" not in src.split("useEffect(")[1].split("}, [")[0]


def test_topo_de_picks_espera_stats_e_picks():
    src = _front("pages/Picks.tsx")
    assert "const topoPronto = !todayLoading && quickStatsPronto" in src
    assert "{!topoPronto ? <PickLoading />" in src


def test_erro_nao_segura_a_tela_para_sempre():
    """`.finally` e nao `.then`: chamada que falhou tem que contar como pronta."""
    assert ".finally(() => setQuickStatsPronto(true))" in _front("pages/Picks.tsx")


# ─────────────────── Abas pesadas fora do chunk de Picks ────────────────────


def test_abas_pesadas_sao_lazy():
    """Juntas sao 68 KB de fonte, e o usuario cai sempre na aba Hoje. O feed e'
    pior: so' renderiza com LIVE_PICKS_ENABLED, DESLIGADA em producao."""
    src = _front("pages/Picks.tsx")
    for comp in ("LivePicks", "LivePicksFeed"):
        assert f"lazy(() => import('../components/{comp}'))" in src


def test_aba_pesada_continua_montada_depois_da_primeira_visita():
    """As duas tem polling proprio e estado que nao pode sumir a cada troca de
    aba · por isso `hidden` em vez de desmontar."""
    src = _front("pages/Picks.tsx")
    assert "jaAbriuMinhasApostas.current" in src
    assert "jaAbriuAoVivo.current" in src
    assert "tab !== 'minhas_apostas' ? 'hidden' : ''" in src


def test_codigo_morto_saiu_de_picks():
    src = _front("pages/Picks.tsx")
    for morto in ("function QuickStats(", "function PicksTable(", "function normalizePickRow("):
        assert morto not in src, morto
