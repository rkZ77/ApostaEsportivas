"""
Serviço para análise de valor esperado.
"""


def calculate_expected_value(probability, odd):
    """
    EV = (probabilidade * odd) - 1
    """
    return (probability * odd) - 1


def classify_ev(ev):
    if ev > 0:
        return "value_bet"
    return "no_value"
