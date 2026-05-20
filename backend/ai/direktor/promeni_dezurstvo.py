"""
Дежурства на лекар — само за директорот.

- „Додади ја д-р X дежурна на 21 мај 20:00-04:00" → INSERT (ново дежурство)
- „Премести / префрли дежурство на X за петок" → UPDATE (најрано идно или совпаѓачко)
"""

import re
from datetime import date, datetime

from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum, format_vreme
from ai.direktor.dezurstvo_kontekst import izgradi_kontekst, lekar_od_kontekst


# sistemski prompt koj mu se prakja na ai modelot
# ovde detalno se objasnuva sto treba ai da vrati
PROMPT = """
Ти си систем што извлекува податоци за дежурство на лекар.

Корисникот (директор) сака да ДОДАДЕ ново дежурство или да го ПРОМЕНИ постоечкото.

Врати САМО JSON:
{
  "akcija": "dodadi" | "promeni",
  "lekar": "Име Презиме" | null,
  "datum": "YYYY-MM-DD" | null,
  "vreme_od": "HH:MM" | null,
  "vreme_do": "HH:MM" | null,
  "oddel": "име на оддел" | null
}

Правила за akcija:
- „додади", „внеси", „закажи дежурство", „нека биде дежурна" → dodadi
- „премести", „префрли", „промени" → promeni

Датум: „21 мај", „21.05.2026", „утре", „петок" → YYYY-MM-DD (годината од „Денес" ако нема година).
Време: „20:00 до 04:00", „од 20:00 до 04:00" → vreme_od, vreme_do (ноќно може vreme_do < vreme_od).
Лекар: без титула (д-р, др). „Марија Хубрева" → lekar.
oddel: само ако е експлицитно (напр. „на Урологија"); инаку null.

БЕЗ markdown. Само JSON.
""".strip()
# strip() se koristi za da se trgnat prazni mesta i novi redovi
# od pocetokot i krajot na stringot


# recnik za pretvaranje ime na mesec -> broj na mesec
# podrzuva i latinica i kirilica
# recnikot raboti kako key-value struktura — primer: _MESECI["maj"] -> 5
_MESECI = {
    "јануари": 1, "февруари": 2, "март": 3, "април": 4, "мај": 5, "јуни": 6,
    "јули": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11, "декември": 12,
    "januari": 1, "fevruari": 2, "mart": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "avgust": 8, "septemvri": 9, "oktomvri": 10, "noemvri": 11, "dekemvri": 12,
}


def _izvlechi_ai(prasanje: str, denes: date) -> dict:
    # funkcija koja go prakja prasanjeto do ai modelot
    # i ocekuva strukturiran json odgovor
    denes_den = [
        "понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"
    ][denes.weekday()]
    # denes.weekday() vraka broj 0-6 (0=ponedelnik, 6=nedela)
    # so toa go zemame imeto na denot od listata
    full = (
        f"Денес: {denes.isoformat()} ({denes_den})\n\n"
        f'Прашање: „{prasanje}"\nВрати JSON.'
    )
    # se kreira finalen prompt za ai — denes + prasanje od direktorot
    odgovor = ask_ai(full, system_prompt=PROMPT)
    # se povikuva ai — system_prompt e pravilata, full e konkretnoto prasanje
    print(f"[promeni_dezurstvo] AI: {odgovor!r}")
    # debug pecatenje vo terminal — !r e raw string
    return parse_ai_json(odgovor, log_tag="promeni_dezurstvo")
    # odgovorot se pretvara vo dict; nevaliden json -> greska


def _datum_od_tekst(prasanje: str, denes: date) -> date | None:
    # rezervna funkcija dokolku ai ne uspeal da izvlece datum
    p = transliterijaj(prasanje).lower()
    # tekstot se normalizira — lower() za polesno sporeduvanje
    m = re.search(
        r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})",
        prasanje,
    )
    # regex za datum: 21.05.2026, 21-05-2026, 21/05/2026
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            # group(1)=den, group(2)=mesec, group(3)=godina
        except ValueError:
            pass
            # nevaliden datum — programata ne pada
    m = re.search(
        r"(\d{1,2})\s+(" + "|".join(_MESECI.keys()) + r")(?:\s+(\d{4}))?",
        p,
        re.IGNORECASE,
    )
    # regex za „21 мај" ili „21 maj 2026"
    if m:
        mes = _MESECI.get(m.group(2).lower())
        if mes:
            god = int(m.group(3)) if m.group(3) else denes.year
            try:
                return date(god, mes, int(m.group(1)))
            except ValueError:
                pass
    return None
    # ako ne se najde datum — None


