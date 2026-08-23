"""O agente do site passa a consultar o BANCO, e nao so' a API-Football.

Ele nascia sabendo tudo de futebol e nada do Pick IA: as 17 ferramentas
anteriores falam com a API (jogo, odd, tabela, escalacao), entao ele respondia
"como o Palmeiras vem jogando?" e travava em "que picks sairam hoje?" -- que e'
a pergunta que a pessoa foi fazer.

O que existia era um TEXTO pre-cozido no prompt (chat.py::_get_site_context).
Serve pra uma pergunta so', a que alguem previu. Ferramenta serve pra pergunta
que ninguem previu.

O QUE ESTES TESTES PROTEGEM, em ordem de dano:

  1. Vazamento entre contas · o `user_id` tem que vir do TOKEN e nunca do texto
     da conversa, senao "me mostre os picks do usuario 42" funciona.
  2. Vazamento de paywall · mercado e linha so' pra plano ativo.
  3. Escrita · nenhuma ferramenta pode alterar nada. Texto livre chegando em
     SQL de escrita e' superficie de injecao de prompt, nao conveniencia.
"""
import inspect

import pytest

from futebol_agent import agent
from futebol_agent.tools import pickia_db


class TestOAgenteGanhouOlhosNoBanco:
    def test_as_quatro_ferramentas_estao_declaradas(self):
        nomes = {t["name"] for t in agent.TOOLS}
        assert agent.FERRAMENTAS_DO_SITE <= nomes

    def test_nenhum_nome_de_ferramenta_repetido(self):
        """Nome repetido faz o despacho cair no primeiro `if` e a segunda
        ferramenta nunca roda · falha silenciosa."""
        nomes = [t["name"] for t in agent.TOOLS]
        assert len(nomes) == len(set(nomes))

    def test_toda_ferramenta_do_site_tem_despacho(self):
        fonte = inspect.getsource(agent._execute_tool)
        for nome in agent.FERRAMENTAS_DO_SITE:
            assert f'"{nome}"' in fonte, f"{nome} declarada e sem despacho"

    def test_a_descricao_separa_pick_de_jogo(self):
        """O modelo escolhe ferramenta pela descricao. Sem essa distincao ele
        chama a agenda de jogos quando perguntam de pick."""
        pick = next(t for t in agent.TOOLS if t["name"] == "get_picks_publicados")
        assert "nao confunda com jogos" in pick["description"].lower()


class TestNaoVazaEntreContas:
    def test_run_agent_recebe_o_contexto_por_parametro(self):
        assert "contexto" in inspect.signature(agent.run_agent).parameters

    def test_o_despacho_repassa_o_contexto(self):
        """Sem isto as ferramentas pessoais rodariam sem dono."""
        assert "_execute_tool(tc.name, tc.input, contexto)" in inspect.getsource(agent.run_agent)

    def test_meus_picks_nao_aceita_user_id_do_texto(self):
        """O esquema da ferramenta NAO pode ter user_id · se tivesse, o modelo
        poderia preencher com o que a pessoa digitou."""
        tool = next(t for t in agent.TOOLS if t["name"] == "get_meus_picks")
        assert "user_id" not in tool["input_schema"].get("properties", {})

    def test_sem_sessao_recusa_em_vez_de_listar(self):
        assert "sem sessao" in pickia_db.meus_picks(None, False, "vip").lower()

    def test_chat_passa_o_usuario_do_token(self):
        from pathlib import Path
        fonte = (Path(__file__).resolve().parents[1] / "routers" / "chat.py").read_text(encoding="utf-8")
        assert '"user_id": current_user["id"]' in fonte


class TestPaywall:
    LINHAS = [{"casa": "Palmeiras", "fora": "Flamengo", "market": "Escanteios",
               "line": 8.5, "odd": 1.85, "result": None, "tipo": "vip",
               "match_date": "2026-08-22"}]

    @pytest.fixture(autouse=True)
    def _sem_banco(self, monkeypatch):
        monkeypatch.setattr(pickia_db, "_consulta", lambda *a, **k: self.LINHAS)

    @pytest.mark.parametrize("plano", ["vip", "admin", "trial"])
    def test_plano_ativo_ve_o_mercado(self, plano):
        assert "Escanteios" in pickia_db.picks_publicados("2026-08-22", plano)

    @pytest.mark.parametrize("plano", ["free", None, "", "expirado"])
    def test_quem_nao_paga_nao_ve_o_mercado(self, plano):
        """Hoje o agente ja' e' exclusivo de assinante, entao isto e'
        redundante · e fica de proposito: se o agente abrir pro free, o
        vazamento nao pode depender de alguem lembrar deste arquivo.
        """
        saida = pickia_db.picks_publicados("2026-08-22", plano)
        assert "Escanteios" not in saida
        assert "exclusivo de assinante" in saida

    def test_o_jogo_aparece_mesmo_sem_plano(self):
        """Esconder o mercado nao e' esconder que existe pick · e' o mesmo
        corte da pagina publica."""
        saida = pickia_db.picks_publicados("2026-08-22", "free")
        assert "Palmeiras" in saida and "Flamengo" in saida


class TestSomenteLeitura:
    ESCRITA = ("insert ", "update ", "delete ", "drop ", "truncate ", "alter ")

    def test_nenhuma_ferramenta_escreve(self):
        fonte = inspect.getsource(pickia_db).lower()
        # Recorta os comentarios: eles CITAM escrita pra explicar por que ela
        # nao existe, e a citacao nao pode reprovar o teste.
        codigo = "\n".join(l for l in fonte.split("\n")
                           if not l.strip().startswith("#"))
        for verbo in self.ESCRITA:
            assert verbo not in codigo, f"apareceu {verbo!r} no modulo"

    def test_consulta_devolve_a_conexao_sempre(self):
        """Vazar slot do pool tira capacidade do site inteiro · sao 10."""
        fonte = inspect.getsource(pickia_db._consulta)
        assert "finally" in fonte and "conn.close()" in fonte


class TestFalhaSemDerrubarOChat:
    def test_erro_de_banco_vira_frase_e_nao_excecao(self, monkeypatch):
        """O agente responde texto · uma excecao aqui derrubaria a conversa
        inteira por causa de uma pergunta."""
        def explode(*a, **k):
            raise RuntimeError("banco fora")
        monkeypatch.setattr(pickia_db, "_consulta", explode)
        for saida in (pickia_db.picks_publicados(None, "vip"),
                      pickia_db.meus_picks(1, False, "vip"),
                      pickia_db.ligas_cobertas()):
            assert isinstance(saida, str) and saida

    def test_dia_sem_pick_responde_em_vez_de_ficar_mudo(self, monkeypatch):
        monkeypatch.setattr(pickia_db, "_consulta", lambda *a, **k: [])
        assert "nenhum pick" in pickia_db.picks_publicados("2026-08-22", "vip").lower()


class TestDesempenho:
    @pytest.fixture(autouse=True)
    def _sem_banco(self, monkeypatch):
        monkeypatch.setattr(pickia_db, "_consulta", lambda *a, **k: [
            {"total": 10, "greens": 7, "reds": 3, "lucro": 4.2}])

    def test_calcula_acerto_e_lucro(self):
        saida = pickia_db.desempenho_da_ia("2026-08", "vip")
        assert "70.0%" in saida and "+4.20u" in saida

    def test_so_conta_pick_resolvido(self):
        """Pendente no denominador afundaria o acerto sozinho, e a pergunta
        'quanto a IA acerta' e' sobre o que ja' fechou."""
        assert "result IS NOT NULL" in inspect.getsource(pickia_db.desempenho_da_ia)
