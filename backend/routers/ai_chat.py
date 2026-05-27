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
from ai._kernel.transliteracija import normaliziraj_prasanje
from ai_chat_store import (
    create_session,
    delete_session,
    get_session_messages,
    import_guest_session,
    list_sessions,
    save_exchange,
)
router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])
MAX_PRASANJE_LEN = 4000
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
    prasanje: str = Field(..., max_length=MAX_PRASANJE_LEN)
    pacient: PacientModel | None = None
    lekar: LekarModel | None = None
    kontekst: dict | None = None
    session_id: int | None = None

class GuestChatMessage(BaseModel):
    uloga: str
    sodrzina: str = Field(..., max_length=MAX_PRASANJE_LEN)

class GuestImportModel(BaseModel):
    pacient: PacientModel | None = None
    lekar: LekarModel | None = None
    messages: list[GuestChatMessage] = Field(default_factory=list)
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


def _intent_strukturiran_za_lekar(
    pitanje_norm: str,
    aktiven_kontekst: dict | None,
    intent: str,
) -> str:
    """Прашања за конкретен лекар не одат на general/AI — ист handler за сите имиња."""
    from ai.pacient.slobodni_termini import prasanje_e_otkazuvanje
    from ai._kernel.intent_detector import (
        _bolnica_info_intent,
        _prasanje_e_asistent_opsto,
        _prasanje_e_konkreten_lekar,
    )
    from ai._kernel.transliteracija import transliterijaj

    if _prasanje_e_asistent_opsto(transliterijaj(pitanje_norm).lower()):
        return "general"

    if prasanje_e_otkazuvanje(pitanje_norm):
        return "otkazi_termin"

    p_low = pitanje_norm.lower()
    bi = _bolnica_info_intent(p_low)
    if bi:
        return bi

    if intent not in ("general",):
        return intent

    from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
    from ai.pacient.slobodni_termini import (
        baranje_e_zakazuvanje,
        lekar_od_zakazi_kontekst,
        prasanje_e_specijalnost_izbran_lekar,
    )

    if not _prasanje_e_konkreten_lekar(pitanje_norm):
        return intent

    lekar = lekar_od_zakazi_kontekst(aktiven_kontekst)
    if not lekar:
        lekar = najdi_lekar_od_prasanje(pitanje_norm)
    if not lekar:
        return intent

    if baranje_e_zakazuvanje(pitanje_norm):
        return "zakazi_termin"

    q = pitanje_norm.lower()
    if prasanje_e_specijalnost_izbran_lekar(pitanje_norm, aktiven_kontekst):
        return "info_lekar"
    if any(
        w in q
        for w in (
            "слобод",
            "термин",
            "кога",
            "има ли",
            "slobod",
            "termin",
            "koga",
        )
    ):
        return "slobodni_termini"
    return "info_lekar"


