"""
FAQ za podgotovka za pregled — prvo JSON (brzo), potoa AI od agent_prompts (faq_pregled).
Podatoci: backend/data/faq_pregled.json
"""

import json  # uvoz na modulot za rabota so json datoteki
from pathlib import Path  # uvoz na pathlib za bezbedno upravuvanje so patistata niz sistemot

from ai._kernel.groq_client import ask_ai  # uvoz na klientot za komunikacija so groq api
from ai._kernel.prompt_loader import load_prompt  # uvoz na funkcijata za vchituvanje sistemski promptovi

# backend/ai/opsto/faq_pregled.py -> tri nivoa nagore = backend/, pa data/faq_pregled.json
_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "faq_pregled.json"


def _load() -> dict:  # interna funkcija za vchituvanje na lokalniot json fajl
    """Vchitaj JSON so FAQ podatoci za podgotovka na pregled."""
    try:  # bezbeden obid za otvaranje na datotekata
        with open(_JSON_PATH, "r", encoding="utf-8") as f:  # otvaranje so eksplicitna utf-8 poddrshka
            return json.load(f)  # vrakjanje на podatocite kako rechnik
    except Exception as e:  # fakanje na eventualna greshka pri chitanje
        print(f"[faq_pregled] greska pri citanje JSON: {e}")  # logiranje na greshkata na latinica
        return {}  # vrakjanje na prazen rechnik so cel da ne padne sistemot


def odgovori_za_faq_pregled(prasanje: str) -> str:  # glavna funkcija za servisiranje na faq baranja
    p = (prasanje or "").lower().strip()  # transformacija na prasanjeto vo mali bukvi i brishenje prazni mesta
    if not p:  # ako korisnikot ne vnesol nikakov tekst
        return "Napishete go prasanjeto (na pr. dali na gladno, shto da ponesam na pregled)."  # upatstvo na latinica

    data = _load()  # vchituvanje na lokalnite faq stavki
    stavki_raw = data.get("stavki")  # zemanje na sirovata lista so FAQ stavki
    stavki: list = stavki_raw if isinstance(stavki_raw, list) else []  # osiguravanje deka e validna lista
    disclaimer = (data.get("disclaimer") or "").strip()  # zemanje na opstiot medicinski disclaimer od fajlot
    default_odgovor = (data.get("default_odgovor") or "").strip()  # zemanje na defaultniot odgovor pri neuspeh

    # 1. BRZO PREBARUVANJE PREKU KLUCNI ZBOROVI (JSON)
    for st in stavki:  # ciklus niz sekoja poedinechna FAQ stavka
        if not isinstance(st, dict):  # proverka za validnost na strukturata
            continue
        kws = st.get("keywords") or []  # zemanje na listata od kluchni zborovi za taa stavka
        if not isinstance(kws, list):  # osiguravanje deka kluchnite zborovi se vo lista
            continue
        for kw in kws:  # ciklus niz sekoj kluchen zbor poedinechno
            if isinstance(kw, str) and kw.lower() in p:  # ako kluchniot zbor e pronajden vo prasanjeto na korisnikot
                naslov = (st.get("naslov") or "").strip()  # zemanje na naslovot na odgovorot
                odg = (st.get("odgovor") or "").strip()  # zemanje na samiot tekstualen odgovor
                parts = []  # sobirna lista za finalniot string
                if naslov:  # ako ima definiran naslov
                    parts.append(f"**{naslov}**\n")  # dodaj go naslovot so bold format
                parts.append(odg)  # dodaj go tekstot na odgovorot
                if disclaimer:  # ako postoi opshth disclaimer vo fajlot
                    parts.append(f"\n\n_{disclaimer}_")  # dodaj go na dnoto vo italic format
                return "\n".join(parts)  # spojuvanje i instantno vrakjanje na odgovorot

    # 2. AI FALLBACK (DOKOLKU NEMA DIREKTNO SOVPAGJANJE VO JSON)
    try:  # bezbeden povik do llm modelot
        ai_odg = ask_ai(  # povik do groq klientot
            f'Prasanje: "{prasanje}"',  # prenesuvanje na originalnoto prasanje na korisnikot
            system_prompt=load_prompt("faq_pregled"),  # vchituvanje na namenskiot sistemski prompt za faq
        ).strip()  # chistenje na okolnite prazni mesta od ai odgovorot
        if ai_odg:  # ako modelot vratil validen odgovor
            parts = [ai_odg]  # stavi go odgovorot vo listata
            if disclaimer:  # ako ima definiran disclaimer
                parts.append(f"\n\n_{disclaimer}_")  # prikachi go na krajot
            return "\n".join(parts)  # vrati go generiraniot odgovor od ai agentot
    except Exception as e:  # fakanje greshki pri povikot na groq api servisot
        print(f"[faq_pregled] AI fallback greska: {e}")  # logiranje na greshkata na konzola

    # 3. KRAJNA ZASHTITA (DEFAULT ODGOVOR AKO SE ZATAJI)
    out = [
        default_odgovor 
        or "Za konkretni baranja za pregled kontaktirajte ja recepcijata (032/ 605-001)."
    ]  # postavuvanje na defaultniot latinicen odgovor so telefonski broj
    if disclaimer:  # proverka za disclaimer
        out.append(f"\n\n_{disclaimer}_")  # dodavanje na dnoto
    return "\n".join(out)  # vrakjanje на finalniot string до korisnikot