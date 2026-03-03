# Модул за управување со конекцијата до базата на податоци
# Според PDF: "Базата на податоци би се изработувала во MySQL"
import mysql.connector  # MySQL конектор за Python - овозможува комуникација со MySQL базата на податоци
from dotenv import load_dotenv  # За вчитување на environment променливи од .env фајл
import os  # За пристап до environment променливи
from pathlib import Path

# Вчитување на .env од папката каде што е database.py (backend/) – работи без разлика од каде се стартува апликацијата
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

# Функција за воспоставување конекција со MySQL базата на податоци
# Враќа mysql.connector објект кој се користи за извршување SQL наредби
# Според PDF: "Податоците од базата на податоци посоодветно е да се чуваат на локален сервер"
def get_connection():
    host = os.getenv("DB_HOST", "localhost")  # Дефолтно на localhost ако DB_HOST не е поставен
    user = os.getenv("DB_USER", "root")  # Дефолтно на root ако DB_USER не е поставен
    password = os.getenv("DB_PASSWORD", "Danielleinad")
    database = os.getenv("DB_NAME", "Klinicka_Bolnica_Stip")
    if not all([host, user, database]):
        raise RuntimeError(
            "Недостасуваат податоци за базата. Во backend/.env постави: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME. "
            "Погледни backend/.env.example за пример."
        )
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password or "",  # лозинка може да е празна за локален MySQL
        database=database,
    )