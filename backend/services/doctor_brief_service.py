"""
Servis za avtomatski dneven brif za sekoj lekar.

Sekoe utro vo 08:00 (lokalno vreme), schedulerot za sekoj lekar:
  1) gi vlece denesnite zakazani termini
  2) ja proveruva najblizkata dezurstvo
  3) generira chovecki citliv tekst na makedonski
  4) snimuva vo Doctor_briefs (UNIQUE per doctor+date - bez duplikati)
  5) (opcionalno) prati email ako SMTP_HOST e konfiguriran vo .env

Schedulerot se startuva preku start_scheduler() povikana od main.py lifespan.
Mozhe da se isklucи preko env: AI_BRIEF_SCHEDULER_ENABLED=0
"""
import os
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_connection

# imiwa na denovi vo nedelata na makedonski (0 = ponedelnik)
WEEKDAY_NAMES_MK = [
    "понеделник", "вторник", "среда", "четврток",
    "петок", "сабота", "недела",
]

# globalen referenca kon scheduler-ot (eden po proces)
_scheduler: Optional[BackgroundScheduler] = None


def _format_weekday_mk(d: date) -> str:
    """Vrakame ime na den vo nedelata na makedonski."""
    return WEEKDAY_NAMES_MK[d.weekday()]


def _format_date_human(d: date) -> str:
    """Format DD.MM.YYYY za prikaz vo poraka."""
    return d.strftime("%d.%m.%Y")