def _vreme_od_tekst(prasanje: str) -> tuple[str | None, str | None]:
    # funkcija za izvlekuvanje pocetno i krajno vreme od tekst
    m = re.search(
        r"(?:од\s+)?(\d{1,2})[:.](\d{2})\s*(?:до|-|–)\s*(\d{1,2})[:.](\d{2})",
        prasanje,
        re.IGNORECASE,
    )
    # regex: 20:00 до 04:00 — ?: grupa koja ne se zacuvuva
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}"
        # :02d dodava nula napred (4 -> 04)
    m2 = re.search(
        r"периодот\s+од\s+(\d{1,2})[:.](\d{2})\s+до\s+(\d{1,2})[:.](\d{2})",
        transliterijaj(prasanje).lower(),
    )
    # alternativen obrazec: „периодот од 20:00 до 04:00"
    if m2:
        return f"{int(m2.group(1)):02d}:{m2.group(2)}", f"{int(m2.group(3)):02d}:{m2.group(4)}"
    return None, None


def _vreme_samo_do(prasanje: str) -> str | None:
    """«да е до 03:00», «до 03»."""
    # samo krajno vreme — na pr. „промени да е до 03:00"
    p = transliterijaj(prasanje).lower()
    m = re.search(
        r"(?:да\s+е\s+)?(?:до|do)\s+(\d{1,2})[:.]?(\d{2})?\b",
        p,
    )
    if m:
        mm = m.group(2) if m.group(2) is not None else "00"
        return f"{int(m.group(1)):02d}:{mm}"
    m2 = re.search(r"\b(\d{1,2})[:.](\d{2})\s*час", p)
    if m2 and any(w in p for w in ("до", "do", "крај", "заврши")):
        return f"{int(m2.group(1)):02d}:{m2.group(2)}"
    return None


def _baranje_ista_data(prasanje: str) -> bool:
    # dali direktorot misli na istiot datum kako vo pretodniot pregled
    p = transliterijaj(prasanje).lower()
    return any(
        x in p
        for x in (
            "иста дата",
            "истиот датум",
            "на истиот датум",
            "на истата дата",
            "ист ден",
            "ista data",
            "istiot datum",
        )
    )
    # any() vraka True ako barem edna fraza postoi vo tekstot


def _baranje_e_premesti_datum(prasanje: str) -> bool:
    # eksplicitno premestuvanje na datum (ne samo vreme)
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in ("премести", "префрли", "пренеси", "одложи", "premesti", "prefrli")
    )


def _baranje_e_promena(prasanje: str, ai_akcija: str | None) -> bool:
    # dali korisnikot saka promena na postoecko dezurstvo
    if (ai_akcija or "").lower() == "promeni":
        return True
        # ako ai vekje zaklucil deka e promena
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in (
            "премести",
            "префрли",
            "промени",
            "промениш",
            "пренеси",
            "одложи",
            "смени",
            "може да го промениш",
            "da go promenish",
        )
    )


def _baranje_e_dodadi(prasanje: str, ai_akcija: str | None) -> bool:
    # dali korisnikot saka novo dezurstvo (INSERT)
    if (ai_akcija or "").lower() == "dodadi":
        return True
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in (
            "додади",
            "dodadi",
            "додадете",
            "внеси",
            "закажи дежурство",
            "ново дежурство",
            "нека биде дежур",
            "да биде дежур",
        )
    )


def _najdi_lekar(ime_prezime: str) -> dict | None:
    # funkcija za pronagjanje lekar vo baza
    if not ime_prezime:
        return None
        # ako nema ime ne moze da se prebaruva
    from ai._kernel.lekar_lookup import (
        izvlechi_delovi_ime,
        najdi_lekar_od_delovi,
        najdi_lekar_od_prasanje,
    )
    # lazy import — pobrzo startuvanje i izbegnuvanje circular imports

    delovi = izvlechi_delovi_ime(ime_prezime) or [
        d for d in ime_prezime.strip().split() if d
    ]
    # „Marija Hubreva" -> ["Marija", "Hubreva"]
    if len(delovi) >= 2:
        return najdi_lekar_od_delovi(delovi)
        # precizno prebaruvanje so ime i prezime
    return najdi_lekar_od_prasanje(ime_prezime)
    # fallback ako ima samo eden zbor


