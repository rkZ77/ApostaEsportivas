
from datetime import datetime
from database.db_connection import get_connection
from main import main as run_pre_game
from services.pre_game_suggestion_service import save_pre_game_suggestion
from services.match_service import ensure_match_exists
from collectors.api_football_collector import ApiFootballCollector
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Pós-jogo: avaliação das recomendações


def run_post_game_evaluation():
    conn = get_connection()
    cursor = conn.cursor()
    collector = ApiFootballCollector()
    cursor.execute('''
        SELECT br.id, br.match_id, br.market, br.team_side, br.line, m.id as api_football_id
        FROM bet_recommendations br
        JOIN matches m ON br.match_id = m.id
        WHERE br.recommendation IS NOT NULL AND (br.result IS NULL OR br.evaluated_at IS NULL)
    ''')
    recs = cursor.fetchall()
    if not recs:
        print("Nenhuma recomendação pendente para avaliação.")
        cursor.close()
        conn.close()
        return
    for rec_id, match_id, market, team_side, line, api_football_id in recs:
        cursor.execute('SELECT status FROM matches WHERE id=%s', (match_id,))
        row = cursor.fetchone()
        if not row or row[0] != 'finished':
            continue
        stats = collector.get_fixture_statistics(api_football_id)
        # Seleção dos valores corretos para cada time/total
        if team_side == 'home':
            goals = stats.get('home', {}).get('Goals', 0)
            corners = stats.get('home', {}).get('Corner Kicks', 0)
            cards = stats.get('home', {}).get(
                'Yellow Cards', 0) + stats.get('home', {}).get('Red Cards', 0)
        elif team_side == 'away':
            goals = stats.get('away', {}).get('Goals', 0)
            corners = stats.get('away', {}).get('Corner Kicks', 0)
            cards = stats.get('away', {}).get(
                'Yellow Cards', 0) + stats.get('away', {}).get('Red Cards', 0)
        else:  # total
            goals = (stats.get('home', {}).get('Goals', 0) or 0) + \
                (stats.get('away', {}).get('Goals', 0) or 0)
            corners = (stats.get('home', {}).get('Corner Kicks', 0) or 0) + \
                (stats.get('away', {}).get('Corner Kicks', 0) or 0)
            cards = (
                (stats.get('home', {}).get('Yellow Cards', 0) or 0) + (stats.get('home', {}).get('Red Cards', 0) or 0) +
                (stats.get('away', {}).get('Yellow Cards', 0) or 0) +
                (stats.get('away', {}).get('Red Cards', 0) or 0)
            )
        # ...restante da lógica de avaliação...
        if market == 'goals':
            if (team_side == 'total' and goals > line) or (team_side != 'total' and goals > line):
                result = 'GREEN'
            else:
                result = 'RED'
        elif market == 'corners':
            if (team_side == 'total' and corners > line) or (team_side != 'total' and corners > line):
                result = 'GREEN'
            else:
                result = 'RED'
        elif market == 'cards':
            if (team_side == 'total' and cards > line) or (team_side != 'total' and cards > line):
                result = 'GREEN'
            else:
                result = 'RED'
        cursor.execute('UPDATE bet_recommendations SET result=%s, evaluated_at=%s WHERE id=%s',
                       (result, datetime.now(), rec_id))
    conn.commit()
    print("Avaliação pós-jogo concluída.")
    cursor.close()
    conn.close()

# Métricas do robô


def run_metrics():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT COUNT(*) FROM bet_recommendations WHERE result IS NOT NULL')
    total = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM bet_recommendations WHERE result='GREEN'")
    greens = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM bet_recommendations WHERE result='RED'")
    reds = cursor.fetchone()[0]
    taxa = (greens / total * 100) if total > 0 else 0
    print(f"Total apostas avaliadas: {total}")
    print(f"Greens: {greens}")
    print(f"Reds: {reds}")
    print(f"Taxa de acerto: {taxa:.2f}%")
    cursor.close()
    conn.close()

# Orquestrador principal


def main():
    print("--- Fase Pré-Jogo: Sugestões ---")
    # Coleta dos jogos futuros
    collector = ApiFootballCollector()
    matches = collector.get_fixtures()
    suggestions = []
    for match in matches:
        fixture_id = match["match_id"]
        league = match["league"]
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        match_datetime = match["startTimestamp"]
        # Garante que o jogo existe na tabela matches
        ensure_match_exists(fixture_id, league, home_team,
                            away_team, match_datetime)
        for market in ["goals", "corners", "cards"]:
            for side in ["total", "home", "away"]:
                suggestions.append(
                    (fixture_id, league, home_team, away_team, market, side, match_datetime))
    # Salvar sugestões sem odds/probabilidade/resultado
    count_saved = 0
    for s in suggestions:
        save_pre_game_suggestion(*s)
        count_saved += 1
    print(f"[INFO] Sugestões pré-jogo salvas: {count_saved}")
    try:
        run_pre_game()
    except Exception as e:
        print(f"[AVISO] Erro na fase pré-jogo: {e}. Continuando fluxo.")
    print("--- Fase Pós-Jogo: Avaliação ---")
    run_post_game_evaluation()
    print("--- Fase de Métricas ---")
    run_metrics()


if __name__ == "__main__":
    main()
