"""
Анализа на најпопуларни оддели - само за директорот.

Примери:
- „Кои се најпопуларни оддели?"
- „Колку прегледи имаме по оддел?"
- „Топ 5 специјалности"
- „Анализа на оддели за оваа година"

Логика:
1. Прашаме во Termin_pregled, групираме по специјалност (или преку doctor_ID → Doctors.specialty).
2. Бројме термини, ги сортираме опаѓачки.
3. Враќаме топ N (default 10).
"""

import re
from datetime import date, timedelta

from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува параметри за статистика на оддели.

Корисникот сака анализа на најпосетени/најпопуларни оддели. Врати САМО JSON:
{"top_n": число (1-20) | null, "period": "denes" | "nedela" | "mesec" | "godina" | "site" | null}

Правила:
- ако корисникот вели „топ 5", „топ 3" → "top_n" = тој број (1-20).
- ако нема број → null (ќе биде default 10).
- период:
  • „денес" / „сегашно" → "denes"
  • „оваа недела" / „последните 7 дена" → "nedela"
  • „овој месец" / „последните 30 дена" → "mesec"
  • „оваа година" → "godina"
  • „воопшто" / „вкупно" / не е спомнат → "site" или null

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)
    print(f"[statistika] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="statistika_oddeli")


def _period_to_dates(period: str | None) -> tuple[date | None, str]:
    """
    Враќа (od_datum, label).
    od_datum=None значи „без филтер" (сите).
    """
    if not period or period == "site":
        return None, "од почеток"
    if period == "denes":
        return date.today(), "за денес"
    if period == "nedela":
        return date.today() - timedelta(days=7), "за последните 7 дена"
    if period == "mesec":
        return date.today() - timedelta(days=30), "за последните 30 дена"
    if period == "godina":
        # од почетокот на годината
        return date(date.today().year, 1, 1), f"за {date.today().year} година"
    return None, "од почеток"


def odgovori_za_statistika(prasanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    podatoci = _izvlechi(prasanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    top_n = podatoci.get("top_n")
    try:
        top_n = int(top_n) if top_n else 10
    except (TypeError, ValueError):
        top_n = 10
    top_n = max(1, min(20, top_n))

    od_datum, label = _period_to_dates(podatoci.get("period"))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Брои термини по специјалност на лекарот (преку JOIN со Doctors)
    # Се користи Doctors.specialty за конзистентност (специјалноста на лекарот = оддел)
    query = """
        SELECT
          COALESCE(NULLIF(TRIM(D.specialty), ''), 'Непознат оддел') AS oddel,
          COUNT(*) AS broj_prevegledi
        FROM Termin_pregled T
        LEFT JOIN Doctors D ON D.doctor_ID = T.doctor_ID
    """
    params: list = []
    if od_datum:
        query += " WHERE T.datum_pregled >= %s"
        params.append(od_datum)
    query += " GROUP BY oddel ORDER BY broj_prevegledi DESC LIMIT %s"
    params.append(top_n)

    cur.execute(query, params)
    redovi = cur.fetchall()

    # Вкупно за процент
    total_query = "SELECT COUNT(*) AS vk FROM Termin_pregled"
    total_params: list = []
    if od_datum:
        total_query += " WHERE datum_pregled >= %s"
        total_params.append(od_datum)
    cur.execute(total_query, total_params)
    total = cur.fetchone()["vk"] or 0
    cur.close()
    conn.close()

    if total == 0 or not redovi:
        return f"Нема прегледи {label}."

    # Изградба на одговор
    linii = [f"Најпопуларни оддели {label} (вкупно {total} прегледи):\n"]
    for i, r in enumerate(redovi, start=1):
        broj = r["broj_prevegledi"] or 0
        procent = (broj / total * 100) if total else 0
        linii.append(f"{i}. {r['oddel']}: {broj} ({procent:.1f}%)")

    return "\n".join(linii)
