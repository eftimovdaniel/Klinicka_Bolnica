from datetime import date, timedelta

from database import get_connection
from ai._kernel.auth import require_lekar
from ai._kernel.groq_helpers import groq_zadolzhitelen, izvlechi_json_so_ai
from ai._kernel.napomena import napomena_za_prikaz_lekar
from ai._kernel.utils import format_datum_so_den, format_vreme
from ai.lekar.lekar_panel_nav import dopuni_so_lekar_panel
from ai.pacient.moi_pregledi import (
    datum_za_pregledi_od_prasanje,
    prasanje_e_lista_site_pregledi,
)


PROMPT = """
Ти си систем што извлекува параметри за распоред на лекар. Корисникот е лекар и сака да види свои закажани прегледи. Врати САМО JSON:
{"period": "denes" | "utre" | "nedela" | "mesec" | "site" | null,
 "datum": "YYYY-MM-DD" | null,
 "broj": число | null}

Правила:
- „денес" / „за денеска" → "period"="denes"
- „утре" / „за утре" → "period"="utre"
- „оваа недела" / „наредните 7 дена" → "period"="nedela"
- „овој месец" / „наредните 30 дена" → "period"="mesec"
- „сите" / „воопшто" → "period"="site"
- ако корисникот спомне конкретен датум (пр. „15.05" или „понеделник") → "datum"=YYYY-MM-DD
- ако корисникот спомне број (пр. „следните 5", „топ 3") → "broj"=число
- ако нема ништо јасно → сите вредности null БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()
from ai.lekar.lekar_intent import prasanje_e_moj_raspored_lekar  # noqa: F401 — re-export


def _izvlechi(prasanje: str) -> dict:
    """Само Groq JSON: period, datum, broj."""
    if prasanje_e_lista_site_pregledi(prasanje):
        return {"period": "site", "datum": None, "broj": None}
    if msg := groq_zadolzhitelen():
        return {"_error": msg}

    denes = date.today().strftime("%Y-%m-%d")
    denes_den = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][
        date.today().weekday()
    ]
    full = f'Денес: {denes} ({denes_den})\n\nПрашање: „{prasanje}"\nВрати JSON.'
    podatoci = izvlechi_json_so_ai(full, PROMPT, log_tag="moj_raspored")
    if podatoci.get("_error"):
        return podatoci
    return podatoci


def _period_to_dates(period: str | None) -> tuple[date | None, date | None, str]:
    """Враќа (od, do, label). None значи без горна граница."""
    denes = date.today()
    if not period:
        # Default: од денес па наваму
        return denes, None, "од денес"
    if period == "denes":
        return denes, denes, "за денес"
    if period == "utre":
        utre = denes + timedelta(days=1)
        return utre, utre, "за утре"
    if period == "nedela":
        return denes, denes + timedelta(days=7), "за следните 7 дена"
    if period == "mesec":
        return denes, denes + timedelta(days=30), "за следните 30 дена"
    if period == "site":
        return None, None, "сите"
    return denes, None, "од денес"


def odgovori_za_raspored(
    prasanje: str, lekar: dict | None, kontekst: dict | None = None
) -> str | dict:
    """Главна точка - повикана од router-от."""
    if err := require_lekar(lekar):
        return err

    doctor_id = lekar["doctor_ID"]
    podatoci = _izvlechi(prasanje)

    if podatoci.get("_error"):
        return str(podatoci["_error"])

    konkreten_datum = podatoci.get("datum")
    if not konkreten_datum:
        d = datum_za_pregledi_od_prasanje(prasanje)
        if d:
            konkreten_datum = d.strftime("%Y-%m-%d")
    broj = podatoci.get("broj")
    try:
        broj = int(broj) if broj else None
    except (TypeError, ValueError):
        broj = None

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    sql = (
        "SELECT termin_ID, ime_pacient, email_pacient, telefon_pacient,"
        "       datum_pregled, vreme_pregled, status_pregled, napomena"
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s"
        "   AND COALESCE(NULLIF(TRIM(status_pregled), ''), 'закажан')"
        " NOT IN ('откажан', 'отказан')"
    )
    params: list = [doctor_id]
    label = ""

    if konkreten_datum:
        sql += " AND datum_pregled = %s"
        params.append(konkreten_datum)
        label = f"за {konkreten_datum}"
    else:
        od, do, label = _period_to_dates(podatoci.get("period"))
        if od:
            sql += " AND datum_pregled >= %s"
            params.append(od)
        if do:
            sql += " AND datum_pregled <= %s"
            params.append(do)

    sql += " ORDER BY datum_pregled, vreme_pregled"
    if broj:
        sql += " LIMIT %s"
        params.append(broj)

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        termini_mode = "date" if konkreten_datum else "all"
        return dopuni_so_lekar_panel(
            f"Немаш закажани или завршени прегледи {label}.",
            tab="pacienti",
            termini_mode=termini_mode,
            datum=konkreten_datum,
        )

    zakazani_ids = [
        int(r["termin_ID"])
        for r in rows
        if (r.get("status_pregled") or "закажан").strip() == "закажан"
    ]

    linii = [f"Прегледи {label} ({len(rows)} вкупно):", ""]

    # Групирај по датум за полесно читање
    po_datum: dict = {}
    for r in rows:
        d = r["datum_pregled"]
        po_datum.setdefault(d, []).append(r)

    for d in sorted(po_datum.keys()):
        linii.append(f"━━ {format_datum_so_den(d)} ━━")
        for r in po_datum[d]:
            st = (r.get("status_pregled") or "закажан").strip()
            st_oznaka = f" [{st}]" if st != "закажан" else ""
            linija = (
                f"• {format_vreme(r['vreme_pregled'])} — {r['ime_pacient']}"
                f" (ID {r['termin_ID']}){st_oznaka}"
            )
            nap = napomena_za_prikaz_lekar(r.get("napomena"))
            if nap:
                linija += f"\n  Напомена: {nap}"
            linii.append(linija)
        linii.append("")

    tekst = "\n".join(linii).strip()
    if zakazani_ids:
        hint = (
            "\n\nЗа завршување со дијагноза и терапија, на пр.:\n"
            "„Затвори го прегледот со Дијагноза: …, и терапија: …“"
        )
        if len(zakazani_ids) == 1:
            hint = (
                f"\n\nЗа завршување (ID {zakazani_ids[0]}), на пр.:\n"
                "„Затвори го прегледот со Дијагноза: …, и терапија: …“"
            )
        tekst += hint

    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    if zakazani_ids:
        ctx["last_raspored_termin_ids"] = zakazani_ids

    termini_mode = "date" if konkreten_datum else "all"
    telo: str | dict = (
        {"odgovor": tekst, "kontekst": ctx} if zakazani_ids else tekst
    )
    return dopuni_so_lekar_panel(
        telo,
        tab="pacienti",
        termini_mode=termini_mode,
        datum=konkreten_datum,
    )
