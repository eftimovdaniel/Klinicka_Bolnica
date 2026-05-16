from fastapi import APIRouter, HTTPException, Request
from datetime import datetime
from database import get_connection

router = APIRouter(prefix="/aparati", tags=["aparati"])

@router.get("")
def get_aparati():
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Земање на сите активни апарати од табелата Aparati
        # Претпоставка: табелата има колони aparat_id, ime, opis, kod, aktiven
        db_cursor.execute("""
            SELECT aparat_id, ime, opis, kod
            FROM Aparati
            WHERE aktiven = TRUE
            ORDER BY ime
        """)
        aparati = db_cursor.fetchall()
        
        return aparati
    except Exception as e:
        # Ако табелата не постои или има грешка, врати празна листа
        # Ова овозможува постепено додавање на апарати во базата на податоци
        return []
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.get("/termini/dostapnost")
def check_aparat_dostapnost(
    aparat: str,
    datum: str,
    vreme: str,
    lekar_id: int | None = None,
    pacient_ime: str | None = None,
    pacient_prezime: str | None = None,
):
    """
    Endpoint за проверка на достапност на апарат за даден датум и време.
    Враќа дали апаратот е достапен или не.
    Ако е даден lekar_id, проверува и дали лекарот има закажан преглед (со било кој пациент) за тоа време.
    Ако се дадени pacient_ime и pacient_prezime, проверува и дали пациентот има закажан преглед за тоа време.
    """
    conn = None
    try:
        if not aparat or not datum or not vreme:
            raise HTTPException(status_code=400, detail="Внесете ги сите параметри")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Парсирање на датум и време
        try:
            dt = datetime.strptime(f"{datum} {vreme}", "%Y-%m-%d %H:%M")
            datum_str = dt.strftime("%Y-%m-%d")
            vreme_str = dt.strftime("%H:%M:%S")
        except ValueError:
            raise HTTPException(status_code=400, detail="Неважечки формат на датум и време")
        
        # Проверка дали има закажан термин за истиот апарат, датум и време 
        db_cursor.execute("""
            SELECT COUNT(*) as count
            FROM Aparati_termini
            WHERE aparat = %s 
            AND datum_pregled = %s 
            AND vreme_pregled = %s
            AND status != 'откажан'
        """, (aparat, datum_str, vreme_str))
        
        result = db_cursor.fetchone()
        count = result['count'] if result else 0
        
        poraki = []
        dostapen = count == 0
        
        if count > 0:
            poraki.append("Апаратот е зафатен за избраниот датум и време")
        
        # Проверка дали пациентот има закажан преглед за тоа време
        if pacient_ime and pacient_prezime:
            pacient_ime_prezime = f"{pacient_ime} {pacient_prezime}".strip()
            db_cursor.execute("""
                SELECT COUNT(*) as count
                FROM Termin_pregled
                WHERE ime_pacient = %s 
                AND DATE(datum_pregled) = %s 
                AND TIME(vreme_pregled) = %s
                AND status_pregled = 'закажан'
            """, (pacient_ime_prezime, datum_str, vreme_str))
            
            pacient_pregled_result = db_cursor.fetchone()
            pacient_pregled_count = pacient_pregled_result['count'] if pacient_pregled_result else 0
            
            if pacient_pregled_count > 0:
                dostapen = False
                poraki.append("Пациентот има закажан преглед за избраниот датум и време")
        
        # Проверка дали лекарот има закажан преглед (со било кој пациент) за тоа конкретно време 
        if lekar_id:
            db_cursor.execute("""
                SELECT COUNT(*) as count
                FROM Termin_pregled
                WHERE doctor_ID = %s 
                AND DATE(datum_pregled) = %s 
                AND TIME(vreme_pregled) = %s
                AND status_pregled = 'закажан'
            """, (lekar_id, datum_str, vreme_str))
            
            pregled_result = db_cursor.fetchone()
            pregled_count = pregled_result['count'] if pregled_result else 0
            
            if pregled_count > 0:
                dostapen = False
                poraki.append("Лекарот има закажан преглед за избраниот датум и време")
        
        poraka = "; ".join(poraki) if poraki else "Апаратот е достапен"
        
        return {
            "dostapen": dostapen,
            "poraka": poraka
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/termini")
async def create_aparat_termin(request: Request):
    """
    Endpoint за закажување термин на медицински апарат.
    Закажува термин за користење на медицински апарат (рендген, CT, MRI, ултразвук).
    """
    conn = None
    try:
        data = await request.json()
        lekar_id = data.get("lekar_id")
        lekar_ime = (data.get("lekar_ime") or "").strip()
        pacient_ime = (data.get("pacient_ime") or "").strip()
        pacient_prezime = (data.get("pacient_prezime") or "").strip()
        aparat_kod = (data.get("aparat") or "").strip()  # Кодот на апаратот (напр. "kt", "mri")
        aparat_ime = (data.get("aparat_ime") or aparat_kod).strip()  # Името за приказ (опционално)
        datum_vreme = data.get("datum_vreme")
        opis = (data.get("opis") or "").strip()
        
        # Валидација
        if not lekar_id:
            raise HTTPException(status_code=400, detail="Изберете лекар")
        if not pacient_ime:
            raise HTTPException(status_code=400, detail="Внесете име на пациент")
        if not pacient_prezime:
            raise HTTPException(status_code=400, detail="Внесете презиме на пациент")
        if not aparat_kod:
            raise HTTPException(status_code=400, detail="Изберете апарат")
        if not datum_vreme:
            raise HTTPException(status_code=400, detail="Изберете датум и време")
        if not opis:
            raise HTTPException(status_code=400, detail="Внесете опис за зошто е потребно користење на апаратот")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали лекар постои
        db_cursor.execute("SELECT doctor_ID, name, surname FROM Doctors WHERE doctor_ID = %s", (lekar_id,))
        doctor = db_cursor.fetchone()
        if not doctor:
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")
        
        # Парсирање на датум и време
        try:
            dt = datetime.strptime(datum_vreme, "%Y-%m-%dT%H:%M")
            datum_str = dt.strftime("%Y-%m-%d")
            vreme_str = dt.strftime("%H:%M:%S")
        except ValueError:
            raise HTTPException(status_code=400, detail="Неважечки формат на датум и време")
        
        # Проверка дали апаратот е достапен за избраниот датум и време
        # Користи го кодот на апаратот за проверка
        db_cursor.execute("""
            SELECT COUNT(*) as count
            FROM Aparati_termini
            WHERE aparat = %s 
            AND datum_pregled = %s 
            AND vreme_pregled = %s
            AND status != 'откажан'
        """, (aparat_kod, datum_str, vreme_str))
        
        result = db_cursor.fetchone()
        if result and result['count'] > 0:
            raise HTTPException(status_code=400, detail="Апаратот е зафатен за избраниот датум и време. Ве молиме изберете друг термин.")
        
        # Комбинирање на име и презиме за зачувување
        pacient_ime_prezime = f"{pacient_ime} {pacient_prezime}".strip()
        
        # Проверка дали пациентот има закажан преглед за тоа време
        # Ако има, не може да закаже термин на апарат во истото време
        db_cursor.execute("""
            SELECT COUNT(*) as count
            FROM Termin_pregled
            WHERE ime_pacient = %s 
            AND DATE(datum_pregled) = %s 
            AND TIME(vreme_pregled) = %s
            AND status_pregled = 'закажан'
        """, (pacient_ime_prezime, datum_str, vreme_str))
        
        pregled_result = db_cursor.fetchone()
        if pregled_result and pregled_result['count'] > 0:
            raise HTTPException(status_code=400, detail="Пациентот има закажан преглед за избраниот датум и време. Не може да се закаже термин на апарат во исто време.")
        
        # Проверка дали лекарот има закажан преглед (со било кој пациент) за тоа време
        db_cursor.execute("""
            SELECT COUNT(*) as count
            FROM Termin_pregled
            WHERE doctor_ID = %s 
            AND DATE(datum_pregled) = %s 
            AND TIME(vreme_pregled) = %s
            AND status_pregled = 'закажан'
        """, (lekar_id, datum_str, vreme_str))
        
        lekar_pregled_result = db_cursor.fetchone()
        if lekar_pregled_result and lekar_pregled_result['count'] > 0:
            raise HTTPException(status_code=400, detail="Лекарот има закажан преглед за избраниот датум и време. Не може да се закаже термин на апарат во исто време.")
        
        # Зачувување на терминот за апарат во посебна табела Aparati_termini
        # Според барањата: закажување термин на апарат со име/презиме на лекар и пациент, термин и зошто е потребно
        # Користи го кодот на апаратот (краток) наместо целото име за да се избегне проблем со должина
        db_cursor.execute("""
            INSERT INTO Aparati_termini 
            (doctor_ID, lekar_ime, pacient_ime, aparat, datum_pregled, vreme_pregled, opis, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            lekar_id,
            lekar_ime,
            pacient_ime_prezime,
            aparat_kod,  # Користи код наместо цело име
            datum_str,
            vreme_str,
            opis,
            'закажан'
        ))
        
        conn.commit()
        termin_id = db_cursor.lastrowid
        
        return {
            "message": "Терминот за апарат е успешно закажан!",
            "termin_id": termin_id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


