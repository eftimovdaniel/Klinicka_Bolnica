import re
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from database import get_connection

router = APIRouter(prefix="/ai-agent", tags=["ai-agent"])


def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


def _extract_iso_date(prompt_text: str) -> str:
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(prompt_text or ""))
    return m.group(1) if m else ""


def _extract_time(prompt_text: str) -> str:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", str(prompt_text or ""))
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _extract_note(prompt_text: str) -> str:
    text = str(prompt_text or "")
    idx = _mk_lower(text).find("напомена")
    if idx < 0:
        return ""
    return re.sub(r"^[:\s-]+", "", text[idx + len("напомена"):]).strip()


def _detect_intent(prompt_text: str) -> str:
    text = _mk_lower(prompt_text)
    if "закаж" in text:
        return "book"
    if "слобод" in text or "достап" in text or "провери" in text:
        return "availability"
    return ""


def _list_busy_times(db_cursor, doctor_id: int, date_iso: str):
    db_cursor.execute(
        """
        SELECT TIME(vreme_pregled) AS vreme
        FROM Termin_pregled
        WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status_pregled = 'закажан'
        UNION
        SELECT TIME(vreme_pregled) AS vreme
        FROM Aparati_termini
        WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status != 'откажан'
        """,
        (doctor_id, date_iso, doctor_id, date_iso),
    )
    rows = db_cursor.fetchall() or []
    out = set()
    for r in rows:
        v = r.get("vreme")
        if v is None:
            continue
        if hasattr(v, "strftime"):
            out.add(v.strftime("%H:%M"))
        elif hasattr(v, "total_seconds"):
            s = int(v.total_seconds())
            out.add(f"{s // 3600:02d}:{(s % 3600) // 60:02d}")
        else:
            out.add(str(v)[:5])
    return out


def _build_workday_slots():
    slots = []
    for h in range(9, 17):
        slots.append(f"{h:02d}:00")
        slots.append(f"{h:02d}:30")
    return slots


@router.post("/termini")
async def ai_agent_termini(request: Request):
    conn = None
    try:
        data = await request.json()
        prompt = (data.get("prompt") or "").strip()
        pacient = data.get("pacient") or {}
        state = data.get("state") or {}

        if not prompt:
            raise HTTPException(status_code=400, detail="Недостига prompt.")
        if not pacient:
            raise HTTPException(status_code=400, detail="Недостигаат податоци за пациент.")

        intent = _detect_intent(prompt)
        if not intent:
            return {
                "ok": False,
                "message": "Не го разбрав барањето. Напишете „провери слободни термини...“ или „закажи ми...“.",
                "state": state,
            }

        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)

        prompt_l = _mk_lower(prompt)
        db_cursor.execute("SELECT doctor_ID, name, surname, specialty, email FROM Doctors")
        doctors = db_cursor.fetchall() or []

        selected_doctor = None
        for d in doctors:
            full = _mk_lower(f"{d.get('name', '')} {d.get('surname', '')}")
            if full and full in prompt_l:
                selected_doctor = d
                break

        if not selected_doctor and state.get("doctor_id"):
            for d in doctors:
                if int(d.get("doctor_ID") or 0) == int(state.get("doctor_id")):
                    selected_doctor = d
                    break

        date_iso = _extract_iso_date(prompt) or (state.get("date") or "")
        if not selected_doctor:
            return {"ok": False, "message": "Не најдов лекар во промптот. Напишете име и презиме на лекарот.", "state": state}
        if not date_iso:
            return {"ok": False, "message": "Недостига датум во формат YYYY-MM-DD.", "state": state}

        try:
            d = datetime.strptime(date_iso, "%Y-%m-%d").date()
            if d.weekday() >= 5:
                return {"ok": False, "message": "Не се закажуваат прегледи во сабота и недела.", "state": state}
        except ValueError:
            return {"ok": False, "message": "Неважечки датум. Користете YYYY-MM-DD.", "state": state}

        busy = _list_busy_times(db_cursor, int(selected_doctor["doctor_ID"]), date_iso)
        all_slots = _build_workday_slots()
        free_slots = [s for s in all_slots if s not in busy]

        new_state = {
            "doctor_id": int(selected_doctor["doctor_ID"]),
            "doctor_name": f"{selected_doctor.get('name', '')} {selected_doctor.get('surname', '')}".strip(),
            "date": date_iso,
            "free_slots": free_slots,
        }

        if intent == "availability":
            if free_slots:
                return {
                    "ok": True,
                    "intent": "availability",
                    "message": (
                        f"Слободни термини кај Д-р {new_state['doctor_name']} на {date_iso}:\n"
                        f"{', '.join(free_slots)}\n\n"
                        f'Закажување пример: "Закажи ми на {date_iso} во {free_slots[0]} со напомена контрола".'
                    ),
                    "state": new_state,
                }
            return {
                "ok": True,
                "intent": "availability",
                "message": f"Нема слободни термини кај Д-р {new_state['doctor_name']} на {date_iso}.",
                "state": new_state,
            }

        time_hhmm = _extract_time(prompt)
        note = _extract_note(prompt)
        if not time_hhmm:
            return {"ok": False, "message": "Недостига време (на пр. 10:30).", "state": new_state}
        if time_hhmm in busy:
            return {
                "ok": False,
                "message": f"Терминот {date_iso} во {time_hhmm} е веќе зафатен. Побарајте нова проверка на слободни термини.",
                "state": new_state,
            }

        patient_name = (pacient.get("ime") or "").strip()
        patient_surname = (pacient.get("prezime") or "").strip()
        patient_email = (pacient.get("email") or "").strip()
        patient_phone = (pacient.get("telefon") or "").strip()
        if not patient_name or not patient_surname or not patient_email:
            raise HTTPException(status_code=400, detail="Недостигаат задолжителни податоци за најавениот пациент.")

        db_cursor.execute(
            """
            INSERT INTO Termin_pregled
            (doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, datum_pregled, vreme_pregled, status_pregled, email_pacient, telefon_pacient, napomena)
            VALUES (%s, %s, %s, %s, %s, %s, 'закажан', %s, %s, %s)
            """,
            (
                int(selected_doctor["doctor_ID"]),
                f"{patient_name} {patient_surname}".strip(),
                selected_doctor.get("specialty") or "",
                new_state["doctor_name"],
                date_iso,
                time_hhmm,
                patient_email,
                patient_phone,
                note,
            ),
        )
        conn.commit()

        return {
            "ok": True,
            "intent": "book",
            "message": (
                f"Успешно закажан термин кај Д-р {new_state['doctor_name']} на {date_iso} во {time_hhmm}."
                + (f"\nНапомена: {note}" if note else "")
            ),
            "state": new_state,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()
