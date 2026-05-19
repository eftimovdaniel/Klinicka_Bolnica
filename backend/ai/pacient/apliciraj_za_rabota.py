"""
Korisnikot moze da aplicira za nekoja rabota pozicija so pomos na ai agento, se najavuva kako pacient, se bara broj na medicinska 
licena i so zapisuvanje na istata podatocite se obrabotuvaat i negovoto ime se smestuva vo the database kako kandidat koj ima podneseno baranje za rabota
"""
import re           # sabloni kako ai da mi gi dava odgovorite
from datetime import datetime       # rabota o datum i vreme, koristam gi koga apliciram za rabota i koga gi prikazuvam aplikaciite na korisnikot
from database import get_connection # konekcija so the database
from ai._kernel.ai_json import parse_ai_json    # funkcija koja go cita i parsira ai odgovorot vo Python recnik
from ai._kernel.db_helpers import ( # pomosna funkcija za interakcija so bazata, kako da gi zemam aplikaciite, da gi brisam, da gi prikazuvam i sl.
    as_dict,        # go pretvarame sql redot vo Python recnik 
    fetch_one,      # vlecam samo eden rezlutat od izvedenata akcija 
    normalize_int,  # normalizacija na integer vrednosti, za da se osiguram deka ID-to e validno
    prijaveni_order_desc,   # se sortiraat aplikaciite za rabota po datumi 
    prijaveni_pk_column,    # go zema imeto na primarniot kluc od tabelata so prijavite
    prijaveni_row_id,       # id od aplikacijata, od redot vo bazata
    prijaveni_select_sql,   # Select za da moze da se vidat lekarite koj aplicirale za rabota
)
from ai._kernel.groq_client import ask_ai   # so ovaa funkcija isprakam poraki do LLM modelot sto go koristam (Groq) za da dobijam nekoj odgovor
from ai._kernel.transliteracija import transliterijaj   # latinica -> kirilica, agento sekogas dava odgovor na kirilica
from ai._kernel.utils import format_datum_vreme # formatiranje na datum i vreme za prikaz na korisnikot
from vrabotuvanje_helpers import fetch_aktivni_oglasi_rows, format_rok_datum   # aktivni oglasi i rok za prijavuvanje
# ai agento moze da gi prenasoce korisnikot na delot kade imame aktivni oglasi za rabota,
# tuka gi prenosocuva na index.html delot kade imame kariera 
NAV_KARIERA = {"target": "index.html#kariera", "label": "Кариера"}
# promtovi so koj ai agento (LLM) modelot go na nekoj nacin treniram da moze od kontekst na porakite da gi izvlece poziciite
PROMPT_POZICIJA = """
Ти си систем што извлекува позиција за работа од прашање.
Корисникот сака да аплицира за работа во болница. Извлечи го името на позицијата за која аплицира.
Врати САМО JSON:
{"pozicija": "<име на позицијата>" | null}
Правила:
- Корисникот пишува на македонски (можно е и латиница).
- Прифатени примери: „кардиолог", „хирург", „анестезиолог", „медицинска сестра",
  „гинеколог", „педијатар", „радиолог", „интернист", „уролог" итн.
- Ако корисникот пишува на латиница, врати на кирилица: „kardiolog" → „Кардиолог".
- Ако позицијата НЕ е јасна → null.
- „сакам да аплицирам за работа", „да работам кај вас", „вработување" БЕЗ
  конкретна специјалност/оддел → null (не „работа" како позиција).
- Ако корисникот залепи цел **оглас за работа** (на пр. „Се вработува медицинска сестра…"),
  извлечи ја позицијата од текстот (на пр. „Медицинска сестра").
БЕЗ markdown, БЕЗ објаснувања.
""".strip() # gi trgame site nepotrebni prazni mesta od vnesenata poraka, za da e se osigurame deka agento ne gleda nekoja zborovi plus
# promtovi za medicinska licena, treba da poznaa dali e vnesena brojak ili ne, 
# bidejki licencata mora da e broj, a ne tekst, i da znae da prepoznae zborovi kako „немам", „преска", „пропушти" за да znae deka korisnikot ne saka da vnesi licenca и da se preskoci toj del od procesot
PROMPT_LICENCA = """
Ти си систем што извлекува број на медицинска лиценца од одговор.
Корисникот ти прати порака која може да содржи број на лиценца.
Врати САМО JSON:
{"licenca": "<број (само цифри)>" | null, "preskoki": true/false}
Правила:
- Извлечи го бројот (само цифрите). Пр. „Бројот ми е 12345" → "12345".
- Ако корисникот напише „немам", „преска", „пропушти", „не сакам" → preskoki: true, licenca: null.
- Ако не е јасно → licenca: null, preskoki: false.
БЕЗ markdown. """.strip() # trgame praznite mesta kaj agento
# funkcija koja proveriva dali korsnikot ima staveno teskt od nadvoresen oglas za rabota, bidejki ako ima, treba da se obideme da izvlece pozicija direktno od toj tekst, namesto da se obiduvame da ja izvlece od prasanje
def _tekst_e_zalepen_oglas(prasanje: str) -> bool:
    """Цел текст на оглас (копиран од сајт/FB), не само „сакам да аплицирам“."""
    p = transliterijaj(prasanje).lower()  # ako e na latinica baranjeto go pretvara na kirilica i site mali bukvi
    ima_oglas = any(    # proverka dali vo vnesenta sodrzina imam bareme eden klucen zbor koj ke detektira dali korisnikot saka da aplicira za rabota ili imam nekoe drugo baranje
        x in p  # od vnesenito tekt (p) se prebaruva dali e venseno nekoj od zboroviet podolu i ako e smestuvame go vo x za obrabotka
        for x in (
            "оглас за работа",
            "oglas za rabota",
            "се вработува",
            "se vrabotuva",
            "можност за аплицирање",
            "moznost za apliciranje",
            "рок за пријавување",
        )
    )
    # proverka dali vo vnesot e vnesen nekoj od klucnite zborovi za pozicija ili oddel 
    ima_pozicija = any(
        x in p   # proverka na zborovite vo tekstot
        for x in (
            "медицинск",
            "сестр",
            "лекар",
            "доктор",
            "гинекол",
            "гиникол",
            "акауш",
            "кардиол",
            "хирург",
            "одделот",
        )
    )
    return ima_oglas and ima_pozicija   # na kraj se vraka true ako korsnikot ima vneseno deka e kandidat za rabota i ima nekoja aktivna pozicija za koja istiot saka da aplicira, vo sprotivno e false
