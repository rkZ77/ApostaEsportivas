from src.collectors.odds_collector_service import OddsCollectorService

SPORT_KEY = "soccer_epl"
EVENT_ID = "342788786c22e570ed2da53a9608113f"

service = OddsCollectorService()

for market in ["totals", "corners_totals", "cards_totals"]:
    print(f"\n[TESTANDO MERCADO] {market}")

    try:
        odds = service.get_odds_by_event_id(
            sport_key=SPORT_KEY,
            event_id=EVENT_ID,
            markets_override=market  # habilitamos override
        )
        print(f"Odds encontradas ({market}): {len(odds)}")
        print(odds[:5])

    except Exception as e:
        print(f"[ERRO] Mercado {market}: {e}")
