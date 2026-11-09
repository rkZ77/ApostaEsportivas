"""Cliente unico de IA do site: OpenAI (09/11/2026, pedido do usuario).

O projeto usava a Anthropic na leitura do Raio-X (resumo_ia), na leitura da
liga (liga_ia) e no agente do chat. Tudo passou pra OpenAI, e este modulo e' a
unica porta: cliente, escolha de modelo e chamada com JSON validado.

QUAL MODELO (09/11/2026, pedido do usuario: "coloca o modelo mais barato").
A variavel especifica do recurso, se existir; senao MODELO_BARATO. O ID foi
conferido na documentacao oficial da OpenAI nesse dia: `gpt-6-luna` e' o mais
barato ativo (US$ 0,10 entrada / 0,50 saida por milhao) e o indicado pra volume
alto. `gpt-5-nano` e `gpt-5-mini` estao descontinuados (saem em 11/12/2026).
Valor `claude-*` que tenha sobrado numa variavel antiga e' ignorado: mandado
pra OpenAI ele so' gera erro.
"""
from __future__ import annotations

import json
import os

_client = None


def chave() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def disponivel() -> bool:
    return bool(chave())


def _valido(valor: str | None) -> str | None:
    v = (valor or "").strip()
    if not v or v.lower().startswith("claude"):
        return None
    return v


MODELO_BARATO = "gpt-6-luna"


def modelo(variavel: str | None = None) -> str:
    """O ID do modelo OpenAI pra este recurso: a variavel dele no Railway, ou
    MODELO_BARATO."""
    proprio = _valido(os.getenv(variavel)) if variavel else None
    return proprio or MODELO_BARATO


def raciocina(model: str) -> bool:
    """Familias de raciocinio aceitam `reasoning_effort`; as outras devolvem
    400 com o campo. Na duvida, nao manda (perde o controle, nao a chamada)."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def cliente():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=chave() or None)
    return _client


def _estrito(schema) -> bool:
    """O modo strict da OpenAI exige todo objeto fechado e com todas as
    chaves obrigatorias. Schema que nao cumpre vai sem strict (o JSON continua
    pedido; quem chama ja' corta e valida o que volta)."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            props = schema.get("properties") or {}
            if schema.get("additionalProperties") is not False:
                return False
            if set(schema.get("required") or []) != set(props):
                return False
        return all(_estrito(v) for v in schema.values())
    if isinstance(schema, list):
        return all(_estrito(v) for v in schema)
    return True


def json_estruturado(system: str, conteudo: str, schema: dict, nome: str,
                     model: str, max_tokens: int = 16000,
                     esforco: str = "low") -> tuple[dict, int, int]:
    """(json, tokens de entrada, tokens de saida). Levanta em falha ou
    resposta cortada -- nunca devolve JSON pela metade."""
    if not model:
        raise RuntimeError("modelo OpenAI nao configurado")
    extra = {"reasoning_effort": esforco} if raciocina(model) else {}
    resposta = cliente().chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        response_format={"type": "json_schema", "json_schema": {
            "name": nome, "strict": _estrito(schema), "schema": schema}},
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": conteudo}],
        **extra,
    )
    escolha = resposta.choices[0]
    if escolha.finish_reason != "stop":
        raise RuntimeError(f"resposta incompleta: {escolha.finish_reason}")
    if getattr(escolha.message, "refusal", None):
        raise RuntimeError("provedor recusou o pedido (recusou)")
    u = resposta.usage
    return (json.loads(escolha.message.content or "{}"),
            int(getattr(u, "prompt_tokens", 0) or 0),
            int(getattr(u, "completion_tokens", 0) or 0))
