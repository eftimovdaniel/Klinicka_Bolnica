"""
Лични статистики на најавен лекар - прегледи + просечна оцена.

Примери:
- „Колку прегледи имам?"
- „Каква ми е просечната оцена?"
- „Моите статистики"
- „Колку прегледи имав оваа недела?"
- „Колку прегледи имав минатиот месец?"
"""
import re  
from datetime import date, timedelta 
from database import get_connection  
from ai._kernel.auth import require_lekar  
from ai._kernel.ai_json import parse_ai_json  
from ai._kernel.groq_client import ask_ai 


# sistemski prompt koj go nasocuva AI modelot strogo da go izvleche vremenskiot period vo JSON format
PROMPT = """ Ти си систем што извлекува период за статистика на лекар. Корисникот е лекар и сака свои статистики. Врати САМО JSON:
{"period": "denes" | "nedela" | "mesec" | "godina" | "site" | null}
Правила:
- „денес" / „сегашно" → "denes"
- „оваа недела" / „последните 7 дена" → "nedela"
- „овој месец" / „последниот месец" / „последните 30 дена" → "mesec"
- „оваа година" → "godina"
- „воопшто" / „вкупно" / не е спомнат → "site"
БЕЗ markdown, БЕЗ објаснувања. Само JSON.""".strip()

# vnatresna funkcija koja go povikuva Groq AI za strukturiranje na baranjeto na lekarot
def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)  # povik do LLM so soodvetniot prompt
    print(f"[moja_statistika] AI: {odgovor!r}")  # logiranje na siroviot odgovor vo konzolata poradi debagiranje
    return parse_ai_json(odgovor, log_tag="moja_statistika")  # parsiranje i vrakjanje na JSON rechnikot


# pomosna funkcija koja go pretvora tekstualniot period vo konkreten poceten datum za SQL filterot
def _period_to_dates(period: str | None) -> tuple[date | None, str]:
    if not period or period == "site":
        return None, "од почеток"  # bez vremensko ogranicuvanje (celosna istorija)
    if period == "denes":
        return date.today(), "за денес"  # filterot zapocnuva od denesniot den
    if period == "nedela":
        return date.today() - timedelta(days=7), "за последните 7 дена"  # ogranicuvanje za poslednite 7 dena
    if period == "mesec":
        return date.today() - timedelta(days=30), "за последните 30 дена"  # ogranicuvanje za poslednite 30 dena
    if period == "godina":
        return date(date.today().year, 1, 1), f"за {date.today().year} година"  # filter od 1-vi januari ovaa godina
    return None, "од почеток"  # sigurnosen fallback opseg


# glavna handler funkcija koja se povikuva od strana na router-ot
def odgovori_za_moja_statistika(prasanje: str, lekar: dict | None) -> str:
    if err := require_lekar(lekar):  # samo najaven lekar moze da gi gleda svoite privatni statistiki
        return err  # ako ne e lekar, rutata se blokira tuka

    doctor_id = lekar["doctor_ID"]  # prevzemanje na id-to na najaveniot lekar

    podatoci = _izvlechi(prasanje)  # povik na AI funkcijata za izvlekuvanje na JSON opseg
    if podatoci.get("_error"):  # ako ai javi greska pri interpretacijata
        return podatoci["_error"]  # se vrakja greskata direktno nazad

    od_datum, label = _period_to_dates(podatoci.get("period"))  # kalkulacija na pocetniot datum i tekstualnata oznaka

    conn = get_connection()  # ootvoranje vrska do MySQL bazata na podatoci
    cur = conn.cursor(dictionary=True)  # inicijalizacija na kursor koj vrakja redovi kako Python recnici

    sql = "SELECT status_pregled, COUNT(*) AS broj FROM Termin_pregled WHERE doctor_ID = %s"
    params: list = [doctor_id]  # postavuvanje na doctor_id kako bezbeden parametar
    if od_datum:  # ako imame definiran vremenski opseg, go dodavame vo WHERE uslovot
        sql += " AND datum_pregled >= %s"
        params.append(od_datum)  # dodavanje na datumot vo listata na parametri
    sql += " GROUP BY status_pregled"  # grupiranje na rezultatot
    cur.execute(sql, params)  # Izvrsuvanje na upitot
    statusi = {r["status_pregled"]: r["broj"] for r in cur.fetchall()}  # preslikuvanje na rezultatite vo brz rechnik

    # izvlekuvanje na brojkite so podrazbira vrednost 0 dokolku statusot voopsto ne stoi vo bazata
    zavrseni = statusi.get("завршен", 0)
    zakazani = statusi.get("закажан", 0)
    otkazani = statusi.get("откажан", 0)
    vkupno = sum(statusi.values())  # vkupen zbir na site zabelezani pregledi
