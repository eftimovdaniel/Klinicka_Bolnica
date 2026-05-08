# import na funkcija za proverka na admin pristap od admin routerot
from routers.admin import check_admin_access


# pomosna funkcija koja go vlece ID-to na lekarot od recnicite pacient i state
def _extract_actor_id(pacient: dict, state: dict) -> int:
    # se obiduvame da go pronajdeme ID-to po prioritet od poveke moznosti (razlicni klucevi)
    raw_id = (
        (pacient or {}).get("doctor_ID") # prvo se proveruva dali postoi kluc 'doctor_ID' vo pacient
        or (pacient or {}).get("doctor_id")  # ako ne postoi, se proveruva varijantata 'doctor_id' (mali bukvi)
        or (pacient or {}).get("id")  # ako ne postoi ni toa, se proveruva opstiot kluc 'id'
        or (state or {}).get("admin_doctor_id")  # potoa se proveruva 'admin_doctor_id' vo state recnikot
        or (state or {}).get("doctor_id") # i na kraj 'doctor_id' vo state recnikot
    )
    # se obiduvame da go konvertirame vo cel broj
    try:
        return int(raw_id)   # vrakame go celiot broj ako uspee konverzijata
    # ako ne uspee, se vraka 0 kako default vrednost
    except Exception:
        return 0

# prikaz na site lekari dokolku se pobara od daden pacient da se prikazat lekarite
# podatocite gi vademe od bazata na podatocite so execute, so id na lekarot
def _doctor_display_name(db_cursor, doctor_id: int) -> str:
    # izvrsuvanje na upit od bazata na podatoci za vlecenje na ime i prezime na lekarot
    db_cursor.execute(
        """
        SELECT name, surname
        FROM Doctors
        WHERE doctor_ID = %s
        LIMIT 1
        """,
        # parameter na upitot: ID-to na lekarot
        (doctor_id,),
    )
    # se vlece konkreten lekar
    # vo full gi smestuvame celosno ime i prezime
    # kade se pecate celoto ime i prezime na lekarot, ili negovoto id
    row = db_cursor.fetchone() or {}
    full = f"{row.get('name', '')} {row.get('surname', '')}".strip() #string vo koj e smesteno imeto i prezimeto a so strip se trgat praznite mesta
    return full or f"ID {doctor_id}"  # ako nema ime/prezime, vrakame samo ID kako fallback

# prikaz na the appointmensts na lekarot za konkreten den, se zimaat od bazata na podatoci
def _load_doctor_day_appointments(db_cursor, doctor_id: int):
    # vlecam podatoci od bazata na podatoci za konkreten lekar sto e vnesen, tekovno najaven na sisitemot
    # site podatoci gi zimame od konkretno vreme vo smisla od momento od koga e pobarana ili napravenot baranjeto
    # se vrakaat vo nasoka pocnuvajki od najraniot do posledniot termin kaj toj lekar 
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
        # parameter na upitot: ID-to na lekarot za koj se baraat terminite
        (doctor_id,),
    )
    # vraka gi site termini koi se zakazani ili vraka mi prazna lista dokolku nemam termini kaj taj lekar, pacienti za pregled
    return db_cursor.fetchall() or []

