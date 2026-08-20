"""Score de confianca (C/Q/K) e classificacao de risco."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG


def confidence_score(C: float, Q: float, K: float, config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    raw = (C * config.weight_c) + (Q * config.weight_q) + (K * config.weight_k)
    return round(min(max(raw, config.confidence_min_clamp), config.confidence_max_clamp), 4)


def confirmation_k(amostra: int, bookmakers_count: int) -> float:
    """Aproximacao de K (confirmadores independentes) usando amostra e
    consenso entre bookmakers. Nao inclui arbitro/standings/contexto
    situacional (esses sinais entram na Fase 2, via context_model) --
    fica mais conservador que o K completo."""
    score = 0.0
    if amostra >= 8:
        score += 1.0
    elif amostra >= 5:
        score += 0.6
    if bookmakers_count >= 3:
        score += 1.0
    elif bookmakers_count >= 2:
        score += 0.6

    if score >= 1.8:
        return 1.00
    if score >= 1.0:
        return 0.70
    if score >= 0.5:
        return 0.40
    return 0.10


def convergence_adjustment(direction: str, line_val: float | None, convergence: dict | None) -> float:
    """Delta pra somar no K bruto: a convergencia feitos/cedidos concorda
    com a direcao (Over/Under) do pick escolhido -> +0.10 (confirmador
    extra); diverge da direcao OU as duas estimativas nem convergem entre
    si -> -0.10. Sem dado suficiente -> 0 (neutro)."""
    if not convergence or line_val is None:
        return 0.0
    if not convergence["converged"]:
        return -0.10
    implied_direction = "over" if convergence["expected_value"] > line_val else "under"
    return 0.10 if implied_direction == direction else -0.10


def model_fit_adjustment(model_fit_diff: float | None,
                         config: PickEngineConfig = DEFAULT_CONFIG) -> float:
    """Delta pra somar no confidence (termo M): quanto a probabilidade do
    modelo (probability_model) concorda com a taxa empirica bruta
    (stats_model) pra MESMA linha -- duas estimativas independentes
    concordando e sinal de que o padrao e real, nao ajuste por acaso.
    Diferenca pequena -> +0.05 (confirmador extra). Diferenca grande ->
    -0.05 (os dois modelos discordam, desconfie). Entre os dois, ou sem dado
    (familia sem leitura de modelo) -> 0 (neutro).

    O corte de baixo era 0.30 ate' 2026-08-08, e nessa faixa larga ele nunca
    disparava na pratica: o pick #1573, com 24.5pp de desacordo, recebeu 0.0.
    Hoje bate com config.model_disagreement_threshold, que e' onde o
    orchestrator passa a usar a estimativa menor -- um desacordo que muda a
    probabilidade tem que cobrar confidence tambem, senao o mesmo fato seria
    tratado como grave num lugar e irrelevante no outro.

    O limiar passou a ser LIDO da config em 2026-08-20, em vez de repetido
    aqui como 0.15. Os dois numeros ja' tinham que ser iguais e havia um teste
    so' pra vigiar isso -- quando a config foi pra 0.12 o teste pegou a
    divergencia, que e' exatamente o que ele existia pra fazer. Derivar em vez
    de duplicar tira a chance de acontecer de novo.

    O corte de baixo acompanha: fica em 0.10, mas nunca acima do limiar de
    penalidade menos uma folga -- senao um limiar apertado faria a MESMA
    diferenca ganhar bonus e penalidade ao mesmo tempo."""
    if model_fit_diff is None:
        return 0.0
    penaliza = config.model_disagreement_threshold
    if penaliza is None:
        # Regra desligada: sem um ponto onde o desacordo passa a mudar a
        # probabilidade, cobrar confidence por ele seria punir por um criterio
        # que o motor decidiu nao usar.
        return 0.05 if model_fit_diff <= 0.10 else 0.0
    confirma = min(0.10, penaliza - 0.02)
    if model_fit_diff <= confirma:
        return 0.05
    if model_fit_diff >= penaliza:
        return -0.05
    return 0.0


def risco_from_confidence(conf: float, config: PickEngineConfig = DEFAULT_CONFIG) -> str:
    if conf >= config.risco_baixo_min:
        return "BAIXO"
    if conf >= config.risco_medio_min:
        return "MEDIO"
    return "ALTO"
