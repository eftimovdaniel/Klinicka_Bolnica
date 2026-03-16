import traceback
from fastapi import APIRouter, HTTPException
from database import get_connection

router = APIRouter(tags=["uslugi"])

@router.get("/specialnosti")              
def get_specialnosti():         # funkcija so ime get_specialnosti(): bez nikakvi prosledeni argumeti
    conn = None                 # nemam vospostaveno konekcija so baza
    try:
        conn = get_connection()         # ostvaruvame konekcija so bazata na podatoci
        db_cursor = conn.cursor(dictionary=True)       # db_cursor posrednik so bazata na podatoci, dictionary=True ni dava izlez
        # se pravi DISTINCT selekcija vo bazata na podatoci, ova go koristam bidejki ima poveke lekari od ista specijalnost, i za da ne mi se pokazuvat povise isti specijalnosti
        # gi zemem lekarite kade ima postavena nekoja specijalnost, znaci deka nema ne null vrednost kaj specijalnosta
        # se podreduvaat po azbucen redosled na specijalnosti 
        db_cursor.execute("""
            SELECT DISTINCT specialty as specijalnost
            FROM Doctors 
            WHERE specialty IS NOT NULL AND specialty != ''
            ORDER BY specialty
        """)
        specialnosti = db_cursor.fetchall()        # se zemaat site karakteri od bazata i se zapisuvaat vo specijalnosta 
        return specialnosti         # dava gi site specijalnosti so koj raspolagame, koi se vneseni vo database 
    # ako nastane greska se frla Exception so statusen kod 500 i objasnuvanje smensteno vo e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))    
    finally:
        if conn and conn.is_connected():                # se proveruva za konekcija, ako ima aktivna konekcija se zatvara
            conn.close()


@router.get("/uslugi")
def get_uslugi():       # funkcija za da se prikazat site uslugi na KB, nema prosledeni nikakvi argumenti
    conn = None         # se postavuva na pocetok kako da nema konekcija, i sleduva try blok
    try:                
        conn = get_connection()                 # konekcija so bazata na podatoci
        db_cursor = conn.cursor(dictionary=True) # db_cursor objekt sto ovozmozuva da se vrsi sql naredba, argumento (dictionary=True) ni go dava izlezot kako recenica ne kako tuples
        # od bazata na se zema tabela Oddeli i se selektira imet na oddelot, po azbucen redosled
        db_cursor.execute("SELECT ime_na_oddel AS naziv FROM Oddeli ORDER BY ime_na_oddel")     
        rows = db_cursor.fetchall()                # se zemaat site redovi od tabelata i se smestuvaat vo rows
        return [{"naziv": (r.get("naziv") or "").strip()} for r in rows]  # procesiranje na podatocite, se zemaat iminjata na oddelite, ako e prazno, se pravi prazen string
                                                                            # se otstranuvaat site prazni mesta, i se kreira lista na uslugi za frontend delot
        # dokulku nastane greska se vraka Exception m so statusen kod 500 i fraza za objasnuvanje na kodot 
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))         
    finally:                                                            # blok za proverka   
        if conn and conn.is_connected():                                # se proveruva za konekcija, ako najde aktivna konekcija se zatvara
            conn.close()


