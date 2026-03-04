# Модул за управување со конекцијата до базата на податоци
# Според PDF: "Базата на податоци би се изработувала во MySQL"
#import mysql.connector  # MySQL конектор за Python - овозможува комуникација со MySQL базата на податоци
#from dotenv import load_dotenv  # За вчитување на environment променливи од .env фајл
#import os  # За пристап до environment променливи
#from pathlib import Path

# Вчитување на .env од папката каде што е database.py (backend/) – работи без разлика од каде се стартува апликацијата
#_env_path = Path(__file__).resolve().parent / ".env"
#load_dotenv(_env_path)

# Функција за воспоставување конекција со MySQL базата на податоци
# Враќа mysql.connector објект кој се користи за извршување SQL наредби
# Според PDF: "Податоците од базата на податоци посоодветно е да се чуваат на локален сервер"
#def get_connection():
 #   host = os.getenv("DB_HOST", "localhost")  # Дефолтно на localhost ако DB_HOST не е поставен
  #  user = os.getenv("DB_USER", "root")  # Дефолтно на root ако DB_USER не е поставен
   # password = os.getenv("DB_PASSWORD", "Danielleinad")
    #database = os.getenv("DB_NAME", "Klinicka_Bolnica_Stip")
    #if not all([host, user, database]):
     #   raise RuntimeError(
      #      "Недостасуваат податоци за базата. Во backend/.env постави: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME. "
       #     "Погледни backend/.env.example за пример."
      #  )
  #  return mysql.connector.connect(
   #     host=host,
    #    user=user,
     #   password=password or "",  # лозинка може да е празна за локален MySQL
      #  database=database,
    #)

# Модул за управување со конекцијата до базата на податоци
# Според PDF: "Базата на податоци би се изработувала во MySQL"

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
import os
from dotenv import load_dotenv
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

Base = declarative_base()
_engine = None

def get_engine():
    global _engine
    if _engine is not None:  # <-- ИСПРАВЕНО: беше `is None`, треба `is not None`
        return _engine
    
    host = os.getenv("DB_HOST", "localhost")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "Danielleinad")
    database = os.getenv("DB_NAME", "Klinicka_Bolnica_Stip")

    if not all([host, user, database]):
        raise RuntimeError(
            "Недостасуваат податоци за базата. Во backend/.env постави: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME. "
            "Погледни backend/.env.example за пример."
        )
    
    database_url = f"mysql+pymysql://{user}:{password}@{host}/{database}"
    _engine = create_engine(
       database_url,
       poolclass=QueuePool,
       pool_size=3, 
       max_overflow=5,
       pool_timeout=30,
       pool_recycle=240, 
       pool_pre_ping=True,  
       echo=False
    )
    return _engine

def get_connection():
    try: 
        engine = get_engine() 
        with engine.connect() as connection:
            result = connection.execute(text("SELECT COUNT(*) AS total FROM Doctors"))  
            count = result.fetchone()[0]
            print(f"Воспоставена е конекција со базата на податоци. Вкупниот број на пронајдени лекари е: {count}")
            return count
    except Exception as e:  
        print(f"Грешка при воспоставување на конекција со базата на податоци: {e}")
        raise

if __name__ == "__main__":  
    get_connection() 