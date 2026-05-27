"""
Закажување термин преку AI агент (Groq).

Сè оди преку AI: лекар, датум, време и специјалност се извлекуваат од
едно Groq повикување. Локалниот код само ги собира пораките, ја пополнува
празнината од контекстот и прави валидација пред INSERT во базата.

Главна функција: odgovori_za_zakazuvanje(prasanje, pacient, kontekst).
"""
import re
from datetime import datetime, date, time
from database import get_connection
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai
from ai._kernel.prompts import ZAKAZI_EXTRACT_PROMPT
from ai._kernel.groq_helpers import izvlechi_json_so_ai
from ai._kernel.db_helpers import db_cursor
from ai._kernel.utils import format_datum, format_vreme
from ai.pacient.slobodni_termini import baranje_e_zakazuvanje, zimi_site_lekari


RABOTNO_OD = time(8, 0)   # pocetok na rabotno vreme
RABOTNO_DO = time(15, 30) # kraj na rabotno vreme

DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]


# ───────────────── ai povik ─────────────────
def _povikaj_ai(prasanje: str) -> dict:
    """Eden povik do Groq — vrazka doctor_id / datum / vreme / specialty."""
    lekari = zimi_site_lekari()
    lista = "\n".join(
        f"ID {l['doctor_ID']}: Д-р {l['name']} {l['surname']} - "
        f"{l.get('specialty') or 'Општа пракса'}"
        for l in lekari
    )
    denes = date.today()
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток",
                     "петок", "сабота", "недела"][denes.weekday()]
    prompt = (
        f"Денешен датум: {denes.isoformat()} ({den_vo_nedela})\n"
        f"Листа на лекари:\n{lista}\n\n"
        f"Корисник пишува: „{prasanje}\"\n\n"
        "Извлечи doctor_id, datum, vreme, specialty и врати JSON."
    )
    podatoci = izvlechi_json_so_ai(prompt, ZAKAZI_EXTRACT_PROMPT, log_tag="zakazi_termin")
    if podatoci.get("_error"):
        # Groq nedostapen — vrati prazna struktura so error flag
        return {"doctor_id": None, "datum": None, "vreme": None, "specialty": None,
                "_error": podatoci["_error"]}
    return {
        "doctor_id": _kako_int(podatoci.get("doctor_id")),
        "datum": _kako_datum(podatoci.get("datum")),
        "vreme": _kako_vreme(podatoci.get("vreme")),
        "specialty": (podatoci.get("specialty") or None),
    }


# ───────────────── helpers ─────────────────
def _kako_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _kako_datum(v) -> str | None:
    if not v:
        return None
    s = str(v).strip()[:10]  # YYYY-MM-DD
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _kako_vreme(v) -> str | None:
    if not v:
        return None
    s = str(v).strip()[:5]   # HH:MM
    try:
        datetime.strptime(s, "%H:%M")
        return s
    except ValueError:
        return None


def _ime_lekar(doctor_id: int | None) -> str:
    """Cita ime + prezime od listata na lekari (kesirana funkcija)."""
    if not doctor_id:
        return ""
    for l in zimi_site_lekari():
        if l.get("doctor_ID") == doctor_id:
            return f"Д-р {l.get('name', '')} {l.get('surname', '')}".strip()
    return ""


def _lekari_po_oddel(oddel: str) -> list[dict]:
    """Lekari za dadena specijalnost (case-insensitive)."""
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                "SELECT doctor_ID, name, surname, specialty, email "
                "FROM Doctors WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s)) "
                "ORDER BY surname, name",
                (oddel,),
            )
            return list(cur.fetchall())
    except Exception as e:
        print(f"[zakazi_termin] lekari_po_oddel: {e}")
        return []


# ───────────────── kontekst ─────────────────
def _spoji_so_kontekst(izvleceno: dict, kontekst: dict | None) -> None:
    """Popolnuva prazni polinja (doctor_id/datum/vreme/specialty) od zapamten pending — in-place."""
    if not isinstance(kontekst, dict):
        return
    pending = (
        kontekst.get("zakazi_pending")
        or kontekst.get("zakazi_od_slobodni")
        or {}
    )
    if not isinstance(pending, dict):
        return
    if not izvleceno.get("doctor_id"):
        izvleceno["doctor_id"] = _kako_int(pending.get("doctor_id"))
    if not izvleceno.get("datum"):
        izvleceno["datum"] = _kako_datum(pending.get("datum"))
    if not izvleceno.get("vreme"):
        izvleceno["vreme"] = _kako_vreme(pending.get("vreme"))
    if not izvleceno.get("specialty"):
        izvleceno["specialty"] = pending.get("specialty")
    if not izvleceno.get("datum") and kontekst.get("last_slobodni_datum"):
        izvleceno["datum"] = _kako_datum(kontekst.get("last_slobodni_datum"))
    if not izvleceno.get("vreme") and kontekst.get("last_slobodni_vreme"):
        izvleceno["vreme"] = _kako_vreme(kontekst.get("last_slobodni_vreme"))


