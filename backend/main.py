from pathlib import Path  # biblioteka za patеки do papki i fajlovi
from typing import Any, cast  # tipovi za Python (Any = bilo što, cast = pretvorba na tip)

from fastapi import FastAPI  # glavnata klasa za web API
from fastapi.middleware.cors import CORSMiddleware  # dozvoluva frontend od drug domen da povikuva API
from fastapi.staticfiles import StaticFiles  # serviranje na sliki, CSS, HTML kako statički fajlovi
from routers import lekari, pacienti, termini, admin, aparati, uslugi, novosti, kariera, ai_chat  # site router moduli so ruti

app = FastAPI(  # kreiranje na FastAPI aplikacijata
    title="Клиничка Болница Штип – API",  # naslov što se gleda vo /docs
    description="API за системот за управување со прегледи, термини и администрација",  # kratok opis na API
    version="1.0",  # verzija na API
    servers=[  # base URL-ovi vo openapi.json (potrebno za GitBook "Test it" / Scalar)
        {"url": "https://klinicka-bolnica-stip2026.onrender.com", "description": "Produkcija (Render)"},
        {"url": "http://localhost:8000", "description": "Lokalen razvoj"},
    ],
)
app.add_middleware(  # dodavanje na CORS sloj (pred sekoj odgovor)
    CORSMiddleware,  # tip na middleware za cross-origin baranja
    allow_origins=["*"],  # dozvoleni izvori (* = site, samo za razvoj)
    allow_credentials=True,  # dozvoluva cookies / credentials vo baranjata
    allow_methods=["*"],  # dozvoleni HTTP metodi (GET, POST, ...)
    allow_headers=["*"],  # dozvoleni HTTP zaglavja
)
STATIC_DIR = Path(__file__).resolve().parent / "static"  # pateka do backend/static (sliki od novosti)
if STATIC_DIR.exists():  # proveri dali papkata postoi
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")  # URL /static → fajlovi od STATIC_DIR

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"  # pateka do frontend papkata (eden nivo nagore)
if FRONTEND_DIR.exists():  # ako frontend papkata postoi
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")  # serviranje na sajtot na /app (html=True = index.html)

app.include_router(lekari.router)  # ruti za lekari (login, lista, profil, ...)
app.include_router(pacienti.router)  # ruti za pacienti
app.include_router(termini.router)  # ruti za termini / pregledi
app.include_router(admin.router)  # ruti za admin panel
app.include_router(aparati.router)  # ruti za aparati
app.include_router(uslugi.router)  # ruti za uslugi
app.include_router(novosti.router)  # ruti za novosti
app.include_router(kariera.router)  # ruti za kariera / oglasi
app.include_router(kariera.app_router)  # posebni ruti za /aplikacija (prijava za rabota)
app.include_router(ai_chat.router)  # AI chat so Groq (asistentot)


@app.get("/")  # HTTP GET na korenot na API (/)
def root():  # funkcija koja go obrabotuva baranjeto
    return {"message": "Клиничка Болница Штип – API", "docs": "/docs"}  # JSON odgovor so poraka i link do dokumentacija


@app.get("/debug-novosti")  # privremen endpoint za test na novosti (debug)
def debug_novosti():  # funkcija za čitanje na novosti od baza
    """Приказ на slika_path и slike_extra за сите новости – за проверка што е во базата."""
    from database import get_connection  # funkcija za konekcija so MySQL
    try:  # probaj da se povrzeš so bazata
        conn = get_connection()  # otvori konekcija
        cur = conn.cursor(dictionary=True)  # kursor so rezultati kako rečnici (kluč = ime na kolona)
        cur.execute("SELECT id, naslov, slika_path, slike_extra FROM Novosti ORDER BY id")  # SQL: site novosti
        rows = cur.fetchall()  # zemi gi site redovi
        cur.close()  # zatvori kursor
        conn.close()  # zatvori konekcija
        return {"novosti": rows}  # vrati gi podatocite kako JSON
    except Exception as e:  # ako nešto padne (baza, SQL, ...)
        return {"error": str(e)}  # vrati ja greškata kako tekst


