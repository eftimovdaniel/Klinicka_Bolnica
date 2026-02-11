from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
