"""Score de confianca (C/Q/K) e classificacao de risco."""
from services.pick_engine.config import PickEngineConfig, DEFAULT_CONFIG
from services.pick_engine.variance_model import CV_HIGH_THRESHOLD


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


_NIVEIS = ("BAIXO", "MEDIO", "ALTO")

# Amostra: os mesmos cortes de qualidade que o resto do motor usa (ver
# stats_model/amostra_label). Abaixo de 5 jogos nao ha' estimativa, so'
# ruido; de 5 a 7 ha' estimativa, com incerteza grande demais pra um pick
# ser anunciado como risco baixo.
_AMOSTRA_INSUFICIENTE = 5
_AMOSTRA_LIMITADA = 8

# Data Quality Score (data_validation.data_quality_score, 0-100). Abaixo de
# 70 a propria validacao chama a base de insuficiente; entre 70 e 80 ela ja'
# eleva o edge minimo exigido, e aqui cobra um degrau de risco pelo mesmo
# motivo.
_DQ_INSUFICIENTE = 70
_DQ_LIMITADA = 80


def risco_from_confidence(conf: float, config: PickEngineConfig = DEFAULT_CONFIG) -> str:
    """Nivel de risco olhando SO' o confidence. Continua sendo o ponto de
    partida de classify_risk() -- e o valor final pros chamadores que nao
    tem os outros sinais em maos."""
    if conf >= config.risco_baixo_min:
        return "BAIXO"
    if conf >= config.risco_medio_min:
        return "MEDIO"
    return "ALTO"


def classify_risk(conf: float, config: PickEngineConfig = DEFAULT_CONFIG, *,
                  data_quality: float | None = None,
                  amostra: int | None = None,
                  coeficiente_variacao: float | None = None,
                  projecao: dict | None = None) -> str:
    """Risco do pick a partir do confidence E dos sinais que dizem quanto
    aquele confidence merece credito.

    POR QUE NAO BASTA O CONFIDENCE
    ------------------------------
    Ate' agora `risco` era funcao unica de `conf`, e conf e' um score
    composto que ja' foi arredondado, somado e teto-limitado varias vezes
    antes de chegar aqui. Um pick com 5 jogos de amostra, dispersao alta e
    projecao em cima da linha podia terminar em 0.81 -- e sair anunciado
    como "BAIXO" -- porque cada penalidade sozinha cabe dentro da folga do
    score. Risco baixo tem que significar "da' pra confiar nesta
    estimativa", nao "a probabilidade saiu alta".

    SO' REBAIXA, NUNCA PROMOVE
    --------------------------
    Nenhum sinal aqui pode transformar um ALTO em MEDIO. Confidence ja' e'
    o unico lugar onde evidencia vira nota; este passo so' cobra dela o que
    o score composto deixou passar. Um sinal ausente (None) e' neutro --
    nao vira nem credito nem penalidade, conforme a regra do motor de nunca
    tratar dado ausente como favoravel.

    A ODD FICA DE FORA DE PROPOSITO
    -------------------------------
    `risco` participa da escolha do is_best_pick (ranking.select_final_picks
    prefere um candidato nao-ALTO). Preco entrando aqui seria preco
    ORDENANDO pick, e no motor a odd elimina nos gates e nunca ordena.
    """
    nivel = _NIVEIS.index(risco_from_confidence(conf, config))

    def rebaixa(degraus: int) -> None:
        nonlocal nivel
        nivel = min(len(_NIVEIS) - 1, nivel + degraus)

    if data_quality is not None:
        if data_quality < _DQ_INSUFICIENTE:
            rebaixa(2)
        elif data_quality < _DQ_LIMITADA:
            rebaixa(1)

    if amostra is not None:
        if amostra < _AMOSTRA_INSUFICIENTE:
            rebaixa(2)
        elif amostra < _AMOSTRA_LIMITADA:
            rebaixa(1)

    # Dispersao acima do limiar ja' desconta confidence (variance_penalty),
    # mas o desconto satura em 0.10 -- um mercado muito instavel com taxa
    # muito alta sobrevive a ele. O degrau aqui e' o que impede esse caso
    # de se anunciar como risco baixo.
    if coeficiente_variacao is not None and coeficiente_variacao > CV_HIGH_THRESHOLD:
        rebaixa(1)

    classe = (projecao or {}).get("classe")
    if classe == "contra_a_linha":
        # A propria projecao aponta pro lado oposto do pick: o que sustenta
        # a entrada e' so' a contagem historica, contra o valor esperado.
        rebaixa(2)
    elif classe == "em_cima_da_linha":
        rebaixa(1)

    return _NIVEIS[nivel]
