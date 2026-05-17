from ai._kernel.prompt_loader import load_prompt
import json
import re
from datetime import date, datetime, timedelta

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=load_prompt("pacient_moi_pregledi"))
    print(f"[moi_pregledi] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="moi_pregledi")


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


def odgovori_za_moi_pregledi(prasanje: str, pacient: dict | None) -> str:
    if not pacient or not pacient.get("email"):
        return (
            'За да ги видиш своите прегледи преку AI асистентот, прво најави '
            'се како пациент (горе десно копчето „Најави се").'
        )

    podatoci = _izvlechi(prasanje)
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
        print(f"[moi_pregledi] DB greska: {e}")
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
