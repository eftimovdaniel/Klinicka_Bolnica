# Dockerfile za Render (gradi od korenot na proektot — serviratь i backend i frontend).
# Lokalniot docker compose go koristi backend/Dockerfile; ovoj e samo za Render.
FROM python:3.11-slim

WORKDIR /app

# 1) Instaliraj gi Python zavisnostite (od backend/requirements.txt)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Kopiraj go backend kodot vo /app (main.py, routers/, ai/, static/, ...)
COPY backend/ /app/

# 3) Kopiraj go frontend vo /frontend taka shto main.py (parent.parent/"frontend") go najduva
#    i go servira sajtot na /app/
COPY frontend/ /frontend/

EXPOSE 8000

# Render zadava svoj $PORT; lokalno pagja na 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
