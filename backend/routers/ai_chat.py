"""
AI чат рутер — POST /ai-chat/ask

1. Нормализација на прашање (транслитерација)
2. Детекција на интент (keyword + Groq fallback)
3. dispatch() → соодветен handler од ai/_kernel/handlers.py
4. За најавен пациент/лекар — зачувување на историја (Ai_chat_session / Ai_chat_message)
"""

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ai._kernel.handlers import AiContext, dispatch
from ai._kernel.intent_detector import detektiraj_intent
from ai._kernel.transliteracija import normaliziraj_prashanje
from ai_chat_store import (
    create_session,
    get_session_messages,
    list_sessions,
    save_exchange,
)

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
    session_id: int | None = None


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


def _owner_ids(
    pacient_dict: dict | None, lekar_dict: dict | None
) -> tuple[int | None, int | None]:
    pid = None
    did = None
    if pacient_dict and pacient_dict.get("pacient_ID"):
        try:
            pid = int(pacient_dict["pacient_ID"])
        except (TypeError, ValueError):
            pid = None
    if lekar_dict and lekar_dict.get("doctor_ID"):
        try:
            did = int(lekar_dict["doctor_ID"])
        except (TypeError, ValueError):
            did = None
    return pid, did


def _dt_iso(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat(sep=" ", timespec="seconds")
    return str(val)


def _resolve_intent(
    pitanje_norm: str,
    aktiven_kontekst: dict | None,
    pacient_dict: dict | None,
    lekar_dict: dict | None,
) -> str:
    if aktiven_kontekst and aktiven_kontekst.get("intent") == "apliciraj_za_rabota":
        return "apliciraj_za_rabota"
    if aktiven_kontekst and aktiven_kontekst.get("intent") == "fb_novosti_odobruvanje":
        return "fb_novosti_odobruvanje"

    try:
        intent = detektiraj_intent(pitanje_norm)
    except Exception as e:
        print(f"[ai_chat] intent detection error: {e}")
        intent = "general"

    if intent == "moj_raspored" and pacient_dict and not lekar_dict:
        intent = "moi_pregledi"

    if aktiven_kontekst and aktiven_kontekst.get("zakazi_od_slobodni"):
        q = pitanje_norm.lower()
        # Закажување со време / „закажи во 10:30“
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q) or re.search(
            r"\bво\s+\d{1,2}\b", q
        ):
            intent = "zakazi_termin"
        elif "закаж" in q and not any(
            w in q
            for w in (
                "провери",
                "провер",
                "слобод",
                "наредн",
                "следн",
                "утре",
                "задутре",
                "понеделник",
                "вторник",
                "среда",
                "четврток",
                "петок",
                "сабота",
                "недела",
            )
        ):
            intent = "zakazi_termin"
        # Следна порака: друг ден / „наредниот петок“ кај истиот лекар
        elif intent in ("general", "zakazi_termin"):
            from ai.pacient.slobodni_termini import cilj_datum_lokalno

            if cilj_datum_lokalno(pitanje_norm) or any(
                w in q
                for w in (
                    "провери",
                    "провер",
                    "слобод",
                    "термин",
                    "има ли",
                    "кога",
                    "може",
                    "наредн",
                    "следн",
                    "утре",
                    "задутре",
                    "понеделник",
                    "вторник",
                    "среда",
                    "четврток",
                    "петок",
                    "сабота",
                    "недела",
                )
            ):
                intent = "slobodni_termini"

    return intent


@router.get("/sessions")
def get_chat_sessions(
    pacient_id: int | None = Query(None),
    doctor_id: int | None = Query(None),
):
    """Листа на претходни разговори за најавен корисник."""
    if not pacient_id and not doctor_id:
        raise HTTPException(status_code=400, detail="Потребен е pacient_id или doctor_id.")
    rows = list_sessions(pacient_id=pacient_id, doctor_id=doctor_id)
    return {
        "sessions": [
            {
                "session_id": r.get("session_id"),
                "naslov": r.get("naslov") or "Разговор",
                "created_at": _dt_iso(r.get("created_at")),
                "updated_at": _dt_iso(r.get("updated_at")),
            }
            for r in rows
        ]
    }


@router.get("/sessions/{session_id}/messages")
def get_chat_messages(
    session_id: int,
    pacient_id: int | None = Query(None),
    doctor_id: int | None = Query(None),
):
    """Пораки од избрана сесија (+ контекст за продолжување на флоу)."""
    if not pacient_id and not doctor_id:
        raise HTTPException(status_code=400, detail="Потребен е pacient_id или doctor_id.")
    data = get_session_messages(
        session_id, pacient_id=pacient_id, doctor_id=doctor_id
    )
    if not data:
        raise HTTPException(status_code=404, detail="Разговорот не е пронајден.")
    msgs = []
    for m in data.get("messages") or []:
        msgs.append(
            {
                "uloga": m.get("uloga"),
                "sodrzina": m.get("sodrzina"),
                "navigacija": m.get("navigacija"),
                "akcija": m.get("akcija"),
                "created_at": _dt_iso(m.get("created_at")),
            }
        )
    return {
        "session_id": data.get("session_id"),
        "kontekst": data.get("kontekst"),
        "messages": msgs,
    }


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
    pacient_id, doctor_id = _owner_ids(pacient_dict, lekar_dict)
    history_enabled = bool(pacient_id or doctor_id)

    session_id: int | None = None
    is_new_session = False
    if history_enabled:
        if data.session_id:
            try:
                session_id = int(data.session_id)
            except (TypeError, ValueError):
                session_id = None
        if session_id:
            existing = get_session_messages(
                session_id, pacient_id=pacient_id, doctor_id=doctor_id
            )
            if not existing:
                session_id = None
        if not session_id:
            session_id = create_session(pacient_id=pacient_id, doctor_id=doctor_id)
            is_new_session = bool(session_id)

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
            "session_id": session_id,
        }

    odgovor = rez.get("odgovor", "")
    nov_kontekst = rez.get("kontekst")
    out: dict[str, Any] = {
        "odgovor": odgovor,
        "kontekst": nov_kontekst,
        "session_id": session_id,
    }
    if rez.get("navigacija"):
        out["navigacija"] = rez["navigacija"]
    if rez.get("akcija"):
        out["akcija"] = rez["akcija"]

    if history_enabled and session_id:
        save_exchange(
            session_id,
            pacient_id=pacient_id,
            doctor_id=doctor_id,
            user_text=pitanje,
            assistant_text=odgovor or "",
            kontekst=nov_kontekst if isinstance(nov_kontekst, dict) else None,
            navigacija=rez.get("navigacija") if isinstance(rez.get("navigacija"), dict) else None,
            akcija=rez.get("akcija") if isinstance(rez.get("akcija"), str) else None,
            set_naslov=is_new_session,
        )

    return out
