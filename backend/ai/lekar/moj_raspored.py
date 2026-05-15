"""
Распоред на лекар - листа на закажани прегледи.

Достапно за СЕКОЈ најавен лекар.

Примери:
- „Прикажи ги закажаните прегледи"
- „Што имам утре?"
- „Мојот распоред за оваа недела"
- „Закажани прегледи денес"
- „Кои се моите следни 5 прегледи?"
"""

import re
from datetime import date, timedelta

from database import get_connection
from ai._kernel.auth import require_lekar
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува параметри за распоред на лекар.

Корисникот е лекар и сака да види свои закажани прегледи. Врати САМО JSON:
{"period": "denes" | "utre" | "nedela" | "mesec" | "site" | null,
 "datum": "YYYY-MM-DD" | null,
 "broj": число | null}

Правила:
- „денес" / „за денеска" → "period"="denes"
- „утре" / „за утре" → "period"="utre"
- „оваа недела" / „наредните 7 дена" → "period"="nedela"
- „овој месец" / „наредните 30 дена" → "period"="mesec"
- „сите" / „воопшто" → "period"="site"
- ако корисникот спомне конкретен датум (пр. „15.05" или „понеделник") → "datum"=YYYY-MM-DD
- ако корисникот спомне број (пр. „следните 5", „топ 3") → "broj"=число
- ако нема ништо јасно → сите вредности null

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    denes = date.today().strftime("%Y-%m-%d")
    denes_den = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][
        date.today().weekday()
    ]
    full = f'Денес: {denes} ({denes_den})\n\nПрашање: „{prashanje}"\nВрати JSON.'
    odgovor = ask_ai(full, system_prompt=PROMPT)
    print(f"[moj_raspored] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="moj_raspored")


def _period_to_dates(period: str | None) -> tuple[date | None, date | None, str]:
    """Враќа (od, do, label). None значи без горна граница."""
    denes = date.today()
    if not period:
        # Default: од денес па наваму
        return denes, None, "од денес"
    if period == "denes":
        return denes, denes, "за денес"
    if period == "utre":
        utre = denes + timedelta(days=1)
        return utre, utre, "за утре"
    if period == "nedela":
        return denes, denes + timedelta(days=7), "за следните 7 дена"
    if period == "mesec":
        return denes, denes + timedelta(days=30), "за следните 30 дена"
    if period == "site":
        return None, None, "сите"
    return denes, None, "од денес"


def _fmt_datum(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y (%a)").replace("Mon", "пон").replace("Tue", "втo").replace(
            "Wed", "сре"
        ).replace("Thu", "чет").replace("Fri", "пет").replace("Sat", "саб").replace("Sun", "нед")
    return str(d)


def _fmt_vreme(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    return str(t)[:5]


def odgovori_za_raspored(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_lekar(lekar):
        return err

    doctor_id = lekar["doctor_ID"]

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    konkreten_datum = podatoci.get("datum")
    broj = podatoci.get("broj")
    try:
        broj = int(broj) if broj else None
    except (TypeError, ValueError):
        broj = None

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    sql = (
        "SELECT termin_ID, ime_pacient, email_pacient, telefon_pacient,"
        "       datum_pregled, vreme_pregled, status_pregled, napomena"
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s AND status_pregled = 'закажан'"
    )
    params: list = [doctor_id]
    label = ""

    if konkreten_datum:
        sql += " AND datum_pregled = %s"
        params.append(konkreten_datum)
        label = f"за {konkreten_datum}"
    else:
        od, do, label = _period_to_dates(podatoci.get("period"))
        if od:
            sql += " AND datum_pregled >= %s"
            params.append(od)
        if do:
            sql += " AND datum_pregled <= %s"
            params.append(do)

    sql += " ORDER BY datum_pregled, vreme_pregled"
    if broj:
        sql += " LIMIT %s"
        params.append(broj)

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    ime_lekar = f"{lekar.get('name','')} {lekar.get('surname','')}".strip() or "тебе"

    if not rows:
        return f"Немаш закажани прегледи {label}."

    linii = [f"Закажани прегледи {label} ({len(rows)} вкупно):", ""]

    # Групирај по датум за полесно читање
    po_datum: dict = {}
    for r in rows:
        d = r["datum_pregled"]
        po_datum.setdefault(d, []).append(r)

    for d in sorted(po_datum.keys()):
        linii.append(f"━━ {_fmt_datum(d)} ━━")
        for r in po_datum[d]:
            linija = (
                f"• {_fmt_vreme(r['vreme_pregled'])} — {r['ime_pacient']} (ID {r['termin_ID']})"
            )
            if r.get("napomena"):
                linija += f"\n  Напомена: {r['napomena']}"
            linii.append(linija)
        linii.append("")

    return "\n".join(linii).strip()
