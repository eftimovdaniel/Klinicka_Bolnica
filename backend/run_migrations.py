"""
Skripta za pushtanje na site SQL migracii vo bazata definirana vo .env
Pokrenuvanje:
    cd backend
    python run_migrations.py

Bezbedno za povtorno pushtanje - migraciite koristat CREATE TABLE IF NOT EXISTS.
"""
import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

# vcituvanje .env od istata papka kako ovaj fajl
HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
if not ENV_PATH.exists():
    print(f"GRESKA: {ENV_PATH} ne postoi!")
    sys.exit(1)
# DEBUG: pred load_dotenv
print(f"[DEBUG] Pred load_dotenv:")
print(f"  os.environ DB_HOST = {os.environ.get('DB_HOST', '<nesetiran>')}")
print(f"  os.environ DB_USER = {os.environ.get('DB_USER', '<nesetiran>')}")

# CHITAME .env DIREKTNO so override (presetuva i shell env vars)
load_dotenv(ENV_PATH, override=True)

# DEBUG: posle load_dotenv
print(f"[DEBUG] Posle load_dotenv:")
print(f"  os.environ DB_HOST = {os.environ.get('DB_HOST', '<nesetiran>')}")
print(f"  os.environ DB_USER = {os.environ.get('DB_USER', '<nesetiran>')}")

# DEBUG: kazi mi sodrzina na .env (samo DB_ klucevi)
print(f"[DEBUG] Sodrzina na {ENV_PATH}:")
with open(ENV_PATH, 'r') as fp:
    for line in fp:
        if 'DB_' in line and not line.strip().startswith('#'):
            print(f"  {line.rstrip()}")

# FORSIRANO: chitame direktno od .env bez da zavisime od os.environ
def read_env_value(key: str) -> str:
    """Chita direktno od .env fajl (ignoriraj shell env)."""
    with open(ENV_PATH, 'r') as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    return ""

# proverka deka postojat env varijabli (chitame direktno od .env, ignoriraj shell)
db_host = read_env_value("DB_HOST")
db_user = read_env_value("DB_USER")
db_password = read_env_value("DB_PASSWORD")
db_name = read_env_value("DB_NAME")
db_port = int(read_env_value("DB_PORT") or "3306")
db_ssl = read_env_value("DB_SSL").lower() in ("1", "true", "yes")
db_ssl_verify = read_env_value("DB_SSL_VERIFY").lower() in ("1", "true", "yes")

if not all([db_host, db_user, db_password, db_name]):
    print(f"GRESKA: nedostigaat vrednosti vo .env! host={db_host}, user={db_user}, db={db_name}")
    sys.exit(1)

print()
print(f"Konektiram kon {db_host}:{db_port} / baza={db_name}")
print(f"Korisnik: {db_user}")

# konekcija (so SSL ako e cloud baza)
kwargs = {
    "host": db_host,
    "user": db_user,
    "password": db_password,
    "database": db_name,
    "port": db_port,
    "use_pure": True,
}
if db_ssl:
    kwargs["ssl_disabled"] = False
    kwargs["ssl_verify_cert"] = db_ssl_verify

try:
    conn = mysql.connector.connect(**kwargs)
except Exception as e:
    print(f"GRESKA pri konekcija: {e}")
    sys.exit(1)

print("Konekcija OK!")
print()

cur = conn.cursor()

# najdi gi site .sql migracii i izvrsi gi po azbuchen red
migrations_dir = HERE / "migrations"
if not migrations_dir.exists():
    print(f"GRESKA: {migrations_dir} ne postoi!")
    sys.exit(1)

migration_files = sorted(migrations_dir.glob("*.sql"))
if not migration_files:
    print("Nema .sql fajlovi vo migrations/")
    sys.exit(0)

print(f"Najdov {len(migration_files)} migracii:")
for f in migration_files:
    print(f"  - {f.name}")
print()

for f in migration_files:
    print(f"\nIzvrsuvam: {f.name}")
    with open(f, "r", encoding="utf-8") as fp:
        sql_content = fp.read()
    # cisten - otstranuvame samostojni linii koi pochnuvaat so --
    cleaned_lines = []
    for line in sql_content.split("\n"):
        if line.strip().startswith("--"):
            continue
        cleaned_lines.append(line)
    cleaned_sql = "\n".join(cleaned_lines)
    # delenje na poedinecni statements (po ;)
    statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]
    print(f"  Najdov {len(statements)} statement(s):")
    for idx, stmt in enumerate(statements, 1):
        # prikaz na prvite 100 znaci za debug
        preview = stmt[:80].replace("\n", " ").strip()
        print(f"    [{idx}] {preview}...")
        try:
            cur.execute(stmt)
            conn.commit()
            # proverka za warnings
            warnings = cur.fetchwarnings() if hasattr(cur, "fetchwarnings") else None
            if warnings:
                print(f"        WARNINGS: {warnings}")
            print(f"        OK (rowcount={cur.rowcount})")
        except mysql.connector.Error as e:
            # 1050 = table already exists, 1061 = duplicate key (idempotentno - ok)
            if e.errno in (1050, 1061, 1826):
                print(f"        (vekje postoi - preskoknuvam)")
            else:
                print(f"        GRESKA [{e.errno}]: {e}")
                raise
print()
print("Site migracii izvrseni uspesno!")
print()
print("Proverka na tabelite (case-insensitive preko INFORMATION_SCHEMA):")
cur.execute(
    """
    SELECT TABLE_NAME 
    FROM INFORMATION_SCHEMA.TABLES 
    WHERE TABLE_SCHEMA = %s 
      AND LOWER(TABLE_NAME) IN ('potsetnici', 'doctor_briefs')
    """,
    (db_name,),
)
found = [r[0] for r in cur.fetchall()]
print(f"  Najdoeni tabeli: {found}")
print()
# isto i prikaz na site tabeli vo bazata
print("Site tabeli vo bazata:")
cur.execute(
    "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
    (db_name,),
)
for r in cur.fetchall():
    marker = " ⭐" if r[0].lower() in ("potsetnici", "doctor_briefs") else ""
    print(f"  - {r[0]}{marker}")

cur.close()
conn.close()
print()
print("Gotovo!")
