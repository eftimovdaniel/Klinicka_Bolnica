from fastapi import APIRouter, HTTPException, Query, Request
from datetime import datetime, timedelta
import secrets

from database import get_connection
from password_utils import hash_password, verify_password

router = APIRouter(
    prefix="/pacienti",
    tags=["pacienti"]) 


# end point za logiranje

@router.post("/login")
async def login_pacienti(request: Request):
    conn = None
    try:
        data = await request.json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

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
            raise HTTPException(status_code=401, detail="Внесена е невалидна електронска пошта или лозинка, проверете го вашиот внес.")
        
        if not patient.get("password") or not verify_password(password, patient["password"]):
            raise HTTPException(status_code=401, detail="Внесена е невалидна електронска пошта или лозинка, проверете го вашиот внес.")
        
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
                raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Грешка при обработка на барањето.")
    finally:
         if conn and conn.is_connected():
            conn.close()


@router.post("/forgot-password")
async def forgot_password_pacient(request: Request):
    """Барање за заборавена лозинка. Кодот се печати во терминалот на серверот."""
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Внесете валидна е-пошта")
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT patient_ID, name_patient, surname_patient FROM patient WHERE LOWER(email) = %s", (email,))
        patient = cur.fetchone()
        if not patient:
            return {"message": "Ако постои пациент со оваа е-пошта, ќе добиете код. За локална употреба погледнете го терминалот на серверот."}
        cur.execute("DELETE FROM password_reset_tokens WHERE email = %s AND user_type = 'pacient'", (email,))
        token = secrets.token_urlsafe(12)
        expires = datetime.utcnow() + timedelta(hours=1)
        cur.execute(
            "INSERT INTO password_reset_tokens (email, token, user_type, expires_at) VALUES (%s, %s, 'pacient', %s)",
            (email, token, expires),
        )
        conn.commit()
        msg = (
            f"\n{'='*60}\n"
            f"  ЗАБОРАВЕНА ЛОЗИНКА – ПАЦИЕНТ\n"
            f"  Е-пошта: {email}\n"
            f"  Код (внесете го во формата): {token}\n"
            f"  Валиден до: {expires.isoformat()}\n"
            f"{'='*60}\n"
        )
        print(msg)
        return {"message": "Ако постои пациент со оваа е-пошта, кодот е испечатен во терминалот каде што работи backend-от. Внесете го кодот и новата лозинка."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/reset-password")
async def reset_password_pacient(request: Request):
    """Промена на лозинка со код од заборавена лозинка (без најава)."""
    data = await request.json()
    email = (data.get("email") or "").strip().lower()
    token = (data.get("token") or "").strip().replace(" ", "").replace("\n", "").replace("\r", "")
    nova = (data.get("nova_lozinka") or "").strip()
    if not email or not token:
        raise HTTPException(status_code=400, detail="Внесете е-пошта и код")
    if not nova or len(nova) < 8:
        raise HTTPException(status_code=400, detail="Лозинката мора да има најмалку 8 карактери")
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, email FROM password_reset_tokens WHERE token = %s AND user_type = 'pacient' AND expires_at > UTC_TIMESTAMP()",
            (token,),
        )
        row = cur.fetchone()
        if not row or (row.get("email") or "").strip().lower() != email:
            raise HTTPException(status_code=400, detail="Неважечки или истечен код. Побарајте нов код.")
        cur.execute("SELECT patient_ID FROM patient WHERE LOWER(email) = %s", (email,))
        patient = cur.fetchone()
        if not patient:
            raise HTTPException(status_code=404, detail="Пациент не е пронајден")
        nova_hash = hash_password(nova)
        cur.execute("UPDATE patient SET password = %s WHERE patient_ID = %s", (nova_hash, patient["patient_ID"]))
        cur.execute("DELETE FROM password_reset_tokens WHERE token = %s", (token,))
        conn.commit()
        return {"message": "Лозинката е успешно променета. Можете да се најавите."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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

          db_cursor.execute("""
               INSERT INTO patient (name_patient, surname_patient, email, phone_number, password)
               VALUES (%s, %s, %s, %s, %s)
          """, (ime, prezime, email.lower(), (telefon or None) if telefon else None, password_hash))
          conn.commit()
          pacient_id = db_cursor.lastrowid

          return {
               "message": "Направена е успешна регистрација. Можете да се најавите со вашата електронска пошта и лозинка.",
               "pacient_id": pacient_id
          }
     except HTTPException as e:
          raise
     except Exception as e:
        err_msg = str(e)
        # Врати ја вистинската грешка за полесно отстранување (на пр. bcrypt не инсталиран или колона password преку кратка)
        raise HTTPException(status_code=500, detail=f"Грешка при регистрација: {err_msg}")
                        
     finally:
        if conn and conn.is_connected():
            conn.close( )


@router.get("/zavrseni-za-ocenka")
async def zavrseni_za_ocenka(pacient_ID: int = Query(..., description="ID на најавениот пациент")):
    """Завршени прегледи за е-поштата на пациентот (за приказ и оцена)."""
    conn = None
    try:
        conn = get_connection()
        posrednik = conn.cursor(dictionary=True)
        posrednik.execute(
            "SELECT email FROM patient WHERE patient_ID = %s",
            (pacient_ID,),
        )
        pac_row = posrednik.fetchone()
        if not pac_row:
            raise HTTPException(status_code=404, detail="Пациентот не е пронајден.")
        email_pac = (pac_row.get("email") or "").strip().lower()
        if not email_pac:
            return {"pregledi": []}

        posrednik.execute(
            """
            SELECT tp.termin_ID, tp.datum_pregled, tp.vreme_pregled, tp.ime_lekar,
                   (pf.feedback_ID IS NOT NULL) AS veke_ocenat, pf.ocena AS dadena_ocena, pf.komentar AS komentar
            FROM Termin_pregled tp
            LEFT JOIN Pregled_feedback pf ON pf.termin_ID = tp.termin_ID
            WHERE LOWER(TRIM(COALESCE(tp.email_pacient, ''))) = %s
              AND tp.status_pregled = 'завршен'
            ORDER BY tp.datum_pregled DESC, tp.vreme_pregled DESC
            """,
            (email_pac,),
        )
        rows = posrednik.fetchall() or []
        pregledi = []
        for r in rows:
            dp = r.get("datum_pregled")
            vp = r.get("vreme_pregled")
            pregledi.append(
                {
                    "termin_ID": r.get("termin_ID"),
                    "datum_pregled": dp.isoformat() if dp else None,
                    "vreme_pregled": str(vp)[:8] if vp else None,
                    "ime_lekar": (r.get("ime_lekar") or "").strip() or None,
                    "veke_ocenat": bool(r.get("veke_ocenat")),
                    "dadena_ocena": int(r["dadena_ocena"]) if r.get("dadena_ocena") is not None else None,
                    "komentar": (r.get("komentar") or "").strip() or None,
                }
            )
        return {"pregledi": pregledi}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Грешка при вчитување на прегледите.") from e
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/oceni-pregled")
async def oceni_pregled(request: Request):
    """Внесува или ажурира оцена за завршен преглед. Еден термин = еден ред (termin_ID уникатен)."""
    conn = None
    try:
        data = await request.json()
        termin_id = data.get("termin_id")
        pacient_id = data.get("pacient_ID") or data.get("pacient_id")
        ocena_raw = data.get("ocena")
        komentar = (data.get("komentar") or "").strip() or None

        if termin_id is None or pacient_id is None:
            raise HTTPException(
                status_code=400,
                detail="Потребни се termin_id и pacient_ID (идентификатор на најавениот пациент).",
            )
        try:
            termin_id = int(termin_id)
            pacient_id = int(pacient_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="termin_id и pacient_ID мора да бидат цели броеви.")

        try:
            ocena = int(ocena_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Оцената мора да биде цел број од 1 до 5.")
        if ocena < 1 or ocena > 5:
            raise HTTPException(status_code=400, detail="Оцената мора да биде од 1 до 5.")

        conn = get_connection()
        posrednik = conn.cursor(dictionary=True)

        posrednik.execute(
            "SELECT email FROM patient WHERE patient_ID = %s",
            (pacient_id,),
        )
        pac_row = posrednik.fetchone()
        if not pac_row:
            raise HTTPException(status_code=404, detail="Пациентот не е пронајден.")

        email_pac = (pac_row.get("email") or "").strip().lower()

        posrednik.execute(
            """
            SELECT termin_ID, status_pregled, email_pacient
            FROM Termin_pregled
            WHERE termin_ID = %s
            """,
            (termin_id,),
        )
        tp = posrednik.fetchone()
        if not tp:
            raise HTTPException(status_code=404, detail="Терминот не е пронајден.")

        em_termin = (tp.get("email_pacient") or "").strip().lower()
        if not em_termin or em_termin != email_pac:
            raise HTTPException(
                status_code=403,
                detail="Не можете да оцените овој термин (не одговара на вашиот профил).",
            )

        status = (tp.get("status_pregled") or "").strip()
        if status != "завршен":
            raise HTTPException(
                status_code=400,
                detail="Оцена може да се остави само за преглед со статус „завршен“.",
            )

        posrednik.execute(
            """
            INSERT INTO Pregled_feedback (termin_ID, ocena, komentar)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
              ocena = VALUES(ocena),
              komentar = VALUES(komentar),
              datum_na_ocena = CURRENT_TIMESTAMP
            """,
            (termin_id, ocena, komentar),
        )
        conn.commit()

        posrednik.execute(
            "SELECT feedback_ID, termin_ID, ocena, komentar, datum_na_ocena FROM Pregled_feedback WHERE termin_ID = %s",
            (termin_id,),
        )
        out = posrednik.fetchone()

        return {
            "message": "Оцената е зачувана.",
            "ocenka": {
                "feedback_ID": out.get("feedback_ID") if out else None,
                "termin_ID": termin_id,
                "ocena": ocena,
                "komentar": komentar,
                "datum_na_ocena": out.get("datum_na_ocena").isoformat() if out and out.get("datum_na_ocena") else None,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Грешка при зачувување на оцената.") from e
    finally:
        if conn and conn.is_connected():
            conn.close()