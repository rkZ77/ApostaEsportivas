import psycopg2
import os

# Parâmetros usados na fase pós-jogo (conforme debug)
DB_NAME = "apostas"
USER = "postgres"
PASSWORD = "postgres"
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
    print("Conexão pós-jogo bem-sucedida!")
    conn.close()
except Exception as e:
    print(f"Erro na conexão pós-jogo: {e}")
