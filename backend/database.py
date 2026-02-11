# Модул за управување со конекцијата до базата на податоци
# Според PDF: "Базата на податоци би се изработувала во MySQL"
import mysql.connector  # MySQL конектор за Python - овозможува комуникација со MySQL базата на податоци
from dotenv import load_dotenv  # За вчитување на environment променливи од .env фајл
import os  # За пристап до environment променливи

# Вчитување на environment променливи од .env фајл
# .env фајлот содржи чувствителни податоци како што се: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
# Ова е безбеден начин за чување на credentials без да се ставаат директно во кодот
load_dotenv()

# Функција за воспоставување конекција со MySQL базата на податоци
# Враќа mysql.connector објект кој се користи за извршување SQL наредби
# Според PDF: "Податоците од базата на податоци посоодветно е да се чуваат на локален сервер"
def get_connection():
    return mysql.connector.connect(
        host = os.getenv("DB_HOST"),  # Хост адреса на MySQL серверот (напр. "localhost" или IP адреса)
        user = os.getenv("DB_USER"),  # Корисничко име за пристап до базата
        password = os.getenv("DB_PASSWORD"),  # Лозинка за пристап до базата
        database = os.getenv("DB_NAME")  # Име на базата на податоци (напр. "klinicka_bolnica")
    )