# ako e vensen pogolem tekst se obiduvame da ja izvleceme rabotnata pozcija pobrzo
# voa go koristam koga groq tokenite ke mi se istroseni, i ja vlecam od kontekst na imputot
def _izvlechi_pozicija_od_oglas_pravila(prasanje: str) -> str | None:
    """Брзо извлекување од типичен текст на оглас (без Groq)."""
    # prasanjeto se pretvara vo mali kirilicno bukvi ode vo proces na obrabotka
    p = transliterijaj(prasanje).lower()
    if "медицинск" in p and "сестр" in p:   # ako nekade ima vnesenо медицинска, se prepoznava i vraka dokolku ima oglas za medicinska sestra
        return "Медицинска сестра"          #   vraka dokolku imame aktivni oglasi
    if "гинекол" in p or "гиникол" in p:    # proverka za ginekolog vo tekstot
        if "сестр" in p:                    # ako ima i sestra se raboti za medicinska sestra
            return "Медицинска сестра"      # vrakame medicinska sestra
        return "Гинеколог"                  # inaku se raboti za ginekolog
    if "акауш" in p:                        # proverka za akuser
        return "Акушер"                      # vrakame akuser
    if "кардиол" in p:                      # proverka za kardiolog
        return "Кардиолог"                   # vrakame kardiolog
    if "хирург" in p:                         # proverka za hirurg
        return "Хирург"                     # vrakame hirurg
    if "урол" in p:                          # proverka zaa urolog
        return "Уролог"                     # vrakame urolog
    if "анестез" in p:                      # proverka za anesteziolog
        return "Анестезиолог"               # vrakame anesteziologg
    
    m = re.search(r"\(([^)]+)\)", prasanje)     # voa go koristi koa go testira i ako ne najde pozicija vo teksto pregleduva dali imam nekade () i ni gi cita
    if m:
        inner = m.group(1).strip()  # dokolku ima () go cita i trga prazni mesta
        if len(inner) > 3 and len(inner) < 80:  # dali iimame dovolno bukvi za da moze da bide pozicija 0<pozicija<80
            return inner[0].upper() + inner[1:] if inner else None  # ako ime go vrakame stringo so golema bukva na pocetok
    return None # dokolku nema vneseno vo tekstot nekoja pozicija ili nema aktiven oglas none

# pozicija od zalepen oglas (pravila) ili preku groq
def _baraj_pozicija_za_aplikacija(prasanje: str) -> str | None:
    """Позиција од оглас (правила) или преку AI."""
    if _tekst_e_zalepen_oglas(prasanje):    # ako e prepoznaen kako kopiran oglas od nadvor
        poz = _izvlechi_pozicija_od_oglas_pravila(prasanje) # probaj da izvleces pozicija po brzi pravila
        if poz:                             # ako e najdeno nesto
            return poz                      # vrati ja izvlecenata pozicija
    return _izvlechi_pozicija(prasanje)     # inaku pusti ja na povomosen ai agent da ja izvlece


# odgovor koj bara najava kako pacient pred da se isprati aplikacija
def _odgovor_bara_pacient_login(kontekst_za_po_login: dict | None, prikaz_pozicija: str) -> dict:
    out: dict = {                           # se podgotvuva odgovorot koj bara najava kako pacient
        "odgovor": (
            f"Го препознав огласот за работа: {prikaz_pozicija}.\n\n"
            "За да ја испратам апликацијата преку AI, прво треба да се "
            "најавиш како пациент (не како лекар). "
            "Ти ја отворам формата за најава — по најавата напиши «да» "
            "или «сакам да аплицирам» за да продолжиме."
        ),
        "akcija": "otvori_pacient_login",   # akcija koja kazuva na frontendo da ja otvori formata za pacient
        "navigacija": NAV_KARIERA,          # navigacija kon kariera
    }
    if kontekst_za_po_login:                # ako imame zacuvan kontekst za po najavata
        out["kontekst"] = kontekst_za_po_login # dodadi go vo izlezot
    else:
        out["kontekst"] = None              # inaku stavi null
    return out                              # vrati go recnikot so podatoci za frontendo


# normalizacija na email za sporedba (gmail tocki i +alias)
def _email_kluc_za_sporedba(email: str) -> tuple[str, str] | None:
    """(local, domain) — Gmail: без точки и +alias."""
    e = (email or "").strip().lower()       # cistenje na prazni mesta i pretvaranje vo mali bukvi
    if "@" not in e:                        # ako nema majmunska bukva toa ne e validen email
        return None                         # vrati null
    local, domain = e.split("@", 1)         # podeli go emailot na lokalen del i domen
    domain = domain.replace("googlemail.com", "gmail.com") # normalizacija na googlemail vo gmail
    if domain == "gmail.com":               # ako domenot e gmail
        local = local.split("+")[0].replace(".", "") # trgni go delot posle plus i trgni gi tockite
    return local, domain                    # vrati go normaliziraniot par za sporedba


def _email_se_sovpaaga(a: str, b: str) -> bool:
    ka, kb = _email_kluc_za_sporedba(a), _email_kluc_za_sporedba(b) # gi zemame klucevite za sporedba na dvata email-i
    if ka and kb:                           # ako dvata se validno parsirani
        return ka == kb                     # sporedi gi lokalniot del i domenot directly
    return (a or "").strip().lower() == (b or "").strip().lower() # inaku napravi obicna sporedba so goli stringovi


# email od patient tabela po pacient_ID
def _email_iz_baza_po_pacient_id(pacient_id: int) -> str | None:
    conn = None                             # inicijalizacija na konekcijata
    try:
        conn = get_connection()             # zemi konekcija do bazata na podatoci
        cur = conn.cursor(dictionary=True)  # otvori kuror koj vraka rezultati kako recnik
        cur.execute(                        # izvrsi selekt query za email po pacient id
            "SELECT email FROM patient WHERE patient_ID = %s LIMIT 1",
            (pacient_id,),
        )
        row = fetch_one(cur)                # zemi go edinstveniot red od rezultatot
        cur.close()                         # zatvori go kursorot
        if row:                             # ako postoi takov pacient
            return (row.get("email") or "").strip() or None # vrati go negoviot email iscisten od prazni mesta
    except Exception as e:                  # fati bilo kakva greska pri rabota so bazata
        print(f"[apliciraj] email od patient_ID: {e!r}") # ispecati ja greskata vo konzola za debagiranje
    finally:
        if conn:                            # ako konekcijata e ostanata otvorena
            conn.close()                    # zatvori ja konekcijata so bazata
    return None                             # vo slucaj na greska vrati null


def _emails_za_prebaruvanje(
    pacient: dict | None, kontekst: dict | None
) -> list[str]:
    """Сите можни email-и (најава, контекст, patient табела)."""
    seen: set[str] = set()                  # set za sledenje na unikatni email adresi
    out: list[str] = []                     # lista kade ke gi smestime unikatnite email-i

    def add(e: str | None) -> None:
        e = (e or "").strip()               # iscisti gi praznite mesta od stringot
        if not e or e.lower() in seen:      # ako e prazen ili veke postoi vo setot
            return                          # preskokni go i ne go dodavaj pak
        seen.add(e.lower())                 # dodadi go vo setot so mali bukvi
        out.append(e)                       # dodadi go vo finalnata lista za vrakanje

    add(_email_za_brisenje_aplikacija(pacient, kontekst)) # probaj da go dodades emailot od kontekstot ili sesijata
    if pacient:                             # ako korisnikot e najaven kako pacient
        pid = normalize_int(pacient.get("pacient_ID")) # normaliziraj go negovoto pacient id vo int
        if pid:                             # ako id-to e validno
            add(_email_iz_baza_po_pacient_id(pid)) # izvleci go emailot directly od bazata i dodadi go
    return out                              # vrati ja listata na email adresi za skeniranje


# trgni duplikati od lista aplikacii i sortiraj po datum
def _dedupe_aplikacii(rows: list[dict]) -> list[dict]:
    seen: set[int] = set()                  # set za sledenje na unikatni id-a na redovite
    out: list[dict] = []                    # lista na unikatni aplikacii
    for r in rows:                          # pomini niz sekoj red od bazata
        try:
            rid = prijaveni_row_id(r)        # izvleci go primarniot kluc na aplikacijata
        except ValueError:                  # ako pretvoranjeto propadne radi los format
            continue                        # preskokni go toj red
        if rid in seen:                     # ako ova id veke sme go obrabotile porano
            continue                        # preskokni go za da nema duplikati
        seen.add(rid)                       # registriraj go id-to vo setot na videni
        if r.get("id") is None:             # ako klucot id ne e postaven vo samiot recnik
            r = {**r, "id": rid}            # dodadi go id-to vnatre vo strukturata
        out.append(r)                       # dodadi ja aplikacijata vo finalnata lista
    out.sort(                               # sortiraj gi site unikatni aplikacii
        key=lambda x: (x.get("datum_prijava") or "", x.get("id") or 0), # po datum na prijava i po id kako vtor kriterium
        reverse=True,                       # od najnovite kon najstarite
    )
    return out                              # vrati ja filtriranata i sortirana lista