def _najdi_oddel_po_ime(oddel: str, specialty: str) -> str:
    # mapiranje hint od ai vo ime na oddel vo baza
    oddel = (oddel or "").strip()
    if oddel:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli")
        for (row,) in cur.fetchall():
            if row and (
                oddel.lower() in str(row).lower() or str(row).lower() in oddel.lower()
            ):
                cur.close()
                conn.close()
                return str(row)
        cur.close()
        conn.close()
    spec = (specialty or "").strip()
    return spec or "Општа"
    # fallback na specijalnost na lekarot


def _najdi_idno_dezurstvo(doctor_id: int) -> dict | None:
    # najblisko idno dezurstvo >= denes za toj lekar
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
        " WHERE doctor_ID = %s AND datum >= CURDATE()"
        " ORDER BY datum, vreme_od LIMIT 1",
        (doctor_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _najdi_dezurstvo(
    doctor_id: int,
    dezurstvo_id: int | None = None,
    na_datum: date | None = None,
) -> dict | None:
    # univerzalen prebaruvac: po id, po datum, ili najblisko idno
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    if dezurstvo_id:
        cur.execute(
            "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
            " WHERE dezurstvo_ID = %s AND doctor_ID = %s",
            (dezurstvo_id, doctor_id),
        )
    elif na_datum:
        cur.execute(
            "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
            " WHERE doctor_ID = %s AND datum = %s"
            " ORDER BY vreme_od LIMIT 1",
            (doctor_id, na_datum),
        )
    else:
        cur.close()
        conn.close()
        return _najdi_idno_dezurstvo(doctor_id)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _ima_preklop(
    doctor_id: int, datum: date, vreme_od: str, vreme_do: str
) -> bool:
    # proveruva dali lekarot vekje ima dezurstvo vo ist termin
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT dezurstvo_ID FROM Dezurstva
        WHERE doctor_ID = %s AND datum = %s
        AND (
            (vreme_od <= %s AND vreme_do >= %s) OR
            (vreme_od <= %s AND vreme_do >= %s) OR
            (vreme_od >= %s AND vreme_do <= %s)
        )
        """,
        (doctor_id, datum, vreme_od, vreme_od, vreme_do, vreme_do, vreme_od, vreme_do),
    )
    # sql proverka za preklopuvanje na vremenski intervali
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None
    # True = terminot e zafaten


def _as_date(d) -> date:
    # pomosna — siguren date objekt od mysql datetime/string
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if hasattr(d, "year") and hasattr(d, "month"):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def _valid_time(s: str) -> bool:
    # proveruva dali tekstot e validno vreme HH:MM
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except Exception:
        return False


def _dodadi_dezurstvo(
    found: dict,
    datum: date,
    vreme_od: str,
    vreme_do: str,
    oddel_hint: str | None,
) -> str:
    # INSERT novo dezurstvo — vraka poraka za chat
    oddel = _najdi_oddel_po_ime(oddel_hint or "", found.get("specialty") or "")
    if _ima_preklop(found["doctor_ID"], datum, vreme_od, vreme_do):
        return (
            f"Д-р {found['name']} {found['surname']} веќе има дежурство на "
            f"{format_datum(datum)} во тој временски период."
        )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO Dezurstva (doctor_ID, datum, oddel, vreme_od, vreme_do, napomena)
        VALUES (%s, %s, %s, %s, %s, NULL)
        """,
        (found["doctor_ID"], datum, oddel, vreme_od, vreme_do),
    )
    conn.commit()
    # commit e vazen — bez nego nema trajno zacuvuvanje
    cur.close()
    conn.close()

    return (
        f"Дежурството е додадено.\n\n"
        f"Лекар: д-р {found['name']} {found['surname']}\n"
        f"Оддел: {oddel}\n"
        f"Датум: {format_datum(datum)}\n"
        f"Време: {vreme_od}–{vreme_do}"
    )


def _prasanje_e_samo_pregled(prasanje: str) -> bool:
    # samo pregled — delegira na pregled_dezurstvo modul
    from ai._kernel.intent_detector import _prasanje_e_pregled_dezurstvo
    from ai._kernel.transliteracija import transliterijaj

    return _prasanje_e_pregled_dezurstvo(transliterijaj(prasanje).lower())


