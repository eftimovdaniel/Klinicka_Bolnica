import re
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from database import get_connection
from routers.admin import check_admin_access
from services.ai_doctor_actions import handle_doctor_action
from services.ai_news_actions import handle_news_intent
from services.ai_parser import parse_prompt
from services.ai_patient_actions import handle_patient_action
from services.doctor_brief_service import (
    get_today_brief_for_doctor,
    mark_brief_as_read,
    run_doctor_briefs,
)

router = APIRouter(prefix="/ai-agent", tags=["ai-agent"])
PATIENT_ACTION_INTENTS = {
    "patient_list_appointments",
    "patient_cancel_appointment",
    "patient_reschedule_appointment",
    "patient_set_reminder",
    "patient_action_confirm",
}
DOCTOR_ACTION_INTENTS = {
    "doctor_today_schedule",
    "doctor_next_patient",
    "doctor_delayed_patients",
    "doctor_patients_overview",
}


def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


def _izvadi_iso_datum(prompt_text: str) -> str:
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(prompt_text or ""))
    return m.group(1) if m else ""


def _izvadi_relativen_ili_iso_datum(prompt_text: str, fallback_iso: str = "") -> str:
    text = _mk_lower(prompt_text)
    today = datetime.now().date()
    if "задутре" in text:
        return (today + timedelta(days=2)).isoformat()
    if "утре" in text:
        return (today + timedelta(days=1)).isoformat()
    if "денес" in text:
        return today.isoformat()
    return _izvadi_iso_datum(prompt_text) or fallback_iso


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


def _contains_any(text: str, needles) -> bool:
    t = _mk_lower(text)
    return any(n in t for n in needles)


def _detect_intent(prompt_text: str) -> str:
    text = _mk_lower(prompt_text)
    if _contains_any(text, ["да, потврди", "да потврди", "потврди", "во ред", "ok"]):
        return "patient_action_confirm"
    if _contains_any(text, ["кој лекар", "кои лекари"]) and _contains_any(text, ["кои пациенти", "пациенти ги има", "има пациенти"]):
        return "doctor_patients_overview"
    if _contains_any(text, ["кои пациенти ги имам денес", "распоред денес", "денешни пациенти", "листа за денес"]):
        return "doctor_today_schedule"
    if _contains_any(text, ["кој е следен", "следен пациент", "next patient"]):
        return "doctor_next_patient"
    if _contains_any(text, ["кој доцни", "кои доцнат", "доцнење", "delayed patients"]):
        return "doctor_delayed_patients"
    if _contains_any(text, ["најнови информации", "што е ново", "новости", "нови вести"]) and _contains_any(text, ["болница", "пациент", "пациенти"]):
        return "hospital_updates"
    asks_people = _contains_any(text, ["кој", "кои", "каков состав", "листа"])
    mentions_doctors = _contains_any(text, ["лекар", "доктор", "уролог", "кардиолог", "радиолог", "педијатар", "хирург"])
    mentions_department = _contains_any(text, ["оддел", "служб", "специјалност", "област", "тим"])
    if asks_people and (mentions_doctors or mentions_department):
        return "department_doctors"
    if _contains_any(text, ["да, објави", "да објави", "објави веднаш"]) or text.strip() == "објави":
        return "news_publish_confirm"
    if _contains_any(text, ["објави", "вести", "вест", "новост", "додади новост", "објава"]):
        return "news_publish_preview"
    if _contains_any(text, ["апарат", "опрема", "уред"]) and _contains_any(text, ["оддел", "област", "служб", "специјалност"]):
        return "department_equipment"
    if mentions_doctors and _contains_any(text, ["недела", "оваа недела", "во неделава", "седмица"]):
        return "specialty_week_availability"
    if _contains_any(text, ["мои термини", "моите термини", "мој термин", "моите закажани"]):
        return "patient_list_appointments"
    if _contains_any(text, ["откажи", "поништи термин", "избриши термин"]):
        return "patient_cancel_appointment"
    if _contains_any(text, ["промени термин", "премести термин", "презакажи"]):
        return "patient_reschedule_appointment"
    if _contains_any(text, ["потсетник", "потсети ме", "подсети ме"]):
        return "patient_set_reminder"
    if _contains_any(text, ["закаж", "резерв", "термин во"]):
        return "book"
    if _contains_any(text, ["слобод", "достап", "провери", "има ли", "кога има"]):
        return "availability"
    return ""