def _zacuvaj_pending(kontekst: dict | None, izvleceno: dict) -> dict:
    """Vrati nov kontekst so zacuvani pending podatoci (za sledna poraka)."""
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    pending: dict = {}
    for k in ("doctor_id", "datum", "vreme", "specialty"):
        v = izvleceno.get(k)
        if v:
            pending[k] = v
    ctx["zakazi_pending"] = pending
    if pending.get("doctor_id"):
        ctx["last_doctor_id"] = int(pending["doctor_id"])
    return ctx


# ───────────────── napomena flow ─────────────────
def _ceka_napomena(kontekst: dict | None) -> dict | None:
    z = (kontekst or {}).get("zakazi_ceka_napomena")
    if isinstance(z, dict) and z.get("doctor_id") and z.get("datum") and z.get("vreme"):
        return z
    return None


def _e_odbiva_napomena(prasanje: str) -> bool:
    p = re.sub(r"\s+", " ", (prasanje or "").strip().lower())
    return p in {"не", "не.", "no", "nema", "нема", "немам", "без напомена",
                 "нема напомена", "не сакам", "не сакам напомена"}


def _e_samo_da(prasanje: str) -> bool:
    p = re.sub(r"\s+", " ", (prasanje or "").strip().lower())
    return p in {"да", "da", "ок", "ok", "okay", "во ред"}


def _postavi_ceka_napomena(kontekst: dict | None, doctor_id: int,
                           datum_str: str, vreme_str: str) -> dict:
    ctx = dict(kontekst) if kontekst else {}
    ctx["zakazi_ceka_napomena"] = {
        "doctor_id": int(doctor_id),
        "datum": datum_str,
        "vreme": vreme_str,
    }
    return ctx


# ───────────────── baza ─────────────────
def _e_slobodno(doctor_id: int, datum_str: str, vreme_str: str) -> bool:
    """True ako terminot ne e zafateн od drug pacient."""
    try:
        with db_cursor(dictionary=True) as (_, cur):
            cur.execute(
                "SELECT termin_ID FROM Termin_pregled "
                "WHERE doctor_ID = %s AND DATE(datum_pregled) = %s "
                "  AND TIME(vreme_pregled) = %s AND status_pregled = 'закажан'",
                (doctor_id, datum_str, vreme_str),
            )
            return cur.fetchone() is None
    except Exception as e:
        print(f"[zakazi_termin] proverka: {e}")
        return False


