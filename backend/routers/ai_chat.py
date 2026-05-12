"""
HTTP endpoint за AI чат.

Прима прашање + (опционално) пациент податоци од frontend.
Според интент, рутира до соодветната функција.

Целата AI логика е во: backend/ai/
"""

from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from ai.gemini_client import ask_gemini
from ai.intent_detector import detektiraj_intent
from ai.slobodni_termini import odgovori_za_slobodni_termini
from ai.zakazi_termin import odgovori_za_zakazuvanje
from ai.otkazi_termin import odgovori_za_otkazuvanje
from ai.prenesi_termin import odgovori_za_prenesuvanje
from ai.postavi_potsetnik import odgovori_za_potsetnik
from ai.oceni_pregled import odgovori_za_ocenuvanje
from ai.trgni_ocena import odgovori_za_trgni_ocena
from ai.preporaka_lekar import odgovori_za_preporaka
from ai.info_lekar import odgovori_za_info_lekar
from ai.bolnica_info import (
    odgovori_za_rabotno_vreme,
    odgovori_za_lokacija,
    odgovori_za_kontakti,
)
from ai.uslugi import odgovori_za_uslugi


router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])


class PacientModel(BaseModel):
    """Податоци за логиран пациент (од frontend localStorage)."""
    pacient_ID: Optional[int] = None
    ime: Optional[str] = None
    prezime: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None


class PitanjeModel(BaseModel):
    prashanje: str
    pacient: Optional[PacientModel] = None


@router.post("/ask")
def ask_ai(data: PitanjeModel):
    """
    Прима: {"prashanje": "...", "pacient": {...}}
    Враќа: {"odgovor": "..."}
    """

    prashanje = (data.prashanje or "").strip()
    if not prashanje:
        return {"odgovor": "Те молам внеси прашање."}

    intent = detektiraj_intent(prashanje)
    pacient_dict = data.pacient.model_dump() if data.pacient else None

    # Рутирање според интент
    if intent == "zakazi_termin":
        return {"odgovor": odgovori_za_zakazuvanje(prashanje, pacient_dict)}

    if intent == "otkazi_termin":
        return {"odgovor": odgovori_za_otkazuvanje(prashanje, pacient_dict)}

    if intent == "prenesi_termin":
        return {"odgovor": odgovori_za_prenesuvanje(prashanje, pacient_dict)}

    if intent == "postavi_potsetnik":
        return {"odgovor": odgovori_za_potsetnik(prashanje, pacient_dict)}

    if intent == "oceni_pregled":
        return {"odgovor": odgovori_za_ocenuvanje(prashanje, pacient_dict)}

    if intent == "trgni_ocena":
        return {"odgovor": odgovori_za_trgni_ocena(prashanje, pacient_dict)}

    if intent == "slobodni_termini":
        return {"odgovor": odgovori_za_slobodni_termini(prashanje)}

    if intent == "preporaka_lekar":
        return {"odgovor": odgovori_za_preporaka(prashanje)}

    if intent == "info_lekar":
        return {"odgovor": odgovori_za_info_lekar(prashanje)}

    if intent == "rabotno_vreme":
        return {"odgovor": odgovori_za_rabotno_vreme(prashanje)}

    if intent == "lokacija":
        return {"odgovor": odgovori_za_lokacija(prashanje)}

    if intent == "kontakti":
        return {"odgovor": odgovori_za_kontakti(prashanje)}

    if intent == "uslugi":
        return {"odgovor": odgovori_za_uslugi(prashanje)}

    # Општо прашање → Gemini
    return {"odgovor": ask_gemini(prashanje)}
