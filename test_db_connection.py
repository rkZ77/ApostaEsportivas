import psycopg2

DB_NAME = "football_stats"
USER = "postgres"
PASSWORD = "Pereira2310!"
HOST = "localhost"
PORT = 5432

try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        options='-c client_encoding=UTF8'
    )
    print("Conexão bem-sucedida!")
    conn.close()
except Exception as e:
    print(f"Erro na conexão: {e}")
