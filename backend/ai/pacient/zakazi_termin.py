"""
Закажување термин преку AI асистент.

Како работи:
1. Пациентот пишува: „Сакам преглед кај д-р Петров среда 10:00"
2. AI (Groq) ги извлекува: doctor_id, datum, vreme
3. Проверуваме во база дали:
   - Лекарот постои
   - Терминот е во иднина
   - Не е сабота/недела
   - Не е веќе зафатен
4. INSERT во Termin_pregled
5. Праќаме email потврда + враќаме потврда во чет

Бара: пациентот да биде логиран (frontend праќа неговите податоци)
"""

import json
import re
from datetime import datetime, date, time
from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai
from ai._kernel.prompts import ZAKAZI_EXTRACT_PROMPT
from ai.pacient.slobodni_termini import (
    baranje_e_zakazuvanje,
    datum_od_prasanje_lokalno,
    lekar_od_zakazi_kontekst,
    prasanje_bar_datum_od_kontekst,
    zimi_site_lekari,
)
from ai._kernel.db_helpers import db_cursor
from ai._kernel.utils import format_datum, format_vreme


# Работно време - не дозволуваме закажување надвор
RABOTNO_OD = time(8, 0)     # pocetok na rabotno vreme 
RABOTNO_DO = time(15, 30)   # kraj na rabotno vreme 


