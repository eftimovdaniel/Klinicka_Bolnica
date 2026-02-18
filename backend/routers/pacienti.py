from fastapi import APIRouter, HTTPException, Request
from datetime import datetime
from database import get_connection
from routers.utils import debug_log
from password_utils import hash_password, verify_password

router = APIRouter(
    prefix="/pacienti",
    tags=["pacienti"]) 

@router.post("/login")
async def login_pacienti(request: Request):
    conn = None
    try:
        debug_log("main.py:817",  "login_pacient: Request received", {"timestamp": datetime.now().isoformat()}, hypothesis_id="F")
        data = await request.json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        debug_log("main.py:823",  "login_pacient: Extracted email and password", {"email": email, "password_length": len(password)}, hypothesis_id="F")
        if not email:
            raise HTTPException(status_code=400, detail="Внесете ја вашата електронска пошта за да продолжите.")
        if not password:
            raise HTTPException(status_code=400, detail="Внесете ја вашата лозинка за да продолжите.")
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)

        db_cursor.execute("""
            SELECT patient_ID, name_patient AS ime, surname_patient AS prezime, email, phone_number AS telefon, password
            FROM patient
            WHERE LOWER(email) = %s
        """, (email,))
        patient = db_cursor.fetchone()

        if not patient:
            debug_log("main.py:843", "login_pacient: Patient not found", {"email": email}, hypothesis_id="F")
            raise HTTPException(status_code=401, detail="Внесена е невалидна електронска пошта или лозинка, проверете го вашиот внес.")
        
        if not patient.get("password") or not verify_password(password, patient["password"]):
            raise HTTPException(status_code=401, detail="Внесена е невалидна електронска пошта или лозинка, проверете го вашиот внес.")
        
        debug_log("main.py:855", "login_pacient: Success", {"pacient_id": patient["patient_ID"]}, hypothesis_id="F")
        
        return {
            "pacient": {
                "pacient_ID": patient["patient_ID"],
                "ime": patient.get("ime") or "",
                "prezime": patient.get("prezime") or "",
                "email": patient.get("email") or "",
                "telefon": patient.get("telefon") or ""
            }
        }
    except HTTPException as e:
                debug_log("main.py:864", "login_pacient: HTTPException", {"status_code": e.status_code, "detail": e.detail}, hypothesis_id="F")
                raise
    except Exception as e:
        debug_log("main.py:868", "login_pacient: Unexpected error", {"error": str(e)}, hypothesis_id="F")
        raise HTTPException(status_code=500, detail="Грешка при обработка на барањето.")
    finally:
         if conn and conn.is_connected():
            conn.close()

@router.post("/register")
async def register_pacienti(request: Request):
     
     conn = None
     try:
          data = await request.json()
          ime = (data.get("ime")or "").strip()
          prezime = (data.get("prezime")or "").strip()
          email = (data.get("email") or "").strip()
          password = data.get("password") or ""
          telefon = (data.get("telefon") or "").strip()
          # Нормализирај телефон: остави само цифри и +, макс. 20 знаци (за да не се прекине во колона phone_number)
          if telefon:
              telefon = "".join(c for c in telefon if c.isdigit() or c == "+")[:20]
          
          if not ime or not prezime:
               raise HTTPException(status_code=400, detail="За да продолжите, ве молиме внесете го името и презимето.")
          if not email:
               raise HTTPException(status_code=400, detail="За да продолжите, ве молиме внесете ја вашата електронска пошта.")
          if '@' not in email or '.' not in email.split('@')[1]:
               raise HTTPException(status_code=400, detail="Внесете валидна електронска пошта за да продолжите.")
          if not password or len(password) < 8:
               raise HTTPException(status_code=400, detail="За да продолжите, ве молиме внесете лозинка од минимум 8 карактери.")
          
          conn = get_connection()
          db_cursor = conn.cursor(dictionary=True)
          db_cursor.execute("SELECT patient_ID FROM patient WHERE LOWER(email) = %s", (email.lower(),))
          if db_cursor.fetchone():
                raise HTTPException(status_code=400, detail="За жал оваа електронска пошта е веќе користена. Обидете се со друга.")
          
          password_hash = hash_password(password)
          debug_log("main.py:988", "register_pacient: Attempting INSERT", {"ime": ime, "prezime": prezime, "email": email}, hypothesis_id="B")

          db_cursor.execute("""
               INSERT INTO patient (name_patient, surname_patient, email, phone_number, password)
               VALUES (%s, %s, %s, %s, %s)
          """, (ime, prezime, email.lower(), (telefon or None) if telefon else None, password_hash))
          conn.commit()
          pacient_id = db_cursor.lastrowid
          debug_log("main.py:996", "register_pacient: Success", {"pacient_id": pacient_id}, hypothesis_id="B")

          return {
               "message": "Направена е успешна регистрација. Можете да се најавите со вашата електронска пошта и лозинка.",
               "pacient_id": pacient_id
          }
     except HTTPException as e:
          debug_log("main.py:1005", "register_pacient: HTTPException",{"status_code": e.status_code, "detail": e.detail}, hypothesis_id="B")
          raise
     except Exception as e:
        err_msg = str(e)
        debug_log("main.py:1010", "register_pacient: Unexpected error", {"error": err_msg}, hypothesis_id="B")
        # Врати ја вистинската грешка за полесно отстранување (на пр. bcrypt не инсталиран или колона password преку кратка)
        raise HTTPException(status_code=500, detail=f"Грешка при регистрација: {err_msg}")
                        
     finally:
        if conn and conn.is_connected():
            conn.close( )