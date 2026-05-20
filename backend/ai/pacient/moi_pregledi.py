"""
Moi pregledi preku AI — pacient gi lista zakazani/zavrsheni/otkazani termini od Termin_pregled po email, datum, status i kategorija.
"""

# Import na potrebni biblioteki za prompt loader, utils za formatiranje, regex, datetime, baza i groq
from ai._kernel.prompt_loader import load_prompt # Vcituvanje na prompt od fajl za Groq
from ai._kernel.utils import format_datum, format_vreme # Formatiranje na datum i vreme za korisnikot
import re           # Regex za prepoznavanje na frazi vo prasanjeto
from datetime import date # Rabota so datumi (denes, idni, minati pregledi)
from database import get_connection # Konekcija so MySQL bazata
from ai._kernel.groq_helpers import izvlechi_json_so_ai # Groq izvlekuva JSON od prasanje
from ai._kernel.transliteracija import transliterijaj   # Latinica -> Kirilica za edinstveno prepoznavanje

# Regex: "pregledi za" / "pregledite za" — ne mesa se so drugi znachenja na "za"
_RE_PREGLEDI_ZA = re.compile(
    r"\b(прегледи|прегледите|pregledi|pregledite)\s+за\b", # Pattern za prepoznavanje na frazata
    re.IGNORECASE | re.UNICODE, # Ne e vazno golema/mala bukva; unicode za kirilica i latinica
)

# Izvleci datum od prasanje za lista pregledi (dozvolen i minat den)
def datum_za_pregledi_od_prasanje(prasanje: str) -> date | None:
    """Датум од прашање за листа прегледи (дозволен и минат ден)."""
    from ai.pacient.slobodni_termini import ( # Pomosni parseri od modulot za termini
        _DATUM_BROJ_RE,
        _ISO_DATUM_RE,
        _RE_DAN_MES,
        _mesec_od_tekst,
        _parsiraj_dan_mesec,
        datum_od_prasanje_lokalno,
    )

    d = datum_od_prasanje_lokalno(prasanje) # Prvo probaj lokalniot parser (denes, utre, ISO)
    if d:
        return d # Ako e najden datum, vrati go

    p = transliterijaj(prasanje).lower()    # Edinstven format na tekstot za obrabotka
    denes = date.today()                # Denesniot datum za presmetka na relativni izrazi

    dm = _parsiraj_dan_mesec(p, denes)  # Parsiranje na den i mesec, na pr. "19 maj"
    if dm:
        return dm

    m = _RE_DAN_MES.search(p)           # Regex za "19 maj" ako parserot propadne
    if m:
        mesec = _mesec_od_tekst(m.group(2)) # Konvertiraj ime na mesec vo broj
        if mesec:
            try:
                return date(denes.year, mesec, int(m.group(1))) # Kreiraj datum ako e validen
            except ValueError:
                pass # Nevaliden kalendar datum

    m = _DATUM_BROJ_RE.search(p)        # Regex za 19.05.2026 ili 19/05
    if m:
        d, mo = int(m.group(1)), int(m.group(2)) # Izvleci den i mesec
        g = int(m.group(3)) if m.group(3) else denes.year # Godina (ili tekovna ako nedostasuva)
        if g < 100:
            g += 2000                   # Korekcija na kratka godina (25 -> 2025)
        try:
            return date(g, mo, d)
        except ValueError:
            pass

    m = _ISO_DATUM_RE.search(prasanje)  # 2026-05-19 vo originalot (bez transliteracija)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None # Nema prepoznaen datum


# Definiranje na zborovi za "prikazi / lista" vo prasanjeto
_RE_LISTA_PREGLEDI = re.compile(
    r"\b(прикаж\w*|приказ\w*|prikaz\w*|покаж\w*|pokaz\w*|види|vidi|листа|lista)\b",
    re.UNICODE | re.IGNORECASE,
)
_RE_GI_ZBOR = re.compile(r"\b(ги|gi)\b", re.UNICODE | re.IGNORECASE) # "gi" vo "prikazi gi"