def _normalize_doctor_id(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _spoi_zakazi_so_slobodni_kontekst(
    prasanje: str,
    izvleceno: dict,
    kontekst: dict | None,
) -> None:
    """Дополнува doctor_id/datum/vreme од конверзација по слободни термини (in-place)."""
    if not kontekst:
        return
    zos = kontekst.get("zakazi_od_slobodni")
    if not isinstance(zos, dict):
        zos = kontekst.get("zakazi_pending")
    if not isinstance(zos, dict):
        return
    p = (prasanje or "").lower()
    izbran = any(
        x in p
        for x in (
            "избраниот",
            "избраниов",
            "истиот",
            "истиов",
            "погоре",
            "од листата",
            "од горе",
        )
    )
    koristi_kontekst_datum = izbran or prasanje_bar_datum_od_kontekst(prasanje)
    prodolzuva = baranje_e_zakazuvanje(prasanje)
    nov_datum = datum_od_prasanje_lokalno(prasanje)

    from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_prasanje

    lekar_od_ime = None
    if izvlechi_delovi_ime(prasanje):
        lekar_od_ime = najdi_lekar_od_prasanje(prasanje, koristi_ai=True)
    if lekar_od_ime and not izbran:
        izvleceno["doctor_id"] = int(lekar_od_ime["doctor_ID"])

    nid = _normalize_doctor_id(zos.get("doctor_id"))
    if nid is not None:
        if not _normalize_doctor_id(izvleceno.get("doctor_id")):
            izvleceno["doctor_id"] = nid
        elif izbran or (prodolzuva and not lekar_od_ime):
            izvleceno["doctor_id"] = nid
    if zos.get("datum"):
        d = str(zos["datum"]).strip()[:10]
        if d:
            if nov_datum is not None:
                izvleceno["datum"] = nov_datum.isoformat()
            elif koristi_kontekst_datum or prodolzuva or not izvleceno.get("datum"):
                izvleceno["datum"] = d
    if zos.get("vreme") and not izvleceno.get("vreme"):
        v = str(zos["vreme"]).strip()[:5]
        if v:
            izvleceno["vreme"] = v
    if isinstance(kontekst, dict):
        if not izvleceno.get("datum") and kontekst.get("last_slobodni_datum"):
            izvleceno["datum"] = str(kontekst["last_slobodni_datum"]).strip()[:10]
        if not izvleceno.get("vreme") and kontekst.get("last_slobodni_vreme"):
            izvleceno["vreme"] = str(kontekst["last_slobodni_vreme"]).strip()[:5]


def _oddel_od_prasanje(prasanje: str) -> str | None:
    """Специјалност/оддел од текст (правила + алијаси, без задолжително Groq)."""
    from ai._kernel.oddel_resolver import resolve_oddel

    r = resolve_oddel(prasanje or "")
    if r.ok and r.oddel:
        return r.oddel
    return None


def _lekari_po_oddel(oddel: str) -> list[dict]:
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s))
                ORDER BY surname, name
                """,
                (oddel,),
            )
            return list(cur.fetchall())
    except Exception as e:
        print(f"[zakazi_termin] lekari_po_oddel: {e}")
        return []


def vreme_od_prasanje_lokalno(prasanje: str) -> str | None:
    """Час од „во 11“, „11:30“, „11 часот“ — без Groq."""
    import re

    from ai._kernel.transliteracija import transliterijaj

    p = transliterijaj(prasanje or "").lower().strip()
    if not p:
        return None

    m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", p)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"

    m = re.search(
        r"(?:во|vo|at)\s+(\d{1,2})(?:\s*(?:час|часот|cas|casot))?\b",
        p,
    )
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    m = re.search(r"\b(\d{1,2})\s*(?:час|часот|cas|casot)\b", p)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    if re.fullmatch(r"\d{1,2}", p):
        h = int(p)
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    return None


def _dopolnuvaj_izvleceno_lokalno(prasanje: str, izvleceno: dict) -> None:
    """Датум/време/лекар од правила — без Groq."""
    from ai._kernel.groq_client import groq_e_isklucen
    from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_prasanje

    if not _normalize_doctor_id(izvleceno.get("doctor_id")):
        if izvlechi_delovi_ime(prasanje):
            lekar = najdi_lekar_od_prasanje(prasanje, koristi_ai=True)
            if lekar:
                izvleceno["doctor_id"] = int(lekar["doctor_ID"])
    if not izvleceno.get("datum"):
        d = datum_od_prasanje_lokalno(prasanje)
        if d is not None:
            izvleceno["datum"] = d.isoformat()
    if not izvleceno.get("vreme"):
        v = vreme_od_prasanje_lokalno(prasanje)
        if v:
            izvleceno["vreme"] = v

def _ima_dovolno_za_zakaz_flow(izvleceno: dict) -> bool:
    """Дали после локално+AI извлекување има смисла да продолжи закажување."""
    return bool(
        _normalize_doctor_id(izvleceno.get("doctor_id"))
        or izvleceno.get("datum")
        or izvleceno.get("vreme")
        or izvleceno.get("specialty")
    )


def _linii_lekari_specijalnost(oddel: str, lekari: list[dict]) -> list[str]:
    linii = [
        f"За преглед кај {oddel} во Клиничка Болница Штип, изберете лекар:",
        "",
    ]
    for l in lekari:
        linii.append(f"- Д-р {l['name']} {l['surname']}")
    return linii


def _poraka_izberi_lekar_specijalnost(
    oddel: str,
    lekari: list[dict],
    datum_str: str | None,
    kontekst: dict | None,
) -> dict:
    from ai.opsto.lekari_oddel import navigacija_lekari

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]
    linii = _linii_lekari_specijalnost(oddel, lekari)
    if datum_str:
        try:
            dt = datetime.strptime(str(datum_str)[:10], "%Y-%m-%d").date()
            linii.append(
                f"\nЗа датумот: {DENOVI[dt.weekday()]}, {format_datum(dt)}."
            )
        except ValueError:
            linii.append(f"\nЗа датумот: {datum_str}.")
    linii.extend(
        [
            "",
            "Наведете презиме (на пр. „кај Петров“) или прашајте:",
            "„Кога е слободен д-р [презиме]?“ — ќе ви прикажам слободни часови.",
            "",
            "Можете и на страницата „Лекари“ да ги видите филтрирани по специјалност "
            "(го отворам делот подолу).",
        ]
    )
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    pending = dict(ctx.get("zakazi_pending") or {})
    pending["specialty"] = oddel
    if datum_str:
        pending["datum"] = str(datum_str).strip()[:10]
    if _normalize_doctor_id(pending.get("doctor_id")) is None:
        pending.pop("doctor_id", None)
    ctx["zakazi_pending"] = pending
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": pending.get("doctor_id"),
        "datum": pending.get("datum"),
    }
    return {
        "odgovor": "\n".join(linii),
        "kontekst": ctx,
        "navigacija": navigacija_lekari(oddel, lekari),
    }


def _vrati_zakazi_poraka(
    odgovor: str,
    kontekst: dict | None,
    izvleceno: dict,
    prasanje: str | None = None,
) -> dict:
    """Порака + зачуван контекст (лекар/датум/време) за следна порака."""
    return {
        "odgovor": odgovor,
        "kontekst": _snimi_zakazi_pending(kontekst, izvleceno, prasanje),
    }


def _snimi_zakazi_pending(
    kontekst: dict | None,
    izvleceno: dict,
    prasanje: str | None = None,
) -> dict | None:
    """Зачувај лекар/датум/време/специјалност за продолжување по најава."""
    pending: dict = {}
    zos = {}
    if isinstance(kontekst, dict):
        pending = dict(kontekst.get("zakazi_pending") or {})
        zos = kontekst.get("zakazi_od_slobodni") or {}
        if not isinstance(zos, dict):
            zos = {}

    did = _normalize_doctor_id(izvleceno.get("doctor_id")) or _normalize_doctor_id(
        zos.get("doctor_id")
    )
    if did is not None:
        pending["doctor_id"] = did
    datum = izvleceno.get("datum") or zos.get("datum")
    if datum:
        pending["datum"] = str(datum).strip()[:10]
    vreme = izvleceno.get("vreme") or zos.get("vreme")
    if vreme:
        pending["vreme"] = str(vreme).strip()[:5]
    if prasanje and not pending.get("specialty"):
        oddel = _oddel_od_prasanje(prasanje)
        if oddel:
            pending["specialty"] = oddel

    if not pending:
        return kontekst

    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_pending"] = pending
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": pending.get("doctor_id"),
        "datum": pending.get("datum"),
        "vreme": pending.get("vreme"),
    }
    if pending.get("doctor_id") is not None:
        ctx["last_doctor_id"] = int(pending["doctor_id"])
    return ctx


def izvlechi_podatoci_so_ai(prasanje: str) -> dict:
    """
    Прашува AI (Groq) да ги извлече: лекар, датум, време од прашањето.

    Враќа dict со 3 полиња:
    {"doctor_id": int|None, "datum": str|None, "vreme": str|None}
    """
    site_lekari = zimi_site_lekari()

    # Lista na lekari koj ke gi koriste AI
    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса" or "Општа медицина"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"

    denes = date.today().strftime("%Y-%m-%d")
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]

    full_prompt = f""" Денешен датум: {denes} ({den_vo_nedela})