def _resolve_intent(
    pitanje_norm: str,
    aktiven_kontekst: dict | None,
    pacient_dict: dict | None,
    lekar_dict: dict | None,
) -> str:
    if aktiven_kontekst and aktiven_kontekst.get("intent") == "apliciraj_za_rabota":
        return "apliciraj_za_rabota"

    from ai.pacient.slobodni_termini import prasanje_e_otkazuvanje

    if prasanje_e_otkazuvanje(pitanje_norm):
        return "otkazi_termin"

    if isinstance(aktiven_kontekst, dict) and aktiven_kontekst.get("last_oddel"):
        q = pitanje_norm.lower()
        if any(x in q for x in ("женск", "машк", "zensk", "maski")) or any(
            x in q
            for x in (
                "овој дел",
                "овој одел",
                "овој оддел",
                "истиот",
                "таму",
                "овде",
                "а женски",
                "а машки",
            )
        ):
            return "preference_lekar"

    dk = (
        aktiven_kontekst.get("dezurstvo_kontekst")
        if isinstance(aktiven_kontekst, dict)
        else None
    )
    if dk:
        q = pitanje_norm.lower()
        if any(
            w in q
            for w in (
                "промени",
                "промениш",
                "премести",
                "префрли",
                "смени",
                "додади",
                "dodadi",
                "иста дата",
                "истиот датум",
                "до ",
                "do ",
            )
        ) or re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
            return "promeni_dezurstvo"
    try:
        intent = detektiraj_intent(pitanje_norm)
    except Exception as e:
        print(f"[ai_chat] intent detection error: {e}")
        intent = "general"

    if intent == "moj_raspored" and pacient_dict and not lekar_dict:
        intent = "moi_pregledi"

    # Лекар: „Прегледи за …“ / закажани прегледи → панел (не patient-only handler)
    if intent == "moi_pregledi" and lekar_dict and lekar_dict.get("doctor_ID"):
        intent = "moj_raspored"
    else:
        try:
            from ai.lekar.lekar_intent import prasanje_e_moj_raspored_lekar

            if intent == "moi_pregledi" and prasanje_e_moj_raspored_lekar(pitanje_norm):
                intent = "moj_raspored"
        except ImportError:
            pass

    from ai.pacient.slobodni_termini import (
        baranje_e_zakazuvanje,
        datum_od_prasanje_lokalno,
        datum_od_zakazi_kontekst,
        prasanje_bar_datum_od_kontekst,
        prasanje_bar_lekar_od_kontekst,
        prasanje_e_drugi_lekari_specijalnost,
        prasanje_e_sleden_raboten_den,
        prasanje_e_specijalnost_izbran_lekar,
    )

    if prasanje_e_drugi_lekari_specijalnost(pitanje_norm):
        return "lekari_oddel"

    has_lekar_kontekst = isinstance(aktiven_kontekst, dict) and (
        aktiven_kontekst.get("zakazi_od_slobodni")
        or aktiven_kontekst.get("zakazi_pending")
        or aktiven_kontekst.get("last_doctor_id")
    )
    if has_lekar_kontekst and prasanje_e_specijalnost_izbran_lekar(
        pitanje_norm, aktiven_kontekst
    ):
        return "info_lekar"

    has_zakazi_flow = bool(
        aktiven_kontekst
        and (
            aktiven_kontekst.get("zakazi_od_slobodni")
            or aktiven_kontekst.get("zakazi_pending")
            or aktiven_kontekst.get("zakazi_ceka_napomena")
        )
    )
    if has_zakazi_flow:
        if aktiven_kontekst.get("zakazi_ceka_napomena"):
            return "zakazi_termin"
        q = pitanje_norm.lower()
        if prasanje_e_otkazuvanje(pitanje_norm):
            return "otkazi_termin"
        # „кој е слободен … во 13:30“ — секогаш слободни термини, не закажување
        from ai.pacient.slobodni_termini import prasanje_e_ko_e_sloboden_datum_vreme

        ima_ko_prasanje = bool(re.search(r"\b(кој|која|кои|koj|koja|koi)\b", q, re.UNICODE))
        ima_slobod = "слобод" in q or "slobod" in q
        ima_provera = any(w in q for w in ("провери", "провер", "има ли", "кога"))
        if (
            ima_ko_prasanje and (ima_slobod or ima_provera)
        ) or prasanje_e_ko_e_sloboden_datum_vreme(pitanje_norm, aktiven_kontekst):
            return "slobodni_termini"
        if baranje_e_zakazuvanje(pitanje_norm):
            return "zakazi_termin"
        if prasanje_bar_datum_od_kontekst(pitanje_norm) and datum_od_zakazi_kontekst(
            aktiven_kontekst
        ):
            return "zakazi_termin"
        if prasanje_e_sleden_raboten_den(pitanje_norm):
            return "slobodni_termini"
        if prasanje_e_specijalnost_izbran_lekar(pitanje_norm, aktiven_kontekst):
            return "info_lekar"
        if any(
            x in q
            for x in (
                "избран",
                "избраниот",
                "истиот",
                "погоре",
                "од листата",
                "од горе",
            )
        ) and not baranje_e_zakazuvanje(pitanje_norm):
            return "slobodni_termini"
        if prasanje_bar_lekar_od_kontekst(pitanje_norm) and not baranje_e_zakazuvanje(
            pitanje_norm
        ):
            return "slobodni_termini"
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
        elif intent in ("general", "zakazi_termin") and not baranje_e_zakazuvanje(
            pitanje_norm
        ):
            if datum_od_prasanje_lokalno(pitanje_norm) or any(
                w in q
                for w in (
                    "провери",
                    "провер",
                    "слобод",
                    "термин",
                    "има ли",
                    "кога",
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
            ) or (
                "може" in q
                and not any(x in q for x in ("закаж", "zakaz", "преглед"))
            ):
                intent = "slobodni_termini"

    return _intent_strukturiran_za_lekar(pitanje_norm, aktiven_kontekst, intent)


@router.post("/sessions/import-guest")
def import_guest_chat(data: GuestImportModel):
    """
    По најава: пренеси гостински разговор во нова DB сесија за најавениот корисник.
    """
    pacient_dict = _pacient_dict(data.pacient)
    lekar_dict = _lekar_dict(data.lekar)
    pacient_id, doctor_id = _owner_ids(pacient_dict, lekar_dict)
    if not pacient_id and not doctor_id:
        raise HTTPException(status_code=400, detail="Потребен е најавен пациент или лекар.")

    msgs = []
    for m in data.messages or []:
        sodrzina = (m.sodrzina or "").strip()
        if not sodrzina:
            continue
        uloga = (m.uloga or "user").lower()
        if uloga not in ("user", "assistant"):
            uloga = "user"
        msgs.append({"uloga": uloga, "sodrzina": sodrzina})
    sid = import_guest_session(
        pacient_id=pacient_id,
        doctor_id=doctor_id,
        messages=msgs,
        kontekst=data.kontekst if isinstance(data.kontekst, dict) else None,
    )
    if not sid:
        raise HTTPException(status_code=500, detail="Не успеав да ја зачувам сесијата.")

    return {
        "session_id": sid,
        "kontekst": data.kontekst,
        "imported": len(msgs),
    }


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


@router.delete("/sessions/{session_id}")
def delete_chat_session(
    session_id: int,
    pacient_id: int | None = Query(None),
    doctor_id: int | None = Query(None),
):
    """Опционално бришење на зачуван разговор (само сопственик)."""
    if not pacient_id and not doctor_id:
        raise HTTPException(status_code=400, detail="Потребен е pacient_id или doctor_id.")
    if not delete_session(session_id, pacient_id=pacient_id, doctor_id=doctor_id):
        raise HTTPException(status_code=404, detail="Разговорот не е пронајден.")
    return {"ok": True, "session_id": session_id}


@router.post("/ask")
def ask(data: PitanjeModel):
    pitanje = (data.prasanje or "").strip()
    if not pitanje:
        return {"odgovor": "Те молам внеси прашање."}
    if len(pitanje) > MAX_PRASANJE_LEN:
        return {"odgovor": f"Пораката е предолга (макс. {MAX_PRASANJE_LEN} знаци)."}

    pitanje_norm = normaliziraj_prasanje(pitanje)
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
