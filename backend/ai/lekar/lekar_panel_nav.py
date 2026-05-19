""" Отворање на постоечки табови во лекарскиот dashboard (frontend).
Користи navigacija.target = „lekar:pacienti" и слично; script.js → kbsOtvoriLekarPanel.
"""
from ai._kernel.auth import require_lekar
from ai._kernel.transliteracija import transliterijaj
# recnik za sekoji od dostapnite tabobi vo sistemot
TAB_LABELS = {
    "pacienti": "Преглед на пациенти", "dezurstva": "Распоред на дежурства", "aparati": "Закажи термин на апарат", "postavki": "Поставки", }
# funkcija koja go pretvara prasanjeto na latinica i so mali bukvi
def _p(prasanje: str) -> str:
    return transliterijaj(prasanje).lower()
# spored klucnite tabovi odreduva koj tab treba da se otvori
def odredi_lekar_tab(prasanje: str) -> str:
    p = _p(prasanje)    # proverka dali vnesot sodrzi nekoj od ponudentite zborovi
    if any(
        x in p
        for x in (  "дежур", "dezur", "дежурств", ) # dokolku ima nekoj
    ) and not any(  # a gi nema ovie
        x in p
        for x in ( "преглед на пациент", "термин", "termin", "пациент", "pacient", "закажан", )
    ):
        return "dezurstva"  # se prenasocuva kon dezurstva
    if any(
        x in p
        for x in ("апарат", "aparat", "мрт", "кт", "рентген", "сонограф", "узи",)
    ):
        return "aparati" # vraka aparati ako ima nesto od pogore navedenite zborovi
    if any(x in p for x in ("поставк", "postavk", "лозинк", "профил")):
        return "postavki"
    return "pacienti"
from ai.lekar.lekar_intent import prasanje_bara_lekar_panel 

def navigacija_za_tab(  # pomosna funkcija koja go generira navigiranjeto za frotend delot
    tab: str,
    *,
    termini_mode: str | None = None,
    datum: str | None = None,
) -> dict:
    label = TAB_LABELS.get(tab, tab)
    nav: dict = {
        "target": f"lekar:{tab}",
        "tab": tab,
        "label": label,
    }
    if termini_mode:
        nav["termini_mode"] = termini_mode
    if datum:
        nav["datum"] = datum
    return nav
# funkcija koja go dopolnuva finalniot odgovor so navigacijata i akcija za otvaranje na lekarskiot panel
def dopuni_so_lekar_panel(
    rezultat: str | dict,
    *,
    tab: str = "pacienti",
    termini_mode: str | None = None,
    datum: str | None = None,
    dodaj_napomena: bool = True,
) -> dict:
    """Додава navigacija + akcija за отворање на лекарскиот dashboard."""
    nav = navigacija_za_tab(tab, termini_mode=termini_mode, datum=datum)
    label = TAB_LABELS.get(tab, tab)

    if isinstance(rezultat, dict):  # ako vlezniot rezultat e vejke recnik
        odgovor = (rezultat.get("odgovor") or "").strip()   # se zema i se cisti postoeckiot odgovor
        out: dict = {
            "odgovor": odgovor,
            "navigacija": nav,  # vmetnuvanje na anvigaciskiot objekt
            "akcija": "otvori_lekar_panel", # se zema akcija do frontend delot
        }
        if rezultat.get("kontekst") is not None:    # dokolku ima vejke kontekst se zema od razgovorot
            out["kontekst"] = rezultat["kontekst"]  # se zacuvuva i prenesuva kontekstot
        if dodaj_napomena and odgovor:  # ako treba da se dade napomena i ime tekstualren odgovor
            out["odgovor"] = (  
                odgovor + f"\n\nЛистата е прикажана на табот «{label}»."    # se izvestuva lekarot kade da gleda na ekranot
            )
        elif not odgovor:   # ako odgovorot e prazen string 
            out["odgovor"] = f"Го отворам табот «{label}» на вашиот панел." # se stava string za sto e otvoreno
        return out

    tekst = (rezultat or "").strip()    # ako vlezniot strinf e obicen tekst
    if dodaj_napomena and tekst:
        tekst = tekst + f"\n\nЛистата е прикажана на табот «{label}»." # ako ima tekst i e pobarano dodavanje na napomena:
    elif not tekst: # ako ne e teskt
        tekst = f"Го отворам табот «{label}» на вашиот панел."  # standardna poraka deka tabot e otovren
    return {
        "odgovor": tekst,
        "navigacija": nav,  # vklucuvanje na navigacija
        "akcija": "otvori_lekar_panel", # davanje na akcija za frontend delot
    }
# funkcija koja se povikuva koga lekarot saka da go smeni tabots
def odgovori_za_otvori_lekar_panel(
    prasanje: str,
    lekar: dict | None,
    kontekst: dict | None = None,
) -> dict:
    """Само отворање на таб (без листа во чат), кога корисникот бара панел."""
    if err := require_lekar(lekar):
        return {
            "odgovor": (
                f"{err}\n\n"
                "Најавете се како лекар преку «Најава за лекар» на сајтот."
            ),
            "akcija": "otvori_lekar_login",
        }

    tab = odredi_lekar_tab(prasanje)    # se analizira prasanjeto i se detektira baraniot tab
    termini_mode = None # inicijalizacija na modot za temini
    datum = None    # inicijalizacija na datumot

    if tab == "pacienti":     # dokolku e baran tabot za pacient
        try:
            from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje # se obiduvame dinamicno da go uvezeme modulot za detekcija na datumi od prasanja
            d = datum_za_pregledi_od_prasanje(prasanje)     # izvlekuvanje na datumot
            if d:   # ako e pronajden konkreten datum
                datum = d.strftime("%Y-%m-%d")  # formatiranje na datumot vo iso format
                termini_mode = "date"   # se postavuva modot na specificen datum
            elif any(x in _p(prasanje) for x in ("сите", "site", "комплетн")):  # dokolku se bara da se prikazat site 
                termini_mode = "all"    # se davaat site
            else:
                termini_mode = "all"
        except ImportError:
            termini_mode = "all"

    label = TAB_LABELS.get(tab, tab)    #prezemanje na finalnata labela za odbraniot tab
    return dopuni_so_lekar_panel(   # pakuvanje i vrakanje na celiot json odgovor nazad 
        f"Го отворам табот «{label}» на вашиот панел.",
        tab=tab,
        termini_mode=termini_mode,
        datum=datum,
        dodaj_napomena=False,  
    )
