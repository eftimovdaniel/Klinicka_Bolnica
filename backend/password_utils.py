"""
Хеширање и верификација на лозинки со bcrypt.
Bcrypt е намерно бавен и отпорен на brute-force; поддржуваме и legacy SHA-256 при верификација.
"""
import hashlib
import os

# За да видите во конзола што се случува при најава: поставете DEBUG_PASSWORD=1
DEBUG_PASSWORD = os.environ.get("DEBUG_PASSWORD", "").strip() in ("1", "true", "yes")

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False


def hash_password(plain: str) -> str:
    """Хеширај лозинка со bcrypt (нов запис). Ако bcrypt не е инсталиран, користи SHA-256 (legacy)."""
    if HAS_BCRYPT:
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    # Fallback за окружувања каде bcrypt не е инсталиран
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def verify_password(plain: str, stored) -> bool:
    """
    Верифицирај лозинка. Поддржува bcrypt (препочитано) и legacy SHA-256.
    stored = вредност од базата (хеш), може да е str или bytes.
    """
    if not plain:
        return False
    if stored is None:
        return False
    # Ако е bytes (на пр. од MySQL), претвори во str
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8", errors="replace")
    stored = str(stored).strip()
    if not stored:
        return False
    # Bcrypt хеш започнува со $2b$ или $2a$, долг ~60 знаци
    if stored.startswith("$2") and len(stored) > 50:
        try:
            ok = bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
            if DEBUG_PASSWORD:
                print("[password] Режим: bcrypt, должина stored:", len(stored), ", резултат:", ok)
            return ok
        except Exception as e:
            if DEBUG_PASSWORD:
                print("[password] bcrypt грешка:", e)
            return False
    # Legacy: SHA-256 hex (64 знаци) – споредба без разлика на големина
    legacy_hash = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    ok = legacy_hash.lower() == stored.lower()
    if DEBUG_PASSWORD:
        print("[password] Режим: legacy SHA-256, должина stored:", len(stored), ", stored почнува со:", stored[:16] + "..." if len(stored) > 16 else stored, ", резултат:", ok)
    return ok
