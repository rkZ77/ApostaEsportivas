from database.db_connection import get_connection
from datetime import datetime


def save_pre_game_suggestion(
    fixture_id: int,
    market: str,
    side: str,
    match_timestamp: int
):
    """
    Salva sugestão pré-jogo.
    - Não usa nomes de times
    - Não depende de odds ainda
    - Status inicial sempre PENDING
    - Line padrão = 0.0
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO bet_recommendations
        (
            match_id,
            market,
            team_side,
            line,
            odd,
            probability,
            expected_value,
            status,
            created_at
        )
        VALUES (%s, %s, %s, %s, NULL, NULL, NULL, %s, %s)
        ON CONFLICT (match_id, market, team_side, line) DO NOTHING
    """, (
        fixture_id,
        market,
        side,
        0.0,
        'PENDING',
        datetime.utcfromtimestamp(match_timestamp)
    ))

    conn.commit()
    cursor.close()
    conn.close()