@app.get("/debug-kariera")  # privremen endpoint za oglasi za rabota
def debug_kariera():  # funkcija za lista na oglasi
    """Приказ на огласи од Vrabotuvanje – за проверка зошто кариера не се прикажува."""
    from database import get_connection  # konekcija so baza
    try:  # obidi se da čitaš
        conn = get_connection()  # konekcija
        cur = conn.cursor(dictionary=True)  # kursor so dict redovi
        cur.execute("""  # SQL so poveke redovi
            SELECT id_oglas, pozicija, oddel, datum_na_prijavuvanje, status_oglas
            FROM Vrabotuvanje
            ORDER BY datum_na_prijavuvanje ASC
        """)
        rows = cur.fetchall()  # site oglasi
        out = []  # prazna lista za formatiran izlez
        for r in rows:  # za sekoj red od bazata
            row = cast(dict[str, Any], r)  # pretvori go redot vo dict so tipovi
            d = row.get("datum_na_prijavuvanje")  # zemi go datumot na prijava
            rok = d.strftime("%d.%m.%Y") if d and hasattr(d, "strftime") else (str(d)[:10] if d else "")  # formatiraj datum ili prazno
            out.append({**row, "rok_str": rok})  # dodadi go formatiraniot datum vo rečnikot
        cur.close()  # zatvori kursor
        conn.close()  # zatvori konekcija
        return {"count": len(out), "oglasi": out}  # kolku oglasi + lista
    except Exception as e:  # greška
        return {"error": str(e)}  # vrati greška


@app.get("/debug-db")  # proverka dali bazata i tabelite rabotat
def debug_db():  # funkcija za test na konekcija i tabeli
    """Проверка на конекција и табели – прикажува точна грешка при проблем."""
    from database import get_connection  # konekcija so MySQL
    results = {}  # rečnik za rezultati od testovite
    try:  # glaven try blok
        conn = get_connection()  # konekcija
        results["connection"] = "OK"  # konekcijata e uspešna
        cur = conn.cursor(dictionary=True)  # kursor
        tests = [  # lista na tabeli i SQL što ke se izvršat
            ("Doctors", "SELECT COUNT(*) as c FROM Doctors"),
            ("Oddeli", "SELECT ime_na_oddel FROM Oddeli LIMIT 1"),
            ("Vrabotuvanje", "SELECT id_oglas, pozicija, oddel, datum_na_prijavuvanje FROM Vrabotuvanje LIMIT 1"),
            ("Novosti", "SELECT id, naslov FROM Novosti LIMIT 1"),
        ]
        for name, sql in tests:  # za sekoja tabela
            try:  # probaj query
                cur.execute(sql)  # izvrši SQL
                rows = cur.fetchall()  # rezultati
                cnt = (  # brojka za prikaz
                    cast(dict[str, Any], rows[0]).get("c", len(rows))  # COUNT ili broj na redovi
                    if rows  # ako ima baranje eden red
                    else 0  # inaku 0
                )
                results[name] = {"ok": True, "count": cnt}  # tabelata e OK
            except Exception as e:  # greška na konkretna tabela
                results[name] = {"ok": False, "error": str(e)}  # zabeleži greška
        cur.close()  # zatvori kursor
        conn.close()  # zatvori konekcija
    except Exception as e:  # ne može da se povrze so bazata
        results["connection"] = f"ГРЕШКА: {e}"  # zabeleži greška na konekcija
    return results  # vrati gi site test rezultati


if __name__ == "__main__":  # samo ako go startuvaš so: python main.py
    import uvicorn  # ASGI server za FastAPI
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)  # start na server (reload = avtomatski restart pri promena)
