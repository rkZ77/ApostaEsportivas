class ValueAnalysisService:
    """
    Responsável por transformar estatísticas + odds
    em probabilidade real e Expected Value
    """

    def implied_probability(self, odd: float) -> float:
        if odd <= 1:
            return 0.0
        return 1 / odd

    def expected_value(self, prob: float, odd: float) -> float:
        return (prob * odd) - 1

    def has_value(self, prob: float, odd: float, min_prob=0.30):
        ev = self.expected_value(prob, odd)

        return {
            "probability": prob,
            "implied_probability": self.implied_probability(odd),
            "expected_value": ev,
            "has_value": prob >= min_prob and ev > 0
        }

    def probability_from_stats(self, market, line, stats_home, stats_away):
        """
        Calcula probabilidade baseada em estatísticas históricas
        """

        if market == "totals":  # GOLS
            avg_goals = (
                stats_home["avg_goals_for"] +
                stats_away["avg_goals_for"]
            ) / 2

            return min(avg_goals / line, 1)

        if market == "corners_totals":
            avg_corners = (
                stats_home["avg_corners"] +
                stats_away["avg_corners"]
            ) / 2

            return min(avg_corners / line, 1)

        if market == "cards_totals":
            avg_cards = (
                stats_home["avg_cards"] +
                stats_away["avg_cards"]
            ) / 2

            return min(avg_cards / line, 1)

        # Resultado (1X2) – simplificado por enquanto
        if market == "h2h":
            return 0.33

        return 0.0
