"""
Фиксни одговори за поздрав / идентитет — без Groq (често крши македонски на кратки поздрави).
"""

from ai._kernel.transliteracija import transliterijaj

ODGOVOR_IDENTITET = (
    "Здраво! Како виртуелен асистент на Клиничка Болница Штип, тука сум да ти помогнам "
    "со сите информации поврзани со закажување прегледи, одделите во болницата, "
    "најновите соопштенија или административните процедури."
)

ODGOVOR_BLAGODARNOST = (
    "Молам! Ако ти треба уште нешто — закажување преглед, лекари, работно време "
    "или услуги — слободно прашај."
)


def odgovori_za_asistent_opsto(prasanje: str) -> str:
    p = transliterijaj(prasanje or "").lower()
    if any(x in p for x in ("благодар", "фала", "thanks", "thank you", "thanks a lot", "thx")):
        return ODGOVOR_BLAGODARNOST
    return ODGOVOR_IDENTITET
