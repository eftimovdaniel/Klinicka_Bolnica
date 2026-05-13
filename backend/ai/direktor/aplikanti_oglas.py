"""
Преглед на апликанти за оглас (само за директор).

Примери:
- „Покажи ми ги апликантите за хирург"
- „Кој се аплицирал за кардиолог?"
- „Аплицирани кандидати за анестезиолог"
- „Сите апликанти" (без позиција – ги враќа сите)
- „Апликанти за оглас 42" (по ID на оглас)

Користи табела `prijaveni_lekari`.
"""

import json
import re

from database import get_connection
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што од прашање извлекува филтри за листа на апликанти за оглас.

Корисникот пишува на македонски. Извлечи:
- "pozicija": име на позицијата (Кардиолог, Хирург, …) или null ако сака сите
- "id_oglas": ID на оглас (само цифри) или null

Врати САМО JSON:
{"pozicija": "..." | null, "id_oglas": <число> | null}

Примери:
- „апликанти за хирург" → {"pozicija":"Хирург","id_oglas":null}
- „кандидати за оглас 42" → {"pozicija":null,"id_oglas":42}
- „сите апликанти" → {"pozicija":null,"id_oglas":null}
- „aplikanti za kardiolog" → {"pozicija":"Кардиолог","id_oglas":null}

БЕЗ markdown, БЕЗ објаснувања.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[aplikanti] AI: {odgovor!r}")
    if "Привремено сум" in odgovor or "Привремена грешка" in odgovor:
        return {"_error": odgovor}
    cist = re.sub(r"^```(?:json)?|```$", "", odgovor.strip()).strip()
    try:
        return json.loads(cist)
    except Exception:
        return {}


def _format_datum(d) -> str:
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y %H:%M")
    return str(d)[:16]


def _is_direktor(lekar: dict | None) -> bool:
    """Истата логика како во другите модули за директор."""
    if not lekar:
        return False
    ime = (lekar.get("name") or "").strip().lower()
    prezime = (lekar.get("surname") or "").strip().lower()
    return ime == "владко" and prezime == "захариев"


def odgovori_za_aplikanti(prashanje: str, lekar: dict | None) -> str:
    if not _is_direktor(lekar):
        return (
            "Оваа функција е достапна само за директорот. "
            "Те молам најави се како директор."
        )

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    pozicija = (podatoci.get("pozicija") or "").strip() or None
    id_oglas = podatoci.get("id_oglas")
    try:
        id_oglas = int(id_oglas) if id_oglas else None
    except (ValueError, TypeError):
        id_oglas = None

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        sql = (
            "SELECT id, id_oglas, pozicija, ime_lekar, prezime_lekar, "
            "       broj_med_licenca, email, telefon, datum_prijava "
            "FROM prijaveni_lekari "
            "WHERE 1=1"
        )
        params: list = []

        if id_oglas:
            sql += " AND id_oglas = %s"
            params.append(id_oglas)
        elif pozicija:
            sql += " AND LOWER(TRIM(pozicija)) LIKE %s"
            params.append(f"%{pozicija.strip().lower()}%")

        sql += " ORDER BY datum_prijava DESC"

        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
        cur.close()
    except Exception as e:
        print(f"[aplikanti] DB greshka: {e}")
        return "Се случи грешка при вчитувањето на апликантите. Те молам обиди се повторно."
    finally:
        if conn:
            conn.close()

    if not rows:
        if id_oglas:
            return f"Нема апликанти за оглас со ID {id_oglas}."
        if pozicija:
            return f'Нема апликанти за позицијата „{pozicija}".'
        return "Нема апликанти во системот."

    naslov_filtri = []
    if id_oglas:
        naslov_filtri.append(f"оглас #{id_oglas}")
    if pozicija:
        naslov_filtri.append(f'„{pozicija}"')
    naslov_suffix = (" (" + ", ".join(naslov_filtri) + ")") if naslov_filtri else ""
    naslov = f"Апликанти ({len(rows)}){naslov_suffix}:"

    redovi = [naslov, ""]
    for r in rows:
        ime = (r.get("ime_lekar") or "").strip()
        prezime = (r.get("prezime_lekar") or "").strip()
        polno = f"{ime} {prezime}".strip() or "—"
        poz = (r.get("pozicija") or "").strip() or "—"
        email = (r.get("email") or "").strip() or "—"
        tel = r.get("telefon") or "—"
        lic = r.get("broj_med_licenca") or "—"
        kogo = _format_datum(r.get("datum_prijava"))
        oglas_ref = r.get("id_oglas")
        oglas_str = f" | оглас #{oglas_ref}" if oglas_ref else ""

        red = (
            f"• {polno} – {poz}{oglas_str}\n"
            f"   Email: {email} | Тел: {tel} | Лиценца: {lic}\n"
            f"   Пријавен: {kogo}"
        )
        redovi.append(red)

    return "\n".join(redovi)
