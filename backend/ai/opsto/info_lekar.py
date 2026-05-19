"""Informacii za konkreten lekar.
Kako raboti:
1. AI (Groq) prepoznava za koj lekar prashuva korisnikot (od lista vo DB).
2. Vrakja: specijalnost, email, dali e dezuren (+ upatstvo za pregled / slobodni termini)."""

from datetime import date, datetime, time, timedelta  
from database import get_connection 
from ai._kernel.utils import format_datum, format_vreme  
from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje  
from ai._kernel.transliteracija import transliterijaj 
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai 
from ai.pacient.slobodni_termini import (  
    lekar_od_zakazi_kontekst,
    prasanje_bar_lekar_od_kontekst,
    prasanje_e_specijalnost_izbran_lekar,
)

def zimi_dezurstva_za_lekar(doctor_id: int, denovi_napred: int = 7) -> list[dict]:  # funkcija za zemanje dezurstva od baza za daden lekar
    conn = None  # inicijalizacija na vrska
    try:  # pocetok na bezbeden sql blok
        conn = get_connection()  # zemanje aktivna konekcija
        cur = conn.cursor(dictionary=True)  # rechnichki kursor za polesno mapiranje na kolonite
        cur.execute(  # izvrshuvanje na selektot za dezurstva pomegju denes i narednite n denovi
            """
            SELECT datum, oddel, vreme_od, vreme_do
            FROM Dezurstva
            WHERE doctor_ID = %s
              AND datum BETWEEN %s AND %s
            ORDER BY datum, vreme_od
            """,
            (doctor_id, date.today(), date.today() + timedelta(days=denovi_napred)),
        )  # kraj na sql upitot so parametri
        rezultati = cur.fetchall()  # prevzemanje na site redovi od bazata
        cur.close()  # zatvoranje na kursorot
        return rezultati  # vrakjanje na listata so dezurstva
    except Exception as e:  # fakanje greski pri sql operacijata
        print(f"[info_lekar] dezurstva greska: {e}")  # logiranje na greskata na latinica
        return []  # vrakjanje prazna lista pri problem
    finally:  # siguren blok za osloboduvanje resursi
        if conn:  # ako konekcijata ostala otvorena
            conn.close()  # zatvori ja vrskata so bazata