# lista aplikacii po primaren kluc (id)
def _lista_aplikacii_po_id(app_id: int) -> list[dict]:
    conn = None                             # podgotovka na konekcijata
    try:
        conn = get_connection()             # otvori nova vrska so bazata
        cur = conn.cursor(dictionary=True)  # kreiraj kursor so recnik opcija
        pk = prijaveni_pk_column()          # zemi ja kolona na primarniot kluc
        cur.execute(                        # izvrsi selekt query preku id
            prijaveni_select_sql() + f" WHERE {pk} = %s LIMIT 1",
            (app_id,),
        )
        row = fetch_one(cur)                # procitaj go edinstveniot red od bazata
        cur.close()                         # zatvori go kursorot vednas
        return [as_dict(row)] if row else [] # ako ima red vrati go kako recnik staven vo lista, inaku prazna lista
    except Exception as e:                  # fati eventualna greska pri izvrsuvanje na sql-ot
        print(f"[apliciraj] lista po id: {e!r}") # deponiraj greska vo logovi
        return []                           # vrati prazna lista pri defekt
    finally:
        if conn:                            # proverka na status na konekcija
            conn.close()                    # bezbedno zatvoranje na resursot


# striktno prebaruvanje po email string vo baza
def _lista_aplikacii_po_email_striktno(email: str) -> list[dict]:
    conn = None                             # pocetna vrednost za konekcija
    try:
        conn = get_connection()             # povrzi se so bazata
        cur = conn.cursor(dictionary=True)  # zemi kursor so konfiguracija za dict
        cur.execute(                        # izvrsi prebaruvanje so striktno spreduvanje na email vo baza
            prijaveni_select_sql()
            + " WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))"
            + prijaveni_order_desc(),
            (email.strip(),),
        )
        rows = [as_dict(r) for r in cur.fetchall()] # konvertiraj gi site najdeni redovi vo python recnici
        cur.close()                         # oslobodi go kursorot
        return rows                         # vrati gi najdenite rezultati
    except Exception as e:                  # menadzment so greski
        print(f"[apliciraj] lista po email: {e!r}") # pecatenje greska vo serverska konzola
        return []                           # vrati prazno bidejki prebaruvanjeto puknalo
    finally:
        if conn:                            # osiguraj se deka baza nema da ostane blokirana
            conn.close()                    # zatvori ja aktivnata sesija kon baza


# gmail alias i tocki — sporedba vo python
def _lista_aplikacii_po_email_fuzzy(email: str) -> list[dict]:
    """Gmail alias/точки — споредба на local+domain во Python."""
    kluc = _email_kluc_za_sporedba(email)   # zemi go unificiraniot kluc od vneseniot email
    if not kluc:                            # ako ne mozelo da se generira kluc
        return []                           # vrati prazna lista, nema sto da barame
    _local, domain = kluc                   # raspakuj gi lokalniot del i domenot
    conn = None                             # postavi ja bazata na default
    try:
        conn = get_connection()             # otvori konekcija za sql
        cur = conn.cursor(dictionary=True)  # zemi kursor so dict format
        cur.execute(                        # selektiraj gi site redovi sto go sodrzat istiot domen za polesno filtriranje
            prijaveni_select_sql()
            + " WHERE LOWER(email) LIKE %s"
            + prijaveni_order_desc(),
            (f"%@{domain}",),
        )
        rows = [                            # napravi dopolnitelno strukturno filtriranje vo python
            as_dict(r)                      # pretvori go sekoj red vo recnik
            for r in cur.fetchall()         # pomini niz site rezultati od bazata
            if _email_se_sovpaaga(r.get("email") or "", email) # proveri dali navistina se sovpagaat preku gmail pravilata
        ]
        cur.close()                         # zatvori go kursorot na bazata
        return rows                         # vrati gi filtriranite aplikacii
    except Exception as e:                  # handling na ekscesni situacii
        print(f"[apliciraj] lista fuzzy email: {e!r}") # zapisi greska vo konzola
        return []                           # vrati prazno bidejki operacijata e neuspesna
    finally:
        if conn:                            # ako konekcijata ne e zatvorena
            conn.close()                    # zatvori ja konekcijata do bazata


# prebaruvanje po ime i prezime na kandidatot
def _lista_aplikacii_po_ime_prezime(ime: str, prezime: str) -> list[dict]:
    conn = None                             # inicializiranje na objektot konekcija
    try:
        conn = get_connection()             # povrzi se so bazata
        cur = conn.cursor(dictionary=True)  # kursor konfiguriran da vraka dict
        cur.execute(                        # query za prebaruvanje na aplikacii spored ime i prezime
            prijaveni_select_sql()
            + """
            WHERE LOWER(TRIM(ime_lekar)) = LOWER(TRIM(%s))
              AND LOWER(TRIM(prezime_lekar)) = LOWER(TRIM(%s))
            """
            + prijaveni_order_desc(),
            (ime.strip(), prezime.strip()),   # parametri za cistenje na vnesovite
        )
        rows = [as_dict(r) for r in cur.fetchall()] # konvertiranje na sekoj red vo standarden python dict
        cur.close()                         # zatvoranje na kursorot
        return rows                         # vrakame se sto e pronajdeno vo tabelata
    except Exception as e:                  # logiranje pri greska vo baza
        print(f"[apliciraj] lista po ime: {e!r}") # pecatenje detalna greska
        return []                           # neuspesno izvrsuvanje, vrati prazno
    finally:
        if conn:                            # proverka pred zatvoranje
            conn.close()                    # zatvori go kanalot kon bazata


def _filtriraj_aplikacii_po_emails(
    rows: list[dict], emails: list[str]
) -> list[dict]:
    """Само пријави чија е-пошта се совпаѓа со најавената (вкл. Gmail нормализација)."""
    if not emails:                          # ako nema prateno nitu eden email za sporedba
        return rows                         # vrati ja celata lista bez filtriranje
    out: list[dict] = []                    # nova lista za filtrirani aplikacii
    for r in rows:                          # pomini niz sekoja aplikacija od listata
        app_em = (r.get("email") or "").strip() # zemi go emailot zacuvan vo aplikacijata
        if app_em and any(_email_se_sovpaaga(app_em, e) for e in emails): # ako emailot se sovpaga so bilo koj od baranite
            out.append(r)                   # dodadi ja aplikacijata vo filtriranata lista
    return out                              # vrati gi isfiltriranite redovi


