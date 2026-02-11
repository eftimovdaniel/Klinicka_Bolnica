from fastapi import APIRouter, HTTPException, Request
from typing import Optional, List
from datetime import datetime, date, time
from database import get_connection

router = APIRouter(prefix="/admin", tags=["admin"])

# Име на директорот на болницата - единствен корисник со административни права
# Административниот панел е достапен само за Владко Захариев (директор на болницата)
# Забелешка: ADMIN_DOCTOR_NAME е дефинирана но не се користи директно во кодот,
# бидејќи проверката се прави преку check_admin_access функцијата

def check_admin_access(doctor_id: int) -> bool:
    """
    Проверува дали лекарот со даденото ID е директорот на болницата.
    Враќа True само ако лекарот е Владко Захариев (или варијации на името).
    """
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        db_cursor.execute("SELECT name, surname FROM Doctors WHERE doctor_ID = %s", (doctor_id,))
        doctor = db_cursor.fetchone()
        
        if not doctor:
            return False
        
        doctor_name = f"{doctor['name']} {doctor['surname']}".strip()
        
        # Проверка за точно совпаѓање или варијации на името
        # Прво проверуваме точното име од базата "Владко Захариев"
        # Потоа и други можни варијации (за случај на транслитерација или мали грешки)
        admin_names = [
            "Владко Захариев",  # Точниот формат во базата
            "Влатко Захариев",  # Варијација со "Влатко"
            "Владко Захаријев",  # Варијација со "Захаријев"
            "Влатко Захаријев"   # Комбинација на двете варијации
        ]
        
        return doctor_name in admin_names
    except Exception:
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()


# ============================================================================
# DEZURSTVA ENDPOINTS
# ============================================================================