# Proverka dali korisnikot bara celosna lista na pregledi
def prasanje_e_lista_site_pregledi(prasanje: str) -> bool:
    """
    „Прикажи ги сите прегледи" / „Prikazi gi site pregledi" — не пребарување лекар по име.

    Латиница „Prikazi" по transliteracija често станува „прикази" (з), не „прикажи" (ж).
    """
    if not prasanje or not prasanje.strip():
        return False # Prazno prasanje -> false
    p = transliterijaj(prasanje).lower()    # Normaliziran tekst
    if not re.search(r"\b(преглед|pregled|термин|termin)\w*\b", p, re.UNICODE):
        return False # Mora da spomne pregled ili termin
    if "закажани преглед" in p or "zakazani pregled" in p:
        return True # Eksplicitno moite zakazani
    if any(
        x in p
        for x in (
            "моите преглед",
            "moite pregled",
            "moi pregled",
            "мој преглед",
            "moj pregled",
            "мојот преглед",
        )
    ):
        return True # Sinonimi za moite pregledi

    ima_site = any(
        x in p for x in ("сите", "site", "all", "целосн", "celosn", "комплетн", "kompletn")
    ) # Proverka za "site"
    ima_prikazi = bool(_RE_LISTA_PREGLEDI.search(p)) or bool(
        re.search(
            r"\b(прикаж\w*|приказ\w*|prikaz\w*|покаж\w*|pokaz\w*)\s+ги\b",
            p,
            re.UNICODE,
        )
    ) # Prikazi / lista
    ima_gi = bool(_RE_GI_ZBOR.search(p))  # Proverka za zborot "gi"
    if ima_site and (ima_prikazi or ima_gi):
        return True # "prikazi gi site"
    if re.search(
        r"\b(прикаж\w*|приказ\w*|prikaz\w*|покаж\w*|pokaz\w*)\s+ги\s+"
        r"(site\s+)?(pregled|преглед)",
        p,
        re.UNICODE,
    ):
        return True
    return False


# Regex za "pregledi na/za datum" — na pr. termini na 25 maj
_RE_TERMINI_NA = re.compile(
    r"\b(прегледи|преглед|pregledi|pregled|термини|термин|termini|termin)\s+"
    r"(на|na|za|за)\b",
    re.UNICODE | re.IGNORECASE,
)


# Proverka za lista pregledi na konkreten datum
def prasanje_e_pregledi_datum(prasanje: str) -> bool:
    """„Прегледи за 19 мај" / „Termini na 25 maj" / „Прегледи на 19ти" — листа термини."""
    if not prasanje or not prasanje.strip():
        return False
    p = transliterijaj(prasanje).lower()
    if not re.search(r"\b(преглед|pregled|термин|termin)\w*\b", p, re.UNICODE):
        return False
    if _RE_PREGLEDI_ZA.search(p) or _RE_TERMINI_NA.search(p):
        return True # "pregledi za" ili "na"
    if re.search(r"\b(на|na|za|за)\s+\d", p):
        return True # "na 19" so brojka
    if re.search(r"\b(на|na)\s+\d{1,2}", p):
        return True
    if re.search(r"\bза\s+\d", p):
        return True
    return datum_za_pregledi_od_prasanje(prasanje) is not None # Ili ima parsiran datum


# Izvleci period/datum/broj/status preku AI ili pravila
def _izvlechi(prasanje: str) -> dict:
    from ai._kernel.groq_helpers import groq_zadolzhitelen, izvlechi_json_so_ai

    if prasanje_e_lista_site_pregledi(prasanje):
        return {"period": "site", "datum": None, "broj": None} # Brz pat bez Groq

    if msg := groq_zadolzhitelen():
        return {"_error": msg} # Proverka na Groq status

    podatoci = izvlechi_json_so_ai(
        f'Прашање: „{prasanje}"',
        load_prompt("pacient_moi_pregledi"),
        log_tag="moi_pregledi",
    ) # AI ekstraktor so prompt od fajl
    if podatoci.get("_error"):
        return podatoci # Greska od AI
    return podatoci # Vrati ekstrahirani podatoci (period, datum, broj, status, kategorija)


