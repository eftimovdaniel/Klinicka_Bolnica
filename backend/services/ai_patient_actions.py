import re
from datetime import datetime, timedelta

# default offset za potsetnik: 24 chasa pred terminot
DEFAULT_REMINDER_OFFSET_MINUTES = 24 * 60


def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


def _parse_reminder_offset_minutes(prompt: str) -> int:
    """Vlecuvajki broj na minuti pred terminot za potsetnik od korisnickiot tekst.
    Primeri: "1 chas pred", "30 minuti pred", "2 dena pred".
    Ako ne se spomenuva, vrakame default (24 chasa).
    """
    text = _mk_lower(prompt)
    # baranje na izrazi tipa "X chas/min/den pred"
    m = re.search(r"(\d{1,3})\s*(минут|мин|час|саат|саати|ден|дена)\s*(пред|before)?", text)
    if not m:
        # alternativna fraza "ден претходно", "час претходно"
        if "час претходно" in text or "саат претходно" in text:
            return 60
        if "ден претходно" in text:
            return 24 * 60
        return DEFAULT_REMINDER_OFFSET_MINUTES
    try:
        amount = int(m.group(1))
    except ValueError:
        return DEFAULT_REMINDER_OFFSET_MINUTES
    unit = m.group(2)
    # spored edinicata, presmetuvame minuti
    if unit.startswith("минут") or unit == "мин":
        return max(5, amount)
    if unit.startswith("час") or unit.startswith("саат"):
        return max(5, amount * 60)
    if unit.startswith("ден"):
        return max(5, amount * 24 * 60)
    return DEFAULT_REMINDER_OFFSET_MINUTES


def _format_offset_human(minutes: int) -> str:
    """Vrakame chovecki citliva forma (na pr. '1 chas', '30 minuti', '2 dena')."""
    if minutes < 60:
        return f"{minutes} минути"
    if minutes < 24 * 60:
        h = minutes // 60
        return f"{h} {'час' if h == 1 else 'часа'}"
    d = minutes // (24 * 60)
    return f"{d} {'ден' if d == 1 else 'дена'}"


def _compute_reminder_datetime(target_row: dict, offset_minutes: int) -> datetime | None:
    """Presmetka na konkreten DATETIME koga treba da se prati potsetnikot.
    Vrakame None ako vremeto bi bilo vo minato.
    """
    date_str = (target_row.get("datum") or "").strip()
    time_str = (target_row.get("vreme") or "").strip()
    if not date_str or not time_str:
        return None
    try:
        # spojuvanje na YYYY-MM-DD i HH:MM vo eden datetime objekt
        appointment_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    # oduzemame offsetot za da dobieme momentot na potsetuvanje
    reminder_dt = appointment_dt - timedelta(minutes=offset_minutes)
    # ako vremeto za potsetuvanje vekje pominalo, vrakame None
    if reminder_dt <= datetime.now():
        return None
    return reminder_dt


def _insert_reminder(db_cursor, conn, termin_id: int, email: str, telefon: str, reminder_dt: datetime, kanal: str = "email") -> int:
    """INSERT vo tabelata Potsetnici. Vrakame ID-to na noviot zapis."""
    db_cursor.execute(
        """
        INSERT INTO Potsetnici
            (termin_ID, email_pacient, telefon_pacient, vreme_potsetuvanje, kanal, status_potsetnik)
        VALUES
            (%s, %s, %s, %s, %s, 0)
        """,
        (
            int(termin_id),
            (email or "").strip().lower(),
            (telefon or "").strip() or None,
            reminder_dt.strftime("%Y-%m-%d %H:%M:%S"),
            (kanal or "email").strip().lower(),
        ),
    )
    conn.commit()
    return int(getattr(db_cursor, "lastrowid", 0) or 0)


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


def _copy_state(state: dict) -> dict:
    return dict(state or {})


def _is_confirmation(prompt: str) -> bool:
    t = _mk_lower(prompt)
    return any(k in t for k in ("да, потврди", "да потврди", "потврди", "ok", "во ред"))


