"""
Главна точка за стартување на FastAPI апликацијата – Клиничка Болница Штип.
Стартување: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import lekari, pacienti, termini, admin, aparati, uslugi, novosti, kariera

app = FastAPI(
    title="Клиничка Болница Штип – API",
    description="API за системот за управување со прегледи, термини и администрација",
    version="1.0",
)

# CORS – дозволи повици од frontend (localhost или друг домен)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статички фајлови (слики од новости, итн.)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Рутери
app.include_router(lekari.router)
app.include_router(pacienti.router)
app.include_router(termini.router)
app.include_router(admin.router)
app.include_router(aparati.router)
app.include_router(uslugi.router)
app.include_router(novosti.router)
app.include_router(kariera.router)
app.include_router(kariera.app_router)  # /aplikacija (пријава за оглас)


@app.get("/")
def root():
    return {"message": "Клиничка Болница Штип – API", "docs": "/docs"}


@app.get("/debug-db")
def debug_db():
    """Проверка на конекција и табели – прикажува точна грешка при проблем."""
    from database import get_connection
    results = {}
    try:
        conn = get_connection()
        results["connection"] = "OK"
        cur = conn.cursor(dictionary=True)
        # Тест на табели (истите query-и како endpoints)
        tests = [
            ("Doctors", "SELECT COUNT(*) as c FROM Doctors"),
            ("Oddeli", "SELECT ime_na_oddel FROM Oddeli LIMIT 1"),
            ("Vrabotuvanje", "SELECT id_oglas, pozicija, oddel, datum_na_prijavuvanje FROM Vrabotuvanje LIMIT 1"),
            ("Novosti", "SELECT id, naslov FROM Novosti LIMIT 1"),
        ]
        for name, sql in tests:
            try:
                cur.execute(sql)
                rows = cur.fetchall()
                cnt = rows[0].get("c", len(rows)) if rows else 0
                results[name] = {"ok": True, "count": cnt}
            except Exception as e:
                results[name] = {"ok": False, "error": str(e)}
        cur.close()
        conn.close()
    except Exception as e:
        results["connection"] = f"ГРЕШКА: {e}"
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
