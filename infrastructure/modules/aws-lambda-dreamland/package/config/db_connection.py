import os
import psycopg2
import psycopg2.extras


DB_CONFIG = {
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'host': os.getenv("DB_HOST"),
    'dbname': os.getenv("DB_NAME"),
    'options': '-c search_path=preprod_eb',
}


def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return conn, cursor
    except psycopg2.Error as err:
        print("DB Connection Error:", err)
        raise