def _as_time(v) -> time | None:  # pomosna funkcija za bezbedna konverzija vo time objekt
    if v is None:  # ako e none vrednosta
        return None
    if isinstance(v, time):  # ako veke e time objekt
        return v
    if hasattr(v, "hour") and hasattr(v, "minute"):  # ako ima atributi za chas i minuta
        return v  # vrakjanje bidejki e datetime.time-like
    if hasattr(v, "total_seconds"):  # handling za timedelta objekti od mysql
        s = int(v.total_seconds())  # pretvoranje vo sekundi
        return time(s // 3600, (s % 3600) // 60)  # presmetka na chas i minuta
    try:  # obid za parsiranje na string vo format HH:MM
        parts = str(v).strip().split(":")  # delenje po dvotocka
        if len(parts) >= 2:  # ako ima barem dva dela
            return time(int(parts[0]), int(parts[1]))  # kreiranje time objekt
    except (ValueError, TypeError):  # preskok na greski pri losh format
        pass
    return None  # vrakjanje none ako konverzijata potfrli


def _dezurstvo_datum_vreme(d: dict) -> tuple[date | None, time | None, time | None]:  # normalizacija na dezurstvo
    datum = d.get("datum")  # zemanje na datumot
    if isinstance(datum, datetime):  # ako e datetime namesto chist date
        datum = datum.date()  # izvlekuvanje na chistiot datum
    return datum, _as_time(d.get("vreme_od")), _as_time(d.get("vreme_do"))  # vrakjanje na torkata со konvertirani vreminja


def _e_na_dezurstvo_sega(d: dict, sega: datetime) -> bool:  # proverka dali doktorot dezura vo tekovniot moment
    datum, vreme_od, vreme_do = _dezurstvo_datum_vreme(d)  # zemanje na normaliziranite podatoci
    if not datum or datum != sega.date() or not vreme_od or not vreme_do:  # ako ne e denes ili falat vreminja
        return False  # ne e na dezurstvo sega
    t = sega.time()  # zemanje na tekovnoto vreme
    return vreme_od <= t <= vreme_do  # vrakjanje na uslovot dali vremeto e vnatre vo intervalot


def _sledno_dezurstvo(dezurstva: list[dict], sega: datetime) -> dict | None:  # baranje na idno najblisko dezurstvo
    """Prvo dezurstvo shto se ushte ne zavrshilo (denes ili idnina)."""
    for d in dezurstva:  # ciklus niz site dezurstva
        datum, vreme_od, vreme_do = _dezurstvo_datum_vreme(d)  # normalizacija na tekovnoto od listata
        if not datum or not vreme_od:  # ako nema bazicni podatoci
            continue  # preskokni go
        if datum > sega.date():  # ako datumot e vo idninata
            return d  # ova e slednoto dezurstvo
        if datum == sega.date() and vreme_do and sega.time() < vreme_do:  # ako e denes no seuste ne zavrshilo
            return d  # go vrakjame deneshnoto aktivno/idno dezurstvo
    return None  # nema idni dezurstva vo listata


def _linija_za_dezurstvo(d: dict, prefiks: str) -> str:  # formatiranje na tekstot za dezurstvo
    datum, vreme_od, _ = _dezurstvo_datum_vreme(d)  # zemanje na podatocite
    if not datum:  # ako nema datum
        return prefiks  # vrati go samo prefiksot
    return f"{prefiks}\nDatum: {format_datum(datum)}\nPocetok na dezurstvo: {format_vreme(vreme_od)}"  # latinichen izlez


def _dezuren_status(dezurstva: list[dict]) -> str:  # glaven status tekst za dezurstvo
    """
    Dezuren: Da — samo ako vo momentot e na dezurstvo (so datum i pocetok).
    Dezuren: Ne — ako ne e sega; ako ima idno dezurstvo, se pechati datum i pocetok.
    """
    if not dezurstva:  # ako listata e prazna
        return "Dezuren: Ne"  # vrati default latinicen string

    sega = datetime.now()  # tekovno vreme na serverot
    for d in dezurstva:  # proverka dali dezura vo momentov
        if _e_na_dezurstvo_sega(d, sega):  # ako uslovot e ispolnet
            return _linija_za_dezurstvo(d, "Dezuren: Da")  # vrati formatiran uspeshen status

    sledno = _sledno_dezurstvo(dezurstva, sega)  # baranje na sledno dezurstvo ako ne dezura sega
    if sledno:  # ako ima idno zakazano dezurstvo во sistemot
        return _linija_za_dezurstvo(sledno, "Dezuren: Ne")  # vrati deka ne e sega no pishi koga ke bide

    return "Dezuren: Ne"  # default izlez ako nema nikakvo idno dezurstvo


def _resolviraj_lekar(prasanje: str, kontekst: dict | None) -> tuple[dict | None, bool]:  # ruter za naogjanje lekar
    from ai.pacient.slobodni_termini import lekar_iz_izbran_kontekst  # uvoz na vnatreshna logika za kontekst

    if prasanje_bar_lekar_od_kontekst(prasanje) or prasanje_e_specijalnost_izbran_lekar(  # ako prasanjeto bara lekar od memorija
        prasanje, kontekst
    ):  # kraj на proverka za kontekstualno baranje
        lekar = lekar_iz_izbran_kontekst(kontekst)  # zemi go zacuvaniot lekar od prethodnata sesija
        if lekar:  # ako navistina imalo zacuvan lekar
            return lekar, True  # vrakjame lekar i flag deka e povlechen od kontekst
            
    lekar = najdi_lekar_od_prasanje(prasanje)  # ako ne e od kontekst probaj da go detektirash preku ime so groq lookup
    if lekar:  # ako e uspeshno pronajden preku ime
        return lekar, False  # vrakjame lekar i flag deka e nov direktno od prasanjeto
        
    lekar = lekar_od_zakazi_kontekst(kontekst)  # posleden posrednik - zemi lekar od tekoven proces na zakazuvanje
    return lekar, lekar is not None  # vrakjanje na rezultatot


def prasanje_e_oblast_ili_specijalnost_lekar(prasanje: str) -> bool:  # detekcija dali se bara struchnost na lekar
    """"Od koja oblast e lekarot Dragica Timova?" — konkretno ime."""
    from ai._kernel.lekar_lookup import (  # uvoz na vnatreshni regex shabloni za prebaruvanje na iminja
        _RE_POSLE_DR,
        _RE_POSLE_LEKAROT,
        izvlechi_delovi_ime,
    )

    p = transliterijaj(prasanje).lower()  # latinica i mali bukvi za pooling
    if any(x in p for x in ("лекари", "lekari", "доктори", "doktori", "koi lekari")):  # ako e opsto prasanje za site lekari
        return False  # prekin bidejki ova ne e za konkreten lekar
        
    if not any(  # proverka dali sodrzi zborovi povrzani so struchnost, specijalnost ili oblast
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
            "od koja",
        )
    ):  # kraj na uslovot za klucni zborovi
        return False  # ne se bara oblast
        
    if _RE_POSLE_DR.search(p) or _RE_POSLE_LEKAROT.search(p):  # ako ima shablon d-r plus tekst
        return True  # potvrda deka e validno prasanje za oblast na lekar
        
    return len(izvlechi_delovi_ime(prasanje)) >= 2  # vrakjanje true ako se detektirani barem dva dela od ime (ime i prezime)


