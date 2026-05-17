"""
Лични статистики на најавен лекар - прегледи + просечна оцена.

Примери:
- „Колку прегледи имам?"
- „Каква ми е просечната оцена?"
- „Моите статистики"
- „Колку прегледи имав оваа недела?"
- „Колку прегледи имав минатиот месец?"
"""

import re
from datetime import date, timedelta

from database import get_connection
from ai._kernel.auth import require_lekar
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува период за статистика на лекар.

Корисникот е лекар и сака свои статистики. Врати САМО JSON:
{"period": "denes" | "nedela" | "mesec" | "godina" | "site" | null}

Правила:
- „денес" / „сегашно" → "denes"
- „оваа недела" / „последните 7 дена" → "nedela"
- „овој месец" / „последниот месец" / „последните 30 дена" → "mesec"
- „оваа година" → "godina"
- „воопшто" / „вкупно" / не е спомнат → "site"

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)
    print(f"[moja_statistika] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="moja_statistika")


def _period_to_dates(period: str | None) -> tuple[date | None, str]:
    if not period or period == "site":
        return None, "од почеток"
    if period == "denes":
        return date.today(), "за денес"
    if period == "nedela":
        return date.today() - timedelta(days=7), "за последните 7 дена"
    if period == "mesec":
        return date.today() - timedelta(days=30), "за последните 30 дена"
    if period == "godina":
        return date(date.today().year, 1, 1), f"за {date.today().year} година"
    return None, "од почеток"


def odgovori_za_moja_statistika(prasanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_lekar(lekar):
        return err

    doctor_id = lekar["doctor_ID"]

    podatoci = _izvlechi(prasanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    od_datum, label = _period_to_dates(podatoci.get("period"))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # 1) Прегледи по статус
    sql = "SELECT status_pregled, COUNT(*) AS broj FROM Termin_pregled WHERE doctor_ID = %s"
    params: list = [doctor_id]
    if od_datum:
        sql += " AND datum_pregled >= %s"
        params.append(od_datum)
    sql += " GROUP BY status_pregled"
    cur.execute(sql, params)
    statusi = {r["status_pregled"]: r["broj"] for r in cur.fetchall()}

    zavrseni = statusi.get("завршен", 0)
    zakazani = statusi.get("закажан", 0)
    otkazani = statusi.get("откажан", 0)
    vkupno = sum(statusi.values())

    # 2) Просечна оцена + број на оцени
    sql2 = (
        "SELECT AVG(F.ocena) AS prosek, COUNT(*) AS broj_ocena"
        " FROM Pregled_feedback F"
        " JOIN Termin_pregled T ON T.termin_ID = F.termin_ID"
        " WHERE T.doctor_ID = %s"
    )
    params2: list = [doctor_id]
    if od_datum:
        sql2 += " AND T.datum_pregled >= %s"
        params2.append(od_datum)
    cur.execute(sql2, params2)
    ocena_row = cur.fetchone()
    prosek = ocena_row["prosek"]
    broj_ocena = ocena_row["broj_ocena"] or 0

    # 3) Топ 3 пациенти (по број на завршени прегледи)
    sql3 = (
        "SELECT ime_pacient, COUNT(*) AS bp FROM Termin_pregled"
        " WHERE doctor_ID = %s AND status_pregled = 'завршен'"
    )
    params3: list = [doctor_id]
    if od_datum:
        sql3 += " AND datum_pregled >= %s"
        params3.append(od_datum)
    sql3 += " GROUP BY ime_pacient ORDER BY bp DESC LIMIT 3"
    cur.execute(sql3, params3)
    top_pacienti = cur.fetchall()

    cur.close()
    conn.close()

    # Изградба на одговор
    ime_lekar = f"{lekar.get('name','')} {lekar.get('surname','')}".strip() or "лекар"
    linii = [
        f"Статистики за д-р {ime_lekar} ({label}):",
        f"",
        f"Прегледи: {vkupno} вкупно",
        f"• Завршени: {zavrseni}",
        f"• Закажани: {zakazani}",
        f"• Откажани: {otkazani}",
        f"",
    ]
    if broj_ocena > 0 and prosek is not None:
        zvezdi = "★" * round(float(prosek))
        linii.append(f"Просечна оцена: {float(prosek):.2f} / 5  {zvezdi}")
        linii.append(f"Број на оцени: {broj_ocena}")
    else:
        linii.append("Просечна оцена: уште нема оцени.")

    if top_pacienti:
        linii.append("")
        linii.append("Топ пациенти (по број на завршени прегледи):")
        for i, p in enumerate(top_pacienti, start=1):
            linii.append(f"{i}. {p['ime_pacient']}: {p['bp']}")

    return "\n".join(linii)
