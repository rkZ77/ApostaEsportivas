
import psycopg2
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PGCLIENTENCODING"] = "utf-8"

DB_NAME = "football_stats"
USER = "postgres"
PASSWORD = "Pereira2310!"
HOST = "localhost"
PORT = 5432


def get_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        options='-c client_encoding=UTF8'
    )
