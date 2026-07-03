"""Limites e pesos configuraveis do motor de picks. Cada pipeline
(VIP/Dica do Dia/Multipla/Alavancagem) pode instanciar sua propria config
em vez de depender de numeros magicos espalhados pelo codigo."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PickEngineConfig:
    # Criterios minimos de elegibilidade (secao 5 / selecao final)
    min_taxa: float = 0.65
    min_amostra: int = 5
    min_confidence: float = 0.55
    min_ev: float = 0.0  # EV deve ser estritamente positivo para aprovar a aposta

    # Smart Safe Line (escolha de linha)
    min_odd: float = 1.60
    min_edge: float = 0.05

    # Fase 5: escolha de linha -- faixa conservadora de odd (preferencia
    # suave, nao filtro: uma linha fora da faixa ainda vence se o edge for
    # claramente maior) + pesos do line_score (taxa+edge+bonus conservador)
    conservative_odd_low: float = 1.50
    conservative_odd_high: float = 1.90
    line_weight_taxa: float = 0.5
    line_weight_edge: float = 0.3
    line_weight_conservative: float = 0.2

    # Pesos da formula de confidence: C*weight_c + Q*weight_q + K*weight_k
    weight_c: float = 0.45
    weight_q: float = 0.25
    weight_k: float = 0.30
    confidence_min_clamp: float = 0.20
    confidence_max_clamp: float = 0.92

    # Decaimento temporal (dias -> peso), avaliado em ordem
    temporal_tiers: tuple = ((14, 1.0), (30, 0.85), (60, 0.70))
    temporal_default: float = 0.50

    # Peso por forca do adversario (rank -> peso)
    opponent_top_rank: int = 6
    opponent_top_weight: float = 2.0
    opponent_mid_rank: int = 12
    opponent_mid_weight: float = 1.0
    opponent_weak_weight: float = 0.5
    opponent_unknown_weight: float = 1.0

    # Amostra (Q)
    sample_rich_n: int = 8
    sample_rich_q: float = 1.00
    sample_moderate_n: int = 4
    sample_moderate_q: float = 0.75
    sample_scarce_n: int = 1
    sample_scarce_q: float = 0.45
    sample_empty_q: float = 0.20

    # Risco (derivado do confidence por enquanto -- modelo de risco
    # independente e trabalho de Fase 2/matchup)
    risco_baixo_min: float = 0.80
    risco_medio_min: float = 0.65


DEFAULT_CONFIG = PickEngineConfig()

# Dica do Dia exige consistencia maior (regra ja existia como constante
# fixa CONFIDENCE_MIN=0.72 em dica_do_dia_pipeline.py)
DICA_CONFIG = PickEngineConfig(min_confidence=0.72)
