import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers import lekari, pacienti, termini, admin, aparati, uslugi, novosti, kariera, ai_chat, facebook_sync

_FB_SYNC_INTERVAL_MIN = int(os.getenv("FB_SYNC_INTERVAL_MINUTES", "0") or "0")


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
    stop = threading.Event()

    def _periodic_fb_sync() -> None:
        if _FB_SYNC_INTERVAL_MIN <= 0:
            return
        import time
        from fb_sync import run_sync_if_configured

        while not stop.wait(timeout=_FB_SYNC_INTERVAL_MIN * 60):
            run_sync_if_configured()

    if _FB_SYNC_INTERVAL_MIN > 0:
        threading.Thread(target=_periodic_fb_sync, daemon=True).start()
    yield
    stop.set()


app = FastAPI(
    title="Клиничка Болница Штип – API",
    description="API за системот за управување со прегледи, термини и администрација",
    version="1.0",
    lifespan=_app_lifespan,
)
#dozvola za povik na api od frontend delot 
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

# Frontend фајлови (за развој) - сервирани од http://localhost:8000/
# Тоа решава Error 153 на YouTube embed-и кои не работат преку file:// протокол.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# site ruti gi povikuvam da ne mi e se vo main
app.include_router(lekari.router)
app.include_router(pacienti.router)
app.include_router(termini.router)
app.include_router(admin.router)
app.include_router(aparati.router)
app.include_router(uslugi.router)
app.include_router(novosti.router)
app.include_router(kariera.router)
app.include_router(kariera.app_router)  # /aplikacija (пријава за оглас)
app.include_router(ai_chat.router)  # AI чат со Groq (Llama 3.3)
app.include_router(facebook_sync.router)


@app.get("/")
def root():
    return {"message": "Клиничка Болница Штип – API", "docs": "/docs"}

# vie treba da gi proveram ama mislam deka nema da mi trebat, voa mi bese za debug 
@app.get("/debug-novosti")
def debug_novosti():
    """Приказ на slika_path и slike_extra за сите новости – за проверка што е во базата."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, naslov, slika_path, slike_extra FROM Novosti ORDER BY id")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {"novosti": rows}
    except Exception as e:
        return {"error": str(e)}

# isto i vaj endpoint nema da mi treba za kraj, prezentacija na proekt
@app.get("/debug-kariera")
def debug_kariera():
    """Приказ на огласи од Vrabotuvanje – за проверка зошто кариера не се прикажува."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id_oglas, pozicija, oddel, datum_na_prijavuvanje, status_oglas
            FROM Vrabotuvanje
            ORDER BY datum_na_prijavuvanje ASC
        """)
        rows = cur.fetchall()
        out = []
        for r in rows:
            row = cast(dict[str, Any], r)
            d = row.get("datum_na_prijavuvanje")
            rok = d.strftime("%d.%m.%Y") if d and hasattr(d, "strftime") else (str(d)[:10] if d else "")
            out.append({**row, "rok_str": rok})
        cur.close()
        conn.close()
        return {"count": len(out), "oglasi": out}
    except Exception as e:
        return {"error": str(e)}

# isto kako i prethodnite dva
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
                cnt = (
                    cast(dict[str, Any], rows[0]).get("c", len(rows))
                    if rows
                    else 0
                )
                results[name] = {"ok": True, "count": cnt}
            except Exception as e:
                results[name] = {"ok": False, "error": str(e)}
        cur.close()
        conn.close()
    except Exception as e:
        results["connection"] = f"ГРЕШКА: {e}"
    return results

# startuvanje lokalno
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