def _odgovor(tekst: str, found: dict | None, dez: dict | None) -> dict:
    # odgovor za chat + kontekst + signal za osvezi tabela
    out: dict = {"odgovor": tekst}
    if found:
        out["kontekst"] = izgradi_kontekst(found, dez)
    if "е додадено" in tekst or "е променето" in tekst:
        out["akcija"] = "osvezi_admin_dezurstva"
    return out


def odgovori_za_dezurstvo(
    prasanje: str,
    lekar: dict | None,
    kontekst: dict | None = None,
) -> dict:
    # glavna funkcija koja ja povikuva routerot
    # tuka pocnuva celata logika za dezurstva
    if err := require_direktor(lekar):
        # walrus operator := — zacuvuva i proveruva istovremeno
        return {"odgovor": err}
        # ako nema dozvola — vrakame greska

    if _prasanje_e_samo_pregled(prasanje):
        # samo pregled, ne promena/dodavanje
        from ai.opsto.pregled_dezurstvo import odgovori_za_pregled_dezurstvo

        raw = odgovori_za_pregled_dezurstvo(prasanje, lekar, kontekst)
        return raw if isinstance(raw, dict) else {"odgovor": raw}

    denes = date.today()
    # denesniot datum od sistemot
    dk = (kontekst or {}).get("dezurstvo_kontekst")
    # memorija od prethodniot razgovor (lekar, dezurstvo_id, datum, vreme)
    ai = _izvlechi_ai(prasanje, denes)
    if ai.get("_error"):
        return {"odgovor": ai["_error"]}

    ime = (ai.get("lekar") or "").strip()
    datum_str = ai.get("datum")
    vreme_od = ai.get("vreme_od")
    vreme_do = ai.get("vreme_do")
    oddel_hint = ai.get("oddel")

    if not datum_str:
        dt = _datum_od_tekst(prasanje, denes)
        if dt:
            datum_str = dt.isoformat()
    if not vreme_od and not vreme_do:
        ro, rd = _vreme_od_tekst(prasanje)
        vreme_od, vreme_do = ro, rd
    if not vreme_do:
        vd = _vreme_samo_do(prasanje)
        if vd:
            vreme_do = vd

    dodadi = _baranje_e_dodadi(prasanje, ai.get("akcija"))
    promena = _baranje_e_promena(prasanje, ai.get("akcija"))
    ista = _baranje_ista_data(prasanje)
    if dk and not dodadi and (promena or ista or vreme_do or _vreme_samo_do(prasanje)):
        promena = True
        # ima kontekst + menuvanje vreme → smetame deka e promena

    found = _najdi_lekar(ime) if ime else None
    if not found:
        found = lekar_od_kontekst(kontekst)
        # ako nema ime vo poraka — lekar od pretoden chat

    if not found:
        return {
            "odgovor": (
                "За кого е дежурството? Напиши име и презиме, "
                'или прво «Кога е дежурна д-р …?» па «Промени да е до 03:00».'
            )
        }

    # promena: datum od kontekst / ista data
    if promena and not dodadi:
        if (ista or not datum_str) and dk and dk.get("datum"):
            datum_str = dk["datum"]
        if not datum_str:
            dez_tmp = _najdi_dezurstvo(
                found["doctor_ID"],
                dk.get("dezurstvo_id") if dk else None,
                None,
            )
            if dez_tmp and dez_tmp.get("datum"):
                d = dez_tmp["datum"]
                datum_str = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]

    if dodadi and not datum_str:
        return {
            "odgovor": (
                "Кој датум треба да биде дежурството?\n"
                "Пример: «Додади ја д-р Марија Хубрева дежурна на 21 мај од 20:00 до 04:00»"
            )
        }

    if not datum_str:
        return {
            "odgovor": (
                "На кој датум е дежурството што го менуваме? "
                "Или напиши «на иста дата» ако веќе го погледнавме распоредот."
            )
        }

    try:
        nov_datum = datetime.strptime(str(datum_str)[:10], "%Y-%m-%d").date()
        # string -> python date objekt
    except Exception:
        return {"odgovor": f'Неважечки датум: „{datum_str}".'}

    if nov_datum < denes and dodadi:
        return {"odgovor": "Не можам да закажам дежурство во минатото."}

    if dodadi:
        # INSERT logika za novo dezurstvo
        if not vreme_od:
            vreme_od = "08:00"
            # default pocetok
        if not vreme_do:
            vreme_do = "20:00"
            # default kraj
        if not _valid_time(vreme_od) or not _valid_time(vreme_do):
            return {"odgovor": "Наведете време, на пр. «од 20:00 до 04:00»."}
        msg = _dodadi_dezurstvo(found, nov_datum, vreme_od, vreme_do, oddel_hint)
        dez = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
        return _odgovor(msg, found, dez)

    dez_id = int(dk["dezurstvo_id"]) if dk and dk.get("dezurstvo_id") else None
    dez = _najdi_dezurstvo(found["doctor_ID"], dez_id, nov_datum)
    if not dez:
        dez = _najdi_idno_dezurstvo(found["doctor_ID"])

    # nov datum vo poraka bez „премести" -> novo dezurstvo (ne go mrda postoeckoto)
    if (
        dez
        and not ista
        and _as_date(nov_datum) != _as_date(dez["datum"])
        and not _baranje_e_premesti_datum(prasanje)
        and vreme_od
        and vreme_do
        and _valid_time(vreme_od)
        and _valid_time(vreme_do)
    ):
        dez_na_datum = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
        if not dez_na_datum:
            msg = _dodadi_dezurstvo(found, nov_datum, vreme_od, vreme_do, oddel_hint)
            dez_new = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
            return _odgovor(msg, found, dez_new or dez)

    if not dez:
        if vreme_od and vreme_do and _valid_time(vreme_od) and _valid_time(vreme_do):
            msg = _dodadi_dezurstvo(found, nov_datum, vreme_od, vreme_do, oddel_hint)
            dez = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
            return _odgovor(msg, found, dez)
        return {
            "odgovor": (
                f"Д-р {found['name']} {found['surname']} нема дежурство на "
                f"{format_datum(nov_datum)} за промена."
            ),
            "kontekst": izgradi_kontekst(found, None),
        }

    if ista:
        nov_datum = _as_date(dez["datum"])
        # ostaj na istiot datum od postoeckoto dezurstvo

    if not vreme_od and dk and dk.get("vreme_od"):
        vreme_od = dk["vreme_od"]
    if not vreme_od and dez.get("vreme_od"):
        vreme_od = format_vreme(dez["vreme_od"])

    sets: list[str] = []
    # lista za dinamicko generiranje SQL UPDATE
    params: list = []
    # vrednosti za %s placeholderi
    if _as_date(nov_datum) != _as_date(dez["datum"]):
        sets.append("datum = %s")
        params.append(nov_datum)
    if vreme_od and _valid_time(vreme_od):
        sets.append("vreme_od = %s")
        params.append(vreme_od)
    if vreme_do and _valid_time(vreme_do):
        sets.append("vreme_do = %s")
        params.append(vreme_do)

    if not sets:
        return {
            "odgovor": (
                "Што точно да сменам? На пр. «на иста дата, да е до 03:00» "
                "или «премести за 25 мај»."
            ),
            "kontekst": izgradi_kontekst(found, dez),
        }

    params.append(dez["dezurstvo_ID"])
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE Dezurstva SET {', '.join(sets)} WHERE dezurstvo_ID = %s",
        params,
    )
    # dinamicki sql — primer: UPDATE Dezurstva SET datum = %s, vreme_do = %s WHERE ...
    conn.commit()
    cur.close()
    conn.close()

    dez = _najdi_dezurstvo(found["doctor_ID"], dez["dezurstvo_ID"], None)
    novo_do = vreme_do or format_vreme(dez.get("vreme_do"))
    novo_od = vreme_od or format_vreme(dez.get("vreme_od"))
    d_show = nov_datum if isinstance(nov_datum, date) else dez["datum"]

    msg = (
        f"Дежурството е променето.\n\n"
        f"Лекар: д-р {found['name']} {found['surname']}\n"
        f"Оддел: {dez['oddel']}\n"
        f"Датум: {format_datum(d_show)}\n"
        f"Време: {novo_od}–{novo_do}"
    )
    return _odgovor(msg, found, dez)
    # vrakja odgovor + nov kontekst za sledni poraki
