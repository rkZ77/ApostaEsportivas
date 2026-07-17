"""Modelo de Consenso -- modo sombra (Fase 3). Nao existem hoje duas fontes
independentes de probabilidade rodando para o mesmo fixture (a IA em
producao e o pick_engine isolado nunca compartilham um gatilho, e em
metade dos pipelines de IA o campo prob_real e uma copia da taxa
deterministica, nao uma segunda opiniao). Por isso este modulo so COMPARA
duas saidas ja prontas -- nao calcula nada, nao afeta nenhuma pick salva.
Quem roda a comparacao de verdade (busca o pick da IA, roda o pick_engine,
grava o log) e shadow_consensus.py."""


def compare_ai_vs_engine(ai_pick: dict, engine_pick: dict) -> dict:
    """Compara um pick ja salvo pela IA com o candidato equivalente gerado
    pelo pick_engine para o mesmo fixture. Nao decide qual esta certo --
    so registra a diferenca para acumular historico real."""
    ai_market = (ai_pick.get("market_type") or "").lower()
    engine_market = (engine_pick.get("market_type") or "").lower()
    same_market = ai_market == engine_market

    ai_conf = ai_pick.get("confidence")
    engine_conf = engine_pick.get("confidence")
    conf_diff = (
        round(engine_conf - ai_conf, 4)
        if ai_conf is not None and engine_conf is not None else None
    )

    return {
        "fixture_id": ai_pick.get("fixture_id"),
        "ai": {
            "market_type": ai_pick.get("market_type"),
            "market": ai_pick.get("market"),
            "line": ai_pick.get("line"),
            "confidence": ai_conf,
            "ev": ai_pick.get("ev"),
            "probability": ai_pick.get("probability"),
        },
        "engine": {
            "market_type": engine_pick.get("market_type"),
            "market": engine_pick.get("market_name"),
            "line": engine_pick.get("value_label"),
            "confidence": engine_conf,
            "ev": engine_pick.get("ev"),
            "probability": engine_pick.get("taxa_real"),
        },
        "same_market_type": same_market,
        "confidence_diff": conf_diff,
    }