def _normalize_intent(value: str) -> str:
    v = _mk_lower(value)
    if v in (
        "availability",
        "book",
        "specialty_week_availability",
        "department_equipment",
        "department_doctors",
        "hospital_updates",
        "news_publish_preview",
        "news_publish_confirm",
        "patient_list_appointments",
        "patient_cancel_appointment",
        "patient_reschedule_appointment",
        "patient_set_reminder",
        "patient_action_confirm",
        "doctor_today_schedule",
        "doctor_next_patient",
        "doctor_delayed_patients",
        "doctor_patients_overview",
    ):
        return v
    if "publish" in v and "confirm" in v:
        return "news_publish_confirm"
    if "publish" in v or "news" in v:
        return "news_publish_preview"
    if "aparat" in v or "equipment" in v:
        return "department_equipment"
    if "doctor" in v and "department" in v:
        return "department_doctors"
    if "specialty" in v and "week" in v:
        return "specialty_week_availability"
    if "update" in v or ("news" in v and "hospital" in v):
        return "hospital_updates"
    if "закаж" in v:
        return "book"
    if "cancel" in v:
        return "patient_cancel_appointment"
    if "reschedule" in v or "change appointment" in v:
        return "patient_reschedule_appointment"
    if "my appointment" in v or "list appointment" in v:
        return "patient_list_appointments"
    if "reminder" in v:
        return "patient_set_reminder"
    if "confirm" in v:
        return "patient_action_confirm"
    if "doctor" in v and "today" in v:
        return "doctor_today_schedule"
    if "next" in v and "patient" in v:
        return "doctor_next_patient"
    if "delay" in v and "patient" in v:
        return "doctor_delayed_patients"
    if "doctor" in v and "patient" in v:
        return "doctor_patients_overview"
    if "слобод" in v or "достап" in v or "провери" in v:
        return "availability"
    return ""

# tuka se gleda dali i koj termini se slobodni 
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
    # se zimat site redovi so se free ako ima, onala se vraka [prazna lista]
    rows = db_cursor.fetchall() or []
    out = set()
    for r in rows:
        # tuka se gledaat slobodnite vreminja
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
    return [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)]


def _format_mk_date(date_iso: str) -> str:
    try:
        parsed = datetime.strptime(date_iso, "%Y-%m-%d").date()
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return date_iso


def _find_selected_doctor(doctors, prompt_l: str, parsed_doctor_name: str, state):
    selected_doctor = None
    cleaned_prompt = re.sub(r"\b(д-р|dr\.?|doctor)\b", " ", prompt_l)
    cleaned_prompt = re.sub(r"\s+", " ", cleaned_prompt).strip()
    cleaned_parsed = re.sub(r"\b(д-р|dr\.?|doctor)\b", " ", parsed_doctor_name)
    cleaned_parsed = re.sub(r"\s+", " ", cleaned_parsed).strip()

    for d in doctors:
        name = _mk_lower(d.get("name", ""))
        surname = _mk_lower(d.get("surname", ""))
        full = _mk_lower(f"{name} {surname}")
        if not full:
            continue
        if (
            full in prompt_l
            or full in cleaned_prompt
            or (cleaned_parsed and full in cleaned_parsed)
            or (surname and surname in cleaned_prompt)
            or (surname and cleaned_parsed and surname in cleaned_parsed)
        ):
            selected_doctor = d
            break

    if not selected_doctor and state.get("doctor_id"):
        for d in doctors:
            if int(d.get("doctor_ID") or 0) == int(state.get("doctor_id")):
                selected_doctor = d
                break

    return selected_doctor


