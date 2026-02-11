from fastapi import APIRouter, HTTPException, Request
from datetime import datetime
from database import get_connection

router = APIRouter(prefix="/termini", tags=["termini"])

@router.get("/dostapni")
def get_dostapni_termini(lekar_id: int, datum: str):    # funkcija koja dava prikaz koj lekar ima sloboden termin, id na lekarot e od tip int, a datum e string
    conn = None                 # nema konekcija pri aktiviranje 
    try:
        if "T" in datum:            # proverka dali vnesot e vo ISO fromat(yy-mm-dd T hh:mm:ss), T go deli vremeto od datumot na pregled
            datum = datum.split("T")[0] # se pravi podelba na mestoto kade e zapisno T ni dava format datum , vreme
                                        # [0] go zema prviot element od listata, toa e datumot (datum T vreme)

        d = datetime.strptime(datum, "%Y-%m-%d").date() # izbraniot string e smesten vo d za proverka na delovi vo nedelata, d se koriste za den 
                                                        # strptime parsiranje na string vo data

        if d.weekday() >= 5:        # proverka dali e vikend, d treba da e pogolemo od 5, sabota i nedela se 6 7 
            return []                  # se vraka prazna lista, nema moznost da se zakaze termin 
        conn = get_connection()         # ostvaruvanje konekcija so bazata 
        db_cursor = conn.cursor(dictionary=True)   # posrednik so bazata na podatoci 
        # se selektira vremeto na pregled od soodvetna tabela
        # ВАЖНО: Според базата, колоната за статус е status_pregled
        # so vneseno ime na lekar i imame status na zakazan pregled
        # СИНХРОНИЗАЦИЈА: Вклучи ги и термините на апарати за да се синхронизираат календарите
        db_cursor.execute("""
            SELECT TIME(vreme_pregled) as vreme
            FROM Termin_pregled
            WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status_pregled = 'закажан'
            UNION
            SELECT TIME(vreme_pregled) as vreme
            FROM Aparati_termini
            WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status != 'откажан'
        """, (lekar_id, datum, lekar_id, datum))         # dve vrednosti za dve prazni mesta (%s) vo SQL
                                        # lekar_id odi vo prviot %s, datum odi vo vtoriot %s
        rows = db_cursor.fetchall()    # se zemaat site zafateni termini kaj lekar
        out = []                    # lista za vreme
        for r in rows:                 # r minuva niz site rows, odnosno niz site zafateni termini
            v = r.get("vreme")      # v go zima vremeto od redovite
            if v is None:           # ako nema vreme, nema zafaten termin se prodolzuva
                continue
            if hasattr(v, "strftime"):         # hasattr proveruva dali postoi strftime, strftime go dobivam avtomstski bidejki vremeto vo bazata mi e datatime, ako e string ne mora 
                out.append(v.strftime("%H:%M"))  # formatiranje na vremeto spored tip nna cas:minuta
            elif hasattr(v, "total_seconds"):       # proverka dali ima total_seconds    
                s = int(v.total_seconds())          # konverzija vo seknudi 
                out.append(f"{s // 3600:02d}:{(s % 3600) // 60:02d}")       # se pretvara vo cas: minuti format
            else:
                out.append(str(v)[:5])  # za drugi tipovi na podatoci, se pretvara vo string i se zema prvite 5 karaktera
        return out
    # nevazecki format na veneso, so status kod
    except ValueError:
        raise HTTPException(status_code=400, detail="Неважечки формат на датум")
    # ostanatie greski, so statusen kod 500 i string za objasnuvanje
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # blok kade se traze ako ima konekcija, ako ima aktivna se naoga i se zatvara.
    finally:
        if conn and conn.is_connected():       
            conn.close()


