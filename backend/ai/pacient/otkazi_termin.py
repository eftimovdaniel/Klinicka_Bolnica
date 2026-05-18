"""
Откажување термин преку AI асистент.

Како работи:
1. Пациент пишува: "Откажи го утрешниот преглед" или "Откажи го прегледот кај Петров"
2. AI ги препознава: датум (опционално) + лекар (опционално)
3. Бараме во базата термини на тој пациент што одговараат
4. Ако има точно еден → UPDATE status_pregled = 'откажан'
5. Ако има повеќе → прашаме кој
6. Ако нема → грешка

Бара логиран пациент.
"""

from ai._kernel.prompt_loader import load_prompt
import re
from datetime import date
from database import get_connection
from ai.pacient.slobodni_termini import (
    datum_od_zakazi_kontekst,
    lekar_od_zakazi_kontekst,
    vreme_od_prasanje_lokalno,
    zimi_site_lekari,
)

_RE_DATUM_DOT = re.compile(
    r"\b(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?\b",
    re.UNICODE,
)
_RE_IME_ZAKAZAN = re.compile(
    r"([А-Яа-яA-Za-z][А-Яа-яA-Za-z\-]*)\s+"
    r"([А-Яа-яA-Za-z][А-Яа-яA-Za-z\-]*)\s*\[?\s*закажан",
    re.UNICODE | re.IGNORECASE,
)


def _normalize_doctor_id(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _datum_od_tekst_otkazi(prasanje: str) -> str | None:
    """DD.MM.YYYY / DD.MM.YY — и „кај 2.02.2026", не само „на 2.02"."""
    from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje

    d = datum_za_pregledi_od_prasanje(prasanje)
    if d:
        return d.isoformat()

    m = _RE_DATUM_DOT.search(prasanje or "")
    if not m:
        return None
    try:
        dan, mes = int(m.group(1)), int(m.group(2))
        god = m.group(3)
        g = int(god) if god else date.today().year
        if g < 100:
            g += 2000
        return date(g, mes, dan).isoformat()
    except (ValueError, TypeError):
        return None


def izvlechi_otkazi_lokalno(prasanje: str) -> dict:
    """Лекар, датум, време од правила — без Groq."""
    from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_prasanje
    from ai._kernel.groq_client import groq_e_isklucen

    out: dict = {"doctor_id": None, "datum": None, "vreme": None, "prezime_filter": None}

    datum_s = _datum_od_tekst_otkazi(prasanje)
    if datum_s:
        out["datum"] = datum_s

    vreme = vreme_od_prasanje_lokalno(prasanje)
    if vreme:
        out["vreme"] = vreme

    m_ime = _RE_IME_ZAKAZAN.search(prasanje or "")
    if m_ime:
        ref = f"д-р {m_ime.group(1)} {m_ime.group(2)}"
        lekar = najdi_lekar_od_prasanje(ref, koristi_ai=False)
        if lekar:
            out["doctor_id"] = int(lekar["doctor_ID"])
        out["prezime_filter"] = m_ime.group(2).strip().lower()

    delovi = izvlechi_delovi_ime(prasanje)
    if delovi and not out.get("doctor_id"):
        lekar = najdi_lekar_od_prasanje(
            prasanje, koristi_ai=not groq_e_isklucen()
        )
        if lekar:
            out["doctor_id"] = int(lekar["doctor_ID"])
        if len(delovi) >= 1:
            out["prezime_filter"] = delovi[-1].lower()

    return out


def izvlechi_otkazi_podatoci(prasanje: str) -> dict:
    """Лекар + датум + време — локално прво, Groq само ако е достапен."""
    from ai._kernel.groq_client import groq_e_isklucen
    from ai._kernel.groq_helpers import izvlechi_json_so_ai

    lokalno = izvlechi_otkazi_lokalno(prasanje)
    if groq_e_isklucen():
        return lokalno

    if lokalno.get("doctor_id") and lokalno.get("datum") and lokalno.get("vreme"):
        return lokalno

    site_lekari = zimi_site_lekari()
    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса"
        lista_text += (
            f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"
        )

    denes = date.today().strftime("%Y-%m-%d")
    den_vo_nedela = [
        "понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"
    ][date.today().weekday()]

    full_prompt = f"""
Денес: {denes} ({den_vo_nedela})

Лекари:
{lista_text}

Корисник: „{prasanje}"

Извлечи doctor_id, datum (YYYY-MM-DD) и vreme (HH:MM).
""".strip()

    podatoci = izvlechi_json_so_ai(
        full_prompt, load_prompt("otkazi_extract"), log_tag="otkazi_termin"
    )
    if podatoci.get("_error"):
        return lokalno

    spoen = dict(lokalno)
    if podatoci.get("doctor_id") is not None:
        spoen["doctor_id"] = podatoci.get("doctor_id")
    if podatoci.get("datum"):
        spoen["datum"] = podatoci.get("datum")
    if podatoci.get("vreme"):
        spoen["vreme"] = str(podatoci.get("vreme")).strip()[:5]
    return spoen


def najdi_termini_za_otkazuvanje(
    pacient_email: str,
    doctor_id: int | None,
    datum: str | None,
    vreme: str | None = None,
    prezime_filter: str | None = None,
) -> list[dict]:
    """
    Враќа активни (закажани, не откажани) термини на пациентот
    што одговараат на филтрите.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID
            FROM Termin_pregled t
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'закажан'
        """
        params: list[object] = [pacient_email]

        # Без конкретен датум — само идни/денес (не цела историја)
        if not datum:
            query += " AND t.datum_pregled >= CURDATE()"

        if doctor_id:
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id)

        if datum:
            query += " AND t.datum_pregled = %s"
            params.append(datum)

        if prezime_filter and not doctor_id:
            query += " AND LOWER(COALESCE(t.ime_lekar, '')) LIKE %s"
            params.append(f"%{prezime_filter.strip().lower()}%")

        if vreme:
            query += " AND TIME(t.vreme_pregled) = %s"
            params.append(vreme)

        query += " ORDER BY t.datum_pregled, t.vreme_pregled"

        cur.execute(query, params)
        rezultati = list(cur.fetchall() or [])
        cur.close()

        if vreme and rezultati:
            vf = vreme.strip()[:5]
            filtrirani = [
                t
                for t in rezultati
                if format_vreme(t.get("vreme_pregled")) == vf
            ]
            if filtrirani:
                return filtrirani

        return rezultati

    except Exception as e:
        print(f"[otkazi_termin] greska: {e}")
        return []
    finally:
        if conn:
            conn.close()


