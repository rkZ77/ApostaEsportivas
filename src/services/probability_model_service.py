import math


class ProbabilityModelService:

    def _poisson_prob_over(self, lam, line):
        """
        Retorna probabilidade de OVER usando distribuição de Poisson.
        line = ex: 2.5 -> usa floor(line)
        """
        threshold = int(math.floor(line))
        cumulative = sum(
            (math.exp(-lam) * (lam ** k) / math.factorial(k))
            for k in range(0, threshold + 1)
        )
        return 1 - cumulative  # OVER probability

    def _calc_weighted_avg(self, stats):
        """
        stats contém:
        stats["last_5"]["total"]["avg_goals_for"]
        stats["last_10"]["total"]["avg_goals_for"]
        stats["last_15"]["total"]["avg_goals_for"]
        """
        return (
            stats["last_5"]["total"]["avg_goals_for"] * 0.6 +
            stats["last_10"]["total"]["avg_goals_for"] * 0.3 +
            stats["last_15"]["total"]["avg_goals_for"] * 0.1
        )

    def compute_probabilities(self, home_stats, away_stats, market, line):
        """
        market → totals, corners_totals, cards_totals
        line → número (ex: 2.5)
        """

        if market == "totals":
            # GOLS
            home_attack = self._calc_weighted_avg(home_stats)
            away_attack = self._calc_weighted_avg(away_stats)

            # defesa estimada
            home_defense = self._calc_weighted_avg(away_stats)
            away_defense = self._calc_weighted_avg(home_stats)

            lam = (home_attack + away_attack + home_defense + away_defense) / 2

            prob_over = self._poisson_prob_over(lam, line)
            prob_under = 1 - prob_over

            return {
                "prob_over": prob_over,
                "prob_under": prob_under,
                "lambda": lam
            }

        elif market == "corners_totals":
            # ESCANTEIOS
            # usando médias simples + ponderação
            home_avg = home_stats["last_5"]["total"]["avg_corners"]
            away_avg = away_stats["last_5"]["total"]["avg_corners"]
            lam = (home_avg + away_avg) / 1.4

            prob_over = self._poisson_prob_over(lam, line)
            prob_under = 1 - prob_over

            return {
                "prob_over": prob_over,
                "prob_under": prob_under,
                "lambda": lam
            }

        elif market == "cards_totals":
            # CARTÕES
            home_avg = home_stats["last_5"]["total"]["avg_cards"]
            away_avg = away_stats["last_5"]["total"]["avg_cards"]
            lam = (home_avg + away_avg) / 1.7

            prob_over = self._poisson_prob_over(lam, line)
            prob_under = 1 - prob_over

            return {
                "prob_over": prob_over,
                "prob_under": prob_under,
                "lambda": lam
            }

        return None
