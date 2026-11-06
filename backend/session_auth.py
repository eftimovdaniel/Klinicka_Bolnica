"""Сесија во HttpOnly колаче. Прелистувачот го праќа сам; JavaScript не го чита токенот."""
import base64
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from runtime_env import IS_PRODUCTION

_TTL_SEC = 8 * 60 * 60
COOKIE_PACIENT = "kb_pacient"
COOKIE_LEKAR = "kb_lekar"
COOKIE_SOGLASNOST = "kb_soglasnost"


def _secret() -> bytes:
    secret = os.getenv("SESSION_SECRET", "").strip() or os.getenv("DB_PASSWORD", "").strip()
    if not secret:
        secret = "kb-dev-session-secret"
    return secret.encode("utf-8")


def cookie_name(role: str) -> str:
    return COOKIE_LEKAR if role == "lekar" else COOKIE_PACIENT


def issue_token(role: str, user_id: int) -> str:
    exp = int(time.time()) + _TTL_SEC
    payload = f"{role}:{int(user_id)}:{exp}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_token(token: str, role: str | None = None) -> dict | None:
    if not token or not isinstance(token, str):
        return None
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode("ascii")).decode("utf-8")
        role_s, id_s, exp_s, sig = raw.split(":")
        payload = f"{role_s}:{id_s}:{exp_s}"
        expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        if int(exp_s) < int(time.time()):
            return None
        if role and role_s != role:
            return None
        return {"role": role_s, "id": int(id_s)}
    except Exception:
        return None


def read_token(request: Request, role: str) -> dict | None:
    token = (request.cookies.get(cookie_name(role)) or "").strip()
    if not token:
        header = "X-Lekar-Token" if role == "lekar" else "X-Pacient-Token"
        token = (request.headers.get(header) or "").strip()
    if not token:
        token = (request.headers.get("X-Session-Token") or "").strip()
    return verify_token(token, role)


def soglasnost_prifatena(request: Request) -> bool:
    return (request.cookies.get(COOKIE_SOGLASNOST) or "").strip() == "prifateni"


def odgovor_so_sesija(body: dict, role: str, user_id: int, request: Request) -> JSONResponse:
    if not soglasnost_prifatena(request):
        raise HTTPException(
            status_code=403,
            detail="Прифатете ги колачињата за да се најавите. Најавата се чува во колаче.",
        )
    response = JSONResponse(body)
    response.set_cookie(
        key=cookie_name(role),
        value=issue_token(role, user_id),
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )
    return response


def odgovor_bez_sesija(role: str) -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        key=cookie_name(role),
        path="/",
        samesite="lax",
        secure=IS_PRODUCTION,
    )
    return response


def require_role(request: Request, role: str, user_id: int) -> None:
    payload = read_token(request, role)
    if not payload or payload["id"] != int(user_id):
        raise HTTPException(status_code=401, detail="Најавете се повторно за да продолжите.")
