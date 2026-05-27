"""
AI-driven intent detector со Groq API.

Зашто:
- Keyword detector-от пропушта природни варијации:
    "Dali možeš da mi zakažeš pregled?" - има „закажеш" не „закажи"
    "Бих сакал да одам кај лекар" - нема јасен keyword
    "Што имам утре?" - не е во ниту еден keyword list
- AI го разбира значењето, не само зборовите.

Стратегија:
- Главна функција: detektiraj_intent_so_ai(prasanje)
- Прима природен текст, враќа intent string
- Ако AI не одговори јасно → "general" (па одговара со општ AI)

Се користи КАКО fallback или замена за keyword detektorot во intent_detector.py.
"""

import re
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_loader import load_prompt


# Промпт: backend/data/prompts/intent_classifier.txt



# Mnozhestvo validni intenti - sluzhi za validacija deka AI vratil poznata vrednost
# (kako safelist - ako AI izmisli neshto, ne se prifaka)
VALIDNI_INTENTI = {
    "zakazi_termin",
    "otkazi_termin",
    "prenesi_termin",
    "postavi_potsetnik",
    "oceni_pregled",
    "trgni_ocena",
    "slobodni_termini",
    "info_lekar",
    "preporaka_lekar",
    "rabotno_vreme",
    "lokacija",
    "kontakti",
    "uslugi",
    "objavi_vest",
    "kreiraj_oglas",
    "izbrisi_vest_oglas",
    "zatvori_oglas",
    "pregled_dezurstvo",
    "promeni_dezurstvo",
    "zavrshi_pregled",
    "istorija_pacient",
    "karton_pacient",
    "moja_statistika",
    "moj_raspored",
    "otvori_lekar_panel",
    "navigacija",
    "lekari_oddel",
    "apliciraj_za_rabota",
    "moi_pregledi",
    "aplikanti_oglas",
    "zapishi_terapija",
    "novosti_rezime",
    "faq_pregled",
    "rezultati_testovi",
    "preference_lekar",
    "general",
}
def detektiraj_intent_so_ai(prasanje: str) -> str:
    """
    Праша AI (Groq) да го класифицира прашањето во еден од поддржаните интенти.

    Враќа: име на интент (string). При било каква грешка → "general".
    """
    if not prasanje or not prasanje.strip():
        return "general"
    # Prazno prasanje - generichen fallback

    try:
        odgovor = ask_ai(prasanje.strip(), system_prompt=load_prompt("intent_classifier"))
        # intent_classifier promptot dava lista na validni intenti i kako da gi vrati
    except Exception as e:
        print(f"[ai_intent] greska pri AI: {e}")
        return "general"
        # Pri greshka - safe fallback na opshti odgovor

    # ISCISTUVANJE NA ODGOVOROT
    cist = (odgovor or "").strip().lower()
    # Mali bukvi za polesno sporeduvanje
    # Тргни markdown ``` или објаснувања
    cist = re.sub(r"^```\w*\s*", "", cist)
    cist = re.sub(r"\s*```$", "", cist)
    # Cisti pochetna i krajna markdown fence (AI ponekade ja zatvara takka)
    # Земи само првиот „збор" (intent_name)
    prv_red = cist.split("\n")[0].strip()
    # Prva linija - vo slucaj AI da napisha objasnuvanje vo slednite redovi
    prv_zbor = re.split(r"[\s,.!?:;()\"]+", prv_red)[0] if prv_red else ""
    # Razdeluvanje na zborovi - prvi zbor e intent imeto

    # VALIDACIJA
    if prv_zbor in VALIDNI_INTENTI:
        return prv_zbor
    # Tochno sovpaganje vo safelist - vrati direktno

    # Ако AI врати нешто слично - barаj подниз
    for v in VALIDNI_INTENTI:
        if v in cist:
            return v
    # Fallback - mozhebi AI go vrati intent imeto vnatre vo dolg tekst

    print(f"[ai_intent] nevaliden odgovor: '{odgovor}' -> general")
    return "general"
    # Posleden fallback - ako AI vrati neshto sosema nepoznato