def _insert_termin(doctor_id: int, ime_pacient: str, email_pacient: str,
                   telefon_pacient: str, datum_str: str, vreme_str: str,
                   napomena: str | None) -> tuple[bool, str, dict | None]:
    """INSERT vo Termin_pregled. Vrazka (uspeh, greska, info_za_lekar)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s",
            (doctor_id,),
        )
        doctor = cur.fetchone()
        if not doctor:
            return False, "Лекарот не постои.", None

        cur.execute(
            "INSERT INTO Termin_pregled "
            "(doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, "
            " datum_pregled, vreme_pregled, status_pregled, email_pacient, "
            " telefon_pacient, napomena) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                doctor_id, ime_pacient,
                doctor.get("specialty") or "",
                f"{doctor['name']} {doctor['surname']}",
                datum_str, vreme_str, "закажан",
                email_pacient, telefon_pacient,
                (napomena or "").strip() or None,
            ),
        )
        conn.commit()
        cur.close()
        return True, "", {
            "doctor_id": doctor_id,
            "ime_lekar": f"{doctor['name']} {doctor['surname']}",
            "specialty": doctor.get("specialty") or "Општа пракса",
        }
    except Exception as e:
        return False, f"Грешка при запис: {e}", None
    finally:
        if conn:
            conn.close()


def _formatiraj_potvrda(ime_pacient: str, ime_lekar: str, specialty: str,
                        datum_str: str, vreme_str: str) -> str:
    """Tekst potvrda preku AI od fakti + sablon ako Groq padne."""
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
        "Ако сакаш промена напиши „откажи термин“ или „префрли на друг ден“."
    )
    fakti = {
        "status": "zakazano", "pacient": ime_pacient, "lekar": f"Д-р {ime_lekar}",
        "specialnost": specialty, "datum": datum_lep, "den": den_ime,
        "vreme": vreme_str, "email_potvrda": True,
    }
    return formatiraj_odgovor_so_ai("zakazi_potvrda", fakti, sablon)


def _finaliziraj(doctor_id: int, datum_str: str, vreme_str: str,
                 pacient: dict, kontekst: dict | None,
                 napomena: str | None) -> dict:
    """Posledna proverka + INSERT + email + potvrda."""
    if not _e_slobodno(doctor_id, datum_str, vreme_str):
        ctx = dict(kontekst) if kontekst else {}
        ctx.pop("zakazi_ceka_napomena", None)
        return {
            "odgovor": "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно.",
            "kontekst": ctx,
        }

    ime_pacient = (
        (pacient.get("ime") or pacient.get("name_patient") or "") + " "
        + (pacient.get("prezime") or pacient.get("surname_patient") or "")
    ).strip() or pacient.get("email", "")
    email_pacient = pacient.get("email", "")
    telefon = pacient.get("telefon") or pacient.get("phone_number") or ""

    uspeh, greska, info = _insert_termin(
        doctor_id, ime_pacient, email_pacient, telefon,
        datum_str, vreme_str, napomena,
    )
    if not uspeh:
        return {"odgovor": f"Не успеа закажувањето: {greska}", "kontekst": kontekst}

    try:
        from routers.termini import _poslati_potvrda_na_email
        _poslati_potvrda_na_email(
            to_email=email_pacient, ime_pacient=ime_pacient,
            ime_lekar=info["ime_lekar"], datum=datum_str, vreme=vreme_str,
        )
    except Exception as e:
        print(f"[zakazi_termin] email: {e}")

    return {
        "odgovor": _formatiraj_potvrda(
            ime_pacient, info["ime_lekar"], info["specialty"],
            datum_str, vreme_str,
        ),
        "kontekst": {
            "zakazi_od_slobodni": {"doctor_id": doctor_id, "datum": datum_str},
            "last_doctor_id": doctor_id,
        },
    }


# ───────────────── napomena handler ─────────────────
def _napomena_faza(prasanje: str, pacient: dict, ceka: dict,
                   kontekst: dict | None) -> dict:
    did = int(ceka["doctor_id"])
    ds = str(ceka["datum"])
    vs = str(ceka["vreme"])

    if _e_odbiva_napomena(prasanje):
        return _finaliziraj(did, ds, vs, pacient, kontekst, napomena=None)
    if _e_samo_da(prasanje):
        return {
            "odgovor": "Во ред. Напишете ја напомената за лекарот (на пр. алергии) во следната порака.",
            "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
        }
    tekst = (prasanje or "").strip()
    if len(tekst) < 2:
        return {
            "odgovor": "Напишете ја напомената или кажете „не\" ако не сакате.",
            "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
        }
    return _finaliziraj(did, ds, vs, pacient, kontekst, napomena=tekst)


# ───────────────── flow control ─────────────────
def _vo_zakazi_flow(prasanje: str, kontekst: dict | None) -> bool:
    """Dali porakata navistina prodolzuva zakaz-flow (so klucni zborovi ili kontekst)."""
    if baranje_e_zakazuvanje(prasanje):
        return True
    if _ceka_napomena(kontekst):
        return True
    if not isinstance(kontekst, dict):
        return False
    if kontekst.get("zakazi_pending") or kontekst.get("zakazi_od_slobodni"):
        q = (prasanje or "").lower()
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
            return True
        if any(x in q for x in (
            "закаж", "zakaz", "термин", "termin", "напомена",
            "нема", "не ", "кај ", "kaj ", "утре", "време", "датум",
        )):
            return True
    return False


# ───────────────── poraki „sto nedostasuva" ─────────────────
def _poraka_nedostasuvaat(izvleceno: dict, kontekst: dict | None,
                          ime_lekar: str) -> dict:
    """Edna funkcija za site varijanti na „nedostasuva lekar/datum/vreme"."""
    did = izvleceno.get("doctor_id")
    ds = izvleceno.get("datum")
    vs = izvleceno.get("vreme")

    if not did and not ds and not vs:
        return _vrati_so_kontekst(
            "Го разбирам барањето како закажување, но недостасуваат податоци.\n\n"
            "Потребни се: лекар (име/презиме), датум и време.\n"
            "Пример: „Закажи кај д-р Петров среда во 10:00“.",
            kontekst, izvleceno,
        )

    if did and not ds and not vs:
        return _vrati_so_kontekst(
            f"Кога би сакал/а да закажеш термин кај {ime_lekar or 'избраниот лекар'}?\n\n"
            "Кажи ми датум и време. Пример: „утре во 10:00“ или „среда во 14:30“.",
            kontekst, izvleceno,
        )

    if did and ds and not vs:
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d").date()
            datum_lepo = format_datum(dt)
        except ValueError:
            datum_lepo = ds
        return _vrati_so_kontekst(
            f"Во кое време сакаш термин кај {ime_lekar or 'лекарот'} на {datum_lepo}?\n\n"
            f"Работно време: {format_vreme(RABOTNO_OD)} – {format_vreme(RABOTNO_DO)}.",
            kontekst, izvleceno,
        )

    if did and not ds and vs:
        return _vrati_so_kontekst(
            f"Кој датум сакаш термин кај {ime_lekar or 'лекарот'} во {vs}?\n\n"
            "Пример: „утре“, „среда“, „15.05“.",
            kontekst, izvleceno,
        )

    # nema lekar — prashaj za prezime ili spec
    return _vrati_so_kontekst(
        "Кај кој лекар сакаш да закажеш? Кажи го презимето или специјалноста.\n\n"
        "Пример: „кај д-р Петров“, „преглед кај кардиолог“.",
        kontekst, izvleceno,
    )


