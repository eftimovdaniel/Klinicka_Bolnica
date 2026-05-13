import json
import re
from datetime import date, datetime, timedelta

from database import get_connection
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува филтри за приказ на лични прегледи на пациент.

Корисникот пишува на македонски. Извлечи:
- "status": "сите" / "завршен" / "закажан" / "откажан" / null
- "kategorija": "минати" / "идни" / "сите" / null
- "broj": максимум прегледи (число) или null
- "datum": ISO датум (YYYY-MM-DD) ако спомне конкретен датум, или null

Врати САМО JSON:
{"status": "...", "kategorija": "...", "broj": ..., "datum": "..."}

Примери:
- „моите прегледи" → {"status":"сите","kategorija":"сите","broj":null,"datum":null}
- „идни прегледи" → {"status":null,"kategorija":"идни","broj":null,"datum":null}
- „минати прегледи" → {"status":null,"kategorija":"минати","broj":null,"datum":null}
- „завршените прегледи" → {"status":"завршен","kategorija":null,"broj":null,"datum":null}
- „закажаните прегледи" → {"status":"закажан","kategorija":null,"broj":null,"datum":null}
- „последните 5 прегледи" → {"status":null,"kategorija":null,"broj":5,"datum":null}

БЕЗ markdown, БЕЗ објаснувања.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[moi_pregledi] AI: {odgovor!r}")
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
        return d.strftime("%d.%m.%Y")
    return str(d)[:10]


def _format_vreme(v) -> str:
    if not v:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


STATUS_OZNAKI = {
    "закажан": "[закажан]",
    "завршен": "[завршен]",
    "откажан": "[откажан]",
}


def odgovori_za_moi_pregledi(prashanje: str, pacient: dict | None) -> str:
    if not pacient or not pacient.get("email"):
        return (
            'За да ги видиш своите прегледи преку AI асистентот, прво најави '
            'се како пациент (горе десно копчето „Најави се").'
        )

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    status_filter = (podatoci.get("status") or "").strip().lower() or None
    if status_filter == "сите":
        status_filter = None
    kategorija = (podatoci.get("kategorija") or "").strip().lower() or None
    broj = podatoci.get("broj")
    try:
        broj = int(broj) if broj else None
    except (ValueError, TypeError):
        broj = None
    datum_str = (podatoci.get("datum") or "").strip() or None

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        sql = (
            "SELECT termin_ID, datum_pregled, vreme_pregled, ime_lekar, "
            "       status_pregled, dijagnoza, terapija "
            "FROM Termin_pregled "
            "WHERE LOWER(TRIM(COALESCE(email_pacient,''))) = %s"
        )
        params: list = [pacient["email"].strip().lower()]

        if status_filter and status_filter in ("завршен", "закажан", "откажан"):
            sql += " AND status_pregled = %s"
            params.append(status_filter)

        if kategorija == "идни":
            sql += " AND datum_pregled >= %s"
            params.append(date.today())
        elif kategorija == "минати":
            sql += " AND datum_pregled < %s"
            params.append(date.today())

        if datum_str:
            sql += " AND datum_pregled = %s"
            params.append(datum_str)

        sql += " ORDER BY datum_pregled DESC, vreme_pregled DESC"
        if broj:
            sql += " LIMIT %s"
            params.append(int(broj))

        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
        cur.close()
    except Exception as e:
        print(f"[moi_pregledi] DB greshka: {e}")
        return "Се случи грешка при вчитувањето на твоите прегледи. Те молам обиди се повторно."
    finally:
        if conn:
            conn.close()

    if not rows:
        return "Немаш прегледи кои одговараат на твоето барање."

    # Резимирано броење
    br_zakazan = sum(1 for r in rows if r.get("status_pregled") == "закажан")
    br_zavrsen = sum(1 for r in rows if r.get("status_pregled") == "завршен")
    br_otkazan = sum(1 for r in rows if r.get("status_pregled") == "откажан")

    naslov = f"Твои прегледи ({len(rows)})"
    summary = (
        f"Закажани: {br_zakazan} | Завршени: {br_zavrsen} | Откажани: {br_otkazan}"
    )
    redovi = [naslov, summary, ""]

    for r in rows:
        dat = _format_datum(r.get("datum_pregled"))
        vrm = _format_vreme(r.get("vreme_pregled"))
        lekar = (r.get("ime_lekar") or "—").strip() or "—"
        status = r.get("status_pregled") or "—"
        oznaka = STATUS_OZNAKI.get(status, "")

        red = f"- {dat} {vrm} – {lekar} {oznaka}".rstrip()
        # Дополнителни инфо за завршени
        if r.get("status_pregled") == "завршен":
            dij = (r.get("dijagnoza") or "").strip()
            ter = (r.get("terapija") or "").strip()
            if dij:
                red += f"\n   Дијагноза: {dij}"
            if ter:
                red += f"\n   Терапија: {ter}"

        redovi.append(red)

    return "\n".join(redovi)