@router.post("")
async def create_termini(request: Request):     # funkcija koja ceka podatoci od klientot 
    conn = None
    try:
        data = await request.json()     # gi zema podatocite od frontend vo vid JSON
        datum_str = data.get("datum", "")       # se zema datumot od formata 
        if "T" in datum_str:               # se pravi proverka dali e vo ISO format 
            datum_str = datum_str.split("T")[0]     # se deli na mestoto na T i se zema samo datumot 
        try:
            # proverka na datumot , konvertiranje na string vo data ovjekt 
            appointment_date = datetime.strptime(datum_str, "%Y-%m-%d").date()
            if appointment_date.weekday() >= 5:     # proverka dali e vikend (sabota i nedela)
                raise HTTPException(    # ako e vikend se javuva greska, so stausen kod i objasnuvanje
                    status_code=400, detail="Не се закажуваат прегледи во сабота и недела. Изберете друг датум."
                )
        except ValueError:   # ako e izbran nevazecki datum
            raise HTTPException(status_code=400, detail="Неважечки формат на датум")
        # se zema vremeto za obrabotka, odnosno delot sto se naoga posle T
        vreme_str = data.get("vreme", "")   # go zema vremeto od podatocite
        if ":" in vreme_str:    # se pravi proverka dali e so :
            parts = vreme_str.split(":")    # se deli na cas i minuti 
            vreme_str = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"      # .zfill(2) = додава водечка нула (2→02, 5→05), sekogas ke e vo oblik 13:06 ili slicno 

        conn = get_connection()         # konekcija so bazata 
        db_cursor = conn.cursor(dictionary=True)       # posrednik so bazata
        # prv povik, se proveruva dali lekar postoi
        db_cursor.execute("SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s", (data['lekar_id'],))
        doctor = db_cursor.fetchone()          # se zema najdobriot lekar
        if not doctor:          # ako ne e pronajden lekar
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")
        # vtor povik, da se proveri dali termin e veke zakazan
        # ВАЖНО: Според базата, колоната за статус е status_pregled
        db_cursor.execute("""
            SELECT termin_ID FROM Termin_pregled
            WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND TIME(vreme_pregled) = %s AND status_pregled = 'закажан'
        """, (data['lekar_id'], datum_str, vreme_str))
        if db_cursor.fetchone():
            raise HTTPException(status_code=409, detail="Овој термин е веќе закажан. Изберете друго време.")
        # povik da vnesenite podatoci se vnesat vo bazata za da se zakaze termin 
        # se vnesuvaat id na lekat, ime na pacient, spacijalnost, ime na lekar, datum na pregled, email na pacienti i napomena dokolku e potreba do lekarot
        db_cursor.execute("""
            INSERT INTO Termin_pregled 
            (doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, datum_pregled, vreme_pregled, status_pregled, email_pacient, telefon_pacient, napomena)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['lekar_id'],       # se zapisuva id na lekaror
            data['ime'] + " " + data['prezime'],        # ime i prezime
            doctor['specialty'],            # speciјалност
            doctor['name'] + " " + doctor['surname'], # ime i prezime na lekar
            datum_str,          # datum
            vreme_str,          # vreme
            'закажан',          # status na pregledot 
            data.get('email', ''),      # email na pacient
            data.get('telefon', ''),    # telefon na pacitne
            data.get('napomena', '')    # napomena od pacient do lekar
        ))
        conn.commit()       # se pravi promena vo bazata, se zacuvuva sekoja promena
        appointment_id = db_cursor.lastrowid   #Se zima id to na novozakazaniot termin

        return {
            "message": "Терминот е успешно закажан!",       # pecatenje na poraka deka imame uspesno zakazan termin
            "appointment_ID": appointment_id
        }
    except HTTPException:                   # formatirana greska
        raise
    except Exception as e:              # bilo koja druga greksa, so statusen kod i soodvetno objasnuvanje
        raise HTTPException(status_code=500, detail=str(e))
    finally:                    # blok koj ja zatvara konekcija bez razlika dali ima ili nema greska
        if conn and conn.is_connected():
            conn.close()


@router.patch("/{termin_id}")
async def update_termin_dijagnoza_terapija(termin_id: int, request: Request):   # funkcija za update na dijagnoza i terapija so id na termin
    conn = None
    try:
        data = await request.json()  # gi zema podatocite od frontend (JSON)
        dijagnoza = data.get("dijagnoza")  # dijagnoza moze da bide string ili None
        terapija = data.get("terapija")    # terapija moze da bide string ili None
        
        conn = get_connection()         # konekcija so bazata na podatoci
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            "SELECT termin_ID FROM Termin_pregled WHERE termin_ID = %s",
            (termin_id,)
        )
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Термин не е пронајден")
        db_cursor.execute(
            "UPDATE Termin_pregled SET dijagnoza = %s, terapija = %s WHERE termin_ID = %s",
            ((dijagnoza or "").strip() or None, (terapija or "").strip() or None, termin_id)
        )
        conn.commit()       # se pravi promena vo bazata, se zacuvuva
        return {"message": "Дијагноза и терапија се ажурирани."}
    except HTTPException:               # formatirana greska
        raise
    except Exception as e:              # dokolku se javi bilo koja druga greska
        raise HTTPException(status_code=500, detail=str(e))   # statusen kod 500 i objasnuvanje smesteno vo e
    finally:                        # se proveruva dali ima konekcija, ako ima se zatvara, se izvrasuva bez razlika dali ima ili nema greksa
        if conn and conn.is_connected():
            conn.close()


