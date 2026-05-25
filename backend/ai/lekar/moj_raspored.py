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
PROMPT = """ Ти си систем што извлекува параметри за распоред на лекар. Корисникот е лекар и сака да види свои закажани прегледи. Врати САМО JSON:
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
- ако нема ништо јасно → сите вредности null БЕЗ markdown, БЕЗ објаснувања. Само JSON.""".strip()
from ai.lekar.lekar_intent import prasanje_e_moj_raspored_lekar
from ai._kernel.transliteracija import transliterijaj

def _lokalno_izvlechi(prasanje: str) -> dict | None:
    """Брза локална детекција без Groq за чести форми."""
    p = transliterijaj(prasanje or "").lower().strip()
    if not p:
        return None
    if prasanje_e_lista_site_pregledi(prasanje):
        return {"period": "site", "datum": None, "broj": None}
    if any(x in p for x in ("денес", "denes", "за денеска", "za deneska")):
        return {"period": "denes", "datum": None, "broj": None}
    if any(x in p for x in ("утре", "utre", "za utre", "за утре")):
        return {"period": "utre", "datum": None, "broj": None}
    if any(
        x in p
        for x in (
            "оваа недела", "ovaa nedela",
            "следната недела", "slednata nedela",
            "наредната недела", "narednata nedela",
            "наредните 7 дена", "narednite 7 dena",
            "7 дена", "7 dena",
        )
    ):
        return {"period": "nedela", "datum": None, "broj": None}
    if any(
        x in p
        for x in (
            "овој месец", "ovoj mesec",
            "наредните 30 дена", "narednite 30 dena",
            "30 дена", "30 dena",
        )
    ):
        return {"period": "mesec", "datum": None, "broj": None}
    # „Мој распоред“ / „распоред“ без друг детал → од денес натаму
    if re.fullmatch(r"(?:мој\s+)?распоред\.?", p) or re.fullmatch(r"(?:moj\s+)?raspored\.?", p):
        return {"period": None, "datum": None, "broj": None}
    return None


import re  # за локалниот parser

# funkcija koja go povikuva llm modelot za strukturiranje na branjeto
def _izvlechi(prasanje: str) -> dict:
    lok = _lokalno_izvlechi(prasanje)
    if lok is not None:
        return lok
    if datum_za_pregledi_od_prasanje(prasanje):
        # Конкретен ден ќе се извлече локално подоцна — нема потреба од Groq
        return {"period": None, "datum": None, "broj": None}
    if groq_zadolzhitelen():
        # Groq недостапен → разумен default наместо грешка
        return {"period": None, "datum": None, "broj": None}

    denes = date.today().strftime("%Y-%m-%d")   # se zema denesnata data kako string
    denes_den = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][
        date.today().weekday()
    ]   # se pravi presmetka na dekovnite denovi
    full = f'Денес: {denes} ({denes_den})\n\nПрашање: „{prasanje}"\nВрати JSON.'
    podatoci = izvlechi_json_so_ai(full, PROMPT, log_tag="moj_raspored")    # povik do groq api i parsiranje na baranjeto
    if podatoci.get("_error"):
        # Тивок fallback за rate-limit / 429 — не блокирај го корисникот
        return {"period": None, "datum": None, "broj": None}
    return podatoci

# funkcija koja detektira period od do 
def _period_to_dates(period: str | None) -> tuple[date | None, date | None, str]:
    denes = date.today()    # za pocetna vrednost se zema denesnata data
    if not period:
        return denes, None, "од денес"  # se podrazbira opseg od do 
    if period == "denes":   # ako e vneseno denes
        return denes, denes, "за денес" # tocno za denesniot den
    if period == "utre":    # vneseno utre
        utre = denes + timedelta(days=1)    # se kalkulira itresniot den
        return utre, utre, "за утре"
    if period == "nedela":
        return denes, denes + timedelta(days=7), "за следните 7 дена"
    if period == "mesec":
        return denes, denes + timedelta(days=30), "за следните 30 дена"
    if period == "site":
        return None, None, "сите"   # gi vraka site bez vremenski opseg
    return denes, None, "од денес"
#glavna funkcija
def odgovori_za_raspored(
    prasanje: str, lekar: dict | None, kontekst: dict | None = None
) -> str | dict:
    if err := require_lekar(lekar): # proverka koj e najven dali e lekar samo toj moze da gleda
        return {
            "odgovor": (
                f"{err}\n\n"
                "Најавете се преку «Најава за лекар» — потоа ќе го отворим панелот "
                "со вашите закажани прегледи."
            ),
            "akcija": "otvori_lekar_login",
        }
    doctor_id = lekar["doctor_ID"]  # se prezema id na lekarot koj e najaven
    podatoci = _izvlechi(prasanje)  # povik na ai funkcijata za izvlekuvanje na json parametri
    if podatoci.get("_error"):  # ako ai dade greska    
        return str(podatoci["_error"])  # greskata se pretvara vo string i se vrka kon korisnikot

    konkreten_datum = podatoci.get("datum") # se proveruva dali modelot uspeal da pronajde konkreten datum
    if not konkreten_datum: # ako ne e pronajden se pravi lokalno
        d = datum_za_pregledi_od_prasanje(prasanje) 
        if d:
            konkreten_datum = d.strftime("%Y-%m-%d")    # formatiranje na vremeto vo iso format
    broj = podatoci.get("broj") # se proveruva dali lekarot pobaral limit na rezultato
    try:
        broj = int(broj) if broj else None
    except (TypeError, ValueError):
        broj = None 
# konekcija so bazata na podatoci
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
# upiti za bazata za izvlekuvanje na pregledi za doktorite koi nemaat satus otkazan
    sql = (
        "SELECT termin_ID, ime_pacient, email_pacient, telefon_pacient,"
        "       datum_pregled, vreme_pregled, status_pregled, napomena"
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s"
        "   AND COALESCE(NULLIF(TRIM(status_pregled), ''), 'закажан')"
        " NOT IN ('откажан', 'отказан')"
    )
    params: list = [doctor_id]  # postavuvanje na doctor id kako prv parametar
    label = ""
# dokolku lekarot ima konkreten datum, se izveduva sql upitot so where uslovot
    if konkreten_datum:
        sql += " AND datum_pregled = %s" # dodananje na datumot 
        params.append(konkreten_datum)
        label = f"за {konkreten_datum}"
    else:   # ako nema tocen datum, se kalkulira  spored period
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
