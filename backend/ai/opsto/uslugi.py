"""
Список на услуги во болницата.

Услугите се составени од:
1. Оддели (Oddeli табела) - специјалистички прегледи
2. Апарати (Aparati табела) - дијагностички
3. Дополнителни услуги (од JSON фајлот)
"""

import json
import os
from database import get_connection


_BAZA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JSON_PATH = os.path.join(_BAZA_DIR, "data", "bolnica_info.json")


def zimi_oddeli() -> list[str]:
    """Враќа листа на оддели од DB."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT ime_na_oddel FROM Oddeli ORDER BY ime_na_oddel")
        rezultati = cur.fetchall()
        cur.close()
        return [r["ime_na_oddel"] for r in rezultati]
    except Exception as e:
        print(f"[uslugi] oddeli greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def zimi_aparati() -> list[dict]:
    """Враќа листа на активни апарати од DB."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT ime, opis
            FROM Aparati
            WHERE aktiven = 1
            ORDER BY ime
        """)
        rezultati = cur.fetchall()
        cur.close()
        return rezultati
    except Exception as e:
        print(f"[uslugi] aparati greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def zimi_dopolnitelni_uslugi() -> list[str]:
    """Враќа дополнителни услуги од JSON."""
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            info = json.load(f)
        return info.get("uslugi_dopolnitelni", [])
    except Exception as e:
        print(f"[uslugi] json greshka: {e}")
        return []


def odgovori_za_uslugi(prashanje: str) -> str:
    """
    Главна точка - повикана од router-от.
    Прикажува сите услуги, групирани.
    """
    oddeli = zimi_oddeli()
    aparati = zimi_aparati()
    dopolnitelni = zimi_dopolnitelni_uslugi()

    delovi = ["Услуги во Клиничка Болница Штип:", ""]

    # Специјалистички оддели
    if oddeli:
        delovi.append("Специјалистички прегледи:")
        for o in oddeli:
            delovi.append(f"- {o}")
        delovi.append("")

    # Дијагностика (апарати)
    if aparati:
        delovi.append("Дијагностички испитувања:")
        for a in aparati:
            ime = a["ime"]
            opis = a.get("opis") or ""
            if opis and opis != ime:
                delovi.append(f"- {ime} ({opis})")
            else:
                delovi.append(f"- {ime}")
        delovi.append("")

    # Дополнителни услуги
    if dopolnitelni:
        delovi.append("Дополнителни услуги:")
        for u in dopolnitelni:
            delovi.append(f"- {u}")
        delovi.append("")

    delovi.append('За закажување напиши: „Сакам преглед кај д-р [презиме] [датум] [време]"')

    return "\n".join(delovi)
