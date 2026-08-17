"""Superfície para agentes de IA: llms.txt, markdown, .well-known e MCP.

O que estes testes protegem, em ordem de importância:

  1. NADA de assinante vaza em markdown ou por MCP. É a regra que um "é só
     texto" futuro pode quebrar sem querer.
  2. Preço não é escrito à mão em lugar nenhum · já houve preço errado no
     index.html por exatamente isso.
  3. Navegador continua recebendo HTML. A negociação por Accept é o ponto
     onde um erro derrubaria o site inteiro para gente de verdade, não só
     para agente.
"""
import json

import pytest
from fastapi.testclient import TestClient

import agent_web


# ─────────────────── negociação de Accept ────────────────────


@pytest.mark.parametrize(
    "accept, esperado",
    [
        ("text/markdown", True),
        ("text/markdown;q=0.9, text/html;q=0.8", True),
        ("text/x-markdown", True),
        # Navegador. Se algum dia isto virar True, o site some para humanos.
        ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", False),
        ("text/html;q=0.9, text/markdown;q=0.5", False),
        # curl padrão pede qualquer coisa, e qualquer coisa não é markdown.
        ("*/*", False),
        ("", False),
        ("application/json", False),
    ],
)
def test_prefere_markdown(accept, esperado):
    assert agent_web.prefere_markdown(accept) is esperado


def test_caminho_desconhecido_nao_tem_markdown():
    assert agent_web.caminho_com_markdown("/picks") is None
    assert agent_web.caminho_com_markdown("/admin") is None
    assert agent_web.caminho_com_markdown("/planos") == "/planos"
    # Barra final não pode criar uma segunda URL com o mesmo conteúdo.
    assert agent_web.caminho_com_markdown("/planos/") == "/planos"


# ─────────────────── llms.txt ────────────────────


def test_llms_txt_segue_o_formato():
    txt = agent_web.llms_txt()
    linhas = [l for l in txt.splitlines() if l.strip()]
    assert linhas[0].startswith("# "), "primeira linha tem que ser o H1"
    assert linhas[1].startswith("> "), "logo depois do H1 vem o blockquote"
    assert "## Páginas" in txt
    assert "/planos.md" in txt
    assert "/llms-full.txt" in txt


def test_llms_txt_avisa_do_risco():
    """Site de aposta sem aviso de risco em texto que agente lê é problema.

    O agente costuma repetir o que leu; sem isto ele resume o produto como
    retorno garantido.
    """
    txt = agent_web.llms_txt().lower()
    assert "risco" in txt
    assert "18 anos" in txt
    assert "não prevê resultado futuro" in txt


