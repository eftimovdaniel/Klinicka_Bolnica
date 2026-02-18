#!/usr/bin/env python3
"""
Поставување лозинка за постоечки лекар во базата (за тест).
Користение: python postavi_lozinka_lekar.py
Скриптата ќе побара email на лекар и лозинка, ќе ја хешира и ќе испечати
SQL UPDATE наредба коју можете да ја копирате и извршите во MySQL Workbench.
"""
try:
    from database import get_connection
    from password_utils import hash_password
    HAS_DB = True
except Exception:
    HAS_DB = False
    hash_password = None

def main():
    email = input("Е-пошта на лекар (од табела Doctors): ").strip().lower()
    if not email:
        print("Внесете email.")
        return
    password = input("Нова лозинка (мин. 6 знаци): ").strip()
    if len(password) < 6:
        print("Лозинката мора да има најмалку 6 знаци.")
        return
    if not hash_password:
        print("Грешка: password_utils не е достапно. Трчајте од backend/.")
        return

    pw_hash = hash_password(password)
    email_escaped = email.replace("'", "''")
    print()
    print("-- Копирајте ја оваа наредба и извршете ја во MySQL Workbench:")
    print("-- (Користете WHERE email = '...' за да работи со Safe Update Mode.)")
    print()
    sql = f"UPDATE Doctors SET password = '{pw_hash}' WHERE email = '{email_escaped}';"
    print(sql)
    print()
    print("-- По ова, лекарот може да се најави со корисничко име (име.презиме на латиница) и оваа лозинка.")
    print("-- Ако пак добиете Error 1175 (Safe Update), трчајте прво: SET SQL_SAFE_UPDATES = 0;")

if __name__ == "__main__":
    main()