Листа на лекари:
{lista_text}

Корисник пишува: „{prasanje}"

Извлечи doctor_id, datum, vreme и врати JSON.
""".strip()

    from ai._kernel.groq_helpers import izvlechi_json_so_ai

    podatoci = izvlechi_json_so_ai(
        full_prompt, ZAKAZI_EXTRACT_PROMPT, log_tag="zakazi_termin"
    )

    if podatoci.get("_error"):
        return {
            "doctor_id": None,
            "datum": None,
            "vreme": None,
            "_error": podatoci["_error"],
        }
    result = {
        "doctor_id": podatoci.get("doctor_id"),
        "datum": podatoci.get("datum"),
        "vreme": podatoci.get("vreme"),
    }
    print(f"[zakazi_termin] Parsed: {result}")
    return result


def proveri_dali_e_slobodno(doctor_id: int, datum_str: str, vreme_str: str) -> bool:
    """Проверка дали терминот е слободен (не е веќе закажан)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT termin_ID FROM Termin_pregled
            WHERE doctor_ID = %s
              AND DATE(datum_pregled) = %s
              AND TIME(vreme_pregled) = %s
              AND status_pregled = 'закажан'
        """, (doctor_id, datum_str, vreme_str))
        return cur.fetchone() is None
    except Exception as e:
        print(f"[zakazi_termin] proveri_dali_e_slobodno: {e}")
        return False
    finally:
        if conn:
            conn.close()


def _kontekst_ceka_napomena(kontekst: dict | None) -> dict | None:
    z = (kontekst or {}).get("zakazi_ceka_napomena")
    if isinstance(z, dict) and z.get("doctor_id") and z.get("datum") and z.get("vreme"):
        return z
    return None


def _prasanje_odbiva_napomena(prasanje: str) -> bool:
    p = re.sub(r"\s+", " ", (prasanje or "").strip().lower())
    if not p:
        return False
    if p in (
        "не",
        "неа",
        "нема",
        "немам",
        "no",
        "nema",
        "нема напомена",
        "без напомена",
        "не сакам",
        "не сакам напомена",
    ):
        return True
    return any(
        x in p
        for x in (
            "нема напомена",
            "без напомена",
            "не сакам напомена",
            "не сакам да оставам",
            "нема да оставам",
        )
    )


def _prasanje_samo_potvrda_da(prasanje: str) -> bool:
    p = re.sub(r"\s+", " ", (prasanje or "").strip().lower())
    return p in ("да", "da", "се", "сеа", "во ред", "ok", "okay")


def _postavi_ceka_napomena(
    kontekst: dict | None,
    doctor_id: int,
    datum_str: str,
    vreme_str: str,
) -> dict:
    ctx = dict(kontekst) if kontekst else {}
    ctx["zakazi_ceka_napomena"] = {
        "doctor_id": int(doctor_id),
        "datum": datum_str,
        "vreme": vreme_str,
    }
    return ctx


def _poraka_prasanje_napomena(ime_lekar: str, datum_lepo: str, vreme_str: str) -> str:
    return (
        f"Сè е подготвено за закажување кај {ime_lekar} на {datum_lepo} во {vreme_str}.\n\n"
        "Дали сакате да оставите напомена за лекарот?\n"
        "Напишете ја (на пр. алергија, претходна терапија) или кажете „не\" / „нема напомена\"."
    )


def vmetni_termin_vo_baza(
    doctor_id: int,
    ime_pacient: str,
    email_pacient: str,
    telefon_pacient: str,
    datum_str: str,
    vreme_str: str,
    napomena: str | None = None,
) -> tuple[bool, str, dict | None]:
    """
    INSERT во Termin_pregled.

    Враќа: (uspeshno, poraka_za_greska, podatoci_za_lekarot)
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # Земи податоци за лекарот
        cur.execute("SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s", (doctor_id,))
        doctor = cur.fetchone()
        if not doctor:
            return False, "Лекарот не постои.", None

        ime_lekar = f"{doctor['name']} {doctor['surname']}"
        napomena_db = (napomena or "").strip() or None

        cur.execute("""
            INSERT INTO Termin_pregled
            (doctor_ID, ime_pacient, specijalnost_termin, ime_lekar,
             datum_pregled, vreme_pregled, status_pregled, email_pacient,
             telefon_pacient, napomena)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            doctor_id,
            ime_pacient,
            doctor.get('specialty') or '',
            ime_lekar,
            datum_str,
            vreme_str,
            'закажан',
            email_pacient,
            telefon_pacient,
            napomena_db,
        ))
        conn.commit()
        cur.close()

        return True, "", {
            "doctor_id": doctor_id,
            "ime_lekar": ime_lekar,
            "specialty": doctor.get('specialty') or 'Општа пракса',
        }

    except Exception as e:
        return False, f"Грешка при запис: {str(e)}", None
    finally:
        if conn:
            conn.close()


def _finaliziraj_zakazuvanje(
    doctor_id: int,
    datum_str: str,
    vreme_str: str,
    pacient: dict,
    kontekst: dict | None,
    napomena: str | None,
) -> str | dict:
    """Валидација (повторна), INSERT, email и потврда."""
    did = int(doctor_id)
    ds = str(datum_str)
    vs = str(vreme_str)

    if not proveri_dali_e_slobodno(did, ds, vs):
        ctx = dict(kontekst) if kontekst else {}
        ctx.pop("zakazi_ceka_napomena", None)
        return {
            "odgovor": (
                "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно."
            ),
            "kontekst": ctx,
        }

    ime_pacient = (
        (pacient.get("ime") or pacient.get("name_patient") or "")
        + " "
        + (pacient.get("prezime") or pacient.get("surname_patient") or "")
    ).strip()
    if not ime_pacient:
        ime_pacient = pacient.get("email", "")

    email_pacient = pacient.get("email", "")
    telefon_pacient = pacient.get("telefon") or pacient.get("phone_number") or ""

    uspesno, greska, info = vmetni_termin_vo_baza(
        doctor_id=did,
        ime_pacient=ime_pacient,
        email_pacient=email_pacient,
        telefon_pacient=telefon_pacient,
        datum_str=ds,
        vreme_str=vs,
        napomena=napomena,
    )

    if not uspesno:
        return {
            "odgovor": f"Не успеа закажувањето: {greska}",
            "kontekst": kontekst,
        }

    try:
        from routers.termini import _poslati_potvrda_na_email

        _poslati_potvrda_na_email(
            to_email=email_pacient,
            ime_pacient=ime_pacient,
            ime_lekar=info["ime_lekar"],
            datum=ds,
            vreme=vs,
        )
    except Exception as e:
        print(f"[zakazi_termin] email greska: {e}")

    return {
        "odgovor": formatiraj_potvrda(
            ime_pacient=ime_pacient,
            ime_lekar=info["ime_lekar"],
            specialty=info["specialty"],
            datum_str=ds,
            vreme_str=vs,
        ),
        "kontekst": {
            "zakazi_od_slobodni": {
                "doctor_id": did,
                "datum": ds,
            },
            "last_doctor_id": did,
        },
    }


def _odgovori_napomena_faza(
    prasanje: str,
    pacient: dict,
    ceka: dict,
    kontekst: dict | None,
) -> str | dict:
    did = int(ceka["doctor_id"])
    ds = str(ceka["datum"])
    vs = str(ceka["vreme"])

    if _prasanje_odbiva_napomena(prasanje):
        return _finaliziraj_zakazuvanje(did, ds, vs, pacient, kontekst, napomena=None)

    if _prasanje_samo_potvrda_da(prasanje):
        return {
            "odgovor": (
                "Во ред. Напишете ја напомената за лекарот "
                "(на пр. алергија, хронична болест) во следната порака."
            ),
            "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
        }

    tekst = (prasanje or "").strip()
    if len(tekst) < 2:
        return {
            "odgovor": (
                "Напишете ја напомената или кажете „не\" ако не сакате да оставите напомена."
            ),
            "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
        }

    return _finaliziraj_zakazuvanje(did, ds, vs, pacient, kontekst, napomena=tekst)


def formatiraj_potvrda(ime_pacient: str, ime_lekar: str, specialty: str, datum_str: str, vreme_str: str) -> str:
    """Текст потврда за корисникот — Groq од факти, шаблон при грешка."""
    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]
    dt = datetime.strptime(datum_str, "%Y-%m-%d").date()
    den_ime = DENOVI[dt.weekday()]
    datum_lep = format_datum(dt)

    sablon = (
        "Задачата за закажување е успешно завршена. Еве што е направено во системот.\n\n"
        f"Пациент: {ime_pacient}\n"
        f"Лекар: Д-р {ime_lekar}\n"
        f"Специјалност: {specialty}\n"
        f"Датум: {den_ime}, {datum_lep}\n"
        f"Време: {vreme_str}\n\n"
        "Потврда е испратена на твојата е-пошта ако е поставен SMTP на серверот. "
        "Ако сакаш промена (откажување или преместување), напиши со свои зборови — "
        "агентот ги препознава формулациите „откажи термин“, „префрли на друг ден“ и слично."
    )
    podatoci = {
        "status": "zakazano",
        "pacient": ime_pacient,
        "lekar": f"Д-р {ime_lekar}",
        "specialnost": specialty,
        "datum": datum_lep,
        "den": den_ime,
        "vreme": vreme_str,
        "email_potvrda": True,
        "sledna_akcija": (
            "За откажување или преместување напишете „откажи термин“ или „префрли на друг ден“."
        ),
    }
    return formatiraj_odgovor_so_ai("zakazi_potvrda", podatoci, sablon)


def _vo_zakazi_flow(prasanje: str, kontekst: dict | None) -> bool:
    """Дали пораката навистина продолжува закажување (не случаен медицински текст)."""
    if baranje_e_zakazuvanje(prasanje):
        return True
    if _kontekst_ceka_napomena(kontekst):
        return True
    if not isinstance(kontekst, dict):
        return False
    if kontekst.get("zakazi_ceka_napomena"):
        return True
    if kontekst.get("zakazi_pending") or kontekst.get("zakazi_od_slobodni"):
        q = (prasanje or "").lower()
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
            return True
        if any(
            x in q
            for x in (
                "закаж",
                "zakaz",
                "термин",
                "termin",
                "напомена",
                "немам",
                "нема",
                "не ",
                "кај ",
                "kaj ",
                "утре",
                "време",
                "датум",
            )
        ):
            return True
    return False


def odgovori_za_zakazuvanje(
    prasanje: str,
    pacient: dict | None,
    kontekst: dict | None = None,
) -> str | dict:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prasanje - целото прашање
        pacient   - dict со пациент податоци од frontend, или None ако не е логиран
        kontekst  - опционално од претходен одговор (на пр. zakazi_od_slobodni по листа слободни)

    Враќа: текст (str) или dict со „odgovor“, опционално „akcija“, опционално „kontekst“ (None = избриши го на фронтот).
    """
    if not _vo_zakazi_flow(prasanje, kontekst):
        return {
            "odgovor": (
                "Не го препознав ова како барање за закажување термин.\n\n"
                "За закажување напишете, на пр.: „Закажи кај д-р Петров утре во 10:00“.\n"
                "За општо прашање опишете го со други зборови."
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    izvleceno = izvlechi_podatoci_so_ai(prasanje)
    _spoi_zakazi_so_slobodni_kontekst(prasanje, izvleceno, kontekst)

    ceka_napomena = _kontekst_ceka_napomena(kontekst)
    if ceka_napomena and pacient and pacient.get("email"):
        return _odgovori_napomena_faza(prasanje, pacient, ceka_napomena, kontekst)

    # Проверка дали пациентот е логиран — фронтот ја отвора формата за најава како пациент
    if not pacient or not pacient.get("email"):
        from ai.opsto.lekari_oddel import navigacija_lekari

        oddel = None
        if isinstance(kontekst, dict):
            lekar_ctx = lekar_od_zakazi_kontekst(kontekst)
            if lekar_ctx:
                oddel = (lekar_ctx.get("specialty") or "").strip() or None
        if not oddel:
            oddel = _oddel_od_prasanje(prasanje)
        spec_hint = ""
        nav = None
        if oddel:
            lekari = _lekari_po_oddel(oddel)
            datum_hint = (
                f", датум {izvleceno['datum'][:10]}"
                if izvleceno.get("datum")
                else ""
            )
            if lekari:
                spec_hint = (
                    "\n\n"
                    + "\n".join(_linii_lekari_specijalnost(oddel, lekari))
                    + f"\n\nЗачувано: специјалност „{oddel}“{datum_hint}. "
                    "По најава наведете презиме (на пр. „кај Петров“)."
                )
                nav = navigacija_lekari(oddel, lekari)
            else:
                spec_hint = (
                    f"\n\nЗачувано: специјалност „{oddel}“{datum_hint}. "
                    "По најава изберете лекар (презиме)."
                )
        odgovor: dict = {
            "odgovor": (
                "За да закажам термин во твое име, треба да се најавиш како пациент "
                "(системот ги користи твоето име, е-пошта и телефон од профилот).\n\n"
                "Ти ја отворам формата за најава — по најавата повтори ја истата наредба; "
                "можеш и поинаку, на пример „закажи во 10:00“ или „за претходно спомнатиот датум“."
                f"{spec_hint}"
            ),
            "akcija": "otvori_pacient_login",
            "kontekst": _snimi_zakazi_pending(kontekst, izvleceno, prasanje),
        }
        if nav:
            odgovor["navigacija"] = nav
        return odgovor

    # Groq грешка само ако локално не се извлече ништо корисно
    if izvleceno.get("_error") and not _ima_dovolno_za_zakaz_flow(izvleceno):
        err = izvleceno["_error"]
        return err if isinstance(err, str) else str(err)

    doctor_id = _normalize_doctor_id(izvleceno.get("doctor_id"))
    datum_str = izvleceno.get("datum")
    vreme_str = izvleceno.get("vreme")
    if datum_str is not None:
        datum_str = str(datum_str).strip()[:10] if str(datum_str).strip() else None
    if vreme_str is not None:
        vreme_str = str(vreme_str).strip()[:5] if str(vreme_str).strip() else None

    # Што недостасува? Поспецифична порака според комбинацијата:
    ima_lekar = bool(doctor_id)
    ima_datum = bool(datum_str)
    ima_vreme = bool(vreme_str)

    # Земи име на лекар за персонализирана порака
    ime_lekar_za_poraka = ""
    if ima_lekar:
        try:
            for lekar in zimi_site_lekari():
                if lekar.get("doctor_ID") == doctor_id:
                    ime_lekar_za_poraka = f"Д-р {lekar.get('name', '')} {lekar.get('surname', '')}".strip()
                    break
        except Exception:
            pass

    # Сите три недостасуваат → провери специјалност (кардиолог, дерматолог, …)
    if not ima_lekar and not ima_datum and not ima_vreme:
        oddel = _oddel_od_prasanje(prasanje)
        if oddel:
            lekari = _lekari_po_oddel(oddel)
            if lekari:
                return _poraka_izberi_lekar_specijalnost(
                    oddel, lekari, None, kontekst
                )
        return _vrati_zakazi_poraka(
            "Го разбирам барањето како закажување на преглед, но недостасуваат клучни податоци.\n\n"
            "Потребни се: лекар (име или презиме), датум и време. "
            "Можеш да ги кажеш во една реченица или во повеќе пораки — агентот ги собира.\n\n"
            'Пример: „Сакам преглед кај д-р Петров среда во 10:00"\n'
            'или: „Закажи кај Серафимов утре во 12:30".',
            kontekst,
            izvleceno,
            prasanje,
        )

    # Имаме само лекар - прашај за датум и време
    if ima_lekar and not ima_datum and not ima_vreme:
        lekar_text = ime_lekar_za_poraka or "избраниот лекар"
        return _vrati_zakazi_poraka(
            f'Кога би сакал/а да закажеш термин кај {lekar_text}?\n\n'
            f'Кажи ми датум и време. Пример:\n'
            f'„утре во 10:00" или „среда во 14:30"',
            kontekst,
            izvleceno,
            prasanje,
        )

    # Имаме лекар + датум, нема време
    if ima_lekar and ima_datum and not ima_vreme:
        lekar_text = ime_lekar_za_poraka or "лекарот"
        try:
            dt = datetime.strptime(str(datum_str)[:10], "%Y-%m-%d").date()
            datum_lepo = format_datum(dt)
        except ValueError:
            datum_lepo = datum_str
        pret = (
            " (претходно спомнатиот ден)"
            if prasanje_bar_datum_od_kontekst(prasanje)
            else ""
        )
        return _vrati_zakazi_poraka(
            f"Во кое време сакаш термин кај {lekar_text} на {datum_lepo}{pret}?\n\n"
            f"Работно време: {format_vreme(RABOTNO_OD)} – "
            f"{format_vreme(RABOTNO_DO)}\n"
            'Пример: „во 10:00“ или „закажи во 10:30“.',
            kontekst,
            izvleceno,
            prasanje,
        )

    # Имаме лекар + време, нема датум
    if ima_lekar and not ima_datum and ima_vreme:
        lekar_text = ime_lekar_za_poraka or "лекарот"
        return _vrati_zakazi_poraka(
            f'Кој датум сакаш термин кај {lekar_text} во {vreme_str}?\n\n'
            f'Пример: „утре", „среда", „15.05" или „2026-05-15"',
            kontekst,
            izvleceno,
            prasanje,
        )

    # Нема лекар — специјалност или име
    if not ima_lekar:
        oddel = _oddel_od_prasanje(prasanje)
        if not oddel and isinstance(kontekst, dict):
            oddel = (kontekst.get("zakazi_pending") or {}).get("specialty")
        if oddel:
            lekari = _lekari_po_oddel(oddel)
            if lekari:
                return _poraka_izberi_lekar_specijalnost(
                    oddel, lekari, datum_str, kontekst
                )
            return {
                "odgovor": (
                    f'Моментално нема регистрирани лекари на „{oddel}".\n\n'
                    'Прашајте „Кои лекари работат во болницата?" или изберете друга специјалност.'
                ),
                "kontekst": kontekst,
            }

        zos = (kontekst or {}).get("zakazi_od_slobodni") if isinstance(kontekst, dict) else {}
        if isinstance(zos, dict) and _normalize_doctor_id(zos.get("doctor_id")):
            return (
                "Не го препознавам лекарот од пораката. Кажи го презимето или избери од листата "
                "со слободни термини погоре, на пример „кај Захариев во 10:30“."
            )

        if isinstance(kontekst, dict) and (kontekst.get("zakazi_pending") or zos):
            extra = ""
            if datum_str:
                try:
                    dt = datetime.strptime(str(datum_str)[:10], "%Y-%m-%d").date()
                    extra = f" Датумот {format_datum(dt)} е зачуван."
                except ValueError:
                    extra = f" Датумот {datum_str} е зачуван."
            return {
                "odgovor": (
                    "За да продолжиме со закажувањето, наведете лекар (презиме), "
                    f"на пр. „кај Петров“ или „слободни термини кај [презиме]“.{extra}"
                ),
                "kontekst": kontekst,
            }

        return (
            "Кај кој лекар сакаш да закажеш термин? Кажи го презимето или специјалноста.\n\n"
            'Пример: „кај д-р Петров", „преглед кај интернист", „следниот вторник кај кардиолог“.\n\n'
            'Ако не знаеш кој лекар, прашај: „Кои лекари имате на интерна?" или '
            '„препорачај лекар за болки во градите".'
        )

    # Сите 3 полиња се присутни - продолжи со валидација и INSERT
    if doctor_id is None or not datum_str or not vreme_str:
        return "Недостасуваат податоци за закажување (лекар, датум, време)."
    did = int(doctor_id)
    ds = str(datum_str)
    vs = str(vreme_str)

    # Валидација на датум
    try:
        datum_obj = datetime.strptime(ds, "%Y-%m-%d").date()
    except ValueError:
        return "Неважечки формат на датум."

    if datum_obj < date.today():
        return {
            "odgovor": "Не може да закажеш термин во минатото. Избери иден датум.",
            "kontekst": kontekst,
        }

    if datum_obj.weekday() >= 5:
        nov_kontekst = dict(kontekst) if kontekst else {}
        pending: dict = {}
        if did is not None:
            pending["doctor_id"] = did
        if vs:
            pending["vreme"] = vs
        if pending:
            nov_kontekst["zakazi_pending"] = pending
        return {
            "odgovor": (
                "Не се закажуваат прегледи во сабота и недела. Избери друг ден.\n\n"
                'Можеш да прашаш: „Кога е следен работен ден?" — ќе ти кажам датум '
                "и слободни термини кај истиот лекар, доколку веќе го имаше избран."
            ),
            "kontekst": nov_kontekst,
        }

    # Валидација на време
    try:
        vreme_obj = datetime.strptime(vs, "%H:%M").time()
    except ValueError:
        return "Неважечки формат на време."

    if vreme_obj < RABOTNO_OD or vreme_obj > RABOTNO_DO:
        return {
            "odgovor": (
                f"Работно време е од {format_vreme(RABOTNO_OD)} до {format_vreme(RABOTNO_DO)}."
            ),
            "kontekst": kontekst,
        }

    # Проверка дали е слободен
    if not proveri_dali_e_slobodno(did, ds, vs):
        return {
            "odgovor": (
                'Тој термин е веќе зафатен. Те молам прашај за слободни термини '
                'со „Кога е слободен д-р [презиме]?" и обиди се повторно.'
            ),
            "kontekst": kontekst,
        }

    lekar_text = ime_lekar_za_poraka or "избраниот лекар"
    try:
        dt = datetime.strptime(ds, "%Y-%m-%d").date()
        datum_lepo = format_datum(dt)
    except ValueError:
        datum_lepo = ds

    return {
        "odgovor": _poraka_prasanje_napomena(lekar_text, datum_lepo, vs),
        "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
    }
