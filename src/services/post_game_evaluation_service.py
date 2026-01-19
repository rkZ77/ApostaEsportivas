import os
import psycopg2
from datetime import datetime

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "football_stats")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "Pereira2310!")


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )


# =====================================================
# 1) Buscar recomendações pendentes
# =====================================================
def get_pending_recommendations():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, match_id, market, side, line, odd
        FROM bet_recommendations
        WHERE status = 'PENDING'
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


# =====================================================
# 2) Carregar estatísticas finais do jogo
# =====================================================
def get_match_final_stats(match_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            fixture_id,
            league_id,
            season,
            home_team_id,
            away_team_id,
            home_goals,
            away_goals,
            total_goals,
            home_corners,
            away_corners,
            total_corners,
            home_yellow_cards,
            away_yellow_cards,
            total_yellow_cards,
            home_red_cards,
            away_red_cards,
            total_red_cards,
            status
        FROM matches
        WHERE id = %s
    """, (match_id,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return None

    return {
        "fixture_id": row[0],
        "league_id": row[1],
        "season": row[2],
        "home_team_id": row[3],
        "away_team_id": row[4],
        "home_goals": row[5],
        "away_goals": row[6],
        "total_goals": row[7],
        "home_corners": row[8],
        "away_corners": row[9],
        "total_corners": row[10],
        "home_yellow": row[11],
        "away_yellow": row[12],
        "total_yellow": row[13],
        "home_red": row[14],
        "away_red": row[15],
        "total_red": row[16],
        "status": row[17],
    }


# =====================================================
# 3) Avaliação individual
# =====================================================
def evaluate_single_bet(rec, final_stats):
    market = rec["market"]
    side = rec["side"]
    line = rec["line"]

    # -----------------------------
    # EXEMPLOS SIMPLES DE REGRAS:
    # -----------------------------
    if market == "totals":
        return "GREEN" if final_stats["total_goals"] > line else "RED"

    elif market == "corners_totals":
        return "GREEN" if final_stats["total_corners"] > line else "RED"

    elif market == "cards_totals":
        total_cards = final_stats["total_yellow"] + final_stats["total_red"]
        return "GREEN" if total_cards > line else "RED"

    return "RED"


# =====================================================
# 4) Atualizar recomendação
# =====================================================
def update_recommendation_status(rec_id, status):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE bet_recommendations
        SET status = %s
        WHERE id = %s
    """, (status, rec_id))

    conn.commit()
    cur.close()
    conn.close()


# =====================================================
# 5) PROCESSO PRINCIPAL
# =====================================================
def evaluate_recommendations():
    print("[POST-GAME] Buscando recomendações pendentes...")
    pending = get_pending_recommendations()

    if not pending:
        print("[POST-GAME] Nenhuma recomendação pendente.")
        return

    print(f"[POST-GAME] {len(pending)} recomendações pendentes.")

    for row in pending:
        rec_id, match_id, market, side, line, odd = row

        rec = {
            "id": rec_id,
            "match_id": match_id,
            "market": market,
            "side": side,
            "line": float(line or 0),
            "odd": float(odd)
        }

        final_stats = get_match_final_stats(match_id)
        if not final_stats or final_stats["status"] != "FT":
            print(f"[POST-GAME] Match {match_id} ainda não finalizado.")
            continue

        result = evaluate_single_bet(rec, final_stats)

        update_recommendation_status(rec_id, result)

        print(f"[POST-GAME] Aposta {rec_id} → {result}")


# Execução direta (debug)
if __name__ == "__main__":
    evaluate_recommendations()
