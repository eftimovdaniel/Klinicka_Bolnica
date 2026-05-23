"""Заеднички контекст за преглед/промена на дежурства во AI разговор."""

from datetime import date, datetime
from ai._kernel.utils import format_vreme


def izgradi_kontekst(found: dict, dez: dict | None) -> dict: # funkcija koja go gradiss kontekstot posle pregled na dezurstvo
    """Го пакува лекарот и дежурството за контекст во разговор.""" # dokumentacija — found e lekar, dez e red od Dezurstva ili None
    datum = dez.get("datum") if dez else None # go zemame datumot od dez ako lekarot veke ima dezurstvo vo baza
    if isinstance(datum, datetime): # proveruvame dali od bazata doagja datetime (so vreme)
        datum = datum.date() # go zemame samo delot datum — vremeto ne ni treba za kontekst
    datum_s = datum.isoformat() if isinstance(datum, date) else None # go pretvorame vo tekst YYYY-MM-DD za ai i za zacuvuvanje
    dez_id = dez.get("dezurstvo_ID") if dez else None # go zemame id na dezurstvoto za UPDATE vo baza podocna
    vreme_od = format_vreme(dez.get("vreme_od")) if dez and dez.get("vreme_od") is not None else None # pocetok na dezurstvoto formatiran
    vreme_do = format_vreme(dez.get("vreme_do")) if dez and dez.get("vreme_do") is not None else None # kraj na dezurstvoto formatiran

    return { # vrakame recnik koj routerot go zacuvuva vo memorijata na razgovorot
        "intent": "promeni_dezurstvo", # kazuvame deka slednite poraki se za promena/dodavanje dezurstvo
        "dezurstvo_kontekst": { # pod-recnik so site podatoci za edno konkretno dezurstvo
            "doctor_id": found["doctor_ID"], # id na lekarot koj go gledame ili menuvame
            "name": found["name"], # ime na lekarot za prikaz i za ai
            "surname": found["surname"], # prezime na lekarot za prikaz i za ai
            "specialty": found.get("specialty"), # specijalnost — ja koristi lekar_od_kontekst koga nema ime vo poraka
            "dezurstvo_id": dez_id, # koj red vo tabela Dezurstva (None = uste nema dezurstvo, ke se dodade)
            "datum": datum_s, # na koj datum e dezurstvoto kako tekst
            "vreme_od": vreme_od, # od koi casovi pocnuva dezurstvoto
            "vreme_do": vreme_do, # do koi casovi trae dezurstvoto
        }, # kraj na blokot dezurstvo_kontekst
    } # kraj na glavniot return — ova odi vo kontekst na sledna poraka


def lekar_od_kontekst(kontekst: dict | None) -> dict | None: # funkcija koja od zacuvan kontekst go vrakame lekarot
    """Враќа податоци за лекар од претходен контекст.""" # dokumentacija — za „промени да е до 03:00" bez povtorno ime
    if not kontekst: # proveruvame dali ima kontekst od pretodna ai poraka
        return None # nema kontekst — ne moze da se najde lekar
    dk = kontekst.get("dezurstvo_kontekst") # go zemame vnatresniot blok so podatoci za dezurstvo
    if not dk or not dk.get("doctor_id"): # proveruvame dali blokot postoi i dali ima doctor_id
        return None # nevaliden kontekst — nema lekar
    return { # vrakame lekar vo format koj go koristi promeni_dezurstvo i lekar_lookup
        "doctor_ID": dk["doctor_id"], # id na lekarot (vo kontekst e doctor_id, vo baza doctor_ID)
        "name": dk.get("name", ""), # ime — prazen string ako nedostasuva
        "surname": dk.get("surname", ""), # prezime — prazen string ako nedostasuva
        "specialty": dk.get("specialty"), # specijalnost za oddel i prikaz
    } # kraj na return — lekar za baranje ili update dezurstvo
