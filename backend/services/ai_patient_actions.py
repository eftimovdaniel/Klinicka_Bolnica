import re
from datetime import datetime, timedelta


def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


def _extract_iso_date(prompt_text: str) -> str:
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(prompt_text or ""))
    return m.group(1) if m else ""


def _extract_relative_or_iso_date(prompt_text: str, fallback_iso: str = "") -> str:
    text = _mk_lower(prompt_text)
    today = datetime.now().date()
    if "задутре" in text:
        return (today + timedelta(days=2)).isoformat()
    if "утре" in text:
        return (today + timedelta(days=1)).isoformat()
    if "денес" in text:
        return today.isoformat()
    return _extract_iso_date(prompt_text) or fallback_iso


def _extract_time(prompt_text: str) -> str:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", str(prompt_text or ""))
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _patient_email_key(pacient: dict) -> str:
    return _mk_lower((pacient or {}).get("email", ""))


def _load_upcoming_appointments(db_cursor, patient_email: str):
    db_cursor.execute(
        """
        SELECT
            termin_ID,
            DATE_FORMAT(datum_pregled, '%%Y-%%m-%%d') AS datum,
            TIME_FORMAT(vreme_pregled, '%%H:%%i') AS vreme,
            ime_lekar,
            status_pregled,
            doctor_ID,
            napomena
        FROM Termin_pregled
        WHERE LOWER(TRIM(email_pacient)) = %s
          AND status_pregled = 'закажан'
          AND datum_pregled >= CURDATE()
        ORDER BY datum_pregled ASC, vreme_pregled ASC
        """,
        (patient_email,),
    )
    return db_cursor.fetchall() or []


def _format_appointments(items):
    if not items:
        return "Немате закажани идни термини."
    lines = ["Ваши идни термини се:"]
    for i, row in enumerate(items[:7], start=1):
        lines.append(
            f"{i}. {row.get('datum')} во {row.get('vreme')} кај {row.get('ime_lekar')}"
        )
    return "\n".join(lines)


def _find_target_appointment(items, prompt: str, ai_out: dict):
    if not items:
        return None
    desired_date = (ai_out or {}).get("date") or _extract_relative_or_iso_date(prompt)
    desired_time = (ai_out or {}).get("time") or _extract_time(prompt)

    if desired_date and desired_time:
        for row in items:
            if row.get("datum") == desired_date and row.get("vreme") == desired_time:
                return row

    if desired_date and not desired_time:
        for row in items:
            if row.get("datum") == desired_date:
                return row

    # fallback: "следен/прв термин" или општо барање -> прв идeн
    return items[0]


def handle_patient_action(intent: str, db_cursor, conn, prompt: str, pacient: dict, state: dict, ai_out: dict):
    patient_email = _patient_email_key(pacient)
    if not patient_email:
        return {
            "ok": False,
            "intent": intent,
            "message": "Недостига е-пошта за пациентот. Најавете се повторно.",
            "state": state,
        }

    if intent == "patient_list_appointments":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        return {
            "ok": True,
            "intent": intent,
            "message": _format_appointments(items),
            "state": state,
        }

    if intent == "patient_cancel_appointment":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        target = _find_target_appointment(items, prompt, ai_out)
        if not target:
            return {
                "ok": False,
                "intent": intent,
                "message": "Немате термин за откажување.",
                "state": state,
            }
        db_cursor.execute(
            "UPDATE Termin_pregled SET status_pregled = 'откажан' WHERE termin_ID = %s",
            (int(target["termin_ID"]),),
        )
        conn.commit()
        return {
            "ok": True,
            "intent": intent,
            "message": (
                f"Терминот на {target.get('datum')} во {target.get('vreme')} кај {target.get('ime_lekar')} е откажан."
            ),
            "state": state,
        }

    if intent == "patient_reschedule_appointment":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        target = _find_target_appointment(items, prompt, ai_out)
        if not target:
            return {
                "ok": False,
                "intent": intent,
                "message": "Немате термин за промена.",
                "state": state,
            }

        # нов термин (датум/време) од текстот
        new_date = (ai_out or {}).get("date") or _extract_relative_or_iso_date(prompt)
        new_time = (ai_out or {}).get("time") or _extract_time(prompt)
        if not new_date or not new_time:
            return {
                "ok": False,
                "intent": intent,
                "message": "За промена на термин наведете нов датум и време (на пр. 2026-05-12 во 13:00).",
                "state": state,
            }

        if new_date == target.get("datum") and new_time == target.get("vreme"):
            return {
                "ok": False,
                "intent": intent,
                "message": "Новиот термин е ист како постоечкиот. Наведете друго време.",
                "state": state,
            }

        db_cursor.execute(
            """
            SELECT termin_ID
            FROM Termin_pregled
            WHERE doctor_ID = %s
              AND DATE(datum_pregled) = %s
              AND TIME(vreme_pregled) = %s
              AND status_pregled = 'закажан'
              AND termin_ID <> %s
            """,
            (int(target["doctor_ID"]), new_date, new_time, int(target["termin_ID"])),
        )
        if db_cursor.fetchone():
            return {
                "ok": False,
                "intent": intent,
                "message": f"Бараниот нов термин ({new_date} во {new_time}) е веќе зафатен.",
                "state": state,
            }

        db_cursor.execute(
            """
            UPDATE Termin_pregled
            SET datum_pregled = %s, vreme_pregled = %s
            WHERE termin_ID = %s
            """,
            (new_date, new_time, int(target["termin_ID"])),
        )
        conn.commit()
        return {
            "ok": True,
            "intent": intent,
            "message": (
                f"Терминот е успешно променет: {target.get('datum')} {target.get('vreme')} -> {new_date} {new_time}."
            ),
            "state": state,
        }

    if intent == "patient_set_reminder":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        target = _find_target_appointment(items, prompt, ai_out)
        if not target:
            return {
                "ok": False,
                "intent": intent,
                "message": "Немате термин за кој може да поставиме потсетник.",
                "state": state,
            }
        return {
            "ok": True,
            "intent": intent,
            "message": (
                f"Поставен е потсетник за терминот на {target.get('datum')} во {target.get('vreme')} кај {target.get('ime_lekar')}."
            ),
            "state": state,
        }

    return None
