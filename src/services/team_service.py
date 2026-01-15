
from database.db_connection import get_connection


def get_team_id_by_name(team_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM teams WHERE name = %s", (team_name,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def ensure_team_exists(team_id, team_name, league_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO teams (id, name, league_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        RETURNING id
        """,
        (team_id, team_name, league_id)
    )
    result = cursor.fetchone()
    if result:
        print(
            f"[INFO] Time inserido no banco: id={team_id}, nome={team_name}, liga={league_id}")
    else:
        print(
            f"[DEBUG] Time já existente no banco: id={team_id}, nome={team_name}, liga={league_id}")
    conn.commit()
    cursor.close()
    conn.close()
