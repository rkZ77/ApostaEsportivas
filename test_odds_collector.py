import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

SPORT_KEY = "soccer_epl"


def main():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/events"

    params = {
        "apiKey": API_KEY,
        "regions": "eu"
    }

    r = requests.get(url, params=params)
    r.raise_for_status()

    events = r.json()
    print(f"Eventos ativos: {len(events)}")

    for e in events[:5]:
        print({
            "id": e["id"],
            "home": e["home_team"],
            "away": e["away_team"],
            "commence_time": e["commence_time"]
        })


if __name__ == "__main__":
    main()
