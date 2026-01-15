from src.collectors.odds_collector_service import OddsCollectorService

def main():
    service = OddsCollectorService()

    # EVENT ID REAL da Odds API (pegue do endpoint /events)
    EVENT_ID = "037d7b6bb128546961e2a06680f63944"
    SPORT_KEY = "soccer_epl"

    odds = service.get_odds_by_event_id(
        sport_key=SPORT_KEY,
        event_id=EVENT_ID
    )

    print("ODDS RETORNADAS:")
    for o in odds:
        print(o)

if __name__ == "__main__":
    main()
