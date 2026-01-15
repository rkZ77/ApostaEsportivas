import requests

url = "https://v3.football.api-sports.io/teams"
headers = {
    "x-apisports-key": "00cfa9ec32195f7ace9c456dc5708383"
}
params = {
    "league": 39,
    "season": 2025
}

r = requests.get(url, headers=headers, params=params)
print(r.status_code)
print(r.text)