def _extract_specialty(prompt_text: str, state):
    text = _mk_lower(prompt_text)
    if _contains_any(text, ["кардиолог", "кардио"]):
        return "Кардиологија"
    if _contains_any(text, ["радиолог", "радио оддел"]):
        return "Радиологија"
    if _contains_any(text, ["педијатр", "детски"]):
        return "Педијатрија"
    if _contains_any(text, ["хирург", "хирурш", "оператив"]):
        return "Хирургија"
    if _contains_any(text, ["уролог", "уролош", "уро"]):
        return "Урологија"
    if _contains_any(text, ["интерна", "внатрешни болести"]):
        return "Интерна медицина"
    if "овој оддел" in text and state.get("specialty"):
        return state.get("specialty")
    return state.get("specialty", "")


def _resp(message: str, state: dict, *, ok: bool = True, intent: str = "", **extra):
    payload = {"ok": ok, "message": message, "state": state}
    if intent:
        payload["intent"] = intent
    if extra:
        payload.update(extra)
    return payload


def _ensure_specialty_or_error(specialty: str, intent: str, state: dict, message: str):
    if specialty:
        return None
    return _resp(message, state, ok=False, intent=intent)


def _build_doctor_state(selected_doctor: dict, date_iso: str, free_slots):
    return {
        "doctor_id": int(selected_doctor["doctor_ID"]),
        "doctor_name": f"{selected_doctor.get('name', '')} {selected_doctor.get('surname', '')}".strip(),
        "date": date_iso,
        "free_slots": free_slots,
    }


def _doctors_by_specialty(doctors, specialty: str):
    s = _mk_lower(specialty)
    return [d for d in doctors if s in _mk_lower(d.get("specialty", ""))]


def _validate_workday_date(date_iso: str):
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        return False, "Неважечки датум. Користете YYYY-MM-DD."
    if d.weekday() >= 5:
        return False, "Не се закажуваат прегледи во сабота и недела."
    return True, ""


def _mk_weekday_name_mk(day_date):
    names = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]
    return names[day_date.weekday()]


def _remaining_weekdays():
    today = datetime.now().date()
    out = []
    for i in range(7):
        d = today + timedelta(days=i)
        if d.weekday() < 5:
            out.append(d)
    return out