# prosecna ocenka
    sql2 = (
        "SELECT AVG(F.ocena) AS prosek, COUNT(*) AS broj_ocena"
        " FROM Pregled_feedback F"
        " JOIN Termin_pregled T ON T.termin_ID = F.termin_ID"
        " WHERE T.doctor_ID = %s"
    )
    params2: list = [doctor_id]  # vtoriot upit
    if od_datum:  # vremenski filter i za ocenite vrz osnova na datumot na pregledot
        sql2 += " AND T.datum_pregled >= %s"
        params2.append(od_datum)
    cur.execute(sql2, params2)  # Izvrsuvanje na upitot za feedback
    ocena_row = cur.fetchone()  # Prevzemanje na presmetaniot red
    prosek = ocena_row["prosek"]  # Sredna vrednost na ocenite
    broj_ocena = ocena_row["broj_ocena"] or 0  # Vkupen broj na dobiveni ocenki

    # 3) Топ 3 пациенти (по број на завршени прегледи)
    sql3 = (
        "SELECT ime_pacient, COUNT(*) AS bp FROM Termin_pregled"
        " WHERE doctor_ID = %s AND status_pregled = 'завршен'"
    )
    params3: list = [doctor_id]  # Bezbedni parametri za tretiot upit
    if od_datum:  # Vremenski filter i za analizata na pacienti
        sql3 += " AND datum_pregled >= %s"
        params3.append(od_datum)
    sql3 += " GROUP BY ime_pacient ORDER BY bp DESC LIMIT 3"  # Grupacija, opagacko sortiranje i limit od top 3
    cur.execute(sql3, params3)  # Izvrsuvanje na top pacienti upitot
    top_pacienti = cur.fetchall()  # Prevzemanje na najaktivnite pacienti

    cur.close()  # Zatvoranje na kursorot
    conn.close()  # Zatvoranje na aktivnata MySQL konekcija

    # Изградба на одговор
    ime_lekar = f"{lekar.get('name','')} {lekar.get('surname','')}".strip() or "лекар"
    linii = [
        f"Статистики за д-р {ime_lekar} ({label}):",
        f"",
        f"Прегледи: {vkupno} вкупно",
        f"• Завршени: {zavrseni}",
        f"• Закажани: {zakazani}",
        f"• Откажани: {otkazani}",
        f"",
    ]
    
    # Ako lekarot ima dobiveno ocenki, formatiraj go prikazot zaedno so vizuelni zvezdicki
    if broj_ocena > 0 and prosek is not None:
        zvezdi = "★" * round(float(prosek))  # Generiranje na zvezdicki spored zaokruzenata ocena
        linii.append(f"Просечна оцена: {float(prosek):.2f} / 5  {zvezdi}")
        linii.append(f"Број на оцени: {broj_ocena}")
    else:
        linii.append("Просечна оцена: уште нема оцени.")

    # Ako ima pronajdeno pacienti, dodaj ja i listata na najcesti pacienti na krajot od porakata
    if top_pacienti:
        linii.append("")
        linii.append("Топ пациенти (по број на завршени прегледи):")
        for i, p in enumerate(top_pacienti, start=1):
            linii.append(f"{i}. {p['ime_pacient']}: {p['bp']}")

    return "\n".join(linii)  # Spojuvanje na site linii vo edinstven tekstualen izvestaj