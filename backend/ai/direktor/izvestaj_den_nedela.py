"""
Дневен / неделен извештај за администратор: термини (закажани/откажани/завршени) и нови апликации за работа.
Користи: Termin_pregled, prijaveni_lekari.
Само за корисник со check_admin_access (директор).
"""
from datetime import date, timedelta
from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import as_dict, db_cursor

# funkcija koja se koriste koga se odreduva vremenski oseg na prasanjeto
# mu se dozvoluva na korisnikot da prasuva prasanje kako naredniot vtornik sreda i slicno da ne so data
def _period_od_prasanje(prasanje: str) -> tuple[date, date, str]:  
    """
    Враќа (start, end, label).
    „недела“ = тековна календарска недела (пон–нед).
    """
    p = (prasanje or "").lower()    # prasanjeto na korisnikot go pretvaram vo mali bukvi i go smestuva vo p
    denes = date.today()    # vo denes se smestuva denesniot datum kako pocetna tocka
    if any(     # proverka dali korisnikot spomenal nekade zbrovi od nedelata. ili za nedela,...
        w in p
        for w in (
            "оваа недела", "овaa недела", "неделата", "неделен", "за недела", "nedela", "nedelata", "nedelen",
        )
    ):
        start = denes - timedelta(days=denes.weekday()) # go presmetuva ponedelnikot od denesniot datum za poslesno presmetuvanje 
        end = start + timedelta(days=6) # dodavanje na 6 dena na ponedelnikot za da stigne do kraj na nedelata
        return start, end, f"календарска недела {start.strftime('%d.%m.')}–{end.strftime('%d.%m.%Y')}"  # vraka pocetok i kraj na nadelta

    return denes, denes, f"денес ({denes.strftime('%d.%m.%Y')})"    # ako ne se spomene nedela, se vraka denesniot datum

# funkcija koja se povikuva za generiranje na izvestaj
def odgovori_za_izvestaj(prasanje: str, lekar: dict | None) -> str:
    if err := require_direktor(lekar):      # se proveruva dali e najaven direktorot na bolnicata
        return err  # ako ne e se vraka error
    d0, d1, label = _period_od_prasanje(prasanje) # se povikuvat datumite od do 

    try:
        with db_cursor() as (_, cur):   # otvaranje na konekciajta so bazata za pregled na izvestaite
            cur.execute(        # kveri za bazata na podatociza sobiranje na brpjot na statusi na terminte
                """
                SELECT status_pregled, COUNT(*) AS c
                FROM Termin_pregled
                WHERE datum_pregled BETWEEN %s AND %s
                GROUP BY status_pregled
                """,
                (d0, d1),   # postavauanje na parametrite od do za vremenskiot period
            )
            status_rows = cur.fetchall() or [] # gi zema site redovi ako nema takvi vraka prazna lista
            cur.execute(        # kveri za vkupen broj na aplikanti za rabota
                """
                SELECT COUNT(*) AS c
                FROM prijaveni_lekari
                WHERE DATE(datum_prijava) BETWEEN %s AND %s
                """,
                (d0, d1),   # se postavuvat od do datumite bez da bidat naglaseni
            )
            apl_row = cur.fetchone()    # od bazata go vlecam redot kade se smesteni vie vrednosti
    except Exception as e:      # Dokolku nastane greska pri obrabotka na podatocite od bazata 
        print(f"[izvestaj_den_nedela] DB: {e}") # pecatenje na tehnicka greska na konzolata
        return f"Не успеав да го извадам извештајот: {e}"   # poraka do korisnikot

    br: dict[str, int] = {"закажан": 0, "откажан": 0, "завршен": 0}     # recnik so pocetni vrednosti 0 za site tri tipa na pregledi
    for r in status_rows:   #minenje na sekoj red od bazata kade se ispolentei uslovite
        row = as_dict(r) # redot go pretvaram vo Python recnik za obrabotka
        st = (row.get("status_pregled") or "").strip().lower()  # go zimame statusot so otstraneti prazni mesta i site mali bukvi
        c = int(row.get("c") or 0) # ja zemame count od bazata kako cel broj
        if st in br:    # ako pronajdeniot status od bazata se sofpaga so ocekuvan status
            br[st] = c  # ja azurirame vrednosta na br so realniot broj

    apl = int(as_dict(apl_row).get("c") or 0) if apl_row else 0 #se izvlekuva brojkata na aplikanit od vtorto baranje ili kveri

    return (    # pecatenje na izlezot
        f"**Извештај за {label}**\n\n"
        f"Термини (по датум на преглед во периодот):\n"
        f"• Закажани: **{br['закажан']}**\n"
        f"• Откажани: **{br['откажан']}**\n"
        f"• Завршени: **{br['завршен']}**\n\n"
        f"Нови апликации за работа (поднесени во периодот): **{apl}**"
    )