def _sablon_oblast_lekar(lekar: dict) -> str:  # brzi template odgovor za oblast na lekar bez povik do llm
    """Kratok, tochen odgovor — bez Groq ("e infektologija" i slicno)."""
    spec = (lekar.get("specialty") or "Opsta praksa").strip()  # zemanje specijalnost со default opsta praksa
    prezime = (lekar.get("surname") or "").strip()  # zemanje na prezime
    ime = f"d-r {lekar['name']} {lekar['surname']}"  # sklopuvanje na celosnoto ime na latinica
    return (  # vrakjanje na struktura na latinica
        f"Specijalnosta na {ime} e {spec}.\n\n"
        f'Za slobodni termini: "Koga e sloboden d-r {prezime}?"'
    )


def _e_prasanje_dali_raboti(prasanje: str) -> bool:  # proverka dali korisnikot prashuva dali doktorot e vraboten tuka
    p = transliterijaj(prasanje).lower()  # prefrli vo latinica i mali bukvi
    return any(  # dali postoi vrakjanje na bilo koj zbor vo prasanjeto
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
    )  # kraj на proverka на kluchni zborovi


def _dezurstvo_za_fakti(dezurstva: list[dict]) -> dict[str, str]:  # konverzija na dezurstvoto vo recnik na fakti za ai formaterot
    sega = datetime.now()  # tekovno vreme
    for d in dezurstva:  # ciklus niz dezurstva
        if _e_na_dezurstvo_sega(d, sega):  # ako dezura sega vo momentov
            datum, vreme_od, _ = _dezurstvo_datum_vreme(d)  # zemi podatoci
            return {  # vrati struktura deka dezura sega
                "status": "da_sega",
                "datum": format_datum(datum) if datum else "",
                "pocetok": format_vreme(vreme_od),
            }
            
    sledno = _sledno_dezurstvo(dezurstva, sega)  # ako ne e sega najdi idno najblisko
    if sledno:  # ako ima idno
        datum, vreme_od, _ = _dezurstvo_datum_vreme(sledno)  # zemi detali za idnoto dezurstvo
        return {  # vrati recnik so status ne no so idni parametri
            "status": "ne_so_idno",
            "datum": format_datum(datum) if datum else "",
            "pocetok": format_vreme(vreme_od),
        }
    return {"status": "ne", "datum": "", "pocetok": ""}  # vrati deka voopshto nema dezurstvo vo sistemot


