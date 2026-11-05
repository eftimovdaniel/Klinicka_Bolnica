import hmac
from bezbednost.postavki import API_ACCESS_KEY
from runtime_env import cors_settings

def verify_api_key(provided: str | None) -> bool:
    if not API_ACCESS_KEY:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, API_ACCESS_KEY)

def dozvolen_pristap(origin: str | None, api_key: str | None) -> bool:
    if not API_ACCESS_KEY:
        return True
    dozvoleni, _ = cors_settings()
    if "*" in dozvoleni:
        return True
    if (origin or "").strip() in dozvoleni:
        return True
    return verify_api_key(api_key)
