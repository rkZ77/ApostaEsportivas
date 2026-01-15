import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")

url = "https://api.the-odds-api.com/v4/sports/soccer_epl/events"
params = {
    "apiKey": API_KEY,
    "regions": "eu"
}

r = requests.get(url, params=params)
r.raise_for_status()

events = r.json()

print(f"Eventos encontrados: {len(events)}")

for e in events[:5]:
    print({
  "id": "3fd1e970c718bfc0f99a7e4575e46f49",
  "home": "Manchester United",
  "away": "Manchester City",
    })