# gi sobira site aplikacii na pacientot (po id, email, ime)
def _zemi_site_aplikacii_pacient(
    pacient: dict | None, kontekst: dict | None ) -> tuple[list[dict], str]:
    rows: list[dict] = []                   # inicijaliziranje na listata na redovi
    nacin = ""                              # string koj ke kaze kako se pronajdeni podatocite
    emails = _emails_za_prebaruvanje(pacient, kontekst) # zemi gi site dostapni email adresi od sesijata
    ima_email = bool(emails)                # flag dali voopsto imame email za prebaruvanje

    app_id = normalize_int((kontekst or {}).get("last_aplikacija_id")) # proveri dali ima id od posledna aplikacija vo kontekst
    if app_id:                              # ako postoi takvo id
        found = _lista_aplikacii_po_id(app_id) # probaj da ja najdes aplikacijata direktno po id
        if found and ima_email:             # ako e najdena i imame email za proverka
            found = _filtriraj_aplikacii_po_emails(found, emails) # potvrdi deka emailot na taa aplikacija se sovpaga so korisnikot
        if found:                           # ako i posle ova e validna
            rows.extend(found)              # dodadi ja vo rezultatite
            nacin = "id"                    # zapisi deka e najdena po id metod

    for email in emails:                    # vrti niz site email adresi na korisnikot
        strict = _lista_aplikacii_po_email_striktno(email) # baraj tochno sovpaganja po string
        if strict:                          # ako najdes nesto
            rows.extend(strict)             # dodadi gi vo glavnata lista
            if not nacin:                   # ako nacinot ne e veke postaven od prethodno
                nacin = "email"             # oznaci deka nacinot e preku strikten email
        fuzzy = _lista_aplikacii_po_email_fuzzy(email) # baraj i polesno spovpaganja (tocki, plus)
        if fuzzy:                           # ako ima takvi rezultati
            rows.extend(fuzzy)              # dodadi gi i niv vo kupot
            if not nacin:                   # ako se uste nema nacin
                nacin = "gmail"             # oznaci deka e pronajdeno preku gmail logika

    rows = _dedupe_aplikacii(rows)          # iscisti gi duplikatite bidejki metodite mozat da zacukaat isti redovi
    if rows:                                # ako listata ne e prazna
        return rows, nacin                  # vrati gi aplikaciite i metodot na naoganje

    # Po ime samo ako nema email (retko — gostin bez smetka)
    if not ima_email and pacient:           # ako nemame email no imame objekt za pacient
        ime = (pacient.get("ime") or "").strip() # zemi go imeto na pacientot
        prezime = (pacient.get("prezime") or "").strip() # zemi go prezimeto na pacientot
        if ime and prezime:                 # ako i dvete se prisutni
            by_name = _lista_aplikacii_po_ime_prezime(ime, prezime) # baraj aplikacija spored imeto na doktorot
            if by_name:                     # ako ima rezultat
                return by_name, "ime_prezime" # vrati gi aplikaciite i oznaci deka se po ime i prezime

    return [], ""                           # ako nisto ne bide najdeno vrati prazna lista i prazen nacin


# odgovor za prasanje „dali imam aplicirano"
def _odgovor_proverka_aplikacija(
    pacient: dict | None, kontekst: dict | None
) -> dict:
    email_prikaz = _email_za_brisenje_aplikacija(pacient, kontekst) # zemi email za vizuelen prikaz vo porakata
    if not email_prikaz and not (pacient and pacient.get("pacient_ID")): # anonimen korisnik — bara login
        return {                            # vrati odgovor so otvori_pacient_login
            "odgovor": (
                "За да проверам дали имате поднесена апликација за работа, "
                "најавете се како пациент со истата сметка со која сте аплицирале.\n\n"
                "Потоа повторете: „Дали имам аплицирано за работа\"."
            ),
            "akcija": "otvori_pacient_login", # frontend ja otvara formata
            "navigacija": NAV_KARIERA,      # del kariera
            "kontekst": None,               # reset kontekst
        }

    apps, nacin = _zemi_site_aplikacii_pacient(pacient, kontekst) # site aplikacii za ovoj korisnik
    if not apps:                            # nema pronajdeno
        ref = email_prikaz or "вашата сметка" # referenca vo porakata
        return {                            # informativen odgovor
            "odgovor": (
                "Не — немам пронајдена апликација за работа во системот "
                f"({ref}).\n\n"
                'Ако сте аплицирале преку формата во "Кариера", проверете дали '
                "сте внеле истата е-пошта како при најавата.\n\n"
                "Ако сакате повторно да аплицирате, наведете ја позицијата, на пример:\n"
                '"Сакам да аплицирам за Уролог".'
            ),
            "kontekst": None,
            "navigacija": NAV_KARIERA,
        }

    if len(apps) == 1:                      # edna aplikacija
        naslov = "Да — имате поднесена апликација за работа:\n"
    else:                                   # poveke aplikacii
        naslov = f"Да — имате {len(apps)} поднесени апликации за работа (на {email_prikaz or 'вашата сметка'}):\n"
    linii = [naslov]                        # pocni so naslov
    if nacin == "ime_prezime":               # pronajdeno po ime, ne po email
        linii.append(
            "(Пронајдено по име и презиме — најавете се со е-поштата од пријавата за поточен преглед.)\n"
        )
    for a in apps:                          # lista na sekoja aplikacija
        poz = (a.get("pozicija") or "—").strip() or "—"
        app_id = a.get("id")
        linii.append(
            f"• {poz} — пријавено на {format_datum_vreme(a.get('datum_prijava'))}"
            + (f" (ID: {app_id})" if app_id is not None else "")
        )
    linii.extend(                           # zavrsni linii
        [
            "",
            "Тимот за човечки ресурси ќе ве контактира за следните чекори.",
            "",
            'За откажување: „Избриши ја апликацијата".',
        ]
    )
    store_email = email_prikaz or (apps[0].get("email") or "").strip() # za kontekst po proverka
    return {                                # struktuiran odgovor
        "odgovor": "\n".join(linii),
        "kontekst": {
            "applicant_email": store_email,
            "last_aplikacija_id": apps[0].get("id"),
            "last_aplikacija_pozicija": (apps[0].get("pozicija") or "").strip(),
        },
        "navigacija": NAV_KARIERA,
    }


# „apliciram za rabota" bez konkretna pozicija
def _prasanje_e_opsto_za_rabota(prasanje: str) -> bool:
    """„Аплицирам за работа" без конкретна позиција/специјалност."""
    if prasanje_e_proverka_aplikacija_rabota(prasanje): # ako prasanjeto bara status ili proverka
        return False                        # toa ne e opsto prasanje za nova prijava
    if prasanje_e_izbrisi_aplikacija_rabota(prasanje): # ako e prasanje za brisenje
        return False                        # isto taka ne e opsto apliciranje
    p = transliterijaj(prasanje).lower()    # pretvori go tekstot vo kirilica so mali bukvi
    if not any(                             # proveri dali sodrzi zbor povrzan so vrabotuvanje
        w in p
        for w in (
            "аплиц", "aplic", "пријав", "prijav", "вработ", "vrabot", "работа", "rabota", "работам","rabotam",
        )
    ):
        return False                        # ako nema takvi zborovi
    spec_hints = ( "кардиол","хирург", "урол","анестез","гинекол", "педијат", "неврол","ортопед","радиол","интерн","офталм","инфект","психијат","оторин","пулмол","гастро","онкол",
        "сестр","неврохирург","пластич","патолош","медицинск",
    )
    return not any(h in p for h in spec_hints) # nema konkretna specijalnost vo tekstot

# gi zema aktivnite oglasi od baza za prikaz na korisnikot
def _aktivni_oglasi() -> list[dict]:
    conn = None                             # postavi bazna varijabla za vrskata
    try:
        conn = get_connection()             # zemi konekcija do bazata
        cur = conn.cursor(dictionary=True)  # kursor so recnici
        rows = fetch_aktivni_oglasi_rows(cur) # aktivni oglasi od tabelata
        cur.close()                         # zatvori kursor
        out: list[dict] = []                # lista za frontendo
        for raw in rows:                    # pomini niz sekoj red
            r = as_dict(raw)                # pretvori vo recnik
            out.append(
                {
                    "id_oglas": r.get("id_oglas"), # id na oglasot
                    "pozicija": (r.get("pozicija") or "").strip(), # ocistena pozicija
                    "oddel": (r.get("oddel") or "").strip(), # oddel
                    "rok": format_rok_datum(r.get("datum_na_prijavuvanje")), # rok za prijava
                }
            )
        return out                          # vrati ja listata
    except Exception as e:                  # greska pri citanje
        print(f"[apliciraj] lista oglasi: {e}")
        return []                           # prazna lista
    finally:
        if conn and conn.is_connected():    # zatvori konekcija
            conn.close()