# API за барања преку AI асистент.
# Ново (македонски): /ai-agent/baranja
# Алијас за постоечки клиенти: /ai-agent/termini
@router.post("/baranja")
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

        ai_out = parse_prompt(prompt)
        intent = _normalize_intent((ai_out or {}).get("intent", "")) or _detect_intent(prompt)
        if not intent:
            return _resp(
                "Не го разбрав барањето. Напишете „провери слободни термини...“ или „закажи ми...“.",
                state,
                ok=False,
            )

        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)

        if intent in PATIENT_ACTION_INTENTS:
            patient_resp = handle_patient_action(intent, db_cursor, conn, prompt, pacient, state, ai_out or {})
            if patient_resp is not None:
                return patient_resp

        if intent in DOCTOR_ACTION_INTENTS:
            doctor_resp = handle_doctor_action(intent, db_cursor, prompt, pacient, state)
            if doctor_resp is not None:
                return doctor_resp

        if intent == "hospital_updates":
            try:
                db_cursor.execute(
                    """
                    SELECT id, naslov, created_at
                    FROM Novosti
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                )
                latest_news = db_cursor.fetchall() or []
            except Exception:
                latest_news = []

            patient_count = None
            try:
                db_cursor.execute("SELECT COUNT(*) AS vkupno FROM Pacienti")
                row = db_cursor.fetchone() or {}
                patient_count = int(row.get("vkupno") or 0)
            except Exception:
                patient_count = None

            if latest_news:
                lines = ["Најнови информации од болницата:"]
                for n in latest_news:
                    title = (n.get("naslov") or "Без наслов").strip()
                    lines.append(f"- {title}")
            else:
                lines = ["Во моментов нема објавени новости во системот."]

            if patient_count is not None:
                lines.append(f"\nЕвидентирани пациенти во системот: {patient_count}.")

            lines.append("Дали сакате да ви прикажам детали за конкретна вест?")
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": state,
            }

        news_resp = handle_news_intent(intent, prompt, pacient, state)
        if news_resp is not None:
            return news_resp

        prompt_l = _mk_lower(prompt)
        parsed_doctor_name = _mk_lower((ai_out or {}).get("doctor_name", ""))
        db_cursor.execute("SELECT doctor_ID, name, surname, specialty, email FROM Doctors")
        doctors = db_cursor.fetchall() or []

        selected_doctor = _find_selected_doctor(doctors, prompt_l, parsed_doctor_name, state)
        specialty = _extract_specialty(prompt, state)

        if not pacient:
            raise HTTPException(status_code=400, detail="Недостигаат податоци за пациент.")

        if intent == "department_doctors":
            err_resp = _ensure_specialty_or_error(
                specialty, intent, state, "Не ја препознав специјалноста. Наведете оддел (на пр. Урологија)."
            )
            if err_resp:
                return err_resp

            department_doctors = _doctors_by_specialty(doctors, specialty)
            if not department_doctors:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Во моментов нема евидентирани лекари за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            doctor_lines = [f"- Д-р {d.get('name', '')} {d.get('surname', '')}".strip() for d in department_doctors]
            return {
                "ok": True,
                "intent": intent,
                "message": (
                    f"На одделот за {specialty.lower()} работат:\n"
                    + "\n".join(doctor_lines)
                    + "\n\nДали сакате да проверам слободни термини кај некој од нив?"
                ),
                "state": {"specialty": specialty},
            }

        if intent == "specialty_week_availability":
            err_resp = _ensure_specialty_or_error(
                specialty, intent, state, "Не ја препознав областа. Наведете специјалност (на пр. кардиологија)."
            )
            if err_resp:
                return err_resp

            specialty_doctors = _doctors_by_specialty(doctors, specialty)
            if not specialty_doctors:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": f"Нема пронајдени лекари за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            weekday_dates = _remaining_weekdays()
            availability_rows = []
            for doc in specialty_doctors:
                doctor_id = int(doc["doctor_ID"])
                first_available_day = None
                for day_date in weekday_dates:
                    day_iso = day_date.isoformat()
                    busy = _list_busy_times(db_cursor, doctor_id, day_iso)
                    free_slots = [s for s in _build_workday_slots() if s not in busy]
                    if free_slots:
                        first_available_day = _mk_weekday_name_mk(day_date)
                        break
                if first_available_day:
                    availability_rows.append((doc, first_available_day))

            if not availability_rows:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Во моментов нема слободни термини оваа недела за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            lines = [
                f"Во моментов во Клиничка болница Штип, на одделот за {specialty.lower()}, достапни термини оваа недела имаат:"
            ]
            for doc, weekday_name in availability_rows[:6]:
                lines.append(f"- Д-р {doc.get('surname', '')} (достапен во {weekday_name})")
            lines.append("Дали сакате да проверам специфичен термин кај некој од нив?")
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": {"specialty": specialty},
            }

        if intent == "department_equipment":
            err_resp = _ensure_specialty_or_error(
                specialty, intent, state, "Не е јасно за кој оддел прашувате. Наведете специјалност (на пр. кардиологија)."
            )
            if err_resp:
                return err_resp

            db_cursor.execute(
                """
                SELECT DISTINCT a.ime, a.kod
                FROM Aparati a
                INNER JOIN Aparati_termini at ON at.aparat = a.kod
                INNER JOIN Doctors d ON d.doctor_ID = at.doctor_ID
                WHERE a.aktiven = 1
                  AND LOWER(d.specialty) = LOWER(%s)
                ORDER BY a.ime
                """,
                (specialty,),
            )
            filtered = db_cursor.fetchall() or []

            if not filtered:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Нема евидентирани апарати во база за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            names = ", ".join(a.get("ime", "") for a in filtered if a.get("ime"))
            return {
                "ok": True,
                "intent": intent,
                "message": f"Одделот за {specialty.lower()} располага со: {names}. Сите апарати се во функција.",
                "state": {"specialty": specialty},
            }

        date_iso = (
            (ai_out or {}).get("date")
            or _izvadi_relativen_ili_iso_datum(prompt)
            or (state.get("date") or "")
        )
        if not selected_doctor:
            return _resp("Не најдов лекар во промптот. Напишете име и презиме на лекарот.", state, ok=False)
        if not date_iso:
            return _resp("Недостига датум во формат YYYY-MM-DD.", state, ok=False)

        ok_date, date_err = _validate_workday_date(date_iso)
        if not ok_date:
            return _resp(date_err, state, ok=False)

        busy = _list_busy_times(db_cursor, int(selected_doctor["doctor_ID"]), date_iso)
        all_slots = _build_workday_slots()
        free_slots = [s for s in all_slots if s not in busy]

        new_state = _build_doctor_state(selected_doctor, date_iso, free_slots)

        if intent == "availability":
            if free_slots:
                date_view = _format_mk_date(date_iso)
                shown_slots = ", ".join(free_slots[:8])
                return {
                    "ok": True,
                    "intent": "availability",
                    "message": (
                        f"За {date_view} кај д-р {new_state['doctor_name']} има слободни термини: {shown_slots}. "
                        "Дали сакате да резервираме некое од овие времиња?"
                    ),
                    "state": new_state,
                }
            return {
                "ok": True,
                "intent": "availability",
                "message": f"Нема слободни термини кај Д-р {new_state['doctor_name']} на {date_iso}.",
                "state": new_state,
            }

        time_hhmm = (ai_out or {}).get("time") or _extract_time(prompt)
        note = (ai_out or {}).get("note") or _extract_note(prompt)
        if not time_hhmm:
            return _resp("Недостига време (на пр. 10:30).", new_state, ok=False)
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
                f"Готово, {patient_name}. Вашиот термин кај д-р {new_state['doctor_name']} е успешно закажан за {date_iso} во {time_hhmm}."
                + (f" Напомена: {note}." if note else "")
                + " Ќе добиете потврда и на вашата е-пошта."
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


# ============================================================================
# DOCTOR BRIEF ENDPOINTS
# ============================================================================

@router.get("/doctor-brief/{doctor_id}")
def api_get_doctor_brief(doctor_id: int):
    """Vrakame denesen brif za daden lekar (ako postoi).
    Frontendot mozhe da go povika koga lekarot ke se najavi.
    """
    try:
        brief = get_today_brief_for_doctor(int(doctor_id))
        if not brief:
            return {
                "ok": True,
                "has_brief": False,
                "message": "Сè уште нема генериран брифинг за денес. Ќе биде достапен по 08:00.",
            }
        # konvertirame date/datetime vo ISO string za JSON
        out = dict(brief)
        if hasattr(out.get("brief_date"), "isoformat"):
            out["brief_date"] = out["brief_date"].isoformat()
        if hasattr(out.get("kreiran_na"), "isoformat"):
            out["kreiran_na"] = out["kreiran_na"].isoformat()
        if out.get("procitan_na") and hasattr(out["procitan_na"], "isoformat"):
            out["procitan_na"] = out["procitan_na"].isoformat()
        return {"ok": True, "has_brief": True, "brief": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/doctor-brief/{brief_id}/read")
def api_mark_brief_read(brief_id: int):
    """Markira brif kako prochitan (frontend povikuva otkako lekarot ke go vidi)."""
    try:
        ok = mark_brief_as_read(int(brief_id))
        return {"ok": True, "updated": ok}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/doctor-briefs/run-now")
async def api_trigger_briefs_now(request: Request):
    """Manuelen triger za testiranje - generira brifovi za site lekari ODMA.
    Dostapno samo za admin (direktor).
    Body: {"admin_doctor_id": <int>}
    """
    try:
        data = await request.json()
        admin_doctor_id = int((data or {}).get("admin_doctor_id") or 0)
        if not admin_doctor_id or not check_admin_access(admin_doctor_id):
            raise HTTPException(status_code=403, detail="Само директорот може рачно да активира брифинзи.")
        stats = run_doctor_briefs()
        return {"ok": True, "stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
