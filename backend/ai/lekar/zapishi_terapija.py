"""
Запиши терапија/дијагноза за пациент од лекар.

Примери:
- „Запиши терапија за пациент Марко Иванов: 2x дневно парацетамол"
- „Додај терапија на термин 42: Аспирин 100mg"
- „Дијагноза за пациент Ана Стојановска: Хипертензија. Терапија: Лосартан 50mg"
- „Запиши: дијагноза грип, терапија витамин Ц"

Логика:
1. AI извлекува: ime_pacient, termin_id, dijagnoza, terapija
2. Идентификува термин:
   - ако има termin_id → користи него
   - инаку → бара завршен или закажан термин за тој пациент кај овој лекар
   - ако има повеќе → бара ID или последниот
3. UPDATE на Termin_pregled.dijagnoza/terapija
4. Ако терминот е „закажан" → автоматски го преместува на „завршен"
"""

import json
import re

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што од прашање извлекува податоци за запис на терапија/дијагноза.

Корисникот (лекар) пишува на македонски. Извлечи:
- "ime_pacient": име+презиме на пациент или null
- "termin_id": ID на термин (само цифри) или null
- "dijagnoza": текст за дијагнозата или null
- "terapija": текст за терапијата или null

Врати САМО JSON:
{"ime_pacient": "...", "termin_id": ..., "dijagnoza": "...", "terapija": "..."}

Правила:
- Ако корисникот пишува „терапија: X" или „пропиши X" → terapija = X
- Ако пишува „дијагноза: Y" или „dx: Y" → dijagnoza = Y
- Ако само набројува лек/пропис без префикс → terapija = тоа
- Запази ги оригиналните зборови (без преведување).

Примери:
- „Запиши терапија за Марко Иванов: 2x дневно парацетамол"
  → {"ime_pacient":"Марко Иванов","termin_id":null,"dijagnoza":null,"terapija":"2x дневно парацетамол"}
- „Дијагноза за термин 42: грип. Терапија: Витамин Ц"
  → {"ime_pacient":null,"termin_id":42,"dijagnoza":"грип","terapija":"Витамин Ц"}
- „За Ана Стојановска препиши Лосартан 50mg"
  → {"ime_pacient":"Ана Стојановска","termin_id":null,"dijagnoza":null,"terapija":"Лосартан 50mg"}

БЕЗ markdown, БЕЗ објаснувања.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[zapishi_terapija] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="zapishi_terapija")


