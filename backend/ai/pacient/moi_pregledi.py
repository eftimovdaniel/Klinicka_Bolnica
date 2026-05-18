from ai._kernel.prompt_loader import load_prompt
import re
from datetime import date

from database import get_connection
from ai._kernel.groq_helpers import izvlechi_json_so_ai
from ai._kernel.transliteracija import transliterijaj

_RE_PREGLEDI_ZA = re.compile(
    r"\b(прегледи|прегледите|pregledi|pregledite)\s+за\b",
    re.IGNORECASE | re.UNICODE,
)


def datum_za_pregledi_od_prasanje(prasanje: str) -> date | None:
    """Датум од прашање за листа прегледи (дозволен и минат ден)."""
    from ai.pacient.slobodni_termini import (
        _DATUM_BROJ_RE,
        _ISO_DATUM_RE,
        _RE_DAN_MES,
        _mesec_od_tekst,
        _parsiraj_dan_mesec,
        datum_od_prasanje_lokalno,
    )

    d = datum_od_prasanje_lokalno(prasanje)
    if d:
        return d

    p = transliterijaj(prasanje).lower()
    denes = date.today()

    dm = _parsiraj_dan_mesec(p, denes)
    if dm:
        return dm

    m = _RE_DAN_MES.search(p)
    if m:
        mesec = _mesec_od_tekst(m.group(2))
        if mesec:
            try:
                return date(denes.year, mesec, int(m.group(1)))
            except ValueError:
                pass

    m = _DATUM_BROJ_RE.search(p)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        g = int(m.group(3)) if m.group(3) else denes.year
        if g < 100:
            g += 2000
        try:
            return date(g, mo, d)
        except ValueError:
            pass

    m = _ISO_DATUM_RE.search(prasanje)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


_RE_LISTA_PREGLEDI = re.compile(
    r"\b(прикаж\w*|приказ\w*|prikaz\w*|покаж\w*|pokaz\w*|види|vidi|листа|lista)\b",
    re.UNICODE | re.IGNORECASE,
)
_RE_GI_ZBOR = re.compile(r"\b(ги|gi)\b", re.UNICODE | re.IGNORECASE)


def prasanje_e_lista_site_pregledi(prasanje: str) -> bool:
    """
    „Прикажи ги сите прегледи" / „Prikazi gi site pregledi" — не пребарување лекар по име.

    Латиница „Prikazi" по transliteracija често станува „прикази" (з), не „прикажи" (ж).
    """
    if not prasanje or not prasanje.strip():
        return False
    p = transliterijaj(prasanje).lower()
    if not re.search(r"\b(преглед|pregled|термин|termin)\w*\b", p, re.UNICODE):
        return False
    if "закажани преглед" in p or "zakazani pregled" in p:
        return True
    if "моите преглед" in p or "moite pregled" in p or "moi pregled" in p:
        return True
    ima_site = any(
        x in p for x in ("сите", "site", "all", "целосн", "celosn", "комплетн", "kompletn")
    )
    ima_prikazi = bool(_RE_LISTA_PREGLEDI.search(p)) or bool(
        re.search(
            r"\b(прикаж\w*|приказ\w*|prikaz\w*|покаж\w*|pokaz\w*)\s+ги\b",
            p,
            re.UNICODE,
        )
    )
    ima_gi = bool(_RE_GI_ZBOR.search(p))
    if ima_site and (ima_prikazi or ima_gi):
        return True
    if re.search(
        r"\b(прикаж\w*|приказ\w*|prikaz\w*|покаж\w*|pokaz\w*)\s+ги\s+"
        r"(site\s+)?(pregled|преглед)",
        p,
        re.UNICODE,
    ):
        return True
    return False


_RE_TERMINI_NA = re.compile(
    r"\b(прегледи|преглед|pregledi|pregled|термини|термин|termini|termin)\s+"
    r"(на|na|za|за)\b",
    re.UNICODE | re.IGNORECASE,
)


def prasanje_e_pregledi_datum(prasanje: str) -> bool:
    """
    „Прегледи за 19 мај" / „Termini na 25 maj" / „Прегледи на 19ти" — листа термини.
    """
    if not prasanje or not prasanje.strip():
        return False
    p = transliterijaj(prasanje).lower()
    if not re.search(r"\b(преглед|pregled|термин|termin)\w*\b", p, re.UNICODE):
        return False
    if _RE_PREGLEDI_ZA.search(p) or _RE_TERMINI_NA.search(p):
        return True
    if re.search(r"\b(на|na|za|за)\s+\d", p):
        return True
    if re.search(r"\b(на|na)\s+\d{1,2}", p):
        return True
    if re.search(r"\bза\s+\d", p):
        return True
    return datum_za_pregledi_od_prasanje(prasanje) is not None


def _izvlechi(prasanje: str) -> dict:
    return izvlechi_json_so_ai(
        f'Прашање: „{prasanje}"',
        load_prompt("pacient_moi_pregledi"),
        log_tag="moi_pregledi",
    )


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


def odgovori_za_moi_pregledi(
    prasanje: str, pacient: dict | None, lekar: dict | None = None
) -> str:
    if not pacient or not pacient.get("email"):
        if lekar and lekar.get("doctor_ID"):
            return (
                "За прегледи на датум како лекар (ваши закажани термини) напишете, на пр.:\n"
                '„Прикажи ми закажани прегледи" или „Прегледи за 19.05“.'
            )
        return (
            'За да ги видиш своите прегледи преку AI асистентот, прво најави '
            'се како пациент (горе десно копчето „Најави се").\n\n'
            "Ако сте лекар, најавете се со лекарски профил — тогаш „Прегледи за [датум]“ "
            "ги прикажува вашите закажани прегледи."
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
    if not datum_str:
        d = datum_za_pregledi_od_prasanje(prasanje)
        if d:
            datum_str = d.strftime("%Y-%m-%d")

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
        if datum_str:
            try:
                d = date.fromisoformat(datum_str[:10])
                return f"Немаш прегледи на {d.strftime('%d.%m.%Y')}."
            except ValueError:
                pass
        return "Немаш прегледи кои одговараат на твоето барање."

    # Резимирано броење
    br_zakazan = sum(1 for r in rows if r.get("status_pregled") == "закажан")
    br_zavrsen = sum(1 for r in rows if r.get("status_pregled") == "завршен")
    br_otkazan = sum(1 for r in rows if r.get("status_pregled") == "откажан")

    if datum_str:
        try:
            d = date.fromisoformat(datum_str[:10])
            naslov = f"Твои прегледи за {d.strftime('%d.%m.%Y')} ({len(rows)})"
        except ValueError:
            naslov = f"Твои прегледи ({len(rows)})"
    else:
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
