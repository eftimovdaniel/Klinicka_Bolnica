"""Заеднички контекст за преглед/промена на дежурства во AI разговор."""

from datetime import date, datetime
# funkcija koja go pakuva kontekstot za dezurstvo za ai agento koga se menuva dezurstvoto, vo found imam podatocit za lekarot a vo dez site podatoci koga daden lekar e dezuren,
# dokolku istiojt toj lekar nema postaveno dezurstvo se postavuva vrednot none
def izgradi_kontekst(found: dict, dez: dict | None) -> dict:
    datum = dez.get("datum") if dez else None   # go zemame datumot od dezurstvo ako e postaven, dokolku nema se zema none, lekarot moze da se stave dezuren 
    if isinstance(datum, datetime): # proveka adli datumot e zemen od bazata 
        datum = datum.date()    # go izolirame datumot, vremeto ne ni e potrebno 
    datum_s = datum.isoformat() if isinstance(datum, date) else None    #datumot go pretvarame vo tekst i go smestuvame vo datum_s za da moze da se obrabote od ai

    dez_id = dez.get("dezurstvo_ID") if dez else None   # go zema id to na dezurstvoto za da znaeme koj podatok se mene vo bazata
    vreme_od = _fmt(dez.get("vreme_od")) if dez else None   # se zema pocetokot na dezurstviti i go formatirame vo tekst za ai 
    vreme_do = _fmt(dez.get("vreme_do")) if dez else None   # se zema krajot na dezurstvoto

    return {    # vraka recnik koj sluzi kako memorija za ai agento
        "intent": "promeni_dezurstvo",  # definiranje na toa sto sakame da izvrsime -> promena na dezurstvoto ako go ima 
        "dezurstvo_kontekst": {     # pod recnik so site informacii za dezurstvoto da moze da se promeni
            "doctor_id": found["doctor_ID"],    # go zema id na lekarot koj e pronajde 
            "name": found["name"],  # go zema imeto na lekarot
            "surname": found["surname"],    # go zema prezimeto na lekarots
            "dezurstvo_id": dez_id, # go zacuvuva id na dezurstvoto 
            "datum": datum_s,       # go zacuvuva datumot na dezurstvot za koja e napravena promena
            "vreme_od": vreme_od,   # pocetok od koga e lekarot treba da pocne so rabota
            "vreme_do": vreme_do,   # kraj do koga lekarot treba da raboti
            # so ovie podatoci ai agento moze da go prepoznae dezurstvoto i da go promeni so novite podatoci koi ke mu se dadat, 
            # dokolku nema dezurstvo se postavuva none i ai agento ke znae deka treba da go postavi lekarot kako dezuren so novite podatoci, 
            # dokolku ima dezurstvo ke znae deka treba da go promeni postoeckoto dezurstvo
        },
    }
# funkcija koja od kontekst na zacuvanite poraki vadi kontekst
def lekar_od_kontekst(kontekst: dict | None) -> dict | None:
    if not kontekst:        # dokolku ne postoi kontekst vo porakite 
        return None         # ne se vrakaat nikakvi infromacii ili none
    dk = kontekst.get("dezurstvo_kontekst") # go vleceme glavniot kontekst so podatoci za dezurstvoto od porakite
    if not dk or not dk.get("doctor_id"):   # dokolku ne postoi takov blok ili nema id na lekarot koj e dezuren 
        return None # se vraka none, nema informacii za lekarot koj e zdezuren
    return {    # dokolku postojat site ovie podatoci se prefrlaat 
        "doctor_ID": dk["doctor_id"],       # id na lekarot za koj se pravi promena vo dezurstvoto
        "name": dk.get("name", ""),         # imeto na lekarot za koj se pravi promena vo dezurstvoto i go zemam od kontekstot na porakite
        "surname": dk.get("surname", ""),   # isto kako i imeto se pravi i za prezimeto
        "specialty": dk.get("specialty"),   # ja zemame specijalnost od kontekstot kako prezimeto i imeto
    }
# pomosna funkcija za formatiranje na vremeto i datumot vo tekstot za ai agentot
def _fmt(t) -> str | None:
    if t is None:   # ako ne e vnesena vrednot za vremeto vo t
        return None # se vraka none, nema vremenski podatoci
    if hasattr(t, "strftime"):  # dokolku ima 
        return t.strftime("%H:%M")  # vremeto se formatira vo cas:minuti
    s = str(t)      # ako ne e vremeski objekt, vrednost na s ja pretvarame vo string
    return s[:5] if len(s) >= 5 else s  # dokolku vremeto ime sekundi se zemaat prvite 5 karakteri cas (2) :(1) minuti (4)
