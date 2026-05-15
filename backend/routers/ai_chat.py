"""
AI чат рутер — POST /ai-chat/ask

1. Нормализација на прашање (транслитерација)
2. Детекција на интент (keyword + Groq fallback)
3. dispatch() → соодветен handler од ai/_kernel/handlers.py
"""

import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ai._kernel.handlers import AiContext, dispatch
from ai._kernel.intent_detector import detektiraj_intent
from ai._kernel.transliteracija import normaliziraj_prashanje

router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])

MAX_PRASHANJE_LEN = 4000


class PacientModel(BaseModel):
    pacient_ID: int | None = None
    ime: str | None = None
    prezime: str | None = None
    email: str | None = None
    telefon: str | None = None
    embg: str | None = None


class LekarModel(BaseModel):
    doctor_ID: int | None = None
    name: str | None = None
    surname: str | None = None
    email: str | None = None
    specialty: str | None = None


class PitanjeModel(BaseModel):
    prashanje: str = Field(..., max_length=MAX_PRASHANJE_LEN)
    pacient: PacientModel | None = None
    lekar: LekarModel | None = None
    kontekst: dict | None = None


def _pacient_dict(p: PacientModel | None) -> dict | None:
    if not p or not p.email:
        return None
    return {
        "pacient_ID": p.pacient_ID,
        "ime": p.ime or "",
        "prezime": p.prezime or "",
        "email": p.email,
        "telefon": p.telefon or "",
        "embg": p.embg or "",
    }


def _lekar_dict(l: LekarModel | None) -> dict | None:
    if not l or not l.doctor_ID:
        return None
    return {
        "doctor_ID": l.doctor_ID,
        "name": l.name or "",
        "surname": l.surname or "",
        "email": l.email or "",
        "specialty": l.specialty or "",
    }


def _resolve_intent(
    pitanje_norm: str,
    aktiven_kontekst: dict | None,
    pacient_dict: dict | None,
    lekar_dict: dict | None,
) -> str:
    if aktiven_kontekst and aktiven_kontekst.get("intent") == "apliciraj_za_rabota":
        return "apliciraj_za_rabota"

    try:
        intent = detektiraj_intent(pitanje_norm)
    except Exception as e:
        print(f"[ai_chat] intent detection error: {e}")
        intent = "general"

    if intent == "moj_raspored" and pacient_dict and not lekar_dict:
        intent = "moi_pregledi"

    if (
        aktiven_kontekst
        and aktiven_kontekst.get("zakazi_od_slobodni")
        and intent == "general"
    ):
        q = pitanje_norm.lower()
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q) or re.search(r"\bво\s+\d{1,2}\b", q) or "закаж" in q:
            intent = "zakazi_termin"

    return intent


@router.post("/ask")
def ask(data: PitanjeModel):
    pitanje = (data.prashanje or "").strip()
    if not pitanje:
        return {"odgovor": "Те молам внеси прашање."}
    if len(pitanje) > MAX_PRASHANJE_LEN:
        return {"odgovor": f"Пораката е предолга (макс. {MAX_PRASHANJE_LEN} знаци)."}

    pitanje_norm = normaliziraj_prashanje(pitanje)
    pacient_dict = _pacient_dict(data.pacient)
    lekar_dict = _lekar_dict(data.lekar)
    aktiven_kontekst = data.kontekst if isinstance(data.kontekst, dict) else None

    intent = _resolve_intent(pitanje_norm, aktiven_kontekst, pacient_dict, lekar_dict)
    print(f"[ai_chat] {pitanje_norm!r} -> {intent}")

    ctx = AiContext(
        pitanje=pitanje,
        pitanje_norm=pitanje_norm,
        pacient=pacient_dict,
        lekar=lekar_dict,
        kontekst=aktiven_kontekst,
    )

    try:
        rez = dispatch(intent, ctx)
    except Exception as e:
        print(f"[ai_chat] handler error ({intent}): {e}")
        return {
            "odgovor": (
                "Се случи неочекувана грешка при обработката на прашањето. "
                "Те молам обиди се повторно или контактирај ја рецепцијата."
            ),
            "kontekst": None,
        }

    odgovor = rez.get("odgovor", "")
    out: dict = {"odgovor": odgovor, "kontekst": rez.get("kontekst")}
    if rez.get("navigacija"):
        out["navigacija"] = rez["navigacija"]
    if rez.get("akcija"):
        out["akcija"] = rez["akcija"]
    return out
