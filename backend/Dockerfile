# koja verzija na python ke koristam
FROM python:3.11-slim   

#avi rabotna papka vnatre vo kontejnerot kade shto kje stoi celiot tvoj kod.
WORKDIR /app  

COPY requirements.txt .
#: Avtomatski gi instalira site tie biblioteki za da bide spremen sistemot za rabota.
RUN pip install --no-cache-dir -r requirements.txt 

COPY . .
# .env се копира при build – за production користи docker-compose env или secrets

#frontendot da komunicira so backendot.
EXPOSE 8000

#: Ja vkluchuva aplikacijata. Render (i sl.) zadava svoj $PORT — ako go nema, koristi 8000.
# shell forma za da se prochita promenlivata $PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
