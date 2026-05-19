from ai._kernel.prompt_loader import load_prompt
from ai._kernel.utils import format_datum, format_vreme
import re
from datetime import date
from database import get_connection
from ai.pacient.slobodni_termini import (
    datum_od_zakazi_kontekst,
    lekar_od_zakazi_kontekst,
    vreme_od_prasanje_lokalno,
    zimi_site_lekari,
)
# se gleda kako e vnesen datumot i go prepoznava moze da e so to. ili so /
_RE_DATUM_DOT = re.compile(
    r"\b(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?\b",
    re.UNICODE, # so Unicode se ovozmozuva vnesot da bide na kirilica
)
# regulatoren izraz  za provekra koj lekar e vnesen i ima status zakazan
_RE_IME_ZAKAZAN = re.compile(
    r"([А-Яа-яA-Za-z][А-Яа-яA-Za-z\-]*)\s+"
    r"([А-Яа-яA-Za-z][А-Яа-яA-Za-z\-]*)\s*\[?\s*закажан",
    re.UNICODE | re.IGNORECASE,
)
# id na lekarot go pertvarame vo int
def _normalize_doctor_id(v) -> int | None:
    if v is None:       # ako ne e vnesen id na lekarot vrka none
        return None
    try:    
        return int(v)   # ako ima vnes go pretvata vo int 
    except (TypeError, ValueError): # ako vnesot ne moze da se pretvori vo int vraka error
        return None
# vraka datum za koj sakame da otkazeme 
def _datum_od_tekst_otkazi(prasanje: str) -> str | None:
    """DD.MM.YYYY / DD.MM.YY — и „кај 2.02.2026", не само „на 2.02"."""
    from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje
    d = datum_za_pregledi_od_prasanje(prasanje) # prebaruvanje na datumot
    if d:
        return d.isoformat()    # ako e pronajden datumot se vraka 

    m = _RE_DATUM_DOT.search(prasanje or "")    # ako ne e uspesno pronajde se prebaruva dali korisnikot go vnel so .
    if not m:   # ako ne e pronajden so . vraka none kako deka nema pregled na izbraniot datum
        return None
    try:
        # se izvlekuvat den i mesec kako celi broevi
        dan, mes = int(m.group(1)), int(m.group(2))
        god = m.group(3)
        g = int(god) if god else date.today().year # dokolku ne e naglasena godinata se zema tekovnata 
        if g < 100: # ako e vnesena 26 namesto 2026 se dodavaat 2000 godini za da se dobie celosna godina
            g += 2000
        return date(g, mes, dan).isoformat()    # se vraka celosno datumot vo isoformat
    except (ValueError, TypeError):
        return None

# funkcija za lokanlo vadenje na datumot, koga nema groq tokeni
def izvlechi_otkazi_lokalno(prasanje: str) -> dict:
    """Лекар, датум, време од правила — без Groq."""
    from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_prasanje
    from ai._kernel.groq_client import groq_e_isklucen
    out: dict = {"doctor_id": None, "datum": None, "vreme": None, "prezime_filter": None}   # se posatavuva site vrednoti da bidat postaveni na none
    datum_s = _datum_od_tekst_otkazi(prasanje)  # se smestuva datumot od vnesot na korisnikot vo datum_s
    if datum_s:
        out["datum"] = datum_s
    vreme = vreme_od_prasanje_lokalno(prasanje) # se prebaaruva lokalno vremeto na pregled od vnesot na kornisnikot 
    if vreme:
        out["vreme"] = vreme        # ako e pronajde se vraka 
# sema koja proveruva dali e vnesento imwto na lekarot i dali ima smesteno nekade zakazi
    m_ime = _RE_IME_ZAKAZAN.search(prasanje or "")
    if m_ime:
        ref = f"д-р {m_ime.group(1)} {m_ime.group(2)}"
        lekar = najdi_lekar_od_prasanje(ref, koristi_ai=False) # se bara lekarot vo bazata so vnesenoto ime
        if lekar:
            out["doctor_id"] = int(lekar["doctor_ID"])
        out["prezime_filter"] = m_ime.group(2).strip().lower()

    delovi = izvlechi_delovi_ime(prasanje)  # se vlecat delovi od imeto na lekarot
    if delovi and not out.get("doctor_id"): # ako se najde lekar so imeto a nemame definirano tocen negov id
        lekar = najdi_lekar_od_prasanje(    # se bara lekarot od bazata 
            prasanje, koristi_ai=not groq_e_isklucen()
        )
        if lekar:
            out["doctor_id"] = int(lekar["doctor_ID"])
        if len(delovi) >= 1:
            out["prezime_filter"] = delovi[-1].lower()

    return out
# kombinacija na lokalno i ai 
def izvlechi_otkazi_podatoci(prasanje: str) -> dict:
    """Лекар + датум + време — локално прво, Groq само ако е достапен."""
    from ai._kernel.groq_client import groq_e_isklucen
    from ai._kernel.groq_helpers import izvlechi_json_so_ai
    lokalno = izvlechi_otkazi_lokalno(prasanje) # se izvlekkuva prasanje lokalno
    if groq_e_isklucen():   # ako gorq e isklucen se vraka lokalno izvlecenite podatoci без da se probuva so ai da se izvlecat podatoci od prasanje na korisnikot
        return lokalno
    # ako podatocite se najdeni lokalno ne se aktivira ai za podetalno prebaruvanje
    if lokalno.get("doctor_id") and lokalno.get("datum") and lokalno.get("vreme"):
        return lokalno
    site_lekari = zimi_site_lekari()    # gi zema site lekari od bazata
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
    # promto do ai so ke go vrate odgovorot do korisnikot deka terminot e otkazan
    full_prompt = f"""
Денес: {denes} ({den_vo_nedela}) Лекари: {lista_text} Корисник: „{prasanje}"
Извлечи doctor_id, datum (YYYY-MM-DD) и vreme (HH:MM).
""".strip()
# se povikuva ai za da izvlece podatoci od vnesot na korisnikot, i se vraka vo formata na dict so doctor_id, datum i vreme
    podatoci = izvlechi_json_so_ai(
        full_prompt, load_prompt("otkazi_extract"), log_tag="otkazi_termin"
    )
    # ako nastane greska se vrakame lokalno
    if podatoci.get("_error"):
        return lokalno
    # se spojuvaat lokalno i ai 
    spoen = dict(lokalno)
    if podatoci.get("doctor_id") is not None:
        spoen["doctor_id"] = podatoci.get("doctor_id")
    if podatoci.get("datum"):
        spoen["datum"] = podatoci.get("datum")
    if podatoci.get("vreme"):
        spoen["vreme"] = str(podatoci.get("vreme")).strip()[:5]
    return spoen

# funkcija koja ja prebaruva bazata za da najde termin koi treba da go otkaze
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
                f"- {den_ime} {format_datum(datum)} во {vreme} "
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
    datum_lep = format_datum(datum)

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
