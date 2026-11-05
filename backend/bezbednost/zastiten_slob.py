from __future__ import annotations
import hashlib
from urllib.parse import parse_qsl, urlencode
from fastapi import Request
from fastapi.responses import JSONResponse
from bezbednost.cistenje_na_vlez import iscisteni_json, sanitize_question
from bezbednost.ogranicuvac import napravi_ogranicuvac
from bezbednost.postavki import (
    MAKS_TEKST as MAX_TEXT_CHARS,
    OGRANICUVANJE_PO_SESIJA as RATE_LIMIT,
    OGRANICUVANJE_PO_ADRESA as RATE_LIMIT_IP,
    OGRANICUVANJE_NA_NAJAVA as RATE_LIMIT_LOGIN,
)
from bezbednost.proverka_na_kluc import dozvolen_pristap

ip_rate_limiter = napravi_ogranicuvac(RATE_LIMIT_IP)
session_rate_limiter = napravi_ogranicuvac(RATE_LIMIT)
login_rate_limiter = napravi_ogranicuvac(RATE_LIMIT_LOGIN)

_PRESKOKNI = ("/app", "/static", "/docs", "/redoc")

def _ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host
    return "unknown"

def _session_key(request: Request, ip: str) -> str:
    for header in ("x-lekar-token", "x-pacient-token", "x-session-token"):
        token = (request.headers.get(header) or "").strip()
        if token:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
            return header + ":" + digest
    return "ip:" + ip

def _login_path(path: str) -> bool:
    return path.endswith("/login") or "forgot-password" in path or "reset-password" in path

class ZastitenSloj:
    def __init__(self, app) -> None:
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        path = request.url.path or ""
        if request.method == "OPTIONS" or path.startswith(_PRESKOKNI) or path == "/openapi.json":
            await self.app(scope, receive, send)
            return
        ip = _ip(request)
        if not ip_rate_limiter.dozvoleno("ip:" + ip):
            await self._odbij(scope, receive, send, 429, "Премногу барања од оваа адреса. Почекај една минута.")
            return
        if _login_path(path) and not login_rate_limiter.dozvoleno("login:" + ip):
            await self._odbij(scope, receive, send, 429, "Премногу обиди за најава. Почекај една минута.")
            return
        if not session_rate_limiter.dozvoleno(_session_key(request, ip)):
            await self._odbij(scope, receive, send, 429, "Премногу барања за оваа сесија. Почекај една минута.")
            return
        if not dozvolen_pristap(request.headers.get("origin"), request.headers.get("x-api-key")):
            await self._odbij(scope, receive, send, 401, "Немате пристап до системот.")
            return
        self._iscisteni_query(scope)
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type and request.method in ("POST", "PUT", "PATCH"):
            raw = await request.body()
            cisto, _ = iscisteni_json(raw, ai=path.startswith("/ai-chat"))
            async def nov_receive():
                return {"type": "http.request", "body": cisto, "more_body": False}
            await self.app(scope, nov_receive, send)
            return
        await self.app(scope, receive, send)

    def _iscisteni_query(self, scope) -> None:
        pairs = parse_qsl(scope.get("query_string", b"").decode("utf-8"), keep_blank_values=True)
        if not pairs:
            return
        novi = []
        for kluc, vrednost in pairs:
            tekst, _ = sanitize_question(vrednost, max_chars=MAX_TEXT_CHARS)
            novi.append((kluc, tekst))
        scope["query_string"] = urlencode(novi).encode("utf-8")

    async def _odbij(self, scope, receive, send, status: int, poraka: str) -> None:
        response = JSONResponse(status_code=status, content={"detail": poraka, "odgovor": poraka})
        await response(scope, receive, send)