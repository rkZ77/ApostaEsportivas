"""
Coletor de odds da Betano POR JOGO usando Playwright.
"""

from playwright.sync_api import sync_playwright
from typing import Dict


class BetanoCollector:
    BASE_LEAGUE_URL = (
        "https://www.betano.bet.br/"
        "sport/futebol/league/campeonato-paulista-serie-a1-brasil/16901/"
    )

    def get_odds_by_match(self, home_team: str, away_team: str) -> Dict[str, float]:
        odds = {
            "goals_over_2_5": None,
            "corners_over_9_5": None,
            "cards_over_4_5": None,
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(self.BASE_LEAGUE_URL, timeout=60000)
            page.wait_for_load_state("networkidle")

            match = page.locator(f"text={home_team}").filter(
                has_text=away_team
            ).first

            if not match:
                browser.close()
                return odds

            match.click()
            page.wait_for_load_state("networkidle")

            try:
                page.locator("text=Total de Gols").click()
                odds["goals_over_2_5"] = float(
                    page.locator("text=Mais de 2.5").first
                    .locator("xpath=../..//span").last.inner_text()
                    .replace(",", ".")
                )
            except Exception:
                pass

            try:
                page.locator("text=Escanteios").click()
                odds["corners_over_9_5"] = float(
                    page.locator("text=Mais de 9.5").first
                    .locator("xpath=../..//span").last.inner_text()
                    .replace(",", ".")
                )
            except Exception:
                pass

            try:
                page.locator("text=Cartões").click()
                odds["cards_over_4_5"] = float(
                    page.locator("text=Mais de 4.5").first
                    .locator("xpath=../..//span").last.inner_text()
                    .replace(",", ".")
                )
            except Exception:
                pass

            browser.close()

        return odds