def test_llms_txt_lista_os_posts_do_manifesto(tmp_path, monkeypatch):
    manifesto = tmp_path / "blog-index.json"
    manifesto.write_text(
        json.dumps(
            {
                "posts": [
                    {
                        "slug": "kelly-criterion-apostas-esportivas",
                        "title": "O que é Kelly Criterion",
                        "description": "Stake ideal por aposta.",
                        "publishedAt": "2026-07-23",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_web, "_BLOG_INDEX", manifesto)

    txt = agent_web.llms_txt()
    assert "## Blog" in txt
    assert "/blog/kelly-criterion-apostas-esportivas" in txt


def test_sem_manifesto_o_llms_txt_ainda_sai(tmp_path, monkeypatch):
    """Dev sem build não pode derrubar a rota."""
    monkeypatch.setattr(agent_web, "_BLOG_INDEX", tmp_path / "nao-existe.json")
    txt = agent_web.llms_txt()
    assert txt.startswith("# Pick IA")
    assert "## Blog" not in txt


# ─────────────────── preço vem de uma fonte só ────────────────────


def test_planos_em_markdown_leem_a_tabela_de_cobranca(monkeypatch):
    import routers.payments as pagamentos

    monkeypatch.setitem(
        pagamentos.PLANS, "mensal", {"price": 44.90, "title": "Plano Picks Mensal", "days": 30}
    )
    md = agent_web.md_planos()
    assert "R$ 44,90" in md, "o preço tem que sair de PLANS, não de texto fixo"
    assert "39,90" not in md


def test_home_nao_promete_retorno():
    md = agent_web.md_home().lower()
    for proibido in ("lucro garantido", "retorno garantido", "sem risco"):
        assert proibido not in md


# ─────────────────── .well-known ────────────────────


def test_api_catalog_no_formato_da_rfc_9727():
    cliente = TestClient(_app())
    r = cliente.get("/.well-known/api-catalog")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/linkset+json")

    corpo = r.json()
    assert "linkset" in corpo
    entrada = corpo["linkset"][0]
    assert entrada["anchor"].endswith("/api/public")
    assert entrada["service-desc"][0]["href"].endswith("/openapi.json")


def test_auth_md_diz_que_nao_ha_registro_de_agente():
    """Guarda contra 'melhorar' o texto até ele prometer o que não existe.

    Não há servidor OAuth nem emissão de credencial para terceiro. Um auth.md
    otimista faria o agente tentar um fluxo inexistente e falhar depois de
    prometer ao usuário que ia dar certo.
    """
    md = agent_web.auth_md()
    assert "NÃO suporta" in md
    assert "client_credentials" in md
    for inventado in ("/oauth/token", "/register", "client_secret"):
        assert inventado not in md


def test_cartao_mcp_aponta_pro_endpoint_real():
    cartao = agent_web.mcp_card()
    assert cartao["transports"]["streamable-http"]["url"].endswith("/mcp")
    assert cartao["authentication"]["type"] == "none"


# ─────────────────── MCP ────────────────────


def _app():
    import main

    return main.app


def _rpc(cliente, metodo, params=None, id_=1):
    return cliente.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}},
    )


def test_mcp_initialize():
    cliente = TestClient(_app())
    r = _rpc(cliente, "initialize", {"protocolVersion": agent_web.PROTOCOLO_MCP})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["jsonrpc"] == "2.0"
    assert corpo["result"]["protocolVersion"] == agent_web.PROTOCOLO_MCP
    assert corpo["result"]["serverInfo"]["name"] == "pickia"


def test_mcp_lista_ferramentas_com_schema():
    cliente = TestClient(_app())
    ferramentas = _rpc(cliente, "tools/list").json()["result"]["tools"]
    nomes = {f["name"] for f in ferramentas}
    assert nomes == {
        "resultados_publicos",
        "picks_de_hoje",
        "dica_gratuita_de_hoje",
        "planos_e_precos",
    }
    for f in ferramentas:
        assert f["inputSchema"]["type"] == "object", f["name"]
        assert f["description"].strip(), f["name"]


def test_mcp_nao_tem_ferramenta_de_pick_vip():
    """A superfície MCP é pública. Pick de assinante não entra nela."""
    cliente = TestClient(_app())
    ferramentas = _rpc(cliente, "tools/list").json()["result"]["tools"]
    texto = json.dumps(ferramentas, ensure_ascii=False).lower()
    assert "picks_vip" not in texto
    for f in ferramentas:
        assert "vip" not in f["name"]


def test_mcp_chama_ferramenta_sem_banco():
    cliente = TestClient(_app())
    r = _rpc(cliente, "tools/call", {"name": "planos_e_precos", "arguments": {}})
    conteudo = r.json()["result"]["content"][0]["text"]
    assert "mensal" in conteudo


def test_mcp_ferramenta_desconhecida_volta_como_iserror():
    cliente = TestClient(_app())
    resultado = _rpc(cliente, "tools/call", {"name": "apagar_tudo"}).json()["result"]
    assert resultado["isError"] is True


def test_mcp_metodo_desconhecido_volta_erro_de_rpc():
    cliente = TestClient(_app())
    corpo = _rpc(cliente, "resources/list").json()
    assert corpo["error"]["code"] == -32601


def test_mcp_falha_de_banco_nao_derruba_a_sessao(monkeypatch):
    """Banco fora do ar vira isError, não exceção 500.

    Cliente MCP que recebe erro de transporte costuma encerrar a sessão
    inteira em vez de mostrar a mensagem.
    """
    import routers.public as publico

    def _explode(*_a, **_kw):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(publico, "public_today_summary", _explode)

    cliente = TestClient(_app())
    r = _rpc(cliente, "tools/call", {"name": "picks_de_hoje", "arguments": {}})
    assert r.status_code == 200
    assert r.json()["result"]["isError"] is True


# ─────────────────── negociação na URL real ────────────────────


def _cliente_com_spa(tmp_path, monkeypatch):
    """App com um dist de mentira, pra exercitar HTML e markdown na mesma URL."""
    import main

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setattr(main, "_dist", dist)
    return TestClient(main.app)


def test_navegador_continua_recebendo_html(tmp_path, monkeypatch):
    cliente = _cliente_com_spa(tmp_path, monkeypatch)
    r = cliente.get("/planos", headers={"Accept": "text/html,*/*;q=0.8"})
    assert r.status_code == 200
    assert "<html>spa</html>" in r.text


def test_agente_recebe_markdown_na_mesma_url(tmp_path, monkeypatch):
    cliente = _cliente_com_spa(tmp_path, monkeypatch)
    r = cliente.get("/planos", headers={"Accept": "text/markdown"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text.startswith("# Planos")


def test_html_anuncia_a_versao_markdown(tmp_path, monkeypatch):
    """Sem Link e Vary, ninguém descobre o markdown e o cache serve o formato
    errado pro público errado."""
    cliente = _cliente_com_spa(tmp_path, monkeypatch)
    r = cliente.get("/como-funciona", headers={"Accept": "text/html"})
    assert 'rel="alternate"' in r.headers["link"]
    assert "/como-funciona.md" in r.headers["link"]
    assert "accept" in r.headers["vary"].lower()


def test_vary_preserva_accept_encoding(tmp_path, monkeypatch):
    """Accept-Encoding não pode ser sobrescrito: perder ele serve corpo
    comprimido pra quem não aceita compressão."""
    cliente = _cliente_com_spa(tmp_path, monkeypatch)
    r = cliente.get("/planos.md", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200


def test_rota_markdown_direta(tmp_path, monkeypatch):
    cliente = _cliente_com_spa(tmp_path, monkeypatch)
    for caminho, inicio in (
        ("/index.md", "# Pick IA"),
        ("/como-funciona.md", "# Como funciona"),
        ("/termos.md", "# Termos"),
        ("/privacidade.md", "# Política"),
    ):
        r = cliente.get(caminho)
        assert r.status_code == 200, caminho
        assert r.text.startswith(inicio), caminho


def test_llms_txt_e_servido_como_texto(tmp_path, monkeypatch):
    cliente = _cliente_com_spa(tmp_path, monkeypatch)
    r = cliente.get("/llms.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("# Pick IA")


# ─────────────────── pick público em markdown ────────────────────


def test_pick_em_markdown_nao_expoe_mercado(monkeypatch):
    """O teaser em markdown usa a MESMA função da API pública.

    Se alguém afrouxar o teaser, este teste não salva · mas ele garante que
    não existe uma SEGUNDA regra de exposição escrita só pro markdown, que
    foi como a divergência apareceu da última vez.
    """
    import routers.public as publico

    monkeypatch.setattr(
        publico,
        "public_pick",
        lambda tipo, pid: {
            "id": pid,
            "home_team_name": "Flamengo",
            "away_team_name": "Palmeiras",
            "league_name": "Brasileirão",
            "match_date": "2026-08-16",
            "odd": 1.85,
            "result": "GREEN",
            "pick_type": tipo,
        },
    )

    cliente = TestClient(_app())
    r = cliente.get("/p/free/123.md")
    assert r.status_code == 200
    assert "Flamengo" in r.text
    for proibido in ("market", "reasoning", "Mercado:"):
        assert proibido not in r.text