def _load_today_appointments(db_cursor, doctor_id: int):
    """Site denesni zakazani termini za daden lekar, sortirani po vreme."""
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
        ORDER BY vreme_pregled ASC
        """,
        (int(doctor_id),),
    )
    return db_cursor.fetchall() or []


def _load_next_dezurstvo(db_cursor, doctor_id: int):
    """Najblizkata dezurstvo (denes ili idnata 14 dni)."""
    db_cursor.execute(
        """
        SELECT
            datum,
            oddel,
            TIME_FORMAT(vreme_od, '%%H:%%i') AS vreme_od,
            TIME_FORMAT(vreme_do, '%%H:%%i') AS vreme_do
        FROM Dezurstva
        WHERE doctor_ID = %s
          AND datum BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 14 DAY)
        ORDER BY datum ASC, vreme_od ASC
        LIMIT 1
        """,
        (int(doctor_id),),
    )
    return db_cursor.fetchone()


def _load_pending_briefings_count(db_cursor, doctor_id: int) -> int:
    """Broj na napravi pregledi koi se uste 'закажан' a se vo minato (propušteni / treba update)."""
    db_cursor.execute(
        """
        SELECT COUNT(*) AS vkupno
        FROM Termin_pregled
        WHERE doctor_ID = %s
          AND status_pregled = 'закажан'
          AND TIMESTAMP(datum_pregled, vreme_pregled) < NOW()
        """,
        (int(doctor_id),),
    )
    row = db_cursor.fetchone() or {}
    return int(row.get("vkupno") or 0)


def build_doctor_brief(db_cursor, doctor_id: int, doctor_full_name: str) -> str:
    """Glavna funkcija koja zgradja string-poraka za daden lekar."""
    # 1) zima denesni termini
    todays = _load_today_appointments(db_cursor, doctor_id)
    # 2) zima sledna dezurstvo
    next_dez = _load_next_dezurstvo(db_cursor, doctor_id)
    # 3) zima broj na pregledi koi treba da se zatvorat (propušteni)
    pending_old = _load_pending_briefings_count(db_cursor, doctor_id)

    # gradi delovi na poraka
    parts = [f"Добро утро, Д-р {doctor_full_name}!"]

    if not todays:
        parts.append("Денес немате закажани прегледи.")
    else:
        first = todays[0]
        first_patient = (first.get("ime_pacient") or "Непознат пациент").strip()
        first_time = (first.get("vreme") or "").strip()
        parts.append(
            f"Денес имате {len(todays)} {'пациент' if len(todays) == 1 else 'пациенти'}. "
            f"Прв е {first_patient} во {first_time}."
        )
        # ako ima poveke od 1 termin, dodavame i posleden
        if len(todays) >= 2:
            last = todays[-1]
            last_time = (last.get("vreme") or "").strip()
            parts.append(f"Последен термин: {last_time}.")
        # ako prviot termin ima napomena, ja istaknuvame
        first_note = (first.get("napomena") or "").strip()
        if first_note:
            parts.append(f"Напомена за првиот пациент: {first_note}.")

    # informacija za sledna dezurstvo
    if next_dez:
        dez_date = next_dez.get("datum")
        if isinstance(dez_date, date):
            dez_weekday = _format_weekday_mk(dez_date)
            dez_human = _format_date_human(dez_date)
            # dali e denes?
            today = datetime.now().date()
            if dez_date == today:
                when_str = f"денес ({dez_weekday}, {dez_human})"
            elif dez_date == today + timedelta(days=1):
                when_str = f"утре ({dez_weekday}, {dez_human})"
            else:
                when_str = f"во {dez_weekday} ({dez_human})"
            oddel = (next_dez.get("oddel") or "").strip()
            vreme_od = (next_dez.get("vreme_od") or "").strip()
            vreme_do = (next_dez.get("vreme_do") or "").strip()
            time_window = f"{vreme_od}-{vreme_do}" if vreme_od and vreme_do else (vreme_od or "")
            dez_line = f"Дежурство имате {when_str}"
            if oddel:
                dez_line += f" на {oddel}"
            if time_window:
                dez_line += f" ({time_window})"
            dez_line += "."
            parts.append(dez_line)
    else:
        parts.append("Нема закажани дежурства во наредните 14 дена.")

    # ako ima propušteni pregledi koi treba da se zatvorat
    if pending_old > 0:
        parts.append(
            f"Внимание: имате {pending_old} {'преглед' if pending_old == 1 else 'прегледи'} "
            "со помината терминска ставка кои сè уште се „закажан“ - "
            "проверете и ажурирајте го статусот."
        )

    parts.append("Пријатен и успешен работен ден!")
    return "\n".join(parts)


def _store_doctor_brief(db_cursor, conn, doctor_id: int, message: str) -> int:
    """INSERT (ili UPDATE ako vekje postoi za istiot den) vo Doctor_briefs.
    Vrakame ID-to na zapisot.
    """
    today_iso = datetime.now().date().isoformat()
    # ON DUPLICATE KEY UPDATE go pokrыva sluchajot koga schedulerot ke stane dvapati
    db_cursor.execute(
        """
        INSERT INTO Doctor_briefs (doctor_ID, brief_date, message)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            message = VALUES(message),
            kreiran_na = CURRENT_TIMESTAMP,
            read_status = 0,
            procitan_na = NULL
        """,
        (int(doctor_id), today_iso, message),
    )
    conn.commit()
    return int(getattr(db_cursor, "lastrowid", 0) or 0)


def _try_send_email(to_email: str, subject: str, body: str) -> bool:
    """Opcionalno prati email ako e konfiguriran SMTP vo .env.
    Vrakame True ako e pratan, False inaku.
    """
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        return False
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user).strip()
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "Клиничка Болница Штип").strip()
    use_tls = os.getenv("SMTP_TLS", "1").strip() in ("1", "true", "yes", "True")

    if not to_email or not smtp_from:
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((smtp_from_name, smtp_from))
    msg["To"] = to_email

    try:
        if use_tls:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                s.starttls()
                if smtp_user:
                    s.login(smtp_user, smtp_password)
                s.sendmail(smtp_from, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                if smtp_user:
                    s.login(smtp_user, smtp_password)
                s.sendmail(smtp_from, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"[doctor_brief] SMTP greška za {to_email}: {e}")
        return False


def run_doctor_briefs() -> dict:
    """Glavna funkcija koja schedulerot ja vika sekoe utro.
    Mozhe i racno da se vika preku endpoint za testiranje.
    Vrakame dict so statistika: {generated, sent_emails, errors}.
    """
    stats = {"generated": 0, "sent_emails": 0, "errors": 0, "doctors_total": 0}
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT doctor_ID, name, surname, email FROM Doctors")
        doctors = cur.fetchall() or []
        stats["doctors_total"] = len(doctors)

        for d in doctors:
            doctor_id = int(d.get("doctor_ID") or 0)
            full_name = f"{d.get('name', '')} {d.get('surname', '')}".strip()
            try:
                # nov cursor za sekoj lekar (za da ne pravime mixanje na rezultati)
                inner_cur = conn.cursor(dictionary=True)
                msg = build_doctor_brief(inner_cur, doctor_id, full_name)
                _store_doctor_brief(inner_cur, conn, doctor_id, msg)
                inner_cur.close()
                stats["generated"] += 1
                # proba za email
                email = (d.get("email") or "").strip()
                if email and _try_send_email(
                    email,
                    f"Дневен брифинг - {datetime.now().strftime('%d.%m.%Y')}",
                    msg,
                ):
                    stats["sent_emails"] += 1
            except Exception as e:
                stats["errors"] += 1
                print(f"[doctor_brief] greška za D-r {full_name}: {e}")
        cur.close()
    except Exception as e:
        print(f"[doctor_brief] kriticna greška vo run_doctor_briefs: {e}")
        stats["errors"] += 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return stats


def get_today_brief_for_doctor(doctor_id: int) -> Optional[dict]:
    """Vrakame najnov brief za daden lekar (denesniot ako postoi)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT brief_ID, doctor_ID, brief_date, message, read_status,
                   kreiran_na, procitan_na
            FROM Doctor_briefs
            WHERE doctor_ID = %s
              AND brief_date = CURDATE()
            LIMIT 1
            """,
            (int(doctor_id),),
        )
        row = cur.fetchone()
        cur.close()
        return row
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def mark_brief_as_read(brief_id: int) -> bool:
    """Markira brif kako prochitan."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE Doctor_briefs
            SET read_status = 1, procitan_na = NOW()
            WHERE brief_ID = %s
            """,
            (int(brief_id),),
        )
        conn.commit()
        affected = cur.rowcount
        cur.close()
        return affected > 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def start_scheduler() -> None:
    """Startuva BackgroundScheduler i go zakazuva dnevniot job vo 08:00.
    Bezbedno e da se vika poveke pati - ako vekje e startuvan, ne pravi nista.
    Mozhe da se isklucи preku env: AI_BRIEF_SCHEDULER_ENABLED=0
    """
    global _scheduler
    enabled = os.getenv("AI_BRIEF_SCHEDULER_ENABLED", "1").strip() not in ("0", "false", "no", "False")
    if not enabled:
        print("[doctor_brief] scheduler iskluchen preku env (AI_BRIEF_SCHEDULER_ENABLED=0)")
        return

    if _scheduler is not None and _scheduler.running:
        return

    timezone = os.getenv("AI_BRIEF_TZ", "Europe/Skopje")
    hour = int(os.getenv("AI_BRIEF_HOUR", "8"))
    minute = int(os.getenv("AI_BRIEF_MINUTE", "0"))

    _scheduler = BackgroundScheduler(timezone=timezone)
    _scheduler.add_job(
        run_doctor_briefs,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_doctor_briefs",
        name="Daily doctor briefs",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    print(f"[doctor_brief] scheduler startuvan ({timezone}, sekoe {hour:02d}:{minute:02d})")


def stop_scheduler() -> None:
    """Stopira schedulerot (vika se na shutdown na FastAPI app)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
        print("[doctor_brief] scheduler stopiran")
