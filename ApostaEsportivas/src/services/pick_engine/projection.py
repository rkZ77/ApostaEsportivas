"""Projecao do mercado (valor esperado) contra a LINHA da casa.

O QUE FALTAVA
-------------
O motor ja' calculava a projecao. `lambda_familia` -- gols/escanteios/faltas/
cartoes esperados na partida, saida de stats_model.expected_value_convergence
-- vira probabilidade em probability_model.poisson_prob_for_line(). Mas a
projecao MORRIA ali dentro: o candidato guardava a probabilidade resultante e
nunca o numero que a produziu, nem a distancia entre ele e a linha. Quem
auditava um RED lia "Poisson dizia 71%" sem poder ver que a projecao era 5.6
numa linha de 5.5, ou seja, praticamente em cima dela.

POR QUE A MARGEM NAO PODE SER EM UNIDADES BRUTAS
------------------------------------------------
"0.4 acima da linha" quer dizer coisas opostas em gols (media ~2.6) e em
escanteios (media ~10): no primeiro e' um quarto do desvio esperado da
contagem, no segundo menos de um decimo. A margem util aqui e' portanto a
margem RELATIVA ao desvio da propria contagem, sigma = sqrt(mu * phi), com
phi vindo da dispersao MEDIDA por familia/escopo (probability_model.dispersao
-- Binomial Negativa desde 2026-08-20, porque so' gols e' Poisson de fato).
E' o mesmo sigma que o modelo de probabilidade ja' usa, entao os dois numeros
descrevem a mesma distribuicao em vez de duas.

O QUE ESTE MODULO NAO FAZ
-------------------------
Nao mexe na probabilidade, e e' de proposito. A distancia projecao-linha JA
esta' inteiramente dentro de poisson_prob_for_line(): projecao em cima da
linha e' exatamente o que produz uma probabilidade perto de 50%, e o desacordo
dessa leitura contra a taxa empirica ja' derruba taxa_real (orchestrator,
regra de config.model_disagreement_threshold) e ja' cobra confidence
(confidence.model_fit_adjustment). Descontar de novo aqui seria cobrar a
mesma evidencia duas vezes -- o erro que o motor ja' evitou uma vez, quando
tirou convergence_adjustment das familias com sinal de Poisson.

A margem entra so' onde nao havia leitura nenhuma antes: no RASTRO (auditoria
do pick) e na classificacao de RISCO, que ate' agora era funcao unica do
confidence.
"""
import math

from services.pick_engine import probability_model

# Fronteiras em DESVIOS-PADRAO da contagem, nao em unidades do mercado.
# 0.50 sigma e' a folga a partir da qual a projecao esta' claramente de um
# lado da linha; abaixo de 0.15 sigma a projecao esta', na pratica, em cima
# dela -- a probabilidade do modelo naquele ponto fica a distancia de um
# arredondamento de 50%.
FOLGA_CONFORTAVEL = 0.50
FOLGA_MINIMA = 0.15


def margem(lambda_val: float | None, line_val: float | None, direction: str,
           family: str | None = None, scope: str | None = None) -> dict | None:
    """Projecao x linha pra UMA linha candidata.

    None quando nao ha' projecao (familia sem leitura de valor esperado --
    btts, resultado, handicap) ou a linha nao e' numerica. Nao inventa
    numero nenhum pra preencher: dado ausente fica ausente.
    """
    if lambda_val is None or line_val is None or lambda_val <= 0:
        return None
    direction = (direction or "").strip().lower()
    if direction not in ("over", "under"):
        return None

    # Sinal da margem sempre a FAVOR do pick: Over quer projecao acima da
    # linha, Under quer abaixo. Margem negativa significa que a propria
    # projecao aponta pro lado contrario do que a pick esta' comprando.
    bruta = (lambda_val - line_val) if direction == "over" else (line_val - lambda_val)
    sigma = math.sqrt(lambda_val * probability_model.dispersao(family, scope))
    em_sigmas = bruta / sigma if sigma > 0 else None

    if em_sigmas is None:
        classe = None
    elif em_sigmas < 0:
        classe = "contra_a_linha"
    elif em_sigmas < FOLGA_MINIMA:
        classe = "em_cima_da_linha"
    elif em_sigmas < FOLGA_CONFORTAVEL:
        classe = "apertada"
    else:
        classe = "folgada"

    return {
        "valor": round(lambda_val, 3),
        "linha": line_val,
        "direcao": direction,
        "margem": round(bruta, 3),
        "sigma": round(sigma, 3),
        "margem_em_sigmas": round(em_sigmas, 3) if em_sigmas is not None else None,
        "classe": classe,
    }
