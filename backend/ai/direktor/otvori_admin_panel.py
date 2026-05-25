from ai._kernel.auth import require_direktor, require_lekar
from ai._kernel.transliteracija import transliterijaj
# funkcija koja proveruva dali direktorot saka pregled vo samiot admin panel ili ne
def _baranje_e_prikazi_dezurstvo_vo_admin(prasanje: str) -> bool:
    """„Прикажи го во админ" по преглед на дежурство."""
    p = transliterijaj(prasanje).lower()    # pasanjeto se pretvara vo mali bukvi i na latinica za polesna obrabotka od strana an groq
    ima_admin = any(    # se baraat slucni zborovi povrzan so administratiskiot del od sistemot
        x in p  # se proveruva sekoj zbor od podole navedenite
        for x in (
            "админ","административ","admin","панел",)
    )
    if not ima_admin:   # ako nema nikoj od zborovite vo prasanjeto
        return False    # se vraka false
    return any( # no dokolku ima se proveruva dali treba da se prikaze dezurstvo na konkreten lekar
        x in p  # toa go praveme so proverka na nekoj od zborovite podole
        for x in (
            "го "," го","неа","тоа","ова","дежур","dezur","прикажи","prikazi","види",
        )
    )# ako ima vraka true deka e duzeure 
# funkcija za odreuvanje na poceten pod tab 
def _odredi_subtab(prasanje: str) -> str:
    p = transliterijaj(prasanje).lower()    # se standardizira testot so latinicna podrska i malku bukvi
    if any(x in p for x in ("оглас", "огласи", "kariera", "oglas", "вработување")): #ako vo vnesot se sretne nesto od ovie se 
        return "oglasi-admin"   # se otvara konktetnio tab i nadolu za site taka
    if any(x in p for x in ("новост", "новости", "вест", "vesti")):
        return "novosti-admin"
    if "статистик" in p and any(x in p for x in ("оцен", "ocena", "рејтинг")):
        return "statistika-prosek-ocena-admin"
    if "статистик" in p or "оптовар" in p:
        return "statistika-optovaruvanje-admin"
    if any(x in p for x in ("дежур", "dezur")):
        return "dezurstva-admin"
    return "dezurstva-admin"
# gi obrabotuva baranja za ootvaranje na administrativnot panel
def odgovori_za_otvori_admin(
    prasanje: str,  
    lekar: dict | None,
    kontekst: dict | None = None,
) -> dict:
    if err := require_lekar(lekar): # proveka dali korisnikot e lekar, samo lekarite imam admin panel
        return {    # dokolku ne sme najaveni kako lekari
            "odgovor": (
                "За административниот панел треба да сте најавени како лекар (директор).\n"
                "Најавете се преку «Најава за лекар» на сајтот."
            ),
            "akcija": "otvori_lekar_login", # akcija frontend avtomatski da go otvore login panelot za lekari
        }

    if err := require_direktor(lekar):  # provekra dali lekarot ja ima ulogata na direktor
        return {    # ako ja nema ne mu se dava
            "odgovor": (
                f"{err}\n\n"
                "Административниот панел е достапен само за директорот на болницата."
            ),
        }
    subtab = _odredi_subtab(prasanje)   # se povikuva detekcija za tocniot pod tab vrz osnova na postavenoto prasanje
    labels = {  # mapiranje na tabovite spored naslovite za korisnikot
        "dezurstva-admin": "Управување со дежурства",
        "oglasi-admin": "Управување со огласи",
        "novosti-admin": "Новости",
        "statistika-optovaruvanje-admin": "Статистика – оптовареност",
        "statistika-prosek-ocena-admin": "Просечна оцена – лекари",
    }
    label = labels.get(subtab, "Администрација") # se zema soodvetniot naslov
    navigacija: dict = {    # podgotovk na osnovnata navikacija za fronend delot
        "target": "lekar:admin",    # glavna destinacija vo administracija
        "subtab": subtab,   # konkreten pod ekran koj treba da se vcita
        "label": label, # naslovot na ekranot
    }
    odgovor_extra = "" # inicijalizacija a prazen string za dopolnitelni infromacii vo odgovort

    dk = (kontekst or {}).get("dezurstvo_kontekst") if kontekst else None   # izvlekuvanje na kontekstot za dezurstvo ako postoi
    if dk and subtab == "dezurstva-admin" and _baranje_e_prikazi_dezurstvo_vo_admin(prasanje):  # ako imame prethodno deurstvo vo kontekstot i se bara prikaz na admin panelot
        if dk.get("doctor_id"): # dokolku e zakucano id na lekarot vo kontekstot
            navigacija["doctor_id"] = dk["doctor_id"] # se nasocuva vo navigacija za filtriranje
        if dk.get("datum"):  #dokolku imam venseno datum
            navigacija["datum"] = dk["datum"]     # se prenasocuva da se selektira vo kalendar
        if dk.get("dezurstvo_id"):  # dokolku posto id za dezurstvo
            navigacija["dezurstvo_id"] = dk["dezurstvo_id"] # se prenasocuva na panelot za dezurstvo
        ime = f"{dk.get('name', '')} {dk.get('surname', '')}".strip()   # se spojuva imeto i prezimeto na lekarot
        if ime: # ako imeto e uspesno izvlezeno i ne e prazno
            navigacija["doctor_name"] = ime # se dodava imeto na lekarot vo navigaciskiot objekt
        if dk.get("datum"): # ako ima datum se generira dipolnitelno pole za odgovor vo catot
            odgovor_extra = (       
                f"\nГо филтрирам според разговорот: {ime or 'лекарот'}, "
                f"датум {dk['datum']}."
            )

    return { # vrakanje na finalen spakuvan odgovor koj ima tekst, navigacija i sistemska akcija
        "odgovor": (        # tekst za korinsikot
            f"Го отворам административниот панел — «{label}».{odgovor_extra}"
        ),  
        "navigacija": navigacija, # navigaciski parametri so filtri za ui
        "akcija": "otvori_admin_panel", # sistemska naredba za frontend za otvaranje na panelot
        "kontekst": kontekst,  # se dava kontekst za da se zacuvuva sostojbata na razgovor
    }
