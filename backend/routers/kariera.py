import traceback
from collections.abc import Mapping
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile
from datetime import datetime
from database import get_connection
from vrabotuvanje_helpers import fetch_aktivni_oglasi_rows, row_to_oglas_public

router = APIRouter(prefix="/kariera", tags=["kariera"])


def _form_str(form: Mapping[str, Any], key: str) -> str:
    """Текст од multipart/form — Pylance: form.get() може да врати UploadFile."""
    raw = form.get(key)
    if raw is None or isinstance(raw, UploadFile):
        return ""
    return str(raw).strip()


def _parse_int_or_none(val: Any) -> int | None:
    if val is None or isinstance(val, UploadFile):
        return None
    if not val:
        return None
    try:
        cleaned = str(val).strip().replace(" ", "").replace("-", "")
        return int(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None

@router.get("")
def get_kariera():          # funkcija koja e namenuvana za da gi vrati site aktivni oglasi za rabota, soodvetno filtrirani i podredeni
    conn = None             # se postavuva konekcijata da e zatvorena
    try:
        conn = get_connection()     # ostvaruvanje so bazata na podatoci 
        db_cursor = conn.cursor(dictionary=True) # db_cursor objekt sto ovozmozuva da se vrsi sql naredba, argumento (dictionary=True) ni go dava izlezot kak orecenica ne kako tuples
        # se selektira id na oglas, pozicija i oddel, datum na prijavuvanje
        # podatocite se zemeni og tabela Vraboteni kade statusot na oglas ne ne null vrednost ili e uste aktiven, != 'завршен'
        # se podreduvaat spored datum na prijava, prednost e na posleniot oglas
        rows = fetch_aktivni_oglasi_rows(db_cursor)
        return [row_to_oglas_public(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:                      # pojava na greska so soodveten kod i poraka do lekar ili korisnik 
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:                                        # krein blok kade se zatvra sekoja otvorena konekcija
        if conn and conn.is_connected():
            conn.close()


# /aplikacija endpoint без prefix бидејќи не е под /kariera
# Креираме посебен router за /aplikacija
app_router = APIRouter(tags=["kariera"])

@app_router.post("/aplikacija")
async def create_aplikacija(request: Request):          # site prijaveni kandidati na oglasi
    conn = None
    try:
        form_data = await request.form()
        pozicija = _form_str(form_data, "pozicija")
        id_oglas_value = _parse_int_or_none(form_data.get("id_oglas"))
        ime = _form_str(form_data, "ime")
        prezime = _form_str(form_data, "prezime")
        email = _form_str(form_data, "email")
        telefon = _parse_int_or_none(form_data.get("telefon"))
        broj_med_lic = _parse_int_or_none(form_data.get("broj_med_licenca"))

        if not pozicija:        # proverka dali e izbrana pozicija
            raise HTTPException(status_code=400, detail="Изберете позиција од листата.")
        if not ime or not prezime:       # proverka dali e vneseno ime i prezime
            raise HTTPException(status_code=400, detail="Внесете име и презиме.")
        if not email:               # proverka za vnes na email
            raise HTTPException(status_code=400, detail="Внесете е-пошта.")
        
        conn = get_connection()         # konekcija so bazata
        db_cursor = conn.cursor(dictionary=True)          # db_cursor za SQL
        
        # datum na prijava
        datum_prijava = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        db_cursor.execute("""
            INSERT INTO prijaveni_lekari (id_oglas, pozicija, ime_lekar, prezime_lekar, broj_med_licenca, email, telefon, datum_prijava)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_oglas_value, pozicija, ime, prezime, broj_med_lic, email, telefon, datum_prijava))
        conn.commit()           # se pravat promeni vo bazata na podatoci, se zacuvuva promena
        return {"message": "Апликацијата е успешно испратена!"}
    except HTTPException:           # formatirana greska
        raise
    except ValueError:              # se probuva da se aplicira na oglas koj nema validen id 
        raise HTTPException(status_code=400, detail="Неважечки id_oglas.")
    except Exception as e:          # site ostanati tipovi na greski 
        raise HTTPException(status_code=500, detail=str(e))
    finally:                    # blok koj ja zatvara konekcija bez razlika dali ima ili nema greska
        if conn and conn.is_connected():
            conn.close()


# endpoint za postavuvanje, kreiranje na novi oglasi za rabota
@router.post("/oglas")
async def create_oglas(request: Request):    # funkcija za kreiranje na nov oglas za rabota
    conn = None
    try:
        data = await request.json()     # gi zemaat podatocite od frontend vo vid JSON
        pozicija = (data.get("pozicija") or "").strip()  # se zema izbranata pozicija od lista (selektirana so klik od /specialnosti endpoint)
        oddel = (data.get("oddel") or "").strip()  # se zema oddelot (npr. "Кардиологија", "Хирургија")
        datum_na_objava = data.get("datum_na_objava")  # datum koga e objaven oglasot
        datum_na_prijavuvanje = data.get("datum_na_prijavuvanje")  # datum do koj moze da se aplicira (rok za prijava)
        status_oglas = (data.get("status_oglas") or "").strip()  # status na oglasot (moze da bide NULL, "активен", "завршен")
        
        if not pozicija:        # proverka dali e izbrana pozicija od lista
            raise HTTPException(status_code=400, detail="Внесете позиција.")
        if not oddel:       # proverka dali e vnesen oddel
            raise HTTPException(status_code=400, detail="Внесете оддел.")
        
        conn = get_connection()         # konekcija so bazata
        db_cursor = conn.cursor(dictionary=True)       # posrednik so bazata
        
        
        # formatiranje na datumite ako se stringovi - proverka i konverzija vo datetime objekt
        # ova e potrebno bidejki frontend moze da prati datum kako string vo razlicni formati
        if isinstance(datum_na_objava, str):
            try:
                # probuvame da go parsiraме kako "YYYY-MM-DD HH:MM:SS" format
                datum_na_objava = datetime.strptime(datum_na_objava, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    # ako ne uspee, probuvame kako "YYYY-MM-DD" format
                    datum_na_objava = datetime.strptime(datum_na_objava, "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Неважечки формат на датум на објава.")
        
        if isinstance(datum_na_prijavuvanje, str):
            try:
                # probuvame da go parsiraме kako "YYYY-MM-DD HH:MM:SS" format
                datum_na_prijavuvanje = datetime.strptime(datum_na_prijavuvanje, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    # ako ne uspee, probuvame kako "YYYY-MM-DD" format
                    datum_na_prijavuvanje = datetime.strptime(datum_na_prijavuvanje, "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Неважечки формат на датум на пријавување.")
        
        # vnes na podatocite vo tabelata Vrabotuvanje
        # se vnesuvaat: pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas
        # id_oglas e auto-increment
        db_cursor.execute("""
            INSERT INTO Vrabotuvanje (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            pozicija,           # pozicijata za koja se bara lekar
            oddel,              # oddelot kade e pozicijata
            datum_na_objava,    # datum koga e objaven oglasot
            datum_na_prijavuvanje,  # datum do koj moze da se aplicira
            status_oglas if status_oglas else None  # status na oglasot, ako ne e vnesen e NULL
        ))
        conn.commit()       # se pravi promena vo bazata, se zacuvuva
        oglas_id = db_cursor.lastrowid   # se zima id na noviot oglas (auto-increment vrednosta)
        
        return {
            "message": "Огласот е успешно креиран!",
            "id_oglas": oglas_id      # vrakanje na id na noviot oglas za da frontend moze da go koristi
        }
    except HTTPException:                   # formatirana greska
        raise
    except Exception as e:              # bilo koja druga greska, so statusen kod i soodvetno objasnuvanje
        raise HTTPException(status_code=500, detail=str(e))
    
    # za pogolema bezbednost, zatvaranje na site konekcii
    finally:                    # blok koj ja zatvara konekcija bez razlika dali ima ili nema greska
        if conn and conn.is_connected():
            conn.close()