@router.get("/dezurstva")
def get_all_dezurstva(doctor_id: Optional[int] = None, datum: Optional[str] = None, oddel: Optional[str] = None, admin_doctor_id: Optional[int] = None):
    """
    Враќа листа на сите дежурства.
    Може да се филтрира по doctor_id, datum, или oddel.
    Задолжително треба да се проследи admin_doctor_id за проверка на пристап.
    """
    # Проверка на административен пристап
    if admin_doctor_id is None:
        raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
    
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
    
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        query = """
            SELECT d.dezurstvo_ID, d.doctor_ID, d.datum, d.oddel, d.vreme_od, d.vreme_do, d.napomena,
                   doc.name, doc.surname, doc.specialty AS specijalnost
            FROM Dezurstva d
            JOIN Doctors doc ON d.doctor_ID = doc.doctor_ID
            WHERE 1=1
        """
        params = []
        
        if doctor_id:
            query += " AND d.doctor_ID = %s"
            params.append(doctor_id)
        
        if datum:
            query += " AND d.datum = %s"
            params.append(datum)
        
        if oddel:
            query += " AND d.oddel = %s"
            params.append(oddel)
        
        query += " ORDER BY d.datum ASC, d.vreme_od ASC"
        
        db_cursor.execute(query, params)
        rows = db_cursor.fetchall()
        
        result = []
        for row in rows:
            result.append({
                "dezurstvo_ID": row["dezurstvo_ID"],
                "doctor_ID": row["doctor_ID"],
                "doctor_name": f"{row['name']} {row['surname']}",
                "doctor_specialty": row["specijalnost"],
                "datum": row["datum"].strftime("%Y-%m-%d") if row["datum"] else None,
                "oddel": row["oddel"],
                "vreme_od": str(row["vreme_od"]) if row["vreme_od"] else None,
                "vreme_do": str(row["vreme_do"]) if row["vreme_do"] else None,
                "napomena": row["napomena"]
            })
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/dezurstva")
async def create_dezurstvo(request: Request):
    """
    Креира ново дежурство.
    Задолжително треба да се проследи admin_doctor_id во body за проверка на пристап.
    """
    conn = None
    try:
        data = await request.json()
        
        # Проверка на административен пристап
        admin_doctor_id = data.get("admin_doctor_id")
        if admin_doctor_id is None:
            raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
        
        if not check_admin_access(admin_doctor_id):
            raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
        
        doctor_id = data.get("doctor_ID")
        datum_str = data.get("datum")
        oddel = (data.get("oddel") or "").strip()
        vreme_od_str = data.get("vreme_od", "08:00")
        vreme_do_str = data.get("vreme_do", "20:00")
        napomena = (data.get("napomena") or "").strip()
        
        if not doctor_id:
            raise HTTPException(status_code=400, detail="Внесете ID на лекар")
        if not datum_str:
            raise HTTPException(status_code=400, detail="Внесете датум")
        if not oddel:
            raise HTTPException(status_code=400, detail="Внесете оддел")
        
        # Парсирање на датум
        try:
            datum = datetime.strptime(datum_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неважечки формат на датум. Користете YYYY-MM-DD")
        
        # Парсирање на времиња
        try:
            vreme_od = datetime.strptime(vreme_od_str, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неважечки формат на време од. Користете HH:MM")
        
        try:
            vreme_do = datetime.strptime(vreme_do_str, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неважечки формат на време до. Користете HH:MM")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали лекарот постои
        db_cursor.execute("SELECT doctor_ID FROM Doctors WHERE doctor_ID = %s", (doctor_id,))
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")
        
        # Проверка дали веќе постои дежурство за истиот лекар, датум и време
        db_cursor.execute("""
            SELECT dezurstvo_ID FROM Dezurstva
            WHERE doctor_ID = %s AND datum = %s
            AND (
                (vreme_od <= %s AND vreme_do >= %s) OR
                (vreme_od <= %s AND vreme_do >= %s) OR
                (vreme_od >= %s AND vreme_do <= %s)
            )
        """, (doctor_id, datum, vreme_od, vreme_od, vreme_do, vreme_do, vreme_od, vreme_do))
        
        if db_cursor.fetchone():
            raise HTTPException(status_code=400, detail="Лекарот веќе има дежурство за овој датум и време")
        
        # Внесување на дежурството
        db_cursor.execute("""
            INSERT INTO Dezurstva (doctor_ID, datum, oddel, vreme_od, vreme_do, napomena)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (doctor_id, datum, oddel, vreme_od, vreme_do, napomena if napomena else None))
        
        conn.commit()
        dezurstvo_id = db_cursor.lastrowid
        
        return {
            "message": "Дежурството е успешно креирано",
            "dezurstvo_ID": dezurstvo_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.put("/dezurstva/{dezurstvo_id}")
async def update_dezurstvo(dezurstvo_id: int, request: Request):
    """
    Ажурира постоечко дежурство.
    Задолжително треба да се проследи admin_doctor_id во body за проверка на пристап.
    """
    conn = None
    try:
        data = await request.json()
        
        # Проверка на административен пристап
        admin_doctor_id = data.get("admin_doctor_id")
        if admin_doctor_id is None:
            raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
        
        if not check_admin_access(admin_doctor_id):
            raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
        
        doctor_id = data.get("doctor_ID")
        datum_str = data.get("datum")
        oddel = (data.get("oddel") or "").strip()
        vreme_od_str = data.get("vreme_od", "08:00")
        vreme_do_str = data.get("vreme_do", "20:00")
        napomena = (data.get("napomena") or "").strip()
        
        if not doctor_id:
            raise HTTPException(status_code=400, detail="Внесете ID на лекар")
        if not datum_str:
            raise HTTPException(status_code=400, detail="Внесете датум")
        if not oddel:
            raise HTTPException(status_code=400, detail="Внесете оддел")
        
        # Парсирање на датум и времиња
        try:
            datum = datetime.strptime(datum_str, "%Y-%m-%d").date()
            vreme_od = datetime.strptime(vreme_od_str, "%H:%M").time()
            vreme_do = datetime.strptime(vreme_do_str, "%H:%M").time()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Неважечки формат на датум или време: {str(e)}")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали дежурството постои
        db_cursor.execute("SELECT dezurstvo_ID FROM Dezurstva WHERE dezurstvo_ID = %s", (dezurstvo_id,))
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Дежурство не е пронајдено")
        
        # Проверка за конфликт со други дежурства (освен текущото)
        db_cursor.execute("""
            SELECT dezurstvo_ID FROM Dezurstva
            WHERE doctor_ID = %s AND datum = %s AND dezurstvo_ID != %s
            AND (
                (vreme_od <= %s AND vreme_do >= %s) OR
                (vreme_od <= %s AND vreme_do >= %s) OR
                (vreme_od >= %s AND vreme_do <= %s)
            )
        """, (doctor_id, datum, dezurstvo_id, vreme_od, vreme_od, vreme_do, vreme_do, vreme_od, vreme_do))
        
        if db_cursor.fetchone():
            raise HTTPException(status_code=400, detail="Лекарот веќе има дежурство за овој датум и време")
        
        # Ажурирање на дежурството
        db_cursor.execute("""
            UPDATE Dezurstva
            SET doctor_ID = %s, datum = %s, oddel = %s, vreme_od = %s, vreme_do = %s, napomena = %s
            WHERE dezurstvo_ID = %s
        """, (doctor_id, datum, oddel, vreme_od, vreme_do, napomena if napomena else None, dezurstvo_id))
        
        conn.commit()
        
        return {"message": "Дежурството е успешно ажурирано"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.delete("/dezurstva/{dezurstvo_id}")
def delete_dezurstvo(dezurstvo_id: int, admin_doctor_id: Optional[int] = None):
    """
    Брише дежурство.
    Задолжително треба да се проследи admin_doctor_id како query параметар за проверка на пристап.
    """
    # Проверка на административен пристап
    if admin_doctor_id is None:
        raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
    
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
    
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали дежурството постои
        db_cursor.execute("SELECT dezurstvo_ID FROM Dezurstva WHERE dezurstvo_ID = %s", (dezurstvo_id,))
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Дежурство не е пронајдено")
        
        # Бришење
        db_cursor.execute("DELETE FROM Dezurstva WHERE dezurstvo_ID = %s", (dezurstvo_id,))
        conn.commit()
        
        return {"message": "Дежурството е успешно избришано"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


# ============================================================================
# OGLASI ENDPOINTS (дополнителни CRUD операции)
# ============================================================================

@router.post("/oglasi")
async def create_oglas_admin(request: Request):
    """
    Креира нов оглас за работа (за администратор).
    Задолжително треба да се проследи admin_doctor_id во body за проверка на пристап.
    """
    conn = None
    try:
        data = await request.json()
        
        # Проверка на административен пристап
        admin_doctor_id = data.get("admin_doctor_id")
        if admin_doctor_id is None:
            raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
        
        if not check_admin_access(admin_doctor_id):
            raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
        
        pozicija = (data.get("pozicija") or "").strip()
        oddel = (data.get("oddel") or "").strip()
        datum_na_objava = data.get("datum_na_objava")
        datum_na_prijavuvanje = data.get("datum_na_prijavuvanje")
        status_oglas = (data.get("status_oglas") or "").strip()
        
        if not pozicija:
            raise HTTPException(status_code=400, detail="Внесете позиција")
        if not oddel:
            raise HTTPException(status_code=400, detail="Внесете оддел")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Парсирање на датуми
        if isinstance(datum_na_objava, str):
            try:
                datum_na_objava = datetime.strptime(datum_na_objava, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Неважечки формат на датум на објава")
        
        if isinstance(datum_na_prijavuvanje, str):
            try:
                datum_na_prijavuvanje = datetime.strptime(datum_na_prijavuvanje, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Неважечки формат на датум на пријавување")
        
        # Внесување на огласот (без валидација за позицијата - администраторот може да креира каква било позиција)
        db_cursor.execute("""
            INSERT INTO Vrabotuvanje (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas)
            VALUES (%s, %s, %s, %s, %s)
        """, (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, 
              status_oglas if status_oglas else None))
        
        conn.commit()
        oglas_id = db_cursor.lastrowid
        
        return {
            "message": "Огласот е успешно креиран",
            "id_oglas": oglas_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.get("/oglasi")
def get_all_oglasi(admin_doctor_id: Optional[int] = None):
    """
    Враќа листа на сите огласи за работа.
    Задолжително треба да се проследи admin_doctor_id како query параметар за проверка на пристап.
    """
    # Проверка на административен пристап
    if admin_doctor_id is None:
        raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
    
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
    
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        db_cursor.execute("""
            SELECT id_oglas, pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas
            FROM Vrabotuvanje
            ORDER BY datum_na_objava DESC
        """)
        
        rows = db_cursor.fetchall()
        result = []
        
        for row in rows:
            result.append({
                "id_oglas": row["id_oglas"],
                "pozicija": row["pozicija"],
                "oddel": row["oddel"],
                "datum_na_objava": row["datum_na_objava"].strftime("%Y-%m-%d") if row["datum_na_objava"] else None,
                "datum_na_prijavuvanje": row["datum_na_prijavuvanje"].strftime("%Y-%m-%d") if row["datum_na_prijavuvanje"] else None,
                "status_oglas": row["status_oglas"]
            })
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.put("/oglasi/{oglas_id}")
async def update_oglas(oglas_id: int, request: Request):
    """
    Ажурира постоечки оглас за работа.
    Задолжително треба да се проследи admin_doctor_id во body за проверка на пристап.
    """
    conn = None
    try:
        data = await request.json()
        
        # Проверка на административен пристап
        admin_doctor_id = data.get("admin_doctor_id")
        if admin_doctor_id is None:
            raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
        
        if not check_admin_access(admin_doctor_id):
            raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
        
        pozicija = (data.get("pozicija") or "").strip()
        oddel = (data.get("oddel") or "").strip()
        datum_na_objava = data.get("datum_na_objava")
        datum_na_prijavuvanje = data.get("datum_na_prijavuvanje")
        status_oglas = (data.get("status_oglas") or "").strip()
        
        if not pozicija:
            raise HTTPException(status_code=400, detail="Внесете позиција")
        if not oddel:
            raise HTTPException(status_code=400, detail="Внесете оддел")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали огласот постои
        db_cursor.execute("SELECT id_oglas FROM Vrabotuvanje WHERE id_oglas = %s", (oglas_id,))
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Оглас не е пронајден")
        
        # Парсирање на датуми
        if isinstance(datum_na_objava, str):
            try:
                datum_na_objava = datetime.strptime(datum_na_objava, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Неважечки формат на датум на објава")
        
        if isinstance(datum_na_prijavuvanje, str):
            try:
                datum_na_prijavuvanje = datetime.strptime(datum_na_prijavuvanje, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Неважечки формат на датум на пријавување")
        
        # Ажурирање
        db_cursor.execute("""
            UPDATE Vrabotuvanje
            SET pozicija = %s, oddel = %s, datum_na_objava = %s, 
                datum_na_prijavuvanje = %s, status_oglas = %s
            WHERE id_oglas = %s
        """, (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, 
              status_oglas if status_oglas else None, oglas_id))
        
        conn.commit()
        
        return {"message": "Огласот е успешно ажуриран"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.delete("/oglasi/{oglas_id}")
def delete_oglas(oglas_id: int, admin_doctor_id: Optional[int] = None):
    """
    Брише оглас за работа.
    Задолжително треба да се проследи admin_doctor_id како query параметар за проверка на пристап.
    """
    # Проверка на административен пристап
    if admin_doctor_id is None:
        raise HTTPException(status_code=403, detail="Недостасува ID на администратор")
    
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап до административниот панел")
    
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали огласот постои
        db_cursor.execute("SELECT id_oglas FROM Vrabotuvanje WHERE id_oglas = %s", (oglas_id,))
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Оглас не е пронајден")
        
        # Бришење
        db_cursor.execute("DELETE FROM Vrabotuvanje WHERE id_oglas = %s", (oglas_id,))
        conn.commit()
        
        return {"message": "Огласот е успешно избришан"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()