# glavna funkcija koja go obrabotuva baranjeto na lekarot vo zavisnost od intentot
# spored intentot odlucuva koj del od kodot ke se izvrsi (raspored, sleden pacient, docnenja ili pregled na site lekari)
def handle_doctor_action(intent: str, db_cursor, prompt: str, pacient: dict, state: dict):
    # parametarot prompt ne se koristi ovde, pa go ignorirame
    _ = prompt
    # se vlece ID na trenutno najaveniot lekar od pacient ili od state
    actor_doctor_id = _extract_actor_id(pacient, state)

    # proverka dali intentot e nekoja od trite akcii sto baraat lekar da bide najaven
    if intent in ("doctor_today_schedule", "doctor_next_patient", "doctor_delayed_patients"):
        # dokolku nema najaven lekar (ID e 0 ili None), vrakame poraka so greska
        if not actor_doctor_id:
            # vrakame recnik so ok=False koj signaliziraza neuspeh
            return {
                "ok": False,
                "intent": intent,
                "message": "За оваа функција мора да сте најавени како лекар.",
                "state": state,
            }

        # se zima imeto na lekarot za prikaz vo porakata preku pomosnata funkcija
        doctor_name = _doctor_display_name(db_cursor, int(actor_doctor_id))
        # se vlecat site denesni termini kaj toj lekar od bazata
        day_items = _load_doctor_day_appointments(db_cursor, int(actor_doctor_id))

        # akcija koja go vraka celiot raspored za denesniot den
        if intent == "doctor_today_schedule":
            # dokolku nemame ni eden termin, vrakame poraka deka nema zakazani pacienti
            if not day_items:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Д-р {doctor_name}, денес немате закажани пациенти.",
                    "state": state,
                }
            # se inicijalizira lista so prva linija (zaglavie so brojot na pacienti)
            lines = [f"Д-р {doctor_name}, денес имате {len(day_items)} закажани пациенти:"]
            # iteracija niz prvite 12 termini, indeksot pocnuva od 1 za prikaz
            for i, row in enumerate(day_items[:12], start=1):
                # se zima imeto na pacientot, ako nema vraka 'Непознат пациент'
                patient = (row.get("ime_pacient") or "Непознат пациент").strip()
                # se zima napomenata ako postoi
                note = (row.get("napomena") or "").strip()
                # ako ima napomena, ja stavame vo zagradi za prikaz
                extra = f" ({note})" if note else ""
                # dodavanje na linija so reden broj, vreme, pacient i napomena
                lines.append(f"{i}. {row.get('vreme')} - {patient}{extra}")
            # dodavanje na pomosna poraka za korisnikot na krajot
            lines.append("Можете да прашате и: „Кој е следен?“ или „Кој доцни?“")
            # vrakanje na uspesen rezultat so site formirani linii spoeni so nov red
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": state,
            }

        # akcija koja go vraka samo sledniot pacient na lekarot za denes
        if intent == "doctor_next_patient":
            # upit od bazata na podatoci koj go zima prviot termin po tekovnoto vreme
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
                # parameter na upitot: ID na lekarot
                (int(actor_doctor_id),),
            )
            # se vlece eden red od rezultatot ili prazen recnik dokolku nema rezultat
            next_row = db_cursor.fetchone() or {}
            # dokolku nema sleden pacient, vrakame poraka deka site termini se pominati
            if not next_row:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Д-р {doctor_name}, нема следен пациент за денес (или сите термини се поминати).",
                    "state": state,
                }
            # se zima napomenata ako postoi
            note = (next_row.get("napomena") or "").strip()
            # se gradi tekstot za napomenata samo ako e neprazna
            note_text = f" Напомена: {note}." if note else ""
            # vrakanje na poraka so podatoci za sledniot pacient
            return {
                "ok": True,
                "intent": intent,
                "message": (
                    f"Следен пациент: {next_row.get('ime_pacient')} во {next_row.get('vreme')}."
                    f"{note_text}"
                ),
                "state": state,
            }

        # akcija koja prikazuva pacienti sto docnat na svoite zakazani termini
        if intent == "doctor_delayed_patients":
            # upit od bazata na podatoci koj gi vlece terminite koi vekje pominale a sé uste se zakazani
            # TIMESTAMPDIFF presmetuva kolku minuti docni sekoj pacient
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
                # parameter na upitot: ID na lekarot
                (int(actor_doctor_id),),
            )
            # se zimaat site redovi ili prazna lista ako nema rezultati
            delayed_rows = db_cursor.fetchall() or []
            # dokolku nema pacienti sto docnat, vrakame soodvetna poraka
            if not delayed_rows:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Д-р {doctor_name}, во моментов нема пациенти што доцнат.",
                    "state": state,
                }
            # inicijalizacija na listata so zaglavie
            lines = ["Пациенти што доцнат за денешни термини:"]
            # iteracija niz prvite 10 pacienti sto docnat
            for row in delayed_rows[:10]:
                # se zima docnenjeto vo minuti, ako e None se zema 0
                delay_m = int(row.get("delay_minutes") or 0)
                # dodavanje na formatirana linija so pacient, vreme na termin i docnenje (max za da ne ide negativno)
                lines.append(f"- {row.get('ime_pacient')} (термин {row.get('vreme')}, доцни {max(delay_m, 0)} мин.)")
            # vrakanje na uspesna poraka so site linii spoeni
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": state,
            }

    # akcija koja prikazuva pregled na site pacienti po lekari (samo za admin/direktor)
    if intent == "doctor_patients_overview":
        # proverka za admin pristap; ako ne e admin, vrakame poraka deka informacijata e nedostapna
        if not actor_doctor_id or not check_admin_access(int(actor_doctor_id)):
            return {
                "ok": False,
                "intent": intent,
                "message": "Оваа информација е достапна само за директор/админ.",
                "state": state,
            }
        # SQL upit koj gi vlece site denesni termini sortirani po lekar i potoa po vreme
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
        # se zimaat site redovi od bazata ili prazna lista
        rows = db_cursor.fetchall() or []
        # ako nema termini denes kaj nieden lekar, vrakame poraka
        if not rows:
            return {
                "ok": True,
                "intent": intent,
                "message": "Денес нема закажани пациенти кај лекарите.",
                "state": state,
            }

        # recnik vo koj ke gi grupirame terminite po lekar (kluc = ime na lekar)
        grouped = {}
        # iteracija niz site redovi od bazata
        for r in rows:
            doctor = (r.get("ime_lekar") or "Непознат лекар").strip() # se zima imeto na lekarot, ako nema fallback e 'Непознат лекар'
            patient = (r.get("ime_pacient") or "Непознат пациент").strip()  # se zima imeto na pacientot, fallback 'Непознат пациент'
            time_str = (r.get("vreme") or "").strip() # se zima vremeto na pregled vo string format
            grouped.setdefault(doctor, []).append((time_str, patient)) # dodavanje na (vreme, pacient) vo listata kaj toj lekar (ja kreira ako ne postoi)

        # se gradi konecnata poraka so zaglavie
        lines = ["Денешна распределба по лекари:"]
        # iteracija niz grupiraniot recnik (lekar -> lista na termini)
        for doctor, items in grouped.items():
            lines.append(f"- Д-р {doctor}:") # dodavanje na red so imeto na lekarot
            for time_str, patient in items[:12]:  # iteracija niz prvite 12 termini kaj toj lekar
                lines.append(f"  • {time_str} - {patient}") # dodavanje na formatirana linija so vreme i ime na pacient
        # vrakanje na uspesna poraka so site formirani linii
        return {
            "ok": True,
            "intent": intent,
            "message": "\n".join(lines),
            "state": state,
        }
    return None  #dokolku intentot ne odgovara na nikoja od podderzhanite akcii, vrakame None