# formatira pozicija i oddel za poraka do korisnikot
def _format_pozicija_oglas(oglas: dict) -> str:
    poz = (oglas.get("pozicija") or "").strip() or "—" # pozicija ili crta
    odd = (oglas.get("oddel") or "").strip() # oddel
    if odd and odd.lower() not in poz.lower(): # oddelot ne e veke vo pozicijata
        return f'„{poz}" ({odd})'           # pozicija (oddel)
    return f'„{poz}"'                       # samo pozicija


# dali korisnikot prasa za status na postoecka aplikacija
def prasanje_e_proverka_aplikacija_rabota(prasanje: str) -> bool:
    """„Дали имам аплицирано", „имам ли апликација" — статус, не нов flow."""
    p = transliterijaj(prasanje).lower()    # unificiraj go pismoto
    if prasanje_e_izbrisi_aplikacija_rabota(prasanje): # brisenje ima prednost
        return False                        # ne e proverka na status
    if any(                                 # eksplicitno saka da aplicira sega
        w in p
        for w in (
            "сакам да аплицирам",
            "sakam da apliciram",
            "аплицирај ме",
            "apliciraj me",
            "како да аплицирам",
            "kako da apliciram",
        )
    ):
        return False                        # nov protok, ne proverka

    if any(                                 # klasicni frazi za status
        x in p
        for x in (
            "дали имам",
            "dali imam",
            "дали сум аплицирал",
            "dali sum apliciral",
            "имам ли апликаци",
            "imam li aplikaci",
            "моја апликаци",
            "moja aplikaci",
            "статус на апликаци",
            "status na aplikaci",
            "поднесов ли",
            "podnesov li",
            "провери ја апликаци",
            "proveri ja aplikaci",
            "дали постои апликаци",
            "која апликација имам",
            "koja aplikacija imam",
        )
    ):
        return True                         # prepoznato kako proverka

    if ("дали" in p or "dali" in p) and any( # kombinacija dali + aplikacija
        w in p for w in ("аплицир", "aplicir", "апликаци", "aplikaci", "пријав", "prijav")
    ):
        return True
    return False                            # ne e proverka


# dali korisnikot saka da ja izbrise/otkaze aplikacijata
def prasanje_e_izbrisi_aplikacija_rabota(prasanje: str) -> bool:
    """„Избриши/избришам ја апликацијата", „откажи пријава" — не нов apply flow."""
    p = transliterijaj(prasanje).lower()    # normaliziraj tekst
    if not any(                             # mora da ima vrska so aplikacija
        w in p
        for w in (
            "апликаци",
            "aplikaci",
            "аплиц",
            "aplic",
            "пријав",
            "prijav",
        )
    ):
        return False                        # ne e brisenje
    if re.search(                           # komanda za brisenje/otkazuvanje
        r"(избриш\w*|izbris\w*|откаж\w*|otkaz\w*|тргни|отстрани|повлеч\w*|delete|cancel)",
        p,
    ):
        return True
    if ("сакам" in p or "sakam" in p) and re.search( # sakam da izbrisam
        r"(избриш|izbris|откаж|otkaz|тргни|отстрани)", p
    ):
        return True
    return False


# go prekinuva aktivniot flow na apliciranje
def _otkazi_aplikacija_flow(kontekst: dict | None) -> dict:
    return {                                # prekinuvanje na flow
        "odgovor": (
            "Го прекинав процесот на аплицирање.\n\n"
            "Ако сакате повторно да аплицирате, наведете ја позицијата "
            '(на пр. „Сакам да аплицирам за медицинска сестра").'
        ),
        "kontekst": None,                   # iscisti kontekst
        "navigacija": NAV_KARIERA,
    }


# hint za pozicija od tekst pri brisenje
def _pozicija_hint_od_brisenje(prasanje: str) -> str | None:
    """„… за медицинска сестра" / „апликацијата за …" → hint за пребарување."""
    p = transliterijaj(prasanje).lower()    # pretvori vo kirilica mali bukvi
    m = re.search(                          # baraj „aplikacija za ..."
        r"апликаци\w*\s+за\s+(.+?)\s*$",
        p,
        flags=re.UNICODE | re.IGNORECASE,
    )
    if not m:                               # ako ne uspea
        m = re.search(                      # poednostaven „za ..." na kraj
            r"\bза\s+(.+?)\s*$",
            p,
            flags=re.UNICODE | re.IGNORECASE,
        )
    if m:                                   # ako ima poklopuvanje
        hint = m.group(1).strip()           # zemi go tekstot
        for stop in (                       # iscisti nepotrebni zborovi
            "апликаци",
            "aplikaci",
            "мојата",
            "мојот",
            "моето",
        ):
            if stop in hint:
                hint = hint.split(stop)[0].strip()
        if len(hint) >= 4:                  # dovolno dolg hint
            return hint
    if "медицинск" in p and "сестр" in p:   # najcest slucaj
        return "медицинск"
    return None                             # nema hint


# id na red vo prijaveni_lekari
def _app_row_id(row: dict) -> int:
    return prijaveni_row_id(row)            # id od redot


# email od najava ili kontekst za brisenje
def _email_za_brisenje_aplikacija(
    pacient: dict | None, kontekst: dict | None
) -> str | None:
    """Email од најава или од контекст по успешна апликација."""
    if pacient and (pacient.get("email") or "").strip(): # email od sesijata
        return str(pacient["email"]).strip()
    if isinstance(kontekst, dict):          # probaj od kontekst
        for key in ("applicant_email", "email", "pacient_email"):
            e = (kontekst.get(key) or "").strip()
            if e:                           # najden email
                return e
    return None                             # nema email


# izvleci broj na aplikacija od tekstot
def _izvlechi_app_id_od_prasanje(prasanje: str) -> int | None:
    p = transliterijaj(prasanje).lower()    # normaliziraj
    m = re.search(r"апликаци[јj][аи]?\s*(?:id)?\s*#?:?\s*(\d+)", p)
    if m:                                   # najden broj
        return int(m.group(1))
    m = re.search(r"\bid\s*(\d+)\b", p)     # izoliran id 123
    if m:
        return int(m.group(1))
    return None                             # nema broj


# dali najaveniot lekar e direktor/admin
def _direktor_e_admin(lekar: dict | None) -> bool:
    if not lekar or not lekar.get("doctor_ID"): # nema lekar id
        return False
    try:
        from routers.admin import check_admin_access # admin proverka

        return bool(check_admin_access(int(lekar["doctor_ID"]))) # ima admin prava
    except Exception:
        return False                        # greska — ne e admin


