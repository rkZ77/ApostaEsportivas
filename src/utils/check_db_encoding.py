import os
import psycopg2

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "football_stats")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")


def check_encoding(table, columns):
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    print(f"Verificando tabela: {table}")
    for col in columns:
        print(f"  Coluna: {col}")
        cur.execute(f"SELECT id, {col} FROM {table}")
        for rec_id, value in cur.fetchall():
            if value is None:
                continue
            try:
                value.encode('utf-8')
            except UnicodeEncodeError:
                print(f"[ERRO] id={rec_id} coluna={col} valor={value}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    # Adicione outras tabelas/colunas conforme necessário
    check_encoding('recommendations', ['market', 'line'])
    check_encoding('teams', ['name'])
    check_encoding('matches', ['home_team', 'away_team'])
