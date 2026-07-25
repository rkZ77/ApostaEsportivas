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
    # Mercado com 1 so bookmaker nao tem consenso pra checar contra erro de
    # precificacao -- visto na pratica: "Cards Asian Handicap Away +1.5" a
    # odd 4.50 (bookmakers_count=1) dando EV=+303%, enquanto a linha irmã
    # do mesmo mercado ("Home +1.5") tava a odd 1.18 -- inconsistencia que
    # so um segundo bookmaker cotando permitiria detectar. Exclui a odd
    # inteira da analise antes mesmo de virar candidato (nao so desconta K).
    min_bookmakers_count: int = 2

    # Smart Safe Line (escolha de linha). min_odd=1.39: piso pedido pelo
    # usuario pra VIP -- abaixo disso o retorno nao compensa o risco de uma
    # unidade presa numa pick de baixo valor, mesmo com confidence alta
    # (ex.: Dupla Chance quase certa mas odd 1.23). Nao ha teto preferencial
    # aqui (so o teto de sanidade max_odd=15.0 abaixo) -- odd mais alta que
    # o ideal (~2.00) e' bem-vinda, so precisa de menos unidades de stake
    # (calculate_stake ja usa Kelly, que naturalmente pondera por odd).
    min_odd: float = 1.39
    min_edge: float = 0.05
    # Teto de sanidade: odds muito extremas (>15) geralmente refletem
    # mercado ilíquido/raramente cotado, não valor real -- visto na pratica
    # com um handicap a odd 51.0 gerando EV de +3839% (taxa historica
    # provavelmente nao reflete o risco real que o mercado ilíquido
    # precifica). Aplica tanto no filtro principal quanto no fallback.
    max_odd: float = 15.0

    # Fase 5: escolha de linha -- faixa conservadora de odd (preferencia
    # suave, nao filtro: uma linha fora da faixa ainda vence se o edge for
    # claramente maior) + pesos do line_score. Prioridade 2 do plano de
    # refatoracao adicionou bookmakers (consenso de preco) e stability
    # (a linha bate de forma consistente ao longo do tempo, nao so na
    # media agregada) -- pesos renormalizados pra somar 1.0. Variancia e
    # Data Quality Score NAO entram aqui de proposito: sao constantes pra
    # todos os candidatos do mesmo mercado/fixture, entao nao ajudam a
    # escolher ENTRE linhas -- variancia already penaliza confidence (V,
    # orchestrator.py) e Data Quality Score ajusta o limiar de edge abaixo
    # (dqs_min_edge_scale), nao o line_score.
    conservative_odd_low: float = 1.50
    conservative_odd_high: float = 1.90
    line_weight_taxa: float = 0.35
    line_weight_edge: float = 0.25
    line_weight_conservative: float = 0.15
    line_weight_bookmakers: float = 0.10
    line_weight_stability: float = 0.15
    # Linha redonda (sem .5) pode empatar exato com o resultado e virar
    # PUSH -- nunca acontece numa linha .5. Penalidade leve no line_score
    # (nao um filtro/gate) pra desempatar a favor da .5 quando as duas
    # opcoes tem merito estatistico parecido (pedido do usuario 2026-07-25).
    round_line_push_penalty: float = 0.05
    # bookmakers_count satura o bonus em N casas (mais que isso nao soma mais)
    bookmakers_bonus_saturation: int = 5

    # Data Quality Score (data_validation.py) ajusta o limiar de edge
    # dinamicamente -- fixture com dado ruim exige uma margem de seguranca
    # maior pra aprovar uma linha, em vez de confiar no mesmo min_edge fixo
    # de sempre. dqs_baseline=sem ajuste; abaixo disso, min_edge efetivo
    # cresce ate dqs_min_edge_scale (fracao) no piso (DQS=0).
    dqs_baseline: float = 80.0
    dqs_min_edge_scale: float = 0.5

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

    # Cartoes: gate duro (referee_model.cards_market_eligible) -- mesma regra
    # que ja existia no prompt de IA legado (dica_do_dia_pipeline.py: "arbitro
    # com >=3 jogos"), agora aplicada no motor deterministico pra TODOS os
    # pipelines (cartoes/handicap_cards ficam fora da analise sem esses dois
    # sinais, nao so com confidence reduzida).
    cards_referee_min_games: int = 3
    # Abaixo deste score de intensidade (0-1, ver referee_model.game_intensity)
    # o jogo e' classificado "frio" e cartoes fica bloqueado -- so o extremo
    # frio bloqueia (permite "morno"+"quente"), pra nao zerar a frequencia de
    # picks de cartoes; ajustar aqui se sair cartao demais em jogo sem tensao.
    cards_intensity_cold_threshold: float = 0.40


DEFAULT_CONFIG = PickEngineConfig()

# Dica do Dia exige consistencia maior (regra ja existia como constante fixa
# CONFIDENCE_MIN=0.72 em dica_do_dia_pipeline.py) e faixa de odd propria --
# piso igual ao VIP (min_odd=1.39) mas com teto mais conservador (1.90 em vez
# de 15.0): pick gratuita precisa ser mais "segura" que VIP, odd muito alta
# tipicamente reflete evento menos provavel (decisao explicita do usuario).
DICA_CONFIG = PickEngineConfig(min_confidence=0.72, min_odd=1.39, max_odd=1.90)
