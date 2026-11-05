"""Дали процесот работи како продукција. Render сам поставува RENDER=true."""
import os


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


_APP_ENV = os.getenv("ENV", os.getenv("APP_ENV", "development")).strip().lower()
IS_PRODUCTION = _APP_ENV in ("production", "prod") or os.getenv("RENDER", "").strip().lower() == "true"
ENABLE_DEBUG = _flag("ENABLE_DEBUG", "0" if IS_PRODUCTION else "1")

_PROD_ORIGINS = ["https://klinicka-bolnica-stip2026.onrender.com"]


def cors_settings() -> tuple[list[str], bool]:
    """Локално сите извори, без credentials. Во продукција само наведените домени."""
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        origins = [part.strip() for part in raw.split(",") if part.strip()]
        if origins:
            return origins, True
    if IS_PRODUCTION:
        return list(_PROD_ORIGINS), True
    return ["*"], False
