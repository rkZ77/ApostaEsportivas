class TeamAnalyticsService:

    ##########################################################################
    # Análise de forma (últimos 20 jogos)
    ##########################################################################
    def calculate_form(self, last20):
        if not last20 or len(last20) == 0:
            return {"wins": 0, "draws": 0, "losses": 0, "form_score": 0.0}

        wins = sum(1 for g in last20 if g["result"] == "W")
        draws = sum(1 for g in last20 if g["result"] == "D")
        losses = sum(1 for g in last20 if g["result"] == "L")

        # Score ponderado: vitória 3 pts, empate 1 pt, derrota 0
        form_score = (wins * 3 + draws * 1) / (len(last20) * 3)

        return {
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "form_score": round(form_score, 3)
        }

    ##########################################################################
    # Tendência de gols nos últimos 20 jogos
    ##########################################################################
    def calculate_goal_trends(self, last20):
        if not last20:
            return {
                "avg_goals_for": 0.0,
                "avg_goals_against": 0.0,
                "avg_total_goals": 0.0
            }

        goals_for = [g["goals_for"] for g in last20]
        goals_against = [g["goals_against"] for g in last20]
        total = [g["goals_for"] + g["goals_against"] for g in last20]

        return {
            "avg_goals_for": round(sum(goals_for) / len(goals_for), 2),
            "avg_goals_against": round(sum(goals_against) / len(goals_against), 2),
            "avg_total_goals": round(sum(total) / len(total), 2)
        }

    ##########################################################################
    # Tendências de cartões
    ##########################################################################
    def calculate_card_trends(self, last20):
        if not last20:
            return {"avg_cards": 0.0}

        cards = [(g["yellow_cards"] + g["red_cards"]) for g in last20]

        return {"avg_cards": round(sum(cards) / len(cards), 2)}

    ##########################################################################
    # Tendências de escanteios
    ##########################################################################
    def calculate_corner_trends(self, last20):
        if not last20:
            return {"avg_corners": 0.0}

        corners = [g["corners"] for g in last20]

        return {"avg_corners": round(sum(corners) / len(corners), 2)}

    ##########################################################################
    # Retorna análise completa do time
    ##########################################################################
    def analyze_team(self, last20):
        return {
            "form": self.calculate_form(last20),
            "goals": self.calculate_goal_trends(last20),
            "cards": self.calculate_card_trends(last20),
            "corners": self.calculate_corner_trends(last20)
        }
