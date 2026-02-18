#!/usr/bin/env python3
"""
Тестирај дали лозинката се совпаѓа со хешот во базата (лекари или пациенти).
Користење (од backend/):
  python proveri_lozinka.py lekar   # за лекар – ќе побара име.презиме и лозинка
  python proveri_lozinka.py pacient # за пациент – ќе побара email и лозинка
"""
import sys

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("lekar", "pacient"):
        print("Употреба: python proveri_lozinka.py lekar   или   python proveri_lozinka.py pacient")
        sys.exit(1)
    tip = sys.argv[1]

    try:
        from database import get_connection
        from password_utils import verify_password
    except Exception as e:
        print("Грешка:", e)
        print("Трчајте од backend/ директориумот.")
        sys.exit(1)

    if tip == "lekar":
        username = input("Корисничко име (име.презиме на латиница): ").strip().lower()
        password = input("Лозинка: ")
        if not username or not password:
            print("Внесете корисничко име и лозинка.")
            sys.exit(1)
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT doctor_ID, name, surname, email, password FROM Doctors")
        for row in cur.fetchall():
            from routers.utils import transliterate_mk_to_lat
            un = (transliterate_mk_to_lat(row.get("name") or "") + "." + transliterate_mk_to_lat(row.get("surname") or "")).lower()
            if un == username:
                stored = row.get("password")
                print("Пронајден лекар:", row.get("name"), row.get("surname"), "| doctor_ID:", row.get("doctor_ID"))
                print("Тип на хеш во база:", "bcrypt" if stored and str(stored).strip().startswith("$2") else "SHA-256 (legacy)", "| должина:", len(str(stored)) if stored else 0)
                ok = verify_password(password, stored)
                print("Верификација (да ли лозинката одговара):", "ДА" if ok else "НЕ")
                conn.close()
                return
        print("Не е пронајден лекар со тоа корисничко име.")
        conn.close()
        sys.exit(1)

    else:
        email = input("Е-пошта (пациент): ").strip().lower()
        password = input("Лозинка: ")
        if not email or not password:
            print("Внесете е-пошта и лозинка.")
            sys.exit(1)
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT patient_ID, name_patient, surname_patient, email, password FROM patient WHERE LOWER(email) = %s", (email,))
        row = cur.fetchone()
        conn.close()
        if not row:
            print("Не е пронајден пациент со таа е-пошта.")
            sys.exit(1)
        stored = row.get("password")
        print("Пронајден пациент:", row.get("name_patient"), row.get("surname_patient"), "| patient_ID:", row.get("patient_ID"))
        print("Тип на хеш во база:", "bcrypt" if stored and str(stored).strip().startswith("$2") else "SHA-256 (legacy)", "| должина:", len(str(stored)) if stored else 0)
        ok = verify_password(password, stored)
        print("Верификација (да ли лозинката одговара):", "ДА" if ok else "НЕ")

if __name__ == "__main__":
    main()
