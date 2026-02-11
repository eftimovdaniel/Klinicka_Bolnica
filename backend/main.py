from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routers import lekari, pacienti, termini, aparati, uslugi, kariera, admin

app = FastAPI(title="Клиничка Болница Штип API")

# CORS middleware за дозвола на повици од frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint кој враќа информации за API-то"""
    return JSONResponse(
        content={
            "message": "Клиничка Болница Штип API",
            "version": "1.0.0",
            "docs": "/docs",
            "redoc": "/redoc",
            "endpoints": {
                "lekari": "/lekari",
                "pacienti": "/pacienti",
                "termini": "/termini",
                "aparati": "/aparati",
                "uslugi": "/uslugi",
                "kariera": "/kariera",
                "admin": "/admin"
            }
        },
        media_type="application/json; charset=utf-8"
    )

# Регистрација на router-ите
app.include_router(lekari.router)
app.include_router(pacienti.router)
app.include_router(termini.router)
app.include_router(aparati.router)
app.include_router(uslugi.router)
app.include_router(kariera.router)
app.include_router(kariera.app_router)  # /aplikacija endpoint без prefix
app.include_router(admin.router)  # Административни endpoints

if __name__ == "__main__":          # proverka dali e startuvam fajlot direktno
    import uvicorn              # se importira uvicorn 
    uvicorn.run(app, host="127.0.0.1", port=8000) # se startuva serverot na dadenata ip adresa i porta  ama raboti so vaj mani da e ne so tvoj 
