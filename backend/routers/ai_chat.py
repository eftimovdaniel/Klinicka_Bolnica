"""
HTTP endpoint за AI чат.

Прима прашање + (опционално) пациент податоци од frontend.
Според интент, рутира до:
- zakazi_termin     → закажува термин во база + е-пошта
- slobodni_termini  → бара слободни термини
- general           → Gemini општ одговор

Целата AI логика е во: backend/ai/
"""

from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from ai.gemini_client import ask_gemini
from ai.intent_detector import detektiraj_intent
from ai.slobodni_termini import odgovori_za_slobodni_termini
from ai.zakazi_termin import odgovori_za_zakazuvanje


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
    Прима: {"prashanje": "Сакам преглед...", "pacient": {...}}
    Враќа: {"odgovor": "..."}
    """

    prashanje = (data.prashanje or "").strip()
    if not prashanje:
        return {"odgovor": "Те молам внеси прашање."}

    intent = detektiraj_intent(prashanje)

    # Закажување нов термин
    if intent == "zakazi_termin":
        # Претвораме pydantic модел во dict (или None)
        pacient_dict = data.pacient.model_dump() if data.pacient else None
        odgovor = odgovori_za_zakazuvanje(prashanje, pacient_dict)
        return {"odgovor": odgovor}

    # Преглед на слободни термини
    if intent == "slobodni_termini":
        odgovor = odgovori_za_slobodni_termini(prashanje)
        return {"odgovor": odgovor}

    # Општо прашање → Gemini
    odgovor = ask_gemini(prashanje)
    return {"odgovor": odgovor}
