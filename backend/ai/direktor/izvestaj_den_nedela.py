"""
Дневен / неделен извештај за администратор: термини (закажани/откажани/завршени) и нови апликации за работа.

Користи: Termin_pregled, prijaveni_lekari.
Само за корисник со check_admin_access (директор).
"""

from datetime import date, timedelta

from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import as_dict, db_cursor


def _period_od_prashanje(prashanje: str) -> tuple[date, date, str]:
    """
    Враќа (start, end, label).
    „недела“ = тековна календарска недела (пон–нед).
    """
    p = (prashanje or "").lower()
    denes = date.today()
    if any(
        w in p
        for w in (
            "оваа недела",
            "овaa недела",
            "неделата",
            "неделен",
            "за недела",
            "nedela",
            "nedelata",
            "nedelen",
        )
    ):
        start = denes - timedelta(days=denes.weekday())
        end = start + timedelta(days=6)
        return start, end, f"календарска недела {start.strftime('%d.%m.')}–{end.strftime('%d.%m.%Y')}"

    return denes, denes, f"денес ({denes.strftime('%d.%m.%Y')})"


def odgovori_za_izvestaj(prashanje: str, lekar: dict | None) -> str:
    if err := require_direktor(lekar):
        return err

    d0, d1, label = _period_od_prashanje(prashanje)

    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT status_pregled, COUNT(*) AS c
                FROM Termin_pregled
                WHERE datum_pregled BETWEEN %s AND %s
                GROUP BY status_pregled
                """,
                (d0, d1),
            )
            status_rows = cur.fetchall() or []

            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM prijaveni_lekari
                WHERE DATE(datum_prijava) BETWEEN %s AND %s
                """,
                (d0, d1),
            )
            apl_row = cur.fetchone()
    except Exception as e:
        print(f"[izvestaj_den_nedela] DB: {e}")
        return f"Не успеав да го извадам извештајот: {e}"

    br: dict[str, int] = {"закажан": 0, "откажан": 0, "завршен": 0}
    for r in status_rows:
        row = as_dict(r)
        st = (row.get("status_pregled") or "").strip().lower()
        c = int(row.get("c") or 0)
        if st in br:
            br[st] = c

    apl = int(as_dict(apl_row).get("c") or 0) if apl_row else 0

    return (
        f"**Извештај за {label}**\n\n"
        f"Термини (по датум на преглед во периодот):\n"
        f"• Закажани: **{br['закажан']}**\n"
        f"• Откажани: **{br['откажан']}**\n"
        f"• Завршени: **{br['завршен']}**\n\n"
        f"Нови апликации за работа (поднесени во периодот): **{apl}**"
    )
