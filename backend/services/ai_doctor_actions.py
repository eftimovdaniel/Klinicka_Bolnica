from routers.admin import check_admin_access


def _extract_actor_id(pacient: dict, state: dict) -> int:
    raw_id = (
        (pacient or {}).get("doctor_ID")
        or (pacient or {}).get("doctor_id")
        or (pacient or {}).get("id")
        or (state or {}).get("admin_doctor_id")
        or (state or {}).get("doctor_id")
    )
    try:
        return int(raw_id)
    except Exception:
        return 0


def _doctor_display_name(db_cursor, doctor_id: int) -> str:
    db_cursor.execute(
        """
        SELECT name, surname
        FROM Doctors
        WHERE doctor_ID = %s
        LIMIT 1
        """,
        (doctor_id,),
    )
    row = db_cursor.fetchone() or {}
    full = f"{row.get('name', '')} {row.get('surname', '')}".strip()
    return full or f"ID {doctor_id}"


def _load_doctor_day_appointments(db_cursor, doctor_id: int):
    db_cursor.execute(
        """
        SELECT
            termin_ID,
            TIME_FORMAT(vreme_pregled, '%%H:%%i') AS vreme,
            ime_pacient,
            napomena,
            status_pregled
        FROM Termin_pregled
        WHERE doctor_ID = %s
          AND DATE(datum_pregled) = CURDATE()
          AND status_pregled = 'закажан'
        ORDER BY vreme_pregled ASC
        """,
        (doctor_id,),
    )
    return db_cursor.fetchall() or []


def handle_doctor_action(intent: str, db_cursor, prompt: str, pacient: dict, state: dict):
    _ = prompt
    actor_doctor_id = _extract_actor_id(pacient, state)

    if intent in ("doctor_today_schedule", "doctor_next_patient", "doctor_delayed_patients"):
        if not actor_doctor_id:
            return {
                "ok": False,
                "intent": intent,
                "message": "За оваа функција мора да сте најавени како лекар.",
                "state": state,
            }

        doctor_name = _doctor_display_name(db_cursor, int(actor_doctor_id))
        day_items = _load_doctor_day_appointments(db_cursor, int(actor_doctor_id))

        if intent == "doctor_today_schedule":
            if not day_items:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Д-р {doctor_name}, денес немате закажани пациенти.",
                    "state": state,
                }
            lines = [f"Д-р {doctor_name}, денес имате {len(day_items)} закажани пациенти:"]
            for i, row in enumerate(day_items[:12], start=1):
                patient = (row.get("ime_pacient") or "Непознат пациент").strip()
                note = (row.get("napomena") or "").strip()
                extra = f" ({note})" if note else ""
                lines.append(f"{i}. {row.get('vreme')} - {patient}{extra}")
            lines.append("Можете да прашате и: „Кој е следен?“ или „Кој доцни?“")
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": state,
            }

        if intent == "doctor_next_patient":
            db_cursor.execute(
                """
                SELECT
                    TIME_FORMAT(vreme_pregled, '%%H:%%i') AS vreme,
                    ime_pacient,
                    napomena
                FROM Termin_pregled
                WHERE doctor_ID = %s
                  AND DATE(datum_pregled) = CURDATE()
                  AND status_pregled = 'закажан'
                  AND TIME(vreme_pregled) >= CURTIME()
                ORDER BY vreme_pregled ASC
                LIMIT 1
                """,
                (int(actor_doctor_id),),
            )
            next_row = db_cursor.fetchone() or {}
            if not next_row:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Д-р {doctor_name}, нема следен пациент за денес (или сите термини се поминати).",
                    "state": state,
                }
            note = (next_row.get("napomena") or "").strip()
            note_text = f" Напомена: {note}." if note else ""
            return {
                "ok": True,
                "intent": intent,
                "message": (
                    f"Следен пациент: {next_row.get('ime_pacient')} во {next_row.get('vreme')}."
                    f"{note_text}"
                ),
                "state": state,
            }

        if intent == "doctor_delayed_patients":
            db_cursor.execute(
                """
                SELECT
                    TIME_FORMAT(vreme_pregled, '%%H:%%i') AS vreme,
                    ime_pacient,
                    TIMESTAMPDIFF(MINUTE, TIMESTAMP(CURDATE(), vreme_pregled), NOW()) AS delay_minutes
                FROM Termin_pregled
                WHERE doctor_ID = %s
                  AND DATE(datum_pregled) = CURDATE()
                  AND status_pregled = 'закажан'
                  AND TIMESTAMP(CURDATE(), vreme_pregled) < NOW()
                ORDER BY vreme_pregled ASC
                """,
                (int(actor_doctor_id),),
            )
            delayed_rows = db_cursor.fetchall() or []
            if not delayed_rows:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Д-р {doctor_name}, во моментов нема пациенти што доцнат.",
                    "state": state,
                }
            lines = ["Пациенти што доцнат за денешни термини:"]
            for row in delayed_rows[:10]:
                delay_m = int(row.get("delay_minutes") or 0)
                lines.append(f"- {row.get('ime_pacient')} (термин {row.get('vreme')}, доцни {max(delay_m, 0)} мин.)")
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": state,
            }

    if intent == "doctor_patients_overview":
        if not actor_doctor_id or not check_admin_access(int(actor_doctor_id)):
            return {
                "ok": False,
                "intent": intent,
                "message": "Оваа информација е достапна само за директор/админ.",
                "state": state,
            }
        db_cursor.execute(
            """
            SELECT
                ime_lekar,
                ime_pacient,
                TIME_FORMAT(vreme_pregled, '%%H:%%i') AS vreme
            FROM Termin_pregled
            WHERE DATE(datum_pregled) = CURDATE()
              AND status_pregled = 'закажан'
            ORDER BY ime_lekar ASC, vreme_pregled ASC
            """
        )
        rows = db_cursor.fetchall() or []
        if not rows:
            return {
                "ok": True,
                "intent": intent,
                "message": "Денес нема закажани пациенти кај лекарите.",
                "state": state,
            }

        grouped = {}
        for r in rows:
            doctor = (r.get("ime_lekar") or "Непознат лекар").strip()
            patient = (r.get("ime_pacient") or "Непознат пациент").strip()
            time_str = (r.get("vreme") or "").strip()
            grouped.setdefault(doctor, []).append((time_str, patient))

        lines = ["Денешна распределба по лекари:"]
        for doctor, items in grouped.items():
            lines.append(f"- Д-р {doctor}:")
            for time_str, patient in items[:12]:
                lines.append(f"  • {time_str} - {patient}")
        return {
            "ok": True,
            "intent": intent,
            "message": "\n".join(lines),
            "state": state,
        }

    return None