# najdi eden red od prijaveni_lekari za brisenje
def _najdi_aplikacija_za_brisenje(
    cur: object,
    *,
    email: str | None = None,
    app_id: int | None = None,
    id_oglas: int | None = None,
    pozicija_hint: str | None = None,
    posledna_bilo_koja: bool = False,
) -> dict | None:
    """Еден ред од prijaveni_lekari за бришење."""
    pk = prijaveni_pk_column()          # primarna kolona
    sel = prijaveni_select_sql()            # bazen SELECT
    ord1 = prijaveni_order_desc() + " LIMIT 1" # najnova edna

    if app_id is not None:                  # direktno po id
        cur.execute(sel + f" WHERE {pk} = %s LIMIT 1", (app_id,))
        return fetch_one(cur)

    if posledna_bilo_koja:                  # admin — posledna vo sistemot
        cur.execute(sel + ord1)
        return fetch_one(cur)

    if not email:                           # nema email za prebaruvanje
        return None

    email_n = email.strip().lower()         # normaliziran email
    base = sel + " WHERE LOWER(TRIM(email)) = %s"
    params: list = [email_n]

    if id_oglas is not None:                # email + id na oglas
        cur.execute(
            base + " AND id_oglas = %s" + ord1,
            tuple(params + [id_oglas]),
        )
        row = fetch_one(cur)
        if row:
            return row

    if pozicija_hint:                       # email + LIKE pozicija
        hint = pozicija_hint.strip().lower()
        cur.execute(
            base + " AND LOWER(TRIM(pozicija)) LIKE %s" + ord1,
            tuple(params + [f"%{hint}%"]),
        )
        row = fetch_one(cur)
        if row:
            return row

    cur.execute(base + ord1, tuple(params)) # najnova na toj email
    row = fetch_one(cur)
    if row:
        return row

    kluc = _email_kluc_za_sporedba(email)   # gmail normalizacija
    if kluc:
        _local, domain = kluc
        cur.execute(
            sel + " WHERE LOWER(email) LIKE %s" + prijaveni_order_desc() + " LIMIT 30",
            (f"%@{domain}",),
        )
        for raw in cur.fetchall():          # filtriraj vo python
            cand = as_dict(raw)
            if not _email_se_sovpaaga(cand.get("email") or "", email):
                continue
            if id_oglas is not None and cand.get("id_oglas") != id_oglas:
                continue
            if pozicija_hint:
                hint = pozicija_hint.strip().lower()
                if hint not in (cand.get("pozicija") or "").lower():
                    continue
            return cand
    return None


# izberi edna aplikacija od lista spored tragite
def _izberi_aplikacija_za_brisenje(
    apps: list[dict],
    *,
    id_oglas: int | None = None,
    pozicija_hint: str | None = None,
    app_id: int | None = None,
) -> dict | None:
    if not apps:                            # prazna lista
        return None
    if app_id is not None:                  # po tocno id
        for a in apps:
            if int(a.get("id") or 0) == int(app_id):
                return a
    if id_oglas is not None:                # po id na oglas
        for a in apps:
            if a.get("id_oglas") == id_oglas:
                return a
    if pozicija_hint:                       # po tekst na pozicija
        hint = pozicija_hint.strip().lower()
        for a in apps:
            if hint in (a.get("pozicija") or "").lower():
                return a
    return apps[0]                          # najnovata (prva vo lista)


