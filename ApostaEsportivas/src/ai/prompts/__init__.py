from ai.prompts._base import SYSTEM_PROMPT, REGRAS_BASE_DYNAMIC  # noqa: F401 · re-exportado para uso externo

# Mapeamento: league_id → módulo com PROMPT específico
# Adicione novas ligas aqui conforme necessário.
_LEAGUE_MAP = {
    1:  "ai.prompts._1",   # Copa do Mundo FIFA
    71: "ai.prompts._71",  # Brasileirão Série A
    72: "ai.prompts._72",  # Brasileirão Série B
}

_cache: dict[int, str] = {}


def get_prompt(league_id: int) -> str:
    """Retorna o template de prompt (com placeholder {dados}) para a liga informada.
    Usa o prompt genérico (_default) se a liga não tiver perfil específico.
    """
    if league_id in _cache:
        return _cache[league_id]

    module_path = _LEAGUE_MAP.get(league_id, "ai.prompts._default")

    import importlib
    module = importlib.import_module(module_path)
    prompt = module.PROMPT

    _cache[league_id] = prompt
    return prompt
