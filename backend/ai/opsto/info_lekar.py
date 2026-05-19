"""
Информации за конкретен лекар.

Како работи:
1. AI (Groq) препознава за кој лекар прашува корисникот (од листа во DB).
2. Враќа: специјалност, email, дали е дежурен (+ упатство за преглед / слободни термини).
"""

from datetime import date, datetime, time, timedelta

from database import get_connection
from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai
from ai._kernel.utils import format_vreme
from ai.pacient.slobodni_termini import (
    lekar_od_zakazi_kontekst,
    prasanje_bar_lekar_od_kontekst,
    prasanje_e_specijalnost_izbran_lekar,
)


def zimi_dezurstva_za_lekar(doctor_id: int, denovi_napred: int = 7) -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT datum, oddel, vreme_od, vreme_do
            FROM Dezurstva
            WHERE doctor_ID = %s
              AND datum BETWEEN %s AND %s
            ORDER BY datum, vreme_od
            """,
            (doctor_id, date.today(), date.today() + timedelta(days=denovi_napred)),
        )
        rezultati = cur.fetchall()
        cur.close()
        return rezultati
    except Exception as e:
        print(f"[info_lekar] dezurstva greska: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _as_time(v) -> time | None:
    if v is None:
        return None
    if isinstance(v, time):
        return v
    if hasattr(v, "hour") and hasattr(v, "minute"):
        return v  # datetime.time-like
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return time(s // 3600, (s % 3600) // 60)
    try:
        parts = str(v).strip().split(":")
        if len(parts) >= 2:
            return time(int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        pass
    return None


def _format_datum(datum: date) -> str:
    return datum.strftime("%d.%m.%Y")


def _dezurstvo_datum_vreme(d: dict) -> tuple[date | None, time | None, time | None]:
    datum = d.get("datum")
    if isinstance(datum, datetime):
        datum = datum.date()
    return datum, _as_time(d.get("vreme_od")), _as_time(d.get("vreme_do"))


def _e_na_dezurstvo_sega(d: dict, sega: datetime) -> bool:
    datum, vreme_od, vreme_do = _dezurstvo_datum_vreme(d)
    if not datum or datum != sega.date() or not vreme_od or not vreme_do:
        return False
    t = sega.time()
    return vreme_od <= t <= vreme_do


def _sledno_dezurstvo(dezurstva: list[dict], sega: datetime) -> dict | None:
    """Прво дежурство што сè уште не завршило (денес или иднина)."""
    for d in dezurstva:
        datum, vreme_od, vreme_do = _dezurstvo_datum_vreme(d)
        if not datum or not vreme_od:
            continue
        if datum > sega.date():
            return d
        if datum == sega.date() and vreme_do and sega.time() < vreme_do:
            return d
    return None


def _linija_za_dezurstvo(d: dict, prefiks: str) -> str:
    datum, vreme_od, _ = _dezurstvo_datum_vreme(d)
    if not datum:
        return prefiks
    return f"{prefiks}\nДатум: {_format_datum(datum)}\nПочеток на дежурство: {format_vreme(vreme_od)}"


def _dezuren_status(dezurstva: list[dict]) -> str:
    """
    Дежурен: Да — само ако во моментот е на дежурство (со датум и почеток).
    Дежурен: Не — ако не е сега; ако има идно дежурство, се печати датум и почеток.
    """
    if not dezurstva:
        return "Дежурен: Не"

    sega = datetime.now()
    for d in dezurstva:
        if _e_na_dezurstvo_sega(d, sega):
            return _linija_za_dezurstvo(d, "Дежурен: Да")

    sledno = _sledno_dezurstvo(dezurstva, sega)
    if sledno:
        return _linija_za_dezurstvo(sledno, "Дежурен: Не")

    return "Дежурен: Не"


def _resolviraj_lekar(prasanje: str, kontekst: dict | None) -> tuple[dict | None, bool]:
    from ai.pacient.slobodni_termini import lekar_iz_izbran_kontekst

    if prasanje_bar_lekar_od_kontekst(prasanje) or prasanje_e_specijalnost_izbran_lekar(
        prasanje, kontekst
    ):
        lekar = lekar_iz_izbran_kontekst(kontekst)
        if lekar:
            return lekar, True
    lekar = najdi_lekar_od_prasanje(prasanje)
    if lekar:
        return lekar, False
    lekar = lekar_od_zakazi_kontekst(kontekst)
    return lekar, lekar is not None


def prasanje_e_oblast_ili_specijalnost_lekar(prasanje: str) -> bool:
    """„Од која област е лекарот Драгица Тимова?" — конкретно име."""
    from ai._kernel.lekar_lookup import (
        _RE_POSLE_DR,
        _RE_POSLE_LEKAROT,
        izvlechi_delovi_ime,
    )

    p = transliterijaj(prasanje).lower()
    if any(x in p for x in ("лекари", "lekari", "доктори", "doktori", "кои лекари")):
        return False
    if not any(
        x in p
        for x in (
            "област",
            "специјалност",
            "oddel",
            "oblast",
            "specijalnost",
            "од која",
            "која е",
            "кое е",
            "од koja",
        )
    ):
        return False
    if _RE_POSLE_DR.search(p) or _RE_POSLE_LEKAROT.search(p):
        return True
    return len(izvlechi_delovi_ime(prasanje)) >= 2