# brisi aplikacija od prijaveni_lekari vo baza
def _izbrisi_aplikacija_od_baza(
    *,
    email: str | None = None,
    id_oglas: int | None = None,
    pozicija_hint: str | None = None,
    app_id: int | None = None,
    posledna_bilo_koja: bool = False,
    pacient: dict | None = None,
    kontekst: dict | None = None,
) -> tuple[bool, str]:
    """Брише апликација од prijaveni_lekari (ист пат како INSERT)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        row = _najdi_aplikacija_za_brisenje(
            cur,
            email=email,
            app_id=app_id,
            id_oglas=id_oglas,
            pozicija_hint=pozicija_hint,
            posledna_bilo_koja=posledna_bilo_koja,
        )
        if not row and not posledna_bilo_koja and app_id is None:
            apps, _ = _zemi_site_aplikacii_pacient(pacient, kontekst)
            picked = _izberi_aplikacija_za_brisenje(
                apps,
                id_oglas=id_oglas,
                pozicija_hint=pozicija_hint,
                app_id=normalize_int((kontekst or {}).get("last_aplikacija_id")),
            )
            if picked:
                row = picked
        if not row:
            cur.close()
            if email:
                return False, (
                    "Немам пронајдена поднесена апликација за работа на вашето име "
                    f"({email}).\n\n"
                    "Најавете се како пациент со истата сметка со која ја "
                    "поднесовте апликацијата, па повторете „Избриши ја апликацијата\"."
                )
            return False, "Немам пронајдена апликација за бришење."

        app_id_del = _app_row_id(as_dict(row))
        poz = (row.get("pozicija") or "").strip()
        pk = prijaveni_pk_column()
        cur.execute(f"DELETE FROM prijaveni_lekari WHERE {pk} = %s", (app_id_del,))
        conn.commit()
        cur.close()
        return True, (
            "Апликацијата е избришана.\n\n"
            f"Позиција: {poz or '—'}\n"
            f"ID: {app_id_del}\n\n"
            'Можете повторно да аплицирате преку "Кариера" ако сакате.'
        )
    except Exception as e:
        print(f"[apliciraj] DELETE aplikacija: {e!r}")
        return False, (
            "Се случи грешка при бришењето на апликацијата. Обидете се повторно."
        )
    finally:
        if conn:
            conn.close()


# odgovor za baranje za brisenje na aplikacija
def _odgovor_izbrisi_aplikacija(
    pacient: dict | None,
    kontekst: dict | None,
    prasanje: str = "",
    lekar: dict | None = None,
) -> dict:
    app_id = _izvlechi_app_id_od_prasanje(prasanje)
    email = _email_za_brisenje_aplikacija(pacient, kontekst)
    id_oglas = normalize_int((kontekst or {}).get("id_oglas"))
    poz_hint = _pozicija_hint_od_brisenje(prasanje)

    if app_id and _direktor_e_admin(lekar):
        ok, poraka = _izbrisi_aplikacija_od_baza(app_id=app_id)
    elif email or pacient:
        ok, poraka = _izbrisi_aplikacija_od_baza(
            email=email,
            id_oglas=id_oglas,
            pozicija_hint=poz_hint,
            app_id=normalize_int((kontekst or {}).get("last_aplikacija_id")),
            pacient=pacient,
            kontekst=kontekst,
        )
    elif _direktor_e_admin(lekar):
        ok, poraka = _izbrisi_aplikacija_od_baza(posledna_bilo_koja=True)
    else:
        return {
            "odgovor": (
                "За бришење на апликација треба да сте најавени како пациент "
                "(истата сметка со која ја поднесовте апликацијата).\n\n"
                "Гостинскиот режим и најавата како лекар не можат да ја избришат "
                "вашата пријава — само вие или директорот (преку админ) може.\n\n"
                "Најавете се како пациент и пишете: „Избриши ја апликацијата\"."
            ),
            "kontekst": None,
            "navigacija": NAV_KARIERA,
        }

    return {
        "odgovor": poraka,
        "kontekst": None,
        "navigacija": NAV_KARIERA,
    }


# prepoznaj da/ne od kratok odgovor na korisnikot
def _parse_da_ne(prasanje: str) -> str | None:
    """Враќа 'da', 'ne' или None."""
    p = transliterijaj(prasanje).lower().strip()
    p = re.sub(r"[^\w\sа-яѓќѕџ]+", " ", p, flags=re.IGNORECASE)
    p = re.sub(r"\s+", " ", p).strip()

    ne_frazi = (
        "не сакам",
        "ne sakam",
        "не би",
        "не сак",
        "откажи",
        "odkazi",
        "нема интерес",
        "не ме интересира",
    )
    if p in ("не", "ne", "no") or any(x in p for x in ne_frazi):
        return "ne"
    if p in (
        "да",
        "da",
        "yes",
        "ja",
        "јас",
        "сакам",
        "аплицирај",
        "аплицирам",
        "во ред",
        "ok",
        "okej",
        "okay",
        "се разбира",
    ) or re.search(r"\bда\b", p):
        if "не" not in p and "ne " not in p:
            return "da"

    return None


# chekor potvrda — prasanje da/ne pred licenca
def _pocni_potvrda_flow(oglas: dict) -> dict:
    """Праша дали сака да аплицира — пред лиценца."""
    pozicija_naslov = oglas["pozicija"]
    id_o = oglas["id_oglas"]
    prikaz = _format_pozicija_oglas(oglas)
    rok = oglas.get("rok")
    rok_linija = f"\nРок за пријава: {rok}." if rok else ""

    return {
        "odgovor": (
            f"Во моментов има отворена позиција за {prikaz}.{rok_linija}\n\n"
            "Дали сакате да аплицирате?\n"
            'Одговорете со „да" или „не".'
        ),
        "kontekst": {
            "intent": "apliciraj_za_rabota",
            "ceka": "potvrda",
            "pozicija": pozicija_naslov,
            "id_oglas": id_o,
            "oddel": oglas.get("oddel") or "",
            "rok": rok or "",
        },
        "navigacija": NAV_KARIERA,
    }


# pretvori go zacuvaniot kontekst vo oglas recnik
def _oglas_od_kontekst(kontekst: dict) -> dict:
    return {
        "id_oglas": kontekst.get("id_oglas"),
        "pozicija": kontekst.get("pozicija") or "",
        "oddel": kontekst.get("oddel") or "",
        "rok": kontekst.get("rok") or "",
    }


# chekor licenca — bara broj ili preskok
def _pocni_licenca_flow(oglas: dict, pacient: dict) -> dict:
    pozicija_naslov = oglas["pozicija"]
    id_o = oglas["id_oglas"]
    return {
        "odgovor": (
            f"Одлично! Продолжуваме со апликацијата за {_format_pozicija_oglas(oglas)}.\n\n"
            f"Ќе ги користам вашите податоци: "
            f'{pacient.get("ime", "")} {pacient.get("prezime", "")}, '
            f'{pacient.get("email", "")}.\n\n'
            "Те молам испратете го бројот на вашата медицинска лиценца "
            '(само цифри), или напишете „немам" ако не сакате да го '
            "споделите сега."
        ),
        "kontekst": {
            "intent": "apliciraj_za_rabota",
            "ceka": "licenca",
            "pozicija": pozicija_naslov,
            "id_oglas": id_o,
            "applicant_email": (pacient.get("email") or "").strip(),
        },
        "navigacija": NAV_KARIERA,
    }


# korisnikot rekol ne na potvrda
def _odgovor_odbien_aplikacija() -> dict:
    return {
        "odgovor": (
            "Ви благодариме.\n\n"
            'Следете ги огласите во делот "Кариера" на сајтот.\n\n'
            "Доколку подоцна сте заинтересирани, тука сме да го обработиме "
            "вашето барање за работа — слободно пишете повторно кога ќе сакате."
        ),
        "kontekst": None,
        "navigacija": NAV_KARIERA,
    }


# nema jasna pozicija — prikazi lista oglasi
def _odgovor_izberi_pozicija(pacient: dict) -> dict:
    """Нема именувана позиција — кратка листа + навигација кон Кариера."""
    oglasi = _aktivni_oglasi()
    if not oglasi:
        return {
            "odgovor": (
                "Моментално нема отворени работни позиции за пријавување.\n\n"
                'Страницата ќе се отвори на делот "Кариера" — проверете повторно подоцна '
                "или контактирајте ја централата."
            ),
            "kontekst": None,
            "navigacija": NAV_KARIERA,
        }

    if len(oglasi) == 1:
        return _pocni_potvrda_flow(oglasi[0])

    linii = [
        "Сакате да аплицирате за работа. Моментално има следниве отворени позиции:",
        "",
    ]
    for o in oglasi:
        linii.append(
            f"• {o['pozicija']} — оддел: {o.get('oddel') or '—'}. "
            f"Рок за пријава: {o.get('rok') or '—'}."
        )
    linii.extend(
        [
            "",
            "Напишете која позиција ве интересира, на пример:",
            '„Сакам да аплицирам за Уролог" или „Аплицирај ме за кардиолог".',
            "Ќе ве водам чекор по чекор (лиценца и потврда).",
            "",
            'Исто така можете да се пријавите преку формата во делот "Кариера" на страницата.',
        ]
    )
    return {
        "odgovor": "\n".join(linii),
        "kontekst": None,
        "navigacija": NAV_KARIERA,
    }


# izvleci pozicija preku groq i parse_ai_json
def _izvlechi_pozicija(prasanje: str) -> str | None:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT_POZICIJA)
    print(f"[apliciraj] pozicija AI: {odgovor!r}")
    data = parse_ai_json(odgovor, log_tag="apliciraj_pozicija")
    if data.get("_error"):
        return None
    val = data.get("pozicija")
    return str(val).strip() if val else None


# izvleci broj na licenca ili preskok preku groq
def _izvlechi_licenca(prasanje: str) -> tuple[str | None, bool]:
    """Враќа (licenca, preskoki) — само преку Groq."""
    from ai._kernel.groq_client import groq_e_isklucen, GROQ_OFFLINE_MSG

    if groq_e_isklucen():
        print(f"[apliciraj] licenca blocked: {GROQ_OFFLINE_MSG}")
        return None, False

    odgovor = ask_ai(f"Одговор: „{prasanje}\"", system_prompt=PROMPT_LICENCA)
    print(f"[apliciraj] licenca AI: {odgovor!r}")
    data = parse_ai_json(odgovor, log_tag="apliciraj_licenca")
    if data.get("_error"):
        return None, False
    licenca = data.get("licenca")
    preskoki = bool(data.get("preskoki"))
    if licenca:
        licenca = re.sub(r"\D", "", str(licenca))
        if not licenca:
            licenca = None
    return licenca, preskoki


# najdi aktivен oglas vo baza spored baranata pozicija
def _najdi_aktiven_oglas(pozicija_baranо: str) -> dict | None:
    """
    Пробува да најде активен оглас чија позиција содржи / е содржана во баранatа.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        site = fetch_aktivni_oglasi_rows(cur)
        cur.close()
    except Exception as e:
        print(f"[apliciraj] DB greska: {e}")
        return None
    finally:
        if conn:
            conn.close()

    if not site:
        return None

    b = pozicija_baranо.lower().strip()

    # 1) Точна еднаквост (case-insensitive)
    for o in site:
        if (o.get("pozicija") or "").strip().lower() == b:
            return o
    # 2) Substring
    for o in site:
        p = (o.get("pozicija") or "").strip().lower()
        if b and (b in p or p in b):
            return o
    return None


