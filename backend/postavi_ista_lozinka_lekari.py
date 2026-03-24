#!/usr/bin/env python3
"""
Поставување иста привремена лозинка за СИТЕ лекари во базата.
При прва најава секој лекар ќе мора да ја смени лозинката.

Стандардна привремена лозинка за сите: Test123..

Користење:
  1. Извршете го add_must_change_password.sql (еднаш) за да постои колоната must_change_password.
  2. Трчајте: python postavi_ista_lozinka_lekari.py
  3. Сите лекари добиваат лозинка Test123.. и при прва најава мораат да ја сменат.
"""
import sys

# Иста привремена лозинка за сите лекари (мин. 8, голема, број, знак)
DEFAULT_LOZINKA_LEKARI = "Test123.."

def main():
    try:
        from database import get_connection
        from password_utils import hash_password
    except Exception as e:
        print("Грешка при поврзување со базата:", e)
        print("Трчајте од backend/ директориумот: python postavi_ista_lozinka_lekari.py")
        sys.exit(1)

    password = DEFAULT_LOZINKA_LEKARI
    pw_hash = hash_password(password)
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE Doctors SET password = %s, must_change_password = 1 WHERE doctor_ID IS NOT NULL", (pw_hash,))
        n = cur.rowcount
        conn.commit()
        print(f"Готово. Поставена е лозинката '{DEFAULT_LOZINKA_LEKARI}' за {n} лекар/и. При прва најава ќе мораат да ја сменат.")
    except Exception as e:
        print("Грешка:", e)
        if conn:
            conn.rollback()
        sys.exit(1)
    finally:
        if conn and conn.is_connected():
            conn.close()

if __name__ == "__main__":
    main()
