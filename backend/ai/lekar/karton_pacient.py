"""
Брз медицински картон на пациент - за најавени лекари.

Разлика од „истории" (D2):
- D2 = броење + кратка листа на прегледи кај овој лекар.
- D3 = детален картон: контакт-податоци + сите прегледи (кај било кој лекар)
       со дијагнози и терапии.

Примери:
- „Дај ми картон на Петар Иванов"
- „Картон Иванов"
- „Покажи ми ги сите прегледи на пациент Иванов"
"""

import re

from database import get_connection
from ai._kernel.auth import require_lekar
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува име на пациент.

Корисникот е лекар и сака медицински картон на пациент. Врати САМО JSON:
{"ime_pacient": "Име Презиме" | null}

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)
    print(f"[karton] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="karton_pacient")


def _fmt_datum(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _fmt_vreme(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    return str(t)[:5]


def odgovori_za_karton(prasanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_lekar(lekar):
        return err

    podatoci = _izvlechi(prasanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    ime = (podatoci.get("ime_pacient") or "").strip()
    if not ime:
        return (
            'За картон ми треба име на пациент.\n'
            'Пример: „Дај ми картон на Петар Иванов"'
        )

    delovi = [d for d in ime.split() if d]
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # 1) Контакт-податоци од patient
    where = []
    params: list = []
    if len(delovi) >= 2:
        where.append("LOWER(name_patient) LIKE %s AND LOWER(surname_patient) LIKE %s")
        params.extend([f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"])
    else:
        where.append("(LOWER(name_patient) LIKE %s OR LOWER(surname_patient) LIKE %s)")
        params.extend([f"%{delovi[0].lower()}%", f"%{delovi[0].lower()}%"])

    cur.execute(
        "SELECT patient_ID, name_patient, surname_patient, email, phone_number"
        f" FROM patient WHERE {' AND '.join(where)} LIMIT 5",
        params,
    )
    pacienti = cur.fetchall()

    if not pacienti:
        cur.close()
        conn.close()
        return f'Не најдов пациент „{ime}" во базата.'

    if len(pacienti) > 1:
        cur.close()
        conn.close()
        lista = "\n".join(
            f"• {p['name_patient']} {p['surname_patient']} ({p['email']})"
            for p in pacienti
        )
        return f'Најдов повеќе пациенти со име „{ime}":\n{lista}\n\nТе молам прецизирај име+презиме.'

    p = pacienti[0]

    # 2) Сите прегледи (кај било кој лекар, прикажано е и името на лекарот)
    cur.execute(
        "SELECT termin_ID, ime_lekar, specijalnost_termin, datum_pregled, vreme_pregled,"
        "       status_pregled, dijagnoza, terapija, napomena"
        " FROM Termin_pregled"
        " WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))"
        " ORDER BY datum_pregled DESC, vreme_pregled DESC",
        (p["email"] or "",),
    )
    pregledi = cur.fetchall()
    cur.close()
    conn.close()

    # 3) Изграни картон
    linii = [
        f"МЕДИЦИНСКИ КАРТОН",
        f"Пациент: {p['name_patient']} {p['surname_patient']}",
        f"E-пошта: {p['email'] or '-'}",
        f"Телефон: {p['phone_number'] or '-'}",
        f"ID на пациент: {p['patient_ID']}",
        "",
    ]
    if not pregledi:
        linii.append("Нема забележани прегледи.")
        return "\n".join(linii)

    zavrseni = sum(1 for r in pregledi if r["status_pregled"] == "завршен")
    zakazani = sum(1 for r in pregledi if r["status_pregled"] == "закажан")
    linii.append(f"Вкупно прегледи: {len(pregledi)} (завршени: {zavrseni}, закажани: {zakazani})")
    linii.append("")
    linii.append("Последни прегледи:")
    for r in pregledi[:6]:
        linija = (
            f"\n• {_fmt_datum(r['datum_pregled'])} {_fmt_vreme(r['vreme_pregled'])}"
            f" — {r['status_pregled']} (ID {r['termin_ID']})"
        )
        if r.get("ime_lekar"):
            linija += f"\n  Лекар: {r['ime_lekar']}"
        if r.get("specijalnost_termin"):
            linija += f" ({r['specijalnost_termin']})"
        if r.get("dijagnoza"):
            linija += f"\n  Дијагноза: {r['dijagnoza']}"
        if r.get("terapija"):
            linija += f"\n  Терапија: {r['terapija']}"
        if r.get("napomena"):
            linija += f"\n  Напомена: {r['napomena']}"
        linii.append(linija)

    return "\n".join(linii)
