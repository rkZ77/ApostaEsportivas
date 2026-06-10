import psycopg2
from utils.db_utils import get_connection

TRANSLATIONS = {
    # GOLS
    "Goals Over/Under": ("Gols - Over/Under", "goals"),
    "Total Goals": ("Gols - Total", "goals"),

    # BTTS
    "Both Teams To Score": ("BTTS", "btts"),

    # ESCANTEIOS
    "Total Corners": ("Escanteios Total", "corners"),
    "Match Corners": ("Escanteios Total", "corners"),
    "Home Corners": ("Escanteios Casa", "corners"),
    "Away Corners": ("Escanteios Fora", "corners"),

    # CARTÕES
    "Cards": ("Cartões Total", "cards"),
    "Home Cards": ("Cartões Casa", "cards"),
    "Away Cards": ("Cartões Fora", "cards"),

    # HANDICAP (não usado mas traduzimos)
    "Asian Handicap": ("Handicap Asiático", "handicap"),
}


def translate_market_name(name):
    for k, v in TRANSLATIONS.items():
        if k.lower() in name.lower():
            return v
    return (None, None)


def update_tables():
    conn = get_connection()
    cur = conn.cursor()

    # === UPDATE odds_markets ===
    cur.execute("SELECT id, market_name FROM odds_markets;")
    rows = cur.fetchall()

    for row in rows:
        row_id, market_name = row
        pt, mtype = translate_market_name(market_name)

        if pt:
            cur.execute("""
                UPDATE odds_markets
                SET market_portugues = %s,
                    market_type = %s
                WHERE id = %s;
            """, (pt, mtype, row_id))

    # === UPDATE odds_values ===
    cur.execute("SELECT id, market_name FROM odds_values;")
    rows = cur.fetchall()

    for row in rows:
        row_id, market_name = row
        pt, mtype = translate_market_name(market_name)

        if pt:
            cur.execute("""
                UPDATE odds_values
                SET market_portugues = %s,
                    market_type = %s
                WHERE id = %s;
            """, (pt, mtype, row_id))

    conn.commit()
    cur.close()
    conn.close()

    print("Tradução concluída com sucesso!")


if __name__ == "__main__":
    update_tables()
