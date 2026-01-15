class ValueAnalysisService:
    """
    Serviço responsável por calcular:
    - probabilidade estimada
    - valor esperado (EV)
    - decisão de VALUE BET
    """

    # Limites defensivos por mercado (controle de risco)
    MAX_PROBABILITY = {
        "GOALS": 0.80,
        "CORNERS": 0.78,
        "CARDS": 0.75
    }

    MIN_EV = 0.05  # 5% mínimo de valor esperado

    def __init__(self):
        pass

    # =========================
    # MÉTODO PRINCIPAL
    # =========================
    def analyze(
        self,
        market: str,
        historical_stats: dict,
        line: float,
        odd: float,
        context: str = "total"  # total | home | away
    ):
        """
        Retorna análise de valor para qualquer mercado.
        """

        if market == "GOALS":
            metric = "avg_goals_for"
        elif market == "CORNERS":
            metric = "avg_corners"
        elif market == "CARDS":
            metric = "avg_cards"
        else:
            raise ValueError(f"Mercado não suportado: {market}")

        avg_value = historical_stats.get(context, {}).get(metric, 0.0)

        probability = self._estimate_probability(avg_value, line)
        probability = min(probability, self.MAX_PROBABILITY[market])

        expected_value = (probability * odd) - 1

        return {
            "market": market,
            "line": line,
            "odd": odd,
            "probability_model": round(probability, 4),
            "expected_value": round(expected_value, 4),
            "has_value": expected_value >= self.MIN_EV
        }

    # =========================
    # MODELO DE PROBABILIDADE
    # =========================
    def _estimate_probability(self, avg: float, line: float) -> float:
        """
        Modelo simples, robusto e controlado.
        """

        if avg <= 0:
            return 0.01

        ratio = avg / line

        # Curva suavizada
        if ratio >= 1.40:
            return 0.78
        elif ratio >= 1.25:
            return 0.72
        elif ratio >= 1.10:
            return 0.65
        elif ratio >= 1.00:
            return 0.58
        elif ratio >= 0.90:
            return 0.48
        elif ratio >= 0.80:
            return 0.38
        else:
            return 0.25