def _sablon_info_lekar(  # osnova na tekstualniot shablon za odgovor za lekar
    lekar: dict, prasanje: str, od_kontekst: bool, kontekst: dict | None = None
) -> str:
    """Shablon fallback — istata sodrzina kako porano, celosno na latinica."""
    spec = lekar.get("specialty") or "Opsta praksa"  # zemi specijalnost
    email = (lekar.get("email") or "").strip()  # zemi email adresa
    doctor_id = lekar["doctor_ID"]  # zemi vnatreshno id
    dezurstva = zimi_dezurstva_za_lekar(doctor_id)  # povlechi gi site dezurstva od bazata за ovoj lekar
    prezime = lekar.get("surname") or ""  # prezime
    ime = f"d-r {lekar['name']} {lekar['surname']}"  # celosno ime

    footer = [  # fusnota so nasoki za pacientot na latinica
        "",
        "Dokolku sakate pregled, najavete se so korisnicki profil na sajtot.",
        f'Za slobodni termini napishete: "Koga e sloboden d-r {prezime}?"',
    ]

    # Izbraniot lekar / oblast — samo ime, specijalnost, email
    if prasanje_e_specijalnost_izbran_lekar(prasanje, kontekst):  # ako e povlecheno od kontekst za specijalnost
        return "\n".join(  # direktno vrakjame chist latinicen tekst na polinjata
            [
                f"Ime i prezime: {lekar['name']} {lekar['surname']}",
                f"Specijalnost: {spec}",
                f"Email: {email if email else '—'}",
            ]
        )

    if prasanje_e_oblast_ili_specijalnost_lekar(prasanje):  # ako e prasanje samo za oblast/specijalnost
        return _sablon_oblast_lekar(lekar)  # vrati go uprosteniot bazičen tekstualen shablon

    # Opsti informacii za lekar
    delovi = [f"{ime} ({spec})"]  # pocetok na listata so redovi za opsto info
    if od_kontekst:  # ako lekarot e detektiran od pretodnata poraka
        delovi.append("(Od prethodnata poraka vo razgovorot.)")  # napomena na latinica
    if _e_prasanje_dali_raboti(prasanje):  # ako eksplicitno prashale dali raboti tuka
        delovi.append("")
        delovi.append("Da, raboti vo Klinicka Bolnica Shtip.")  # potvrdna poraka na latinica
    delovi.extend(  # lepenje na email, status na dezurstvo i fusnota vo paket
        [
            "",
            f"Email: {email if email else '—'}",
            _dezuren_status(dezurstva),  # povik do funkcijata shto go vrakja statusot za dezurstvo
            *footer,  # otpakuvane na fusnotata na dnoto
        ]
    )
    return "\n".join(delovi)  # spojuvanje so novi redovi i izlez на stringot


def _format_info_lekar(  # funkcija za predavanje na podatocite na finalno ai doteruvanje na jazikot
    lekar: dict, prasanje: str, od_kontekst: bool, kontekst: dict | None = None
) -> str:
    sablon = _sablon_info_lekar(lekar, prasanje, od_kontekst, kontekst)  # zemi go bazicniot latinicen shablon
    if prasanje_e_specijalnost_izbran_lekar(  # ako se raboti za specificni pod-prasanja, preskokni go ai-to
        prasanje, kontekst
    ) or prasanje_e_oblast_ili_specijalnost_lekar(prasanje):  # proverka
        return sablon  # direktno vrati go shablonot bez dopolnitelno procesiranje

    spec = lekar.get("specialty") or "Opsta praksa"  # polnenje podatoci za rechnik na fakti
    email = (lekar.get("email") or "").strip()  # chistenje email
    dezurstva = zimi_dezurstva_za_lekar(lekar["doctor_ID"])  # zemanje dezurstva od baza
    prezime = lekar.get("surname") or ""  # prezime

    podatoci = {  # struktura so fakti vrz koja ai modelot ke ja dopolni porakata
        "ustanova": "Klinicka Bolnica Shtip",  # latinicna vrednost
        "ime": lekar.get("name") or "",
        "prezime": prezime,
        "specialnost": spec,
        "email": email or None,
        "dezurstvo": _dezurstvo_za_fakti(dezurstva),  # recnik so statusi za dezurstvo
        "raboti_vo_bolnica": True,
        "od_kontekst": od_kontekst,
        "prasanje_dali_raboti": _e_prasanje_dali_raboti(prasanje),
        "sledna_akcija": (  # sledni чекори за корисникот напишани на латиница
            f'Za slobodni termini: "Koga e sloboden d-r {prezime}?". '
            "Za pregled — najava so korisnicki profil na sajtot."
        ),
    }  # kraj на rechnikot so fakti
    return formatiraj_odgovor_so_ai(  # povik do ai formaterot koj ke ja zacuva strukturata no ke ja napravi prirodna
        "info_lekar",
        podatoci,
        sablon,
        prasanje=prasanje,
    )


def _kontekst_posle_info(lekar: dict, kontekst: dict | None) -> dict:  # azuriranje na memorijata na razgovorot so id na lekarot
    did = int(lekar["doctor_ID"])  # zemanje cel broj id
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}  # kloniranje na postoickiot kontekst
    ctx["zakazi_od_slobodni"] = {  # podgotovka na pod-struktura za eventualno direktno zakazuvanje
        "doctor_id": did,
        "datum": (ctx.get("zakazi_od_slobodni") or {}).get("datum"),
    }
    ctx["last_doctor_id"] = did  # postavuvanje na kluchot za posleden spomnat doktor vo sesijata
    return ctx  # vrakjanje na azuriraniot kontekst rechnik


