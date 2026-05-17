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
from ai._kernel.prompts import ZAKAZI_EXTRACT_PROMPT
from ai.pacient.slobodni_termini import (
    datum_od_prasanje_lokalno,
    prasanje_bar_datum_od_kontekst,
    zimi_site_lekari,
)


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
    nid = _normalize_doctor_id(zos.get("doctor_id"))
    if nid is not None and (not izvleceno.get("doctor_id") or izbran):
        izvleceno["doctor_id"] = nid
    if zos.get("datum"):
        d = str(zos["datum"]).strip()[:10]
        if d:
            if datum_od_prasanje_lokalno(prasanje) is None:
                izvleceno["datum"] = d
            elif koristi_kontekst_datum or not izvleceno.get("datum"):
                izvleceno["datum"] = d
    if zos.get("vreme") and not izvleceno.get("vreme"):
        v = str(zos["vreme"]).strip()[:5]
        if v:
            izvleceno["vreme"] = v


def _snimi_zakazi_pending(
    kontekst: dict | None, izvleceno: dict
) -> dict | None:
    """Зачувај лекар/датум/време за продолжување по најава."""
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

    if not pending:
        return kontekst

    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_pending"] = pending
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": pending.get("doctor_id"),
        "datum": pending.get("datum"),
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

    odgovor = ask_ai(full_prompt, system_prompt=ZAKAZI_EXTRACT_PROMPT)
    print(f"[zakazi_termin] AI raw: {odgovor!r}")

    podatoci = parse_ai_json(odgovor, log_tag="zakazi_termin")
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


def vmetni_termin_vo_baza(
    doctor_id: int,
    ime_pacient: str,
    email_pacient: str,
    telefon_pacient: str,
    datum_str: str,
    vreme_str: str,
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
            'Закажано преку AI асистент'
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


def formatiraj_potvrda(ime_pacient: str, ime_lekar: str, specialty: str, datum_str: str, vreme_str: str) -> str:
    """Текст потврда за корисникот — повеќе реченици, јасна сумаризација."""
    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]
    dt = datetime.strptime(datum_str, "%Y-%m-%d").date()
    den_ime = DENOVI[dt.weekday()]
    datum_lep = dt.strftime("%d.%m.%Y")

    return (
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
    # AI извлекува податоци (и пред најава — за да се зачува датумот/времето)
    izvleceno = izvlechi_podatoci_so_ai(prasanje)
    _spoi_zakazi_so_slobodni_kontekst(prasanje, izvleceno, kontekst)

    # Проверка дали пациентот е логиран — фронтот ја отвора формата за најава како пациент
    if not pacient or not pacient.get("email"):
        return {
            "odgovor": (
                "За да закажам термин во твое име, треба да се најавиш како пациент "
                "(системот ги користи твоето име, е-пошта и телефон од профилот).\n\n"
                "Ти ја отворам формата за најава — по најавата повтори ја истата наредба; "
                "можеш и поинаку, на пример „закажи во 10:00“ или „за претходно спомнатиот датум“."
            ),
            "akcija": "otvori_pacient_login",
            "kontekst": _snimi_zakazi_pending(kontekst, izvleceno),
        }

    # Ако имало AI грешка (rate limit, timeout) - врати ја директно на корисникот
    if izvleceno.get("_error"):
        return izvleceno["_error"]

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

    # Сите три недостасуваат → најмалку информации
    if not ima_lekar and not ima_datum and not ima_vreme:
        return (
            "Го разбирам барањето како закажување на преглед, но недостасуваат клучни податоци.\n\n"
            "Потребни се: лекар (име или презиме), датум и време. "
            "Можеш да ги кажеш во една реченица или во повеќе пораки — агентот ги собира.\n\n"
            'Пример: „Сакам преглед кај д-р Петров среда во 10:00"\n'
            'или: „Закажи кај Серафимов утре во 12:30".'
        )

    # Имаме само лекар - прашај за датум и време
    if ima_lekar and not ima_datum and not ima_vreme:
        lekar_text = ime_lekar_za_poraka or "избраниот лекар"
        return (
            f'Кога би сакал/а да закажеш термин кај {lekar_text}?\n\n'
            f'Кажи ми датум и време. Пример:\n'
            f'„утре во 10:00" или „среда во 14:30"'
        )

    # Имаме лекар + датум, нема време
    if ima_lekar and ima_datum and not ima_vreme:
        lekar_text = ime_lekar_za_poraka or "лекарот"
        try:
            dt = datetime.strptime(str(datum_str)[:10], "%Y-%m-%d").date()
            datum_lepo = dt.strftime("%d.%m.%Y")
        except ValueError:
            datum_lepo = datum_str
        pret = (
            " (претходно спомнатиот ден)"
            if prasanje_bar_datum_od_kontekst(prasanje)
            else ""
        )
        return (
            f"Во кое време сакаш термин кај {lekar_text} на {datum_lepo}{pret}?\n\n"
            f"Работно време: {RABOTNO_OD.strftime('%H:%M')} – "
            f"{RABOTNO_DO.strftime('%H:%M')}\n"
            'Пример: „во 10:00“ или „закажи во 10:30“.'
        )

    # Имаме лекар + време, нема датум
    if ima_lekar and not ima_datum and ima_vreme:
        lekar_text = ime_lekar_za_poraka or "лекарот"
        return (
            f'Кој датум сакаш термин кај {lekar_text} во {vreme_str}?\n\n'
            f'Пример: „утре", „среда", „15.05" или „2026-05-15"'
        )

    # Имаме датум и/или време, нема лекар
    if not ima_lekar:
        if kontekst and isinstance(kontekst.get("zakazi_od_slobodni"), dict):
            return (
                'Не го препознавам лекарот од пораката. Кажи го презимето или избери од листата '
                'со слободни термини погоре, на пример „кај Захариев во 10:30".'
            )
        return (
            'Кај кој лекар сакаш да закажеш термин? Кажи го името и презимето.\n\n'
            'Пример: „кај д-р Петров", „кај Александар Серафимов"\n\n'
            'Ако не знаеш кој лекар, прашај ме: „Кои лекари имате?" или опиши го '
            'проблемот (на пр. „боли ме грб") и ќе ти препорачам.'
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
                f"Работно време е од {RABOTNO_OD.strftime('%H:%M')} до {RABOTNO_DO.strftime('%H:%M')}."
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

    # Состави име на пациент
    ime_pacient = (
        (pacient.get("ime") or pacient.get("name_patient") or "") + " " +
        (pacient.get("prezime") or pacient.get("surname_patient") or "")
    ).strip()
    if not ime_pacient:
        ime_pacient = pacient.get("email", "")

    email_pacient = pacient.get("email", "")
    telefon_pacient = pacient.get("telefon") or pacient.get("phone_number") or ""

    # INSERT во базата
    uspesno, greska, info = vmetni_termin_vo_baza(
        doctor_id=did,
        ime_pacient=ime_pacient,
        email_pacient=email_pacient,
        telefon_pacient=telefon_pacient,
        datum_str=ds,
        vreme_str=vs,
    )

    if not uspesno:
        return {
            "odgovor": f"Не успеа закажувањето: {greska}",
            "kontekst": kontekst,
        }

    # Прати email потврда (го користиме постоечкиот SMTP код)
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
            "last_doctor_id": int(doctor_id),
        },
    }
