import os
import psycopg2

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "apostas")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")


def get_metrics():
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT,
                            dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM recommendations WHERE status IN ('GREEN', 'RED')
    """)
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM recommendations WHERE status = 'GREEN'")
    greens = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM recommendations WHERE status = 'RED'")
    reds = cur.fetchone()[0]
    hit_rate = (greens / total * 100) if total > 0 else 0.0
    print("[METRICS]")
    print(f"Total apostas: {total}")
    print(f"Greens: {greens}")
    print(f"Reds: {reds}")
    print(f"Hit rate: {hit_rate:.2f}%")
    cur.close()
    conn.close()


if __name__ == "__main__":
    get_metrics()
