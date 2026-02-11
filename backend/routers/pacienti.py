from fastapi import APIRouter, HTTPException, Request
from datetime import datetime
import hashlib
from database import get_connection
from routers.utils import debug_log

router = APIRouter(prefix="/pacienti", tags=["pacienti"])

@router.post("/login")
async def login_pacient(request: Request):
    """
    Endpoint за најава на пациент со е-пошта и лозинка.
    Валидира дали комбинацијата е-пошта/лозинка е точна и враќа податоци за пациентот.
    """
    conn = None
    try:
        # #region agent log
        debug_log("main.py:817", "login_pacient: Request received", {"timestamp": datetime.now().isoformat()}, hypothesis_id="F")
        # #endregion
        data = await request.json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        
        # #region agent log
        debug_log("main.py:819", "login_pacient: Data parsed", {"email": email, "has_password": bool(password)}, hypothesis_id="F")
        # #endregion
        
        if not email:
            raise HTTPException(status_code=400, detail="Внесете е-пошта")
        if not password:
            raise HTTPException(status_code=400, detail="Внесете лозинка")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Хеширање на лозинката за споредба
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Проверка дали постои пациент со дадената е-пошта
        # ВАЖНО: Табелата се вика 'patient' (не 'Pacienti') според постоечката структура
        # Колоните се: patient_ID, name_patient, surname_patient, email, phone_number, password
        db_cursor.execute("""
            SELECT patient_ID, name_patient AS ime, surname_patient AS prezime, email, phone_number AS telefon, password
            FROM patient 
            WHERE LOWER(email) = %s
        """, (email,))
        
        pacient = db_cursor.fetchone()
        
        if not pacient:
            # #region agent log
            debug_log("main.py:843", "login_pacient: Patient not found", {"email": email}, hypothesis_id="F")
            # #endregion
            raise HTTPException(status_code=401, detail="Невалидна е-пошта или лозинка")
        
        # #region agent log
        debug_log("main.py:846", "login_pacient: Patient found", {"pacient_id": pacient.get("patient_ID"), "has_stored_password": bool(pacient.get("password"))}, hypothesis_id="F")
        # #endregion
        
        # Проверка на лозинката
        stored_password_hash = pacient.get("password") or ""
        
        if stored_password_hash:
            if password_hash != stored_password_hash:
                # #region agent log
                debug_log("main.py:851", "login_pacient: Password mismatch", {"password_match": False}, hypothesis_id="F")
                # #endregion
                raise HTTPException(status_code=401, detail="Невалидна е-пошта или лозинка")
        
        # #region agent log
        debug_log("main.py:855", "login_pacient: Success", {"pacient_id": pacient["patient_ID"]}, hypothesis_id="F")
        # #endregion
        
        # Враќаме податоци за пациентот (без лозинка)
        # ВАЖНО: Користиме точните имиња на колони од базата
        return {
            "pacient": {
                "pacient_ID": pacient["patient_ID"],  # patient_ID од базата се мапира на pacient_ID за frontend
                "ime": pacient.get("ime") or "",  # name_patient од базата се мапира на ime
                "prezime": pacient.get("prezime") or "",  # surname_patient од базата се мапира на prezime
                "email": pacient.get("email") or "",
                "telefon": pacient.get("telefon") or "",  # phone_number од базата се мапира на telefon
            }
        }
    except HTTPException as e:
        # #region agent log
        debug_log("main.py:864", "login_pacient: HTTPException", {"status_code": e.status_code, "detail": e.detail}, hypothesis_id="F")
        # #endregion
        raise
    except Exception as e:
        # #region agent log
        debug_log("main.py:867", "login_pacient: Exception", {"error_type": type(e).__name__, "error_message": str(e)}, hypothesis_id="F")
        # #endregion
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/register")
async def register_pacient(request: Request):
    """
    Endpoint за регистрација на нов пациент.
    Креира нов профил за пациент со е-пошта и лозинка.
    """
    conn = None
    try:
        # #region agent log
        # debug_log("main.py:959", "register_pacient: Request received", {"timestamp": datetime.now().isoformat()}, hypothesis_id="B")
        # #endregion
        data = await request.json()
        
        # #region agent log
        # debug_log("main.py:963", "register_pacient: Data parsed", {"ime": data.get("ime"), "prezime": data.get("prezime"), "email": data.get("email"), "telefon": data.get("telefon"), "has_password": bool(data.get("password"))}, hypothesis_id="B")
        # #endregion
        
        ime = (data.get("ime") or "").strip()
        prezime = (data.get("prezime") or "").strip()
        email = (data.get("email") or "").strip().lower()
        telefon = (data.get("telefon") or "").strip()
        password = data.get("password") or ""
        
        # validacija na podatoci od frontend
        if not ime or not prezime:
            raise HTTPException(status_code=400, detail="Внесете име и презиме")
        if not email:
            raise HTTPException(status_code=400, detail="Внесете е-пошта")
        # mail proverka, dali ima @ i . posle @
        if '@' not in email or '.' not in email.split('@')[1]:
            raise HTTPException(status_code=400, detail="Внесете валидна е-пошта")
        # proverka dali e lozinkata e barem 6 karakteri, ne e dozvoleno da e pod 6
        if not password or len(password) < 6:
            raise HTTPException(status_code=400, detail="Лозинката мора да има најмалку 6 карактери")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали веќе постои пациент со истата е-пошта
        # ВАЖНО: Табелата се вика 'patient' (не 'Pacienti')
        db_cursor.execute("SELECT patient_ID FROM patient WHERE LOWER(email) = %s", (email,))
        if db_cursor.fetchone():
            raise HTTPException(status_code=400, detail="Пациент со оваа е-пошта веќе постои")
        
        # Хеширање на лозинката
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # #region agent log
        debug_log("main.py:988", "register_pacient: Attempting INSERT", {"ime": ime, "prezime": prezime, "email": email, "telefon": telefon}, hypothesis_id="B")
        # #endregion
        
        # Креирање на нов пациент
        # ВАЖНО: Користиме точните имиња на колони: name_patient, surname_patient, phone_number
        db_cursor.execute("""
            INSERT INTO patient (name_patient, surname_patient, email, phone_number, password)
            VALUES (%s, %s, %s, %s, %s)
        """, (ime, prezime, email, telefon, password_hash))
        
        conn.commit()
        pacient_id = db_cursor.lastrowid
        
        # #region agent log
        debug_log("main.py:996", "register_pacient: Success", {"pacient_id": pacient_id}, hypothesis_id="B")
        # #endregion
        
        return {
            "message": "Успешно се регистриравте!",
            "pacient_ID": pacient_id
        }
    except HTTPException as e:
        # #region agent log
        debug_log("main.py:1001", "register_pacient: HTTPException", {"status_code": e.status_code, "detail": e.detail}, hypothesis_id="B")
        # #endregion
        raise
    except Exception as e:
        # #region agent log
        debug_log("main.py:1004", "register_pacient: Exception", {"error_type": type(e).__name__, "error_message": str(e)}, hypothesis_id="B")
        # #endregion
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


