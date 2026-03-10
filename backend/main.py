import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import lekari, pacienti, termini, aparati, uslugi, kariera, admin, novosti

app = FastAPI(title="Клиничка Болница Штип API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).resolve().parent / "static" / "uploads"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(static_dir)), name="uploads")

app.include_router(lekari.router)
app.include_router(pacienti.router)
app.include_router(termini.router)
app.include_router(aparati.router)
app.include_router(uslugi.router)
app.include_router(kariera.router)
app.include_router(kariera.app_router)
app.include_router(admin.router)
app.include_router(novosti.router)

if __name__ == "__main__":          # proverka dali e startuvam fajlot direktno
    import uvicorn              # se importira uvicorn 
    uvicorn.run(app, host="127.0.0.1", port=8000) # se startuva serverot na dadenata ip adresa i porta  ama raboti so vaj mani da e ne so tvoj 
