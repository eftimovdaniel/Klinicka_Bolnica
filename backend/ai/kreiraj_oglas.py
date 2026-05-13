"""
Креирање оглас за работа преку AI - само за директорот.

Tek: Корисник пишува „Креирај оглас за кардиолог со рок 1 јуни"
→ AI извлекува pozicija, oddel, рок → INSERT во Vrabotuvanje.
"""

import json
import re
from datetime import date, datetime, timedelta

from database import get_connection
from ai.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува податоци за оглас за работа.

Корисникот пишува на македонски. Врати САМО JSON:
{"pozicija": "Кардиолог", "oddel": "Кардиологија", "rok": "YYYY-MM-DD"}

Правила:
- pozicija: наслов (пр. „Кардиолог", „Медицинска сестра"). Ако нема → null.
- oddel: мора од листата подолу. „кардиолог"→„Кардиологија", „гинеколог"→„Акушерство и геникологија".
- rok: датум во формат YYYY-MM-DD. Ако нема → null.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _zimi_oddeli() -> list[str]:
    """Сите имиња на оддели од базата."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli ORDER BY ime_na_oddel")
    oddeli = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return oddeli


def _najdi_oddel(oddel: str, site_oddeli: list[str]) -> str | None:
    """Match (case-insensitive, или содржан)."""
    if not oddel:
        return None
    o = oddel.lower().strip()
    for x in site_oddeli:
        if x.lower() == o or o in x.lower() or x.lower() in o:
            return x
    return None


def _izvlechi(prashanje: str) -> dict:
    """AI враќа dict со pozicija/oddel/rok."""
    oddeli = _zimi_oddeli()
    prompt = f"Оддели: {', '.join(oddeli)}\n\nПрашање: „{prashanje}\"\nВрати JSON."
    odgovor = ask_ai(prompt, system_prompt=PROMPT)
    print(f"[kreiraj_oglas] AI: {odgovor!r}")

    if "Привремено сум" in odgovor or "Привремена грешка" in odgovor:
        return {"_error": odgovor}

    cist = re.sub(r"^```(?:json)?|```$", "", odgovor.strip()).strip()
    try:
        return json.loads(cist)
    except Exception:
        return {}


def odgovori_za_kreiranje_oglas(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if not lekar or not lekar.get("doctor_ID"):
        return "Мораш прво да се најавиш како директор."

    from routers.admin import check_admin_access
    if not check_admin_access(lekar["doctor_ID"]):
        return "Само директорот може да креира огласи."

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    pozicija = (podatoci.get("pozicija") or "").strip()
    oddel = _najdi_oddel(podatoci.get("oddel") or "", _zimi_oddeli())
    rok_str = podatoci.get("rok")

    if not pozicija or not oddel:
        return (
            'За оглас ми треба позиција + оддел.\n'
            'Пример: „Креирај оглас за кардиолог" или „Оглас за гинеколог со рок 1 јуни"'
        )

    # Рок: ако нема → 30 дена; ако е во минатото → +30 дена
    denes = date.today()
    try:
        rok = datetime.strptime(rok_str, "%Y-%m-%d").date() if rok_str else denes + timedelta(days=30)
    except Exception:
        rok = denes + timedelta(days=30)
    if rok < denes:
        rok = denes + timedelta(days=30)

    # INSERT
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO Vrabotuvanje (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas)"
        " VALUES (%s, %s, %s, %s, 'активен')",
        (pozicija, oddel, denes, rok),
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.close()
    conn.close()

    return (
        f"Огласот е креиран!\n\n"
        f"Позиција: {pozicija}\n"
        f"Оддел: {oddel}\n"
        f"Рок: {rok.strftime('%d.%m.%Y')}\n"
        f"ID: {new_id}"
    )