def _sablon_oblast_lekar(lekar: dict) -> str:
    """Краток, точен одговор — без Groq („е инфектологија" и слично)."""
    spec = (lekar.get("specialty") or "Општа пракса").strip()
    prezime = (lekar.get("surname") or "").strip()
    ime = f"д-р {lekar['name']} {lekar['surname']}"
    return (
        f"Специјалноста на {ime} е {spec}.\n\n"
        f'За слободни термини: „Кога е слободен д-р {prezime}?"'
    )


def _e_prasanje_dali_raboti(prasanje: str) -> bool:
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in (
            "работи",
            "вработен",
            "дали работи",
            "дали е вработен",
            "работи ли",
            "има ли тука",
            "дали е тука",
            "во оваа болница",
            "во болницата",
            "dali raboti",
            "raboti li",
        )
    )


def _dezurstvo_za_fakti(dezurstva: list[dict]) -> dict[str, str]:
    sega = datetime.now()
    for d in dezurstva:
        if _e_na_dezurstvo_sega(d, sega):
            datum, vreme_od, _ = _dezurstvo_datum_vreme(d)
            return {
                "status": "da_sega",
                "datum": _format_datum(datum) if datum else "",
                "pocetok": format_vreme(vreme_od),
            }
    sledno = _sledno_dezurstvo(dezurstva, sega)
    if sledno:
        datum, vreme_od, _ = _dezurstvo_datum_vreme(sledno)
        return {
            "status": "ne_so_idno",
            "datum": _format_datum(datum) if datum else "",
            "pocetok": format_vreme(vreme_od),
        }
    return {"status": "ne", "datum": "", "pocetok": ""}


def _sablon_info_lekar(
    lekar: dict, prasanje: str, od_kontekst: bool, kontekst: dict | None = None
) -> str:
    """Шаблон fallback — истата содржина како порано."""
    spec = lekar.get("specialty") or "Општа пракса"
    email = (lekar.get("email") or "").strip()
    doctor_id = lekar["doctor_ID"]
    dezurstva = zimi_dezurstva_za_lekar(doctor_id)
    prezime = lekar.get("surname") or ""
    ime = f"д-р {lekar['name']} {lekar['surname']}"

    footer = [
        "",
        "Доколку сакате преглед, најавете се со кориснички профил на сајтот.",
        f'За слободни термини напишете: „Кога е слободен д-р {prezime}?"',
    ]

    # Избраниот лекар / област — само име, специјалност, email
    if prasanje_e_specijalnost_izbran_lekar(prasanje, kontekst):
        return "\n".join(
            [
                f"Име и презиме: {lekar['name']} {lekar['surname']}",
                f"Специјалност: {spec}",
                f"Email: {email if email else '—'}",
            ]
        )

    if prasanje_e_oblast_ili_specijalnost_lekar(prasanje):
        return _sablon_oblast_lekar(lekar)

    # Општи информации за лекар
    delovi = [f"{ime} ({spec})"]
    if od_kontekst:
        delovi.append("(Од претходната порака во разговорот.)")
    if _e_prasanje_dali_raboti(prasanje):
        delovi.append("")
        delovi.append("Да, работи во Клиничка Болница Штип.")
    delovi.extend(
        [
            "",
            f"Email: {email if email else '—'}",
            _dezuren_status(dezurstva),
            *footer,
        ]
    )
    return "\n".join(delovi)


