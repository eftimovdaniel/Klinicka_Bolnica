import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

DEBUG_DB = os.getenv("DEBUG_DB", "").strip().lower() in ("1", "true", "yes")

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    mysql = None
    MySQLError = Exception


def get_connection():
    if mysql is None:
        raise RuntimeError(
            "mysql-connector-python не е инсталиран. Инсталирај: pip install mysql-connector-python"
        )

    host = os.getenv("DB_HOST", "localhost")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "Klinicka_Bolnica_Stip")
    port = int(os.getenv("DB_PORT", "3306"))

    if not all([host, user, database]):
        raise RuntimeError(
            "Недостасуваат податоци за базата. Во backend/.env постави: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME. "
            "Погледни backend/.env.example за пример."
        )

    kwargs = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
        "port": port,
        "autocommit": False,
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "use_pure": True,  # Избегнува грешка 'mysql_native_password cannot be loaded'
    }

    ssl_ca = os.getenv("DB_SSL_CA", "").strip()
    if ssl_ca:
        kwargs["ssl_ca"] = ssl_ca
        kwargs["ssl_verify_cert"] = True
    elif os.getenv("DB_SSL", "").strip().lower() in ("1", "true", "yes"):
        kwargs["ssl_disabled"] = False

    try:
        conn = mysql.connector.connect(**kwargs)
        if DEBUG_DB:
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM Doctors")
                n = cur.fetchone()[0]
                cur.close()
                print(f"[DEBUG_DB] Конекција OK. Број на лекари во Doctors: {n}")
            except Exception:
                pass
        return conn
    except MySQLError as e:
        if DEBUG_DB:
            print(f"[DEBUG_DB] Грешка при конекција: {e}")
        raise RuntimeError(f"Не може да се поврзе со базата: {e}") from e


if __name__ == "__main__":
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS total FROM Doctors")
    row = cur.fetchone()
    cur.close()
    conn.close()
    print(f"Вкупен број на лекари во базата: {row['total']}")