def odgovori_za_info_lekar(prasanje: str, kontekst: dict | None = None) -> str | dict:  # GLAVNA EKSPORTIRANA FUNKCIJA
    lekar, od_kontekst = _resolviraj_lekar(prasanje, kontekst)  # obid za naogjanje lekar preku ime ili memorija

    if not lekar:  # AKO NEMA PRONAJDENO LEKAR — proverka dali korisnikot vsushnost utnal namera (intent)
        from ai.pacient.moi_pregledi import prasanje_e_pregledi_datum  # uvoz na proverki za drugi intents
        from ai.opsto.vest_naslov import pronajdi_vest_po_naslov  # uvoz za proverka na vesti
        from ai.pacient.moi_pregledi import prasanje_e_lista_site_pregledi  # uvoz za lista pregledi

        if prasanje_e_lista_site_pregledi(prasanje):  # scenario 1: korisnikot saka lista na pregledi no ne e najaven
            return {  # vrakjame recnik so latinicni nasoki za najava na interfejsot
                "odgovor": (
                    "Za lista na pregledi najavete se kako lekar ili pacient, pa napishete, na pr.:\n"
                    '"Prikazi mi zakazani pregledi" (lekar) ili "Moite pregledi" / '
                    '"Prikazi gi site pregledi" (pacient).'
                ),
                "kontekst": kontekst if isinstance(kontekst, dict) else None,
            }

        if prasanje_e_pregledi_datum(prasanje):  # scenario 2: korisnikot prashal za termini na datum bez sesija
            return {  # vrakjame latinicno predupreduvanje za avtentikacija
                "odgovor": (
                    "Za termini na datum najavete se kako pacient ili lekar, pa napishete, na pr.:\n"
                    '"Pregledi za 19.05" (pacient) or "Prikazi zakazani pregledi" / '
                    '"Termini na 25.05" (lekar).'
                ),
                "kontekst": kontekst if isinstance(kontekst, dict) else None,
            }

        vest = pronajdi_vest_po_naslov(prasanje)  # scenario 3: prasanjeto lici na naslov na vest od sajtot namesto lekar
        if vest:  # ako e pronajdena vest so takov naslov vo bazata
            naslov = (vest.get("naslov") or "").strip()  # zemi go naslovot
            return {  # vrati odgovor koj go nasocuva kon brishenje vesti (ako e direktor) na latinica
                "odgovor": (
                    f"Ova lici na naslov na vest, ne na ime na lekar: \"{naslov}\".\n\n"
                    "Za brishenje (samo direktor) napishete, na pr.:\n"
                    f"\"Izbrishi ja vesta so naslov {naslov}\"."
                ),
                "kontekst": kontekst if isinstance(kontekst, dict) else None,
            }
            
        if prasanje_bar_lekar_od_kontekst(prasanje) or prasanje_e_specijalnost_izbran_lekar(  # scenario 4: pobaran lekar od prazna memorija
            prasanje, kontekst
        ):  # proverka
            return {  # izvestuvanje na latinica deka nema zacuvan lekar vo razgovorot
                "odgovor": (
                    "Ne gledam zacuvoriziran izbran lekar od prethodnata poraka.\n\n"
                    "Prvo navedete go lekarot (na pr. \"Koga e sloboden d-r Petrovski?\") "
                    "ili zakazete pregled, pa povtorete."
                ),
                "kontekst": kontekst,
            }
            
        return {  # KRAEN FALLBACK: standarden latinicen odgovor koga navistina nema pronajdeno takvo ime vo celata baza
            "odgovor": (
                "Ne najdov lekar so toa ime vo evidencijata na Klinicka Bolnica Shtip.\n"
                "Proverete go pravopisot ili prebarajte na sajtot vo delot \"Lekari\".\n"
                "Primer: \"Informacii za d-r Marko Petrov\" ili \"Dali raboti dr Marija Hubreva?\""
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    # AKO LEKAROT E USPESHNO DETEKTIRAN
    text = _format_info_lekar(lekar, prasanje, od_kontekst, kontekst)  # generiraj go finalniot latinicen tekst
    return {"odgovor": text, "kontekst": _kontekst_posle_info(lekar, kontekst)}  # vrati recnik so odgovor i nov kontekst