"""Cliente unico de IA do motor: OpenAI (09/11/2026, pedido do usuario).

Copia do website/backend/ia_openai.py pro motor (os dois rodam em processos
separados): perfil de liga e descoberta de regulamento. Mesma cascata de
modelo, mesmo cliente.

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
import re

_client = None


def chave() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def disponivel() -> bool:
    return bool(chave())


# Modelos que a OpenAI desliga em 11/12/2026 (doc de deprecations conferida em
# 09/11/2026). Valor antigo numa variavel do Railway vira o substituto aqui,
# senao a chamada comeca a falhar nesse dia -- e na revisao dos picks, falha
# bloqueia o pick. Snapshots com data (gpt-5-mini-2025-08-07) contam tambem.
SUBSTITUTOS = {
    "gpt-5": "gpt-5.6-terra",
    "gpt-5-mini": "gpt-5.6-terra",
    "gpt-5-nano": "gpt-6-luna",
    "o3": "gpt-5.6-terra",
}
_SNAPSHOT = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def _valido(valor: str | None) -> str | None:
    v = (valor or "").strip()
    if not v or v.lower().startswith("claude"):
        return None
    base = _SNAPSHOT.sub("", v.lower())
    return SUBSTITUTOS.get(base, v)


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


def texto(system: str, conteudo: str, model: str, max_tokens: int = 1500,
          esforco: str = "low") -> str:
    """Resposta em texto livre. Levanta em falha ou resposta cortada."""
    if not model:
        raise RuntimeError("modelo OpenAI nao configurado")
    extra = {"reasoning_effort": esforco} if raciocina(model) else {}
    resposta = cliente().chat.completions.create(
        model=model, max_completion_tokens=max_tokens,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": conteudo}],
        **extra,
    )
    escolha = resposta.choices[0]
    if escolha.finish_reason != "stop":
        raise RuntimeError(f"resposta incompleta: {escolha.finish_reason}")
    return escolha.message.content or ""