# insert na nova prijava vo prijaveni_lekari
def _zapisi_aplikacija(
    id_oglas: int | None,
    pozicija: str,
    ime: str,
    prezime: str,
    email: str,
    telefon: str | None,
    licenca: str | None,
) -> tuple[bool, str]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        denes = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tel_int = None
        if telefon:
            t = re.sub(r"\D", "", str(telefon))
            tel_int = int(t) if t else None
        lic_int = None
        if licenca:
            l = re.sub(r"\D", "", str(licenca))
            lic_int = int(l) if l else None
        email_norm = (email or "").strip().lower()
        cur.execute("""
            INSERT INTO prijaveni_lekari
              (id_oglas, pozicija, ime_lekar, prezime_lekar,
               broj_med_licenca, email, telefon, datum_prijava)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_oglas, pozicija, ime, prezime, lic_int, email_norm, tel_int, denes))
        conn.commit()
        cur.close()
        return True, ""
    except Exception as e:
        print(f"[apliciraj] INSERT greska: {e}")
        return False, str(e)
    finally:
        if conn:
            conn.close()


# glaven handler — intent apliciraj_za_rabota (login → pozicija → potvrda → licenca → INSERT)
def odgovori_za_aplikacija(
    prasanje: str,
    pacient: dict | None,
    kontekst: dict | None,
    lekar: dict | None = None,
) -> dict:
    """
    Враќа: { "odgovor": str, "kontekst": dict|None }

    Логика:
    - Ако нема пациент логиран → бара логин.
    - Ако нема активен kontekst → почни нов flow: извлечи позиција, потврди, прашај за лиценца.
    - Ако има активен kontekst со ceka='licenca' → прими лиценца и испрати апликација.
    - Ако има активен kontekst со ceka='potvrduvanje' → потврди и испрати.
    """

    ceka = (kontekst or {}).get("ceka")     # koj chekor go cekame (login, potvrda, licenca)

    if prasanje_e_izbrisi_aplikacija_rabota(prasanje):
        if _email_za_brisenje_aplikacija(pacient, kontekst) or _direktor_e_admin(lekar):
            return _odgovor_izbrisi_aplikacija(pacient, kontekst, prasanje, lekar)
        return _otkazi_aplikacija_flow(kontekst)

    if prasanje_e_proverka_aplikacija_rabota(prasanje):
        return _odgovor_proverka_aplikacija(pacient, kontekst)

    # По најава: продолжи од зачуваниот оглас
    if ceka == "login" and pacient and pacient.get("email"):
        oglas = _oglas_od_kontekst(kontekst or {})
        if oglas.get("id_oglas") and oglas.get("pozicija"):
            return _pocni_potvrda_flow(
                {
                    "id_oglas": oglas["id_oglas"],
                    "pozicija": oglas["pozicija"],
                    "oddel": oglas.get("oddel") or "",
                    "rok": oglas.get("rok") or "",
                }
            )

    if not pacient or not pacient.get("email"):
        if not ceka and (_tekst_e_zalepen_oglas(prasanje) or "аплиц" in transliterijaj(prasanje).lower()):
            baran = _baraj_pozicija_za_aplikacija(prasanje)
            if baran:
                oglas = _najdi_aktiven_oglas(baran)
                if oglas:
                    prikaz = _format_pozicija_oglas(oglas)
                    return _odgovor_bara_pacient_login(
                        {
                            "intent": "apliciraj_za_rabota",
                            "ceka": "login",
                            "pozicija": oglas["pozicija"],
                            "id_oglas": oglas["id_oglas"],
                            "oddel": oglas.get("oddel") or "",
                            "rok": oglas.get("rok") or "",
                        },
                        prikaz,
                    )
                return _odgovor_bara_pacient_login(
                    None,
                    f'„{baran}" (во моментов нема точен активен оглас во системот — провери Кариера)',
                )
        return _odgovor_bara_pacient_login(
            None,
            "аплицирање за работа",
        )

    pozicija = (kontekst or {}).get("pozicija")
    id_oglas = (kontekst or {}).get("id_oglas")

    # === Чекор 1: нов flow — извлечи позиција ===
    if not ceka:
        if _prasanje_e_opsto_za_rabota(prasanje):
            return _odgovor_izberi_pozicija(pacient)

        if prasanje_e_izbrisi_aplikacija_rabota(prasanje):
            if _email_za_brisenje_aplikacija(pacient, kontekst) or _direktor_e_admin(lekar):
                return _odgovor_izbrisi_aplikacija(pacient, kontekst, prasanje, lekar)
            return _otkazi_aplikacija_flow(kontekst)

        baran = _baraj_pozicija_za_aplikacija(prasanje)
        if not baran:
            return _odgovor_izberi_pozicija(pacient)

        oglas = _najdi_aktiven_oglas(baran)
        if not oglas:
            return {
                "odgovor": (
                    f'Во моментот нема активен оглас за „{baran}". '
                    "Подолу се сите отворени позиции — изберете друга или проверете "
                    'на делот „Кариера".'
                ),
                "kontekst": None,
                "navigacija": NAV_KARIERA,
            }

        return _pocni_potvrda_flow(oglas)

    # === Чекор 2: потврда (да / не) ===
    if ceka == "potvrda":
        odluka = _parse_da_ne(prasanje)
        if odluka is None:
            prikaz = _format_pozicija_oglas(_oglas_od_kontekst(kontekst or {}))
            return {
                "odgovor": (
                    f"Не разбрав. За позицијата {prikaz} — "
                    'одговорете со „да" ако сакате да аплицирате, или „не" ако не.'
                ),
                "kontekst": kontekst,
            }
        if odluka == "ne":
            return _odgovor_odbien_aplikacija()
        return _pocni_licenca_flow(_oglas_od_kontekst(kontekst or {}), pacient)

    # === Чекор 3: лиценца ===
    if ceka == "licenca":
        if prasanje_e_izbrisi_aplikacija_rabota(prasanje):
            return _odgovor_izbrisi_aplikacija(pacient, kontekst, prasanje, lekar)

        licenca, preskoki = _izvlechi_licenca(prasanje)
        if licenca is None and not preskoki:
            return {
                "odgovor": (
                    'Не препознав важечки број на лиценца. Те молам '
                    'прати само цифри (пр. „12345") или напиши „немам" '
                    'за да продолжиме без лиценца.'
                ),
                "kontekst": kontekst,
            }

        ok, err = _zapisi_aplikacija(
            id_oglas=id_oglas,
            pozicija=pozicija or "",
            ime=pacient.get("ime", "") or "",
            prezime=pacient.get("prezime", "") or "",
            email=pacient.get("email", "") or "",
            telefon=pacient.get("telefon"),
            licenca=licenca,
        )
        if not ok:
            return {
                "odgovor": (
                    'Се случи грешка при зачувувањето на апликацијата. '
                    'Те молам обиди се повторно или контактирај ја рецепцијата.'
                ),
                "kontekst": None,
            }

        lic_info = f"Лиценца: {licenca}" if licenca else "Лиценца: (без)"
        app_email = (pacient.get("email") or "").strip()
        last_id = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            pk = prijaveni_pk_column()
            cur.execute(
                f"""
                SELECT {pk} AS id FROM prijaveni_lekari
                WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))
                {prijaveni_order_desc()} LIMIT 1
                """,
                (app_email,),
            )
            r = cur.fetchone()
            cur.close()
            conn.close()
            if r:
                last_id = int(r[0] if not isinstance(r, dict) else r.get("id") or r[0])
        except Exception as e:
            print(f"[apliciraj] last id po insert: {e!r}")

        return {
            "odgovor": (
                'Готово! Апликацијата е успешно испратена.\n\n'
                f'Позиција: {pozicija}\n'
                f'Кандидат: {pacient.get("ime","")} {pacient.get("prezime","")}\n'
                f'Email: {app_email}\n'
                f'{lic_info}\n\n'
                'Тимот за човечки ресурси ќе те контактира за следните чекори. Среќно!\n\n'
                'За откажување: „Избриши ја апликацијата" (најавени како пациент).'
            ),
            "kontekst": {
                "applicant_email": app_email,
                "last_aplikacija_id": last_id,
                "last_aplikacija_pozicija": pozicija,
            },
        }

    return {                                # neпознат ceka — reset na flow
        "odgovor": 'Те молам обиди се повторно: „Сакам да аплицирам за [позиција]".',
        "kontekst": None,                   # iscisti go kontekstot
    }