def _vrati_so_kontekst(odgovor: str, kontekst: dict | None,
                       izvleceno: dict) -> dict:
    return {"odgovor": odgovor, "kontekst": _zacuvaj_pending(kontekst, izvleceno)}


def _poraka_izberi_lekar_oddel(oddel: str, lekari: list[dict],
                               datum_str: str | None,
                               kontekst: dict | None) -> dict:
    """Korisnikot kaza specijalnost — pokazi gi lekarite + filter na frontend."""
    from ai.opsto.lekari_oddel import navigacija_lekari

    linii = [f"За преглед кај {oddel} во Клиничка Болница Штип, изберете лекар:", ""]
    linii += [f"- Д-р {l['name']} {l['surname']}" for l in lekari]
    if datum_str:
        try:
            dt = datetime.strptime(datum_str[:10], "%Y-%m-%d").date()
            linii.append(f"\nЗа датумот: {DENOVI[dt.weekday()]}, {format_datum(dt)}.")
        except ValueError:
            pass
    linii += [
        "",
        "Наведете презиме (на пр. „кај Петров“) или прашајте:",
        "„Кога е слободен д-р [презиме]?“",
    ]

    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    pending = {"specialty": oddel}
    if datum_str:
        pending["datum"] = datum_str[:10]
    ctx["zakazi_pending"] = pending
    return {
        "odgovor": "\n".join(linii),
        "kontekst": ctx,
        "navigacija": navigacija_lekari(oddel, lekari),
    }


