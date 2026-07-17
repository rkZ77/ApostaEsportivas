"""Bayesian Adjustment (Prioridade 6): melhora a estimativa de taxa em
amostras pequenas puxando ela em direcao a um prior confiavel, proporcional
a quao pequena e' a amostra -- NAO mascara amostra insuficiente (Q/
sample_quality ja penaliza isso, continua penalizando), so evita que uma
amostra de 2-3 jogos com taxa 100% seja tratada com o mesmo peso literal
que uma taxa realmente estabelecida em 15 jogos.

Formula padrao de encolhimento Bayesiano (equivalente a um prior Beta
conjugado pra taxa binomial): taxa_ajustada = (n*taxa + k*prior) / (n+k).
n>>k: quase nao muda (amostra grande domina). n<<k: quase todo peso vai
pro prior (amostra pequena nao sustenta a taxa bruta sozinha).

O PRIOR usado e' o hit-rate real historico do market_type
(calibration.get_market_calibration(), ja existente desde a Fase 1, mesma
fonte que calibration_adjustment ja usa) -- nao um numero inventado. Sem
prior confiavel disponivel (market_type sem historico com amostra
suficiente), retorna a taxa empirica sem alterar -- nunca inventa dado."""

_DEFAULT_PRIOR_STRENGTH = 10


def shrink_taxa(taxa_empirica: float | None, amostra: int | None, prior: float | None,
                 prior_strength: int = _DEFAULT_PRIOR_STRENGTH) -> float | None:
    """Taxa ajustada por encolhimento Bayesiano. None se faltar taxa/amostra
    (nao ha o que ajustar); devolve a taxa empirica sem mudar se nao houver
    prior confiavel (calibration_data sem historico suficiente pra esse
    market_type -- ver calibration._MIN_N_FOR_ADJUSTMENT)."""
    if taxa_empirica is None or amostra is None:
        return None
    if prior is None:
        return taxa_empirica
    return round((amostra * taxa_empirica + prior_strength * prior) / (amostra + prior_strength), 4)
