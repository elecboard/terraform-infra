import os
import mysql.connector


DB_CONFIG = {
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'host': os.getenv("DB_HOST"),
    'database': os.getenv("DB_NAME"),
}


def get_db_connection():
    try:
        conn = mysql.connector.connect(
            **DB_CONFIG,
            charset='utf8mb4',
            use_unicode=True,
        )
        conn.autocommit = False
        cursor = conn.cursor(dictionary=True)
        return conn, cursor
    except mysql.connector.Error as err:
        print("DB Connection Error:", err)
        raise
