"""
Информации за конкретен лекар.

Како работи:
1. AI (Groq) препознава за кој лекар прашува корисникот (од листа во DB).
2. Враќа: име, специјалност, email, оддел, дежурства.
"""

from datetime import date, timedelta
from database import get_connection
from ai.slobodni_termini import najdi_lekar_so_ai

# vraka dezurstvo za daden lekar, koga toj lekar e dezuren
def zimi_dezurstva_za_lekar(doctor_id: int, denovi_napred: int = 7) -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT datum, oddel, vreme_od, vreme_do, napomena
            FROM Dezurstva
            WHERE doctor_ID = %s
              AND datum BETWEEN %s AND %s
            ORDER BY datum, vreme_od
        """, (doctor_id, date.today(), date.today() + timedelta(days=denovi_napred)))
        rezultati = cur.fetchall()
        cur.close()
        return rezultati
    except Exception as e:
        print(f"[info_lekar] dezurstva greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()

# Broi kolku pregledi ima zakazano daden lekar vo daden vremenski interval (denovi)
def prebroj_zakazani_termini(doctor_id: int, denovi_napred: int = 7) -> int:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT COUNT(*) AS c
            FROM Termin_pregled
            WHERE doctor_ID = %s
              AND datum_pregled BETWEEN %s AND %s
              AND status_pregled = 'закажан'
        """, (doctor_id, date.today(), date.today() + timedelta(days=denovi_napred)))
        rezultat = cur.fetchone()
        cur.close()
        return rezultat["c"] if rezultat else 0
    except Exception as e:
        print(f"[info_lekar] termini greshka: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def format_vreme(v) -> str:
    """Претвора time/timedelta во HH:MM string."""
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def odgovori_za_info_lekar(prashanje: str) -> str:
    """
    Главна точка - повикана од router-от.
    """
    # AI наоѓа кој лекар е во прашањето
    lekar = najdi_lekar_so_ai(prashanje)

    if not lekar:
        return (
            'Не препознав за кој лекар прашуваш. Те молам напиши име и презиме, '
            'на пример: „Каков е д-р Марко Петров?"'
        )

    ime = f"Д-р {lekar['name']} {lekar['surname']}"
    spec = lekar.get("specialty") or "Општа пракса"
    doctor_id = lekar["doctor_ID"]

    # Доп. податоци
    dezurstva = zimi_dezurstva_za_lekar(doctor_id)
    br_termini = prebroj_zakazani_termini(doctor_id)

    delovi = [
        f"Информации за {ime}",
        "",
        f"Специјалност: {spec}",
        f"Email: {lekar.get('email', '—')}",
        f"Закажани прегледи (наредни 7 дена): {br_termini}",
    ]

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

    if dezurstva:
        delovi.append("")
        delovi.append("Дежурства во следните 7 дена:")
        for d in dezurstva:
            datum = d["datum"]
            den_ime = DENOVI[datum.weekday()]
            datum_str = datum.strftime("%d.%m")
            vreme_od = format_vreme(d.get("vreme_od"))
            vreme_do = format_vreme(d.get("vreme_do"))
            oddel = d.get("oddel") or ""
            delovi.append(f"- {den_ime} {datum_str}: {vreme_od} - {vreme_do} ({oddel})")
    else:
        delovi.append("")
        delovi.append("Нема закажани дежурства во следните 7 дена.")

    delovi.append("")
    delovi.append(f'За слободни термини напиши: „Кога е слободен д-р {lekar["surname"]}?"')

    return "\n".join(delovi)