def _najdi_termin_po_id(doctor_id: int, termin_id: int) -> dict | None:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled,
                   status_pregled, dijagnoza, terapija
            FROM Termin_pregled
            WHERE termin_ID = %s AND doctor_ID = %s
        """, (termin_id, doctor_id))
        r = cur.fetchone()
        cur.close()
        return r
    except Exception as e:
        print(f"[zapishi_terapija] DB greshka: {e}")
        return None
    finally:
        if conn:
            conn.close()


def _najdi_termini_po_ime(doctor_id: int, ime_pacient: str) -> list[dict]:
    """Враќа сите термини за тој пациент кај овој лекар, најнови прво."""
    delovi = [d for d in ime_pacient.strip().split() if d]
    if not delovi:
        return []

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        sql = (
            "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, "
            "       status_pregled, dijagnoza, terapija "
            "FROM Termin_pregled "
            "WHERE doctor_ID = %s"
        )
        params: list = [doctor_id]
        for d in delovi:
            sql += " AND LOWER(ime_pacient) LIKE %s"
            params.append(f"%{d.lower()}%")
        sql += " ORDER BY datum_pregled DESC, vreme_pregled DESC LIMIT 10"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
        cur.close()
        return rows
    except Exception as e:
        print(f"[zapishi_terapija] DB greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _update_terapija(
    termin_id: int,
    dijagnoza: str | None,
    terapija: str | None,
    avtomatski_zavrshi: bool,
) -> bool:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        delovi = []
        params: list = []
        if dijagnoza is not None:
            delovi.append("dijagnoza = %s")
            params.append(dijagnoza)
        if terapija is not None:
            delovi.append("terapija = %s")
            params.append(terapija)
        if avtomatski_zavrshi:
            delovi.append("status_pregled = 'завршен'")
        if not delovi:
            return False
        sql = "UPDATE Termin_pregled SET " + ", ".join(delovi) + " WHERE termin_ID = %s"
        params.append(termin_id)
        cur.execute(sql, tuple(params))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[zapishi_terapija] UPDATE greshka: {e}")
        return False
    finally:
        if conn:
            conn.close()


def _format_datum(d) -> str:
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)[:10]


def _format_vreme(v) -> str:
    if not v:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def odgovori_za_terapija(prashanje: str, lekar: dict | None) -> str:
    if not lekar or not lekar.get("doctor_ID"):
        return (
            "За да запишеш терапија преку AI асистентот, прво најави "
            "се како лекар."
        )

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    ime_pacient = (podatoci.get("ime_pacient") or "").strip() or None
    termin_id = podatoci.get("termin_id")
    try:
        termin_id = int(termin_id) if termin_id else None
    except (ValueError, TypeError):
        termin_id = None
    dijagnoza = (podatoci.get("dijagnoza") or "").strip() or None
    terapija = (podatoci.get("terapija") or "").strip() or None

    if not dijagnoza and not terapija:
        return (
            'Не препознав терапија или дијагноза за запис. Пробај пр.: '
            '„Запиши терапија за Марко Иванов: 2x дневно парацетамол" или '
            '„Дијагноза за термин 42: грип, терапија Витамин Ц".'
        )

    doctor_id = lekar["doctor_ID"]

    # --- Сценарио A: даден е termin_id ---
    if termin_id:
        termin = _najdi_termin_po_id(doctor_id, termin_id)
        if not termin:
            return (
                f"Не најдов твој термин со ID {termin_id}. "
                "Провери го бројот или пробај по име на пациент."
            )

        avtomatski = (termin.get("status_pregled") == "закажан")
        ok = _update_terapija(termin_id, dijagnoza, terapija, avtomatski)
        if not ok:
            return "Се случи грешка при зачувувањето. Те молам обиди се повторно."

        return _ispisi_uspesh(termin, dijagnoza, terapija, avtomatski)

    # --- Сценарио B: даден е ime_pacient ---
    if not ime_pacient:
        return (
            'Не препознав ниту ID на термин ниту име на пациент. '
            'Пробај пр.: „Запиши терапија за Марко Иванов: ..." или '
            '„за термин 42 додај терапија ...".'
        )

    termini = _najdi_termini_po_ime(doctor_id, ime_pacient)
    if not termini:
        return f'Не најдов твој термин со пациент „{ime_pacient}".'

    # Ако има само 1 → користи него
    if len(termini) == 1:
        t = termini[0]
        avtomatski = (t.get("status_pregled") == "закажан")
        ok = _update_terapija(t["termin_ID"], dijagnoza, terapija, avtomatski)
        if not ok:
            return "Се случи грешка при зачувувањето. Те молам обиди се повторно."
        return _ispisi_uspesh(t, dijagnoza, terapija, avtomatski)

    # Има повеќе → понуди им избор (земи го најновиот „закажан" или „завршен"
    # без терапија, иначе кажи на доктор да даде ID)
    # Преферирај: закажан без терапија > завршен без терапија > најнов
    def prioritet(t):
        ima_ter = bool((t.get("terapija") or "").strip())
        ima_dij = bool((t.get("dijagnoza") or "").strip())
        st = t.get("status_pregled")
        # Помал број → повисок приоритет
        if st == "закажан" and not (ima_ter or ima_dij):
            return 0
        if st == "завршен" and not (ima_ter or ima_dij):
            return 1
        if st == "закажан":
            return 2
        return 3

    termini_sortirani = sorted(termini, key=prioritet)
    najpriroditen = termini_sortirani[0]

    # Ако има многу „соодветни", барај експлицитен ID за безбедност
    relevantni = [t for t in termini if not (
        (t.get("terapija") or "").strip() or (t.get("dijagnoza") or "").strip()
    )]
    if len(relevantni) > 1:
        redovi = [
            f'Имаш повеќе термини со пациент „{ime_pacient}" без запис. '
            'Те молам наведи го ID:',
            "",
        ]
        for t in relevantni[:5]:
            redovi.append(
                f'• ID {t["termin_ID"]} – {_format_datum(t.get("datum_pregled"))} '
                f'{_format_vreme(t.get("vreme_pregled"))} ({t.get("status_pregled")})'
            )
        redovi.append("")
        redovi.append('Пр.: „за термин 42 запиши терапија ..."')
        return "\n".join(redovi)

    # Еден природен избор → користи го
    avtomatski = (najpriroditen.get("status_pregled") == "закажан")
    ok = _update_terapija(najpriroditen["termin_ID"], dijagnoza, terapija, avtomatski)
    if not ok:
        return "Се случи грешка при зачувувањето. Те молам обиди се повторно."
    return _ispisi_uspesh(najpriroditen, dijagnoza, terapija, avtomatski)


def _ispisi_uspesh(termin: dict, dijagnoza: str | None, terapija: str | None,
                   avtomatski_zavrshi: bool) -> str:
    pac = (termin.get("ime_pacient") or "").strip() or "—"
    dat = _format_datum(termin.get("datum_pregled"))
    vrm = _format_vreme(termin.get("vreme_pregled"))
    delovi = [
        "Записот е сочуван!",
        "",
        f'Пациент: {pac}',
        f'Термин: ID {termin["termin_ID"]} – {dat} {vrm}',
    ]
    if dijagnoza:
        delovi.append(f"Дијагноза: {dijagnoza}")
    if terapija:
        delovi.append(f"Терапија: {terapija}")
    if avtomatski_zavrshi:
        delovi.append("")
        delovi.append('Статусот на терминот е автоматски променет на „завршен".')
    return "\n".join(delovi)