def otkazi_termin_vo_baza(termin_id: int) -> bool:
    """Поставува status_pregled = 'откажан'."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE Termin_pregled
            SET status_pregled = 'откажан'
            WHERE termin_ID = %s
        """, (termin_id,))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[otkazi_termin] update greska: {e}")
        return False
    finally:
        if conn:
            conn.close()


def format_vreme(v) -> str:
    """time/timedelta → HH:MM string."""
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def _spoi_otkazi_so_kontekst(
    prasanje: str,
    izvleceno: dict,
    kontekst: dict | None,
) -> None:
    """Лекар/датум од претходен разговор (слободни термини / закажување)."""
    if not isinstance(kontekst, dict):
        return
    lekar = lekar_od_zakazi_kontekst(kontekst)
    if lekar and not izvleceno.get("doctor_id"):
        izvleceno["doctor_id"] = lekar["doctor_ID"]
    if izvleceno.get("datum"):
        return
    baran = datum_od_zakazi_kontekst(kontekst)
    if not baran:
        return
    p = (prasanje or "").lower()
    if any(
        x in p
        for x in (
            "терминот",
            "термин",
            "прегледот",
            "преглед",
            "го откаж",
            "го отказ",
            "избраниот",
            "истиот",
            "погоре",
        )
    ):
        izvleceno["datum"] = baran.isoformat()


def odgovori_za_otkazuvanje(
    prasanje: str, pacient: dict | None, kontekst: dict | None = None
) -> str:
    """Главна точка - повикана од router-от."""
    if not pacient or not pacient.get("email"):
        return (
            'За да откажеш термин, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_otkazi_podatoci(prasanje)
    _spoi_otkazi_so_kontekst(prasanje, izvleceno, kontekst)
    doctor_id = _normalize_doctor_id(izvleceno.get("doctor_id"))
    datum_str = (izvleceno.get("datum") or "").strip()[:10] or None
    vreme_str = (izvleceno.get("vreme") or "").strip()[:5] or None
    prezime_filter = (izvleceno.get("prezime_filter") or "").strip() or None

    if not datum_str:
        datum_str = _datum_od_tekst_otkazi(prasanje)
    if not vreme_str:
        vreme_str = vreme_od_prasanje_lokalno(prasanje)

    termini = najdi_termini_za_otkazuvanje(
        pacient["email"],
        doctor_id,
        datum_str,
        vreme_str,
        prezime_filter,
    )

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

    if not termini:
        detali = []
        if datum_str:
            detali.append(f"датум {datum_str}")
        if vreme_str:
            detali.append(f"време {vreme_str}")
        if doctor_id or prezime_filter:
            detali.append("лекар од пораката")
        extra = f" (барано: {', '.join(detali)})" if detali else ""
        return (
            f"Не најдов активен термин со статус „закажан“ што одговара{extra}.\n\n"
            'Проверете со „Моите прегледи“ или „Прикажи ги сите мои прегледи“, '
            'па повторете, на пр.:\n'
            '„Откажи го прегледот на 02.02.2026 во 09:30 кај Серафимов“.'
        )

    if len(termini) > 1:
        # Многу совпаѓања - прикажи ги
        delovi = ["Имаш повеќе термини. Кој точно сакаш да го откажеш?", ""]
        for t in termini:
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]
            vreme = format_vreme(t["vreme_pregled"])
            delovi.append(
                f"- {den_ime} {datum.strftime('%d.%m.%Y')} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']})"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Откажи го прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    # Точно еден термин
    t = termini[0]
    if not otkazi_termin_vo_baza(t["termin_ID"]):
        return "Не успеа да го откажам терминот. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])
    datum_lep = datum.strftime("%d.%m.%Y")

    ime_pacient = (
        (pacient.get("ime") or "") + " " + (pacient.get("prezime") or "")
    ).strip() or (t.get("ime_pacient") or pacient.get("email", ""))

    try:
        from routers.termini import _poslati_otkaz_na_email

        _poslati_otkaz_na_email(
            to_email=pacient["email"],
            ime_pacient=ime_pacient,
            ime_lekar=f"Д-р {t['ime_lekar']}",
            datum=f"{den_ime}, {datum_lep}",
            vreme=vreme,
            specialnost=t.get("specijalnost_termin") or "",
        )
    except Exception as e:
        print(f"[otkazi_termin] email greska: {e}")

    return (
        f"Терминот е откажан!\n\n"
        f"Лекар: Д-р {t['ime_lekar']}\n"
        f"Специјалност: {t['specijalnost_termin']}\n"
        f"Датум: {den_ime}, {datum_lep}\n"
        f"Време: {vreme}\n\n"
        "Потврда е испратена на вашата е-пошта (ако е поставен SMTP на серверот).\n\n"
        'Можеш да закажеш нов термин со „Сакам преглед кај [презиме] [датум] [време]".'
    )