def _is_abort(prompt: str) -> bool:
    t = _mk_lower(prompt)
    return any(k in t for k in ("откажи", "стоп", "не", "прекини"))


def _appointment_brief(row: dict) -> str:
    return f"{row.get('datum')} во {row.get('vreme')} кај {row.get('ime_lekar')}"


def _time_to_minutes(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _minutes_to_time(total: int) -> str:
    h = total // 60
    m = total % 60
    return f"{h:02d}:{m:02d}"


def _load_taken_times_for_doctor_date(db_cursor, doctor_id: int, date_iso: str):
    db_cursor.execute(
        """
        SELECT TIME_FORMAT(vreme_pregled, '%%H:%%i') AS vreme
        FROM Termin_pregled
        WHERE doctor_ID = %s
          AND DATE(datum_pregled) = %s
          AND status_pregled = 'закажан'
        """,
        (doctor_id, date_iso),
    )
    return {str((r or {}).get("vreme") or "").strip() for r in (db_cursor.fetchall() or [])}


def _suggest_alternative_times(db_cursor, doctor_id: int, date_iso: str, desired_time: str, limit: int = 3):
    start_min = 9 * 60
    end_min = 16 * 60 + 30
    taken = _load_taken_times_for_doctor_date(db_cursor, int(doctor_id), date_iso)
    desired_min = _time_to_minutes(desired_time or "00:00")
    candidates = []
    for minute in range(start_min, end_min + 1, 30):
        t = _minutes_to_time(minute)
        if t in taken:
            continue
        candidates.append(t)
    candidates.sort(key=lambda t: abs(_time_to_minutes(t) - desired_min))
    return candidates[:limit]


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


def _find_item_by_id(items, termin_id: int):
    for r in items:
        if int(r.get("termin_ID") or 0) == int(termin_id):
            return r
    return None


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
    new_state = _copy_state(state)
    patient_email = _patient_email_key(pacient)
    if not patient_email:
        return {
            "ok": False,
            "intent": intent,
            "message": "Недостига е-пошта за пациентот. Најавете се повторно.",
            "state": new_state,
        }

    pending = (new_state.get("pending_action") or {})
    if pending:
        if _is_abort(prompt):
            new_state.pop("pending_action", None)
            return {
                "ok": True,
                "intent": intent,
                "message": "Акцијата е откажана. Можете да внесете ново барање.",
                "state": new_state,
            }
        if pending.get("intent") == "patient_reschedule_appointment" and pending.get("awaiting_alternative_pick"):
            picked_time = _extract_time(prompt)
            if picked_time:
                pending["new_time"] = picked_time
                pending["awaiting_alternative_pick"] = False
                new_state["pending_action"] = pending
                return {
                    "ok": False,
                    "intent": "patient_reschedule_appointment",
                    "message": (
                        f"Избрано е ново време {picked_time} за {pending.get('new_date')}.\n"
                        "Потврдете со: „Да, потврди“."
                    ),
                    "state": new_state,
                }
            return {
                "ok": False,
                "intent": "patient_reschedule_appointment",
                "message": "Изберете едно од предложените времиња (пример: 14:00).",
                "state": new_state,
            }
        if _is_confirmation(prompt):
            items = _load_upcoming_appointments(db_cursor, patient_email)
            target = _find_item_by_id(items, int(pending.get("termin_id") or 0))
            if not target:
                new_state.pop("pending_action", None)
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Терминот веќе не е достапен. Побарајте нова листа на термини.",
                    "state": new_state,
                }

            p_intent = pending.get("intent")
            if p_intent == "patient_cancel_appointment":
                db_cursor.execute(
                    "UPDATE Termin_pregled SET status_pregled = 'откажан' WHERE termin_ID = %s",
                    (int(target["termin_ID"]),),
                )
                conn.commit()
                new_state.pop("pending_action", None)
                return {
                    "ok": True,
                    "intent": p_intent,
                    "message": f"Терминот {_appointment_brief(target)} е откажан.",
                    "state": new_state,
                }

            if p_intent == "patient_set_reminder":
                # vlecuvame parametri od pending_action: koga (offset) i kade (kanal)
                offset_minutes = int(pending.get("offset_minutes") or DEFAULT_REMINDER_OFFSET_MINUTES)
                kanal = (pending.get("kanal") or "email").strip().lower()
                # presmetka na momentot koga treba da se prati potsetnikot
                reminder_dt = _compute_reminder_datetime(target, offset_minutes)
                # ako vremeto vekje pominalo (pr. termin za 1 chas, a se bara potsetnik 24h pred)
                if not reminder_dt:
                    new_state.pop("pending_action", None)
                    return {
                        "ok": False,
                        "intent": p_intent,
                        "message": (
                            f"Не може да се постави потсетник {_format_offset_human(offset_minutes)} пред терминот "
                            f"({_appointment_brief(target)}) - тоа време веќе помина."
                        ),
                        "state": new_state,
                    }
                # realen INSERT vo bazata
                try:
                    reminder_id = _insert_reminder(
                        db_cursor,
                        conn,
                        termin_id=int(target["termin_ID"]),
                        email=(pacient or {}).get("email", ""),
                        telefon=(pacient or {}).get("telefon", "") or (pacient or {}).get("phone_number", ""),
                        reminder_dt=reminder_dt,
                        kanal=kanal,
                    )
                except Exception as e:
                    new_state.pop("pending_action", None)
                    return {
                        "ok": False,
                        "intent": p_intent,
                        "message": f"Грешка при зачувување на потсетникот: {e}",
                        "state": new_state,
                    }
                new_state.pop("pending_action", None)
                return {
                    "ok": True,
                    "intent": p_intent,
                    "reminder_id": reminder_id,
                    "message": (
                        f"Потсетникот е активен. Ќе ве известиме на {kanal} "
                        f"{_format_offset_human(offset_minutes)} пред терминот "
                        f"{_appointment_brief(target)} (точно во {reminder_dt.strftime('%d.%m.%Y во %H:%M')})."
                    ),
                    "state": new_state,
                }

            if p_intent == "patient_reschedule_appointment":
                new_date = (pending.get("new_date") or "").strip()
                new_time = (pending.get("new_time") or "").strip()
                if not new_date or not new_time:
                    new_state.pop("pending_action", None)
                    return {
                        "ok": False,
                        "intent": p_intent,
                        "message": "Недостигаат нови податоци за термин. Повторете ја промената.",
                        "state": new_state,
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
                    alternatives = _suggest_alternative_times(
                        db_cursor,
                        int(target["doctor_ID"]),
                        new_date,
                        new_time,
                        limit=3,
                    )
                    if alternatives:
                        pending["awaiting_alternative_pick"] = True
                        pending["suggested_times"] = alternatives
                        new_state["pending_action"] = pending
                        return {
                            "ok": False,
                            "intent": p_intent,
                            "message": (
                                f"Бараниот термин ({new_date} во {new_time}) е зафатен.\n"
                                f"Предлог алтернативи: {', '.join(alternatives)}.\n"
                                "Изберете едно време (на пр. 14:00), па потоа потврдете."
                            ),
                            "state": new_state,
                        }
                    new_state.pop("pending_action", None)
                    return {
                        "ok": False,
                        "intent": p_intent,
                        "message": f"Бараниот нов термин ({new_date} во {new_time}) е веќе зафатен.",
                        "state": new_state,
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
                new_state.pop("pending_action", None)
                return {
                    "ok": True,
                    "intent": p_intent,
                    "message": f"Терминот е успешно променет во {new_date} во {new_time}.",
                    "state": new_state,
                }

    if intent == "patient_list_appointments":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        new_state["last_appointments_list"] = [
            {
                "termin_ID": int(r.get("termin_ID") or 0),
                "datum": r.get("datum"),
                "vreme": r.get("vreme"),
                "ime_lekar": r.get("ime_lekar"),
            }
            for r in items[:10]
        ]
        return {
            "ok": True,
            "intent": intent,
            "message": _format_appointments(items),
            "state": new_state,
        }

    if intent == "patient_cancel_appointment":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        target = _find_target_appointment(items, prompt, ai_out)
        if not target:
            return {
                "ok": False,
                "intent": intent,
                "message": "Немате термин за откажување.",
                "state": new_state,
            }
        new_state["pending_action"] = {
            "intent": intent,
            "termin_id": int(target["termin_ID"]),
        }
        return {
            "ok": False,
            "intent": intent,
            "message": (
                f"Ќе го откажам терминот {_appointment_brief(target)}.\n"
                "Потврдете со: „Да, потврди“."
            ),
            "state": new_state,
        }

    if intent == "patient_reschedule_appointment":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        target = _find_target_appointment(items, prompt, ai_out)
        if not target:
            return {
                "ok": False,
                "intent": intent,
                "message": "Немате термин за промена.",
                "state": new_state,
            }

        # нов термин (датум/време) од текстот
        new_date = (ai_out or {}).get("date") or _extract_relative_or_iso_date(prompt)
        new_time = (ai_out or {}).get("time") or _extract_time(prompt)
        if not new_date or not new_time:
            return {
                "ok": False,
                "intent": intent,
                "message": "За промена на термин наведете нов датум и време (на пр. 2026-05-12 во 13:00).",
                "state": new_state,
            }

        if new_date == target.get("datum") and new_time == target.get("vreme"):
            return {
                "ok": False,
                "intent": intent,
                "message": "Новиот термин е ист како постоечкиот. Наведете друго време.",
                "state": new_state,
            }
        new_state["pending_action"] = {
            "intent": intent,
            "termin_id": int(target["termin_ID"]),
            "new_date": new_date,
            "new_time": new_time,
            "awaiting_alternative_pick": False,
        }
        return {
            "ok": False,
            "intent": intent,
            "message": (
                f"Ќе го променам терминот {_appointment_brief(target)} во {new_date} во {new_time}.\n"
                "Потврдете со: „Да, потврди“."
            ),
            "state": new_state,
        }

    if intent == "patient_set_reminder":
        items = _load_upcoming_appointments(db_cursor, patient_email)
        target = _find_target_appointment(items, prompt, ai_out)
        if not target:
            return {
                "ok": False,
                "intent": intent,
                "message": "Немате термин за кој може да поставиме потсетник.",
                "state": new_state,
            }
        # parsiranje na koga sakaat da se potseti (offset vo minuti)
        offset_minutes = _parse_reminder_offset_minutes(prompt)
        # validacija deka vremeto se uste ne pominalo (pred preview da se prati)
        reminder_dt_preview = _compute_reminder_datetime(target, offset_minutes)
        if not reminder_dt_preview:
            return {
                "ok": False,
                "intent": intent,
                "message": (
                    f"Не може потсетник {_format_offset_human(offset_minutes)} пред терминот "
                    f"({_appointment_brief(target)}) - тоа време веќе помина. "
                    "Пробајте пократок интервал (на пр. 30 минути пред)."
                ),
                "state": new_state,
            }
        # default kanal e email; ako pacientot ima telefon i spomenuva 'sms', koristi sms
        kanal = "sms" if "sms" in _mk_lower(prompt) and (pacient or {}).get("telefon") else "email"
        new_state["pending_action"] = {
            "intent": intent,
            "termin_id": int(target["termin_ID"]),
            "offset_minutes": int(offset_minutes),
            "kanal": kanal,
        }
        return {
            "ok": False,
            "intent": intent,
            "message": (
                f"Ќе поставам потсетник за терминот {_appointment_brief(target)} - "
                f"{_format_offset_human(offset_minutes)} пред (преку {kanal}).\n"
                "Потврдете со: „Да, потврди“."
            ),
            "state": new_state,
        }

    if intent == "patient_action_confirm":
        return {
            "ok": False,
            "intent": intent,
            "message": "Нема активна пациентска акција за потврда. Прво побарајте откажување, промена или потсетник.",
            "state": new_state,
        }

    return None
