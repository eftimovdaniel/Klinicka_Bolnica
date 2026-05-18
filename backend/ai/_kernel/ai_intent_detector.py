"""
AI-driven intent detector со Groq (Llama 3.3 70B).

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



# Множество валидни интенти за валидација на одговорот
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
    "statistika_oddeli",
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
    "izvestaj_den_nedela",
    "otvori_admin_panel",
    "general",
}
def detektiraj_intent_so_ai(prasanje: str) -> str:
    """
    Праша AI (Groq) да го класифицира прашањето во еден од поддржаните интенти.

    Враќа: име на интент (string). При било каква грешка → "general".
    """
    if not prasanje or not prasanje.strip():
        return "general"

    try:
        odgovor = ask_ai(prasanje.strip(), system_prompt=load_prompt("intent_classifier"))
    except Exception as e:
        print(f"[ai_intent] greska pri AI: {e}")
        return "general"

    # Исчисти го одговорот
    cist = (odgovor or "").strip().lower()
    # Тргни markdown ``` или објаснувања
    cist = re.sub(r"^```\w*\s*", "", cist)
    cist = re.sub(r"\s*```$", "", cist)
    # Земи само првиот „збор" (intent_name)
    prv_red = cist.split("\n")[0].strip()
    prv_zbor = re.split(r"[\s,.!?:;()\"]+", prv_red)[0] if prv_red else ""

    # Валидирај
    if prv_zbor in VALIDNI_INTENTI:
        return prv_zbor

    # Ако AI врати нешто слично - barаj подниз
    for v in VALIDNI_INTENTI:
        if v in cist:
            return v

    print(f"[ai_intent] nevaliden odgovor: '{odgovor}' -> general")
    return "general"