# Oznaki za statusite vo listata (kirilica kako vo baza)
STATUS_OZNAKI = {
    "закажан": "[закажан]",
    "завршен": "[завршен]",
    "откажан": "[откажан]",
}


def _baranje_e_lekarski_raspored(prasanje: str) -> bool:
    """Дали барањето е за лекарски распоред (не за лични прегледи на пациент)."""
    try:
        from ai.lekar.lekar_intent import prasanje_e_moj_raspored_lekar

        if prasanje_e_moj_raspored_lekar(prasanje):
            return True
    except ImportError:
        pass
    p = transliterijaj(prasanje).lower()
    if "закажан" in p and re.search(r"\b(преглед|pregled|термин|termin)\w*\b", p, re.UNICODE):
        if not any(x in p for x in ("мои", "moite", "moi ", "твои", "tvoi ")):
            return True
    return prasanje_e_pregledi_datum(prasanje) and not any(
        x in p for x in ("мои", "moite", "moi ", "твои", "tvoi ")
    )


# Glaven handler za lista na pregledi za najaven pacient
def odgovori_za_moi_pregledi(
    prasanje: str,
    pacient: dict | None,
    lekar: dict | None = None,
    kontekst: dict | None = None,
) -> str | dict:
    # Најавен лекар → ист flow како moj_raspored (отвора таб на панелот)
    if lekar and lekar.get("doctor_ID"):
        from ai.lekar.moj_raspored import odgovori_za_raspored

        return odgovori_za_raspored(prasanje, lekar, kontekst)

    # Validacija: pacientot mora da e najaven
    if not pacient or not pacient.get("email"):
        if _baranje_e_lekarski_raspored(prasanje):
            return {
                "odgovor": (
                    "За да ги видите закажаните прегледи на панелот, најавете се како лекар "
                    "(«Најава за лекар» на сајтот).\n\n"
                    'Потоа напишете, на пр.: „Прикажи ми закажани прегледи" или „Прегледи за 19.05".'
                ),
                "akcija": "otvori_lekar_login",
            }
        return {
            "odgovor": (
                'За да ги видиш своите прегледи преку AI асистентот, прво најави '
                'се како пациент (горе десно копчето „Најави се").\n\n'
                "Ако сте лекар, најавете се со лекарски профил — тогаш „Прегледи за [датум]“ "
                "ги прикажува вашите закажани прегледи на панелот."
            ),
            "akcija": "otvori_pacient_login",
        }

    podatoci = _izvlechi(prasanje) # Izvleci filteri od prasanje
    if podatoci.get("_error"):
        return str(podatoci["_error"]) # Greska od Groq

    # Normalizacija na statusi i kategorii
    status_filter = (podatoci.get("status") or "").strip().lower() or None
    if status_filter == "сите":
        status_filter = None # "site statusi" = bez filter
    kategorija = (podatoci.get("kategorija") or "").strip().lower() or None # Idni / minati
    broj = podatoci.get("broj") # Limit kolku redovi da se prikazat
    try:
        broj = int(broj) if broj else None
    except (ValueError, TypeError):
        broj = None # Nevaliden broj
    datum_str = (podatoci.get("datum") or "").strip() or None # ISO datum od AI
    if not datum_str:
        d = datum_za_pregledi_od_prasanje(prasanje) # Probaj lokalno od tekstot
        if d:
            datum_str = d.strftime("%Y-%m-%d")

    # SQL kverija za baza
    conn = None
    try:
        conn = get_connection() # Konekcija kon baza
        cur = conn.cursor(dictionary=True) # Rezultati kako recnik
        sql = (
            "SELECT termin_ID, datum_pregled, vreme_pregled, ime_lekar, "
            "       status_pregled, dijagnoza, terapija "
            "FROM Termin_pregled "
            "WHERE LOWER(TRIM(COALESCE(email_pacient,''))) = %s"
        ) # Bazen SELECT za termini na pacientot
        params: list = [pacient["email"].strip().lower()] # Email od najava

        if status_filter and status_filter in ("завршен", "закажан", "откажан"):
            sql += " AND status_pregled = %s" # Filter po status
            params.append(status_filter)

        if kategorija == "идни":
            sql += " AND datum_pregled >= %s" # Samo idni termini
            params.append(date.today())
        elif kategorija == "минати":
            sql += " AND datum_pregled < %s" # Samo minati termini
            params.append(date.today())

        if datum_str:
            sql += " AND datum_pregled = %s" # Konkreten den
            params.append(datum_str)

        sql += " ORDER BY datum_pregled DESC, vreme_pregled DESC" # Najnovi prvi
        if broj:
            sql += " LIMIT %s" # LIMIT ako e baran broj
            params.append(int(broj))

        cur.execute(sql, tuple(params)) # Izvrsi query
        rows = cur.fetchall() or [] # Site najdeni termini
        cur.close()
    except Exception as e:
        print(f"[moi_pregledi] DB greska: {e}") # Logiranje na greska
        return "Се случи грешка при вчитувањето на твоите прегледи. Те молам обиди се повторно."
    finally:
        if conn:
            conn.close() # Zatvori konekcija

    if not rows: # Nema termini za baranjeto
        if datum_str:
            try:
                d = date.fromisoformat(datum_str[:10])
                return f"Немаш прегледи на {format_datum(d)}."
            except ValueError:
                pass
        return "Немаш прегледи кои одговараат на твоето барање."

    # Rezime po status
    br_zakazan = sum(1 for r in rows if r.get("status_pregled") == "закажан") # Broj zakazani
    br_zavrsen = sum(1 for r in rows if r.get("status_pregled") == "завршен") # Broj zavrseni
    br_otkazan = sum(1 for r in rows if r.get("status_pregled") == "откажан") # Broj otkazani

    if datum_str: # Naslov so datum
        try:
            d = date.fromisoformat(datum_str[:10])
            naslov = f"Твои прегледи за {format_datum(d)} ({len(rows)})"
        except ValueError:
            naslov = f"Твои прегледи ({len(rows)})"
    else:
        naslov = f"Твои прегледи ({len(rows)})" # Opst naslov
    summary = (
        f"Закажани: {br_zakazan} | Завршени: {br_zavrsen} | Откажани: {br_otkazan}"
    ) # Edna linija so brojki
    redovi = [naslov, summary, ""] # Pocetok na izlezot

    # Formatiranje na izlezot za pacientot
    for r in rows:
        dat = format_datum(r.get("datum_pregled")) # Datum za prikaz
        vrm = format_vreme(r.get("vreme_pregled")) # Vreme za prikaz
        ime_lekar = (r.get("ime_lekar") or "—").strip() or "—" # Ime na lekarot
        status = r.get("status_pregled") or "—"
        oznaka = STATUS_OZNAKI.get(status, "") # Oznaka [zakazan] i sl.

        red = f"- {dat} {vrm} – {ime_lekar} {oznaka}".rstrip() # Eden red vo listata
        if r.get("status_pregled") == "завршен": # Za zavrseni — dijagnoza i terapija
            dij = (r.get("dijagnoza") or "").strip()
            ter = (r.get("terapija") or "").strip()
            if dij:
                red += f"\n   Дијагноза: {dij}"
            if ter:
                red += f"\n   Терапија: {ter}"

        redovi.append(red) # Dodadi vo listata

    return "\n".join(redovi) # Vrati go tekstot do korisnikot
