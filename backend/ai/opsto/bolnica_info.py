"""
Informacii za bolnicata - rabotno vreme, lokacii, kontakti.
Ovie podatoci ne se vo DB (nema takvi tabeli), pa se vchituvaat
od backend/data/bolnica_info.json.

Sodrzi:
- odgovori_za_rabotno_vreme()  -> #12
- odgovori_za_lokacija()       -> #13
- odgovori_za_kontakti()       -> #14
"""

import json  # uvoz na modulot za rabota so json datoteki
from pathlib import Path  # uvoz na pathlib za bezbedno upravuvanje so patistata niz operativniot sistem

from ai._kernel.ai_json import is_ai_error_response  # prepoznavanje groq greska vo odgovorot
from ai._kernel.groq_client import ask_ai  # uvoz na klientot za komunikacija so groq api
from ai._kernel.prompts import ODDEL_EXTRACT_PROMPT  # sistemski prompt za ekstrakcija na oddeli (makedonski vo agent_prompts.txt)

# backend/ai/opsto/bolnica_info.py -> tri nivoa nagore = backend/, pa data/bolnica_info.json
_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "bolnica_info.json"


def _zimi_info() -> dict:  # pomosna funkcija za vcituvanje na json strukturata od lokalniot disk
    """Vchitaj JSON so info za bolnicata."""
    try:  # obid za bezbedno otvaranje na datotekata
        with open(_JSON_PATH, "r", encoding="utf-8") as f:  # otvaranje so eksplicitna utf-8 poddrshka za jazicite
            return json.load(f)  # vrakjanje na jsonot kako klasichen python rechnik
    except Exception as e:  # fakanje na sefakov tip na greska (izbrisana datoteka, nevaliden json...)
        print(f"[bolnica_info] greska pri citanje: {e}")  # pecatenje na greskata na konzola
        return {}  # vrakjanje na prazen rechnik so cel da ne padne celata aplikacija


def _najdi_oddel_so_ai(prasanje: str, oddeli: list[str]) -> str | None:  # glavna interna funkcija za prepoznavanje oddel preku llm
    """
    Prashuva AI (Groq) koj oddel e vo prasanjeto.
    Vrakja tocno ime na oddel ili None.
    """
    if not oddeli:  # nema oddeli vo json za ovaa sekcija
        return None  # nema sto da se bara

    lista_text = "\n".join([f"- {o}" for o in oddeli])  # kreiranje na tekstualna lista od dostapnite oddeli

    full_prompt = f"""
Достапни оддели:
{lista_text}

Корисникот пишува: „{prasanje}"

Кој оддел е спомнат во прашањето? Врати го само ТОЧНОТО ИМЕ од листата погоре
(исти големи/мали букви како во листата) или зборот NONE ако нема конкретен оддел.
    """.strip()  # makedonski prompt za groq (iminjata na oddeli se od json na kirilica)

    odgovor = ask_ai(full_prompt, system_prompt=ODDEL_EXTRACT_PROMPT)  # povik do groq api-to so prasanjeto i sistemskiot prompt
    if is_ai_error_response(odgovor):  # nema api kluc ili 429 rate limit
        return None  # fallback: prikazi gi site oddeli

    odgovor_cist = odgovor.strip().replace('"', '').replace("'", "").strip()  # cistenje na quotes i navodnici od ai odgovorot

    if "NONE" in odgovor_cist.upper():  # ako modelot se izjasnil deka nema prepoznat oddel
        return None  # vrakjame none

    for o in oddeli:  # prv ciklus: barame apsolutno isto sovpagjanje vo tekstot bez razlika na golemina na bukvi
        if o.lower() == odgovor_cist.lower():  # sporedba
            return o  # go vrakjame originalnoto ime od jsonot

    for o in oddeli:  # vtor ciklus: polesna proverka za delumno sovpagjanje na stringovite (substring)
        if o.lower() in odgovor_cist.lower() or odgovor_cist.lower() in o.lower():  # dvosmerna substring proverka
            return o  # vrakjame uspesen naod

    return None  # ako nieden uslov ne pominal, default vrakjame none


def odgovori_za_rabotno_vreme(prasanje: str) -> str:  # eksportirana funkcija za servisiranje na rabotno vreme
    info = _zimi_info()  # vcitaj go jsonot
    rabotno = info.get("rabotno_vreme", {})  # zemi ja sekcijata za rabotno vreme
    po_oddel = rabotno.get("po_oddel", {})  # zemi go rechnikot po oddeli
    oddeli = list(po_oddel.keys())  # izvadat lista na site klucni oddeli od jsonot

    izbran_oddel = _najdi_oddel_so_ai(prasanje, oddeli)  # pusti go prasanjeto na proverka preku ai agentot
    if izbran_oddel:  # ako e pronajden specificen oddel
        vreme = po_oddel.get(izbran_oddel, "—")  # zemi go negovoto vreme od rechnikot
        return f"Работно време на {izbran_oddel}:\n\n{vreme}"  # odgovor na makedonski (kirilica)

    # Dokolku prasanjeto e opsto, generiraj celosen raspored za site oddeli
    delovi = ["Работно време на Клиничка Болница Штип:", ""]  # naslovni linii
    delovi.append(rabotno.get("opsto", "—"))  # dodaj opsto rabotno vreme
    delovi.append(rabotno.get("vikendi", ""))  # dodaj rabotno vreme za vikendi
    delovi.append("")  # prazen red za format
    delovi.append("По оддели:")  # podnaslov
    for od, vreme in po_oddel.items():  # ciklus niz site oddeli od json
        delovi.append(f"- {od}: {vreme}")  # lepenje na sekoj oddel vo listata za izlez
    return "\n".join(delovi)  # spojuvanje so nov red i vrakjanje na tekstot


