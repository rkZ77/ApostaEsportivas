"""A IA do projeto e' so' OpenAI (09/11/2026, pedido do usuario)."""
import asyncio
import json
import pathlib
import re
from types import SimpleNamespace as NS

import ia_openai
from futebol_agent import agent

RAIZ = pathlib.Path(__file__).resolve().parents[3]


def test_nenhum_codigo_importa_o_sdk_da_anthropic():
    achados = []
    for pasta in ("website/backend", "ApostaEsportivas/src"):
        for arq in (RAIZ / pasta).rglob("*.py"):
            if "tests" in arq.parts or "__pycache__" in arq.parts:
                continue
            texto = arq.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"^\s*(import anthropic|from anthropic\b)", texto, re.M):
                achados.append(str(arq.relative_to(RAIZ)))
    assert achados == []


def test_requirements_sem_anthropic():
    for req in ("website/backend/requirements.txt", "ApostaEsportivas/requirements.txt"):
        linhas = (RAIZ / req).read_text(encoding="utf-8").splitlines()
        assert not any(l.strip().lower().startswith("anthropic") for l in linhas), req


def test_modelo_padrao_e_o_mais_barato_e_ignora_id_claude(monkeypatch):
    """09/11/2026: sem variavel propria, o mais barato ativo (gpt-6-luna,
    conferido na documentacao da OpenAI). gpt-5-nano/mini saem em 11/12/2026."""
    monkeypatch.delenv("CHAT_AGENT_MODEL", raising=False)
    assert ia_openai.MODELO_BARATO == "gpt-6-luna"
    assert ia_openai.modelo("CHAT_AGENT_MODEL") == "gpt-6-luna"
    monkeypatch.setenv("CHAT_AGENT_MODEL", "claude-haiku-4-5-20251001")
    assert ia_openai.modelo("CHAT_AGENT_MODEL") == "gpt-6-luna"
    monkeypatch.setenv("CHAT_AGENT_MODEL", "gpt-chat")
    assert ia_openai.modelo("CHAT_AGENT_MODEL") == "gpt-chat"


def test_strict_so_quando_o_schema_e_fechado():
    fechado = {"type": "object", "properties": {"a": {"type": "string"}},
               "required": ["a"], "additionalProperties": False}
    aberto = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
              "required": ["a"], "additionalProperties": False}
    assert ia_openai._estrito(fechado)
    assert not ia_openai._estrito(aberto)
    assert not ia_openai._estrito({"type": "object", "properties": {"x": aberto},
                                   "required": ["x"], "additionalProperties": False})


def test_raciocinio_so_pra_familia_que_aceita():
    assert ia_openai.raciocina("gpt-5-mini") and ia_openai.raciocina("o4-mini")
    assert ia_openai.raciocina("gpt-6-luna")
    assert not ia_openai.raciocina("gpt-4o-mini")


def test_historico_antigo_em_blocos_vira_texto():
    h = agent._clean_history([
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": [{"type": "text", "text": "ola"}]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "dados"},
    ])
    assert h == [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "ola"}]


def test_ferramentas_vao_no_formato_da_openai():
    tools = agent._tools_openai()
    assert len(tools) == len(agent.TOOLS)
    assert all(t["type"] == "function" and "parameters" in t["function"] for t in tools)


def test_agente_chama_ferramenta_e_responde(monkeypatch):
    monkeypatch.delenv("CHAT_AGENT_MODEL", raising=False)
    pedidos, executadas = [], []

    def resposta(msg, fim):
        return NS(choices=[NS(message=msg, finish_reason=fim)],
                  usage=NS(prompt_tokens=10, completion_tokens=5))

    roteiro = [
        resposta(NS(content=None, tool_calls=[NS(id="c1", function=NS(
            name="get_ligas_cobertas", arguments=json.dumps({}))) ]), "tool_calls"),
        resposta(NS(content="Cobrimos o Brasileirao.", tool_calls=None), "stop"),
    ]

    class _Comp:
        def create(self, **kw):
            pedidos.append(json.loads(json.dumps(kw, default=str)))
            return roteiro.pop(0)

    async def ferramenta(nome, entrada, contexto):
        executadas.append((nome, entrada, contexto))
        return "Brasileirao Serie A"

    monkeypatch.setattr(ia_openai, "_client", NS(chat=NS(completions=_Comp())))
    monkeypatch.setattr(agent, "_execute_tool", ferramenta)
    texto, historico = asyncio.run(agent.run_agent("quais ligas?", [], {"user_id": 7, "plano": "vip"}))

    assert texto == "Cobrimos o Brasileirao."
    assert executadas == [("get_ligas_cobertas", {}, {"user_id": 7, "plano": "vip"})]
    assert pedidos[0]["model"] == "gpt-6-luna" and pedidos[0]["messages"][0]["role"] == "system"
    # gpt-6-luna so' chama ferramenta no Chat Completions com raciocinio "none".
    assert pedidos[0]["reasoning_effort"] == "none"
    segunda = pedidos[1]["messages"]
    assert segunda[-1] == {"role": "tool", "tool_call_id": "c1", "content": "Brasileirao Serie A"}
    assert historico[-1] == {"role": "assistant", "content": "Cobrimos o Brasileirao."}


def test_modelo_que_a_openai_desliga_vira_o_substituto(monkeypatch):
    """gpt-5/mini/nano e o3 saem em 11/12/2026: valor antigo no Railway nao
    pode derrubar a IA nesse dia."""
    casos = {"gpt-5": "gpt-5.6-terra", "gpt-5-mini": "gpt-5.6-terra",
             "gpt-5-mini-2025-08-07": "gpt-5.6-terra", "GPT-5-nano": "gpt-6-luna",
             "o3": "gpt-5.6-terra", "gpt-5.6-terra": "gpt-5.6-terra",
             "gpt-6-luna": "gpt-6-luna", "o4-mini": "o4-mini"}
    for antes, depois in casos.items():
        monkeypatch.setenv("CHAT_AGENT_MODEL", antes)
        assert ia_openai.modelo("CHAT_AGENT_MODEL") == depois, antes