def _format_info_lekar(
    lekar: dict, prasanje: str, od_kontekst: bool, kontekst: dict | None = None
) -> str:
    sablon = _sablon_info_lekar(lekar, prasanje, od_kontekst, kontekst)
    if prasanje_e_specijalnost_izbran_lekar(
        prasanje, kontekst
    ) or prasanje_e_oblast_ili_specijalnost_lekar(prasanje):
        return sablon

    spec = lekar.get("specialty") or "Општа пракса"
    email = (lekar.get("email") or "").strip()
    dezurstva = zimi_dezurstva_za_lekar(lekar["doctor_ID"])
    prezime = lekar.get("surname") or ""

    podatoci = {
        "ustanova": "Клиничка Болница Штип",
        "ime": lekar.get("name") or "",
        "prezime": prezime,
        "specialnost": spec,
        "email": email or None,
        "dezurstvo": _dezurstvo_za_fakti(dezurstva),
        "raboti_vo_bolnica": True,
        "od_kontekst": od_kontekst,
        "prasanje_dali_raboti": _e_prasanje_dali_raboti(prasanje),
        "sledna_akcija": (
            f'За слободни термини: „Кога е слободен д-р {prezime}?". '
            "За преглед — најава со кориснички профил на сајтот."
        ),
    }
    return formatiraj_odgovor_so_ai(
        "info_lekar",
        podatoci,
        sablon,
        prasanje=prasanje,
    )


def _kontekst_posle_info(lekar: dict, kontekst: dict | None) -> dict:
    did = int(lekar["doctor_ID"])
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": did,
        "datum": (ctx.get("zakazi_od_slobodni") or {}).get("datum"),
    }
    ctx["last_doctor_id"] = did
    return ctx


def odgovori_za_info_lekar(prasanje: str, kontekst: dict | None = None) -> str | dict:
    lekar, od_kontekst = _resolviraj_lekar(prasanje, kontekst)

    if not lekar:
        from ai.pacient.moi_pregledi import prasanje_e_pregledi_datum
        from ai.opsto.vest_naslov import pronajdi_vest_po_naslov

        from ai.pacient.moi_pregledi import prasanje_e_lista_site_pregledi

        if prasanje_e_lista_site_pregledi(prasanje):
            return {
                "odgovor": (
                    "За листа на прегледи најавете се како лекар или пациент, па напишете, на пр.:\n"
                    "„Прикажи ми закажани прегледи“ (лекар) или „Моите прегледи“ / "
                    "„Прикажи ги сите прегледи“ (пациент)."
                ),
                "kontekst": kontekst if isinstance(kontekst, dict) else None,
            }

        if prasanje_e_pregledi_datum(prasanje):
            return {
                "odgovor": (
                    "За термини на датум најавете се како пациент или лекар, па напишете, на пр.:\n"
                    "„Прегледи за 19.05“ (пациент) или „Прикажи закажани прегледи“ / "
                    "„Termini na 25.05“ (лекар)."
                ),
                "kontekst": kontekst if isinstance(kontekst, dict) else None,
            }

        vest = pronajdi_vest_po_naslov(prasanje)
        if vest:
            naslov = (vest.get("naslov") or "").strip()
            return {
                "odgovor": (
                    f"Ова личи на наслов на вест, не на име на лекар: „{naslov}“.\n\n"
                    "За бришење (само директор) напишете, на пр.:\n"
                    f"„Избриши ја веста со наслов {naslov}“."
                ),
                "kontekst": kontekst if isinstance(kontekst, dict) else None,
            }
        if prasanje_bar_lekar_od_kontekst(prasanje) or prasanje_e_specijalnost_izbran_lekar(
            prasanje, kontekst
        ):
            return {
                "odgovor": (
                    "Не гледам зачуван избран лекар од претходната порака.\n\n"
                    "Прво наведете го лекарот (на пр. „Кога е слободен д-р Петровски?“) "
                    "или закажете преглед, па повторете."
                ),
                "kontekst": kontekst,
            }
        return {
            "odgovor": (
                "Не најдов лекар со тоа име во евиденцијата на Клиничка Болница Штип.\n"
                'Проверете го правописот или пребарајте на сајтот во делот „Лекари".\n'
                'Пример: „Информации за д-р Марко Петров" или „Дали работи др Марија Хубрева?"'
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    text = _format_info_lekar(lekar, prasanje, od_kontekst, kontekst)
    return {"odgovor": text, "kontekst": _kontekst_posle_info(lekar, kontekst)}
