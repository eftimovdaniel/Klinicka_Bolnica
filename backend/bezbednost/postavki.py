"""Ги чита поставките за безбедносниот слој од околината."""
import os


def _cel_broj(ime: str, osnovno: int) -> int:
    """Ако променливата ја нема или не е број, се користи основната вредност."""
    try:
        return int(os.getenv(ime, str(osnovno)))
    except ValueError:
        return osnovno


# Колку барања се дозволени во 60 секунди.
OGRANICUVANJE_PO_SESIJA = _cel_broj("OGRANICUVANJE_PO_SESIJA", 40)
OGRANICUVANJE_PO_ADRESA = _cel_broj("OGRANICUVANJE_PO_ADRESA", 120)
OGRANICUVANJE_NA_NAJAVA = _cel_broj("OGRANICUVANJE_NA_NAJAVA", 8)

# Најдолг текст што се прифаќа.
MAKS_TEKST = _cel_broj("MAKS_TEKST", 50000)
MAKS_PRASANJE = _cel_broj("MAKS_PRASANJE", 4000)

# Празна адреса значи ограничување во меморијата на овој процес.
REDIS_ADRESA = os.getenv("REDIS_URL", "").strip()

# Празен клуч значи дека проверката е исклучена (локална работа).
KLUC_ZA_PRISTAP = os.getenv("API_ACCESS_KEY", "").strip()
