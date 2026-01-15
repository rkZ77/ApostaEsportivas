from src.collectors.odds_collector_service import OddsCollectorService

def main():
    odds_service = OddsCollectorService()

    odds = odds_service.get_odds_for_fixture(
        home_team="Manchester United",
        away_team="Chelsea"
    )

    print("\n=== ODDS RETORNADAS ===")

    if not odds:
        print("❌ Nenhuma odd retornada")
        return

    for o in odds:
        print(o)

if __name__ == "__main__":
    main()