# ───────────────── glavna ─────────────────
def odgovori_za_zakazuvanje(prasanje: str, pacient: dict | None,
                            kontekst: dict | None = None) -> str | dict:
    """
    Vlezna tocka — povikana od router.

    Flow:
      1. proverka dali e voopsto zakaz-baranje
      2. AI izvlekuva doctor_id/datum/vreme/specialty
      3. spoj so zapamten kontekst (po slobodni_termini ili prethodno pending)
      4. ako cekame napomena → napomena_faza
      5. ako pacient ne e najaven → otvori login + zachuvaj pending
      6. valdacija + INSERT
    """
    # ne e zakaz-baranje — vrati uputstvo bez da pravime nista
    if not _vo_zakazi_flow(prasanje, kontekst):
        return {
            "odgovor": (
                "Не го препознав ова како барање за закажување термин.\n\n"
                "Пример: „Закажи кај д-р Петров утре во 10:00“."
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    # AI izvlekuvanje (eden Groq povik)
    izvleceno = _povikaj_ai(prasanje)
    _spoji_so_kontekst(izvleceno, kontekst)

    # cekame napomena (vtor cekor) — pacient mora da e najaven
    ceka = _ceka_napomena(kontekst)
    if ceka and pacient and pacient.get("email"):
        return _napomena_faza(prasanje, pacient, ceka, kontekst)

    # pacient ne e najaven — otvori login modal i zacuvaj pending
    if not pacient or not pacient.get("email"):
        return _odgovor_neprijaven(izvleceno, kontekst)

    # Groq padna i nema sto da koristime — vrati greska
    if izvleceno.get("_error") and not any(
        izvleceno.get(k) for k in ("doctor_id", "datum", "vreme", "specialty")
    ):
        return str(izvleceno["_error"])

    did = izvleceno.get("doctor_id")
    ds = izvleceno.get("datum")
    vs = izvleceno.get("vreme")
    oddel = izvleceno.get("specialty")
    ime_lekar = _ime_lekar(did)

    # nema lekar ama ima specijalnost → pokazi lekari od taa specijalnost
    if not did and oddel:
        lekari = _lekari_po_oddel(oddel)
        if lekari:
            return _poraka_izberi_lekar_oddel(oddel, lekari, ds, kontekst)
        return {
            "odgovor": f"Моментално нема регистрирани лекари на „{oddel}“.",
            "kontekst": kontekst,
        }

    # ako falet bilo koe od 3-te polinja → prashaj
    if not (did and ds and vs):
        return _poraka_nedostasuvaat(izvleceno, kontekst, ime_lekar)

    # site 3 polinja gi imame — validacija + napomena prashanje
    try:
        datum_obj = datetime.strptime(ds, "%Y-%m-%d").date()
    except ValueError:
        return "Неважечки формат на датум."

    if datum_obj < date.today():
        return {"odgovor": "Не може да закажеш термин во минатото.", "kontekst": kontekst}

    if datum_obj.weekday() >= 5:
        return {
            "odgovor": "Не се закажуваат прегледи во сабота и недела. Избери друг ден.",
            "kontekst": _zacuvaj_pending(kontekst, izvleceno),
        }

    try:
        vreme_obj = datetime.strptime(vs, "%H:%M").time()
    except ValueError:
        return "Неважечки формат на време."

    if vreme_obj < RABOTNO_OD or vreme_obj > RABOTNO_DO:
        return {
            "odgovor": f"Работно време е од {format_vreme(RABOTNO_OD)} до {format_vreme(RABOTNO_DO)}.",
            "kontekst": kontekst,
        }

    if not _e_slobodno(did, ds, vs):
        return {
            "odgovor": "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно.",
            "kontekst": kontekst,
        }

    # site uslovi se ispolneti → prashaj za napomena pred INSERT
    try:
        datum_lepo = format_datum(datum_obj)
    except Exception:
        datum_lepo = ds
    return {
        "odgovor": (
            f"Сè е подготвено за закажување кај {ime_lekar or 'лекарот'} "
            f"на {datum_lepo} во {vs}.\n\n"
            "Дали сакате да оставите напомена за лекарот?\n"
            "Напишете ја или кажете „не“."
        ),
        "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
    }


def _odgovor_neprijaven(izvleceno: dict, kontekst: dict | None) -> dict:
    """Pacient ne e najaven — otvori login modal i zacuvaj pending podatoci."""
    oddel = izvleceno.get("specialty")
    nav = None
    spec_hint = ""
    if oddel:
        from ai.opsto.lekari_oddel import navigacija_lekari
        lekari = _lekari_po_oddel(oddel)
        if lekari:
            linii = [f"За преглед кај {oddel}, изберете лекар:", ""]
            linii += [f"- Д-р {l['name']} {l['surname']}" for l in lekari]
            spec_hint = "\n\n" + "\n".join(linii) + f"\n\nЗачувано: специјалност „{oddel}“."
            nav = navigacija_lekari(oddel, lekari)

    out: dict = {
        "odgovor": (
            "За да закажам термин во твое име, треба да се најавиш како пациент.\n\n"
            "Ти ја отворам формата за најава — по најавата повтори ја истата наредба."
            f"{spec_hint}"
        ),
        "akcija": "otvori_pacient_login",
        "kontekst": _zacuvaj_pending(kontekst, izvleceno),
    }
    if nav:
        out["navigacija"] = nav
    return out