def odgovori_za_lokacija(prasanje: str) -> str:  # eksportirana funkcija za lokacii na oddelite
    info = _zimi_info()  # vcituvanje podatoci
    lokacii = info.get("lokacii", {})  # zemanje na sekcijata za lokacii

    if not lokacii:  # ako rechnikot e prazen poradi greska vo fajlot
        return "Нема расположливи податоци за локации."  # poraka na makedonski

    oddeli = list(lokacii.keys())  # lista od oddelite koi imaat lokacija
    izbran_oddel = _najdi_oddel_so_ai(prasanje, oddeli)  # detekcija preku ai modelot

    if izbran_oddel:  # ako e prepoznat konkreten oddel od korisnikot
        lokacija = lokacii.get(izbran_oddel, "—")  # zemi ja lokacijata na toj oddel
        return f"Локација на {izbran_oddel}:\n\n{lokacija}"  # vrati precizen odgovor za toj oddel

    # Opsto prebaruvanje - gi vrakja site lokacii
    delovi = ["Локации на оддели во Клиничка Болница Штип:", ""]  # pocetni linii
    for od, lok in lokacii.items():  # vrtenje niz site lokacii vo json
        delovi.append(f"- {od}: {lok}")  # formatiranje na redot
    delovi.append("")  # formatiracki prazen prostor
    delovi.append(f'Адреса: {info.get("kontakti", {}).get("adresa", "—")}')  # dodavanje na fiksna adresa na dnoto
    return "\n".join(delovi)  # spojuvanje i izlez


def odgovori_za_kontakti(prasanje: str) -> str:  # eksportirana funkcija za telefoni i kontakti
    info = _zimi_info()  # vcitaj json
    kontakti = info.get("kontakti", {})  # izvleci kontakti sekcija

    if not kontakti:  # ako sekcijata nedostasuva vo json datotekata
        return "Нема расположливи контакти."  # zastitna poraka

    prasanje_lower = prasanje.lower()  # prefrli vo mali bukvi za pobrzi proverki so klucni zborovi

    # Detekcija na itni slucaevi preku klucni zborovi na kirilica i latinica (bez ai)
    if (
        "итн" in prasanje_lower
        or "itn" in prasanje_lower
        or "urgent" in prasanje_lower
        or "urgat" in prasanje_lower
        or "vednas" in prasanje_lower
        or "веднаш" in prasanje_lower
    ):  # ako e prepoznata itnost vo porakata
        return (  # direktno vrakjame detali za itniot oddel
            "Итна помош:\n\n"
            f"Телефон: {kontakti.get('itna', '—')}\n"  # telefon za itni povici
            "Локација: Главна зграда, приземје, главен влез\n"  # lokaciski nasoki
            "Достапна: 24 часа, 7 дена во неделата"  # dostapnost
        )  # kraj na itniot odgovor

    # Generiranje na celosniot telefonski imenik i kontakti od json datotekata
    delovi = ["Контакти на Клиничка Болница Штип:", ""]  # naslovni linii
    if kontakti.get("centrala"):  # proverka dali postoi kluchot centrala
        delovi.append(f"Централа: {kontakti['centrala']}")  # dodavanje vo izlezot
    if kontakti.get("itna"):  # proverka za brojot na itna sluzba
        delovi.append(f"Итна помош: {kontakti['itna']}")  # broj za itna pomosh
    if kontakti.get("informacii"):  # proverka za informacisko biro
        delovi.append(f"Рецепција / информации: {kontakti['informacii']}")  # format na redot
    if kontakti.get("rezervacii"):  # proverka za zakazuvanje termini
        delovi.append(f"Резервации: {kontakti['rezervacii']}")  # dodavanje rezervaciski kontakt
    if kontakti.get("email"):  # proverka dali ima email kontakt vo fajlot
        delovi.append(f"Email: {kontakti['email']}")  # lepenje email adresa
    if kontakti.get("adresa"):  # proverka za fizicka lokacija/adresa
        delovi.append("")  # estetski prazen red pred adresata
        delovi.append(f"Адреса: {kontakti['adresa']}")  # ispisuvanje na adresata na bolnicata

    return "\n".join(delovi)  # finalno spojuvanje na tekstualnite delovi vo eden string
