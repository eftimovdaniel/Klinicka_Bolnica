from __future__ import annotations
import json
import re
from bezbednost import MAX_QUESTION_CHARS, MAX_TEXT_CHARS

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?|"
    r"disregard\s+(the\s+)?(above|previous|prior)|"
    r"you\s+are\s+now\b|act\s+as\s+(a|an)\b|new\s+instructions?\s*:|"
    r"system\s*prompt|developer\s+message|reveal\s+your\s+(instructions|prompt)|"
    r"игнорирај\s+ги\s+(претходните|инструкциите|горните)|"
    r"заборави\s+ги\s+претходните|системски\s+промпт)"
)
_TAJNI_POLINJA = {
    "password", "lozinka", "trenutna_lozinka", "nova_lozinka",
    "token", "session_token", "api_key",
}

def sanitize_question(raw: str, *, max_chars: int | None = None) -> tuple [str, bool] :
    prashanje = _CONTROL_RE.sub ("", raw or "")
    prashanje = re.sub(r"\s+", " ", prashanje).strip()
    prashanje = prashanje[: max_chars or MAX_QUESTION_CHARS]
    oznaceno = bool (_INJECTION_RE.search(prashanje))
    if oznaceno:
        prashanje = _INJECTION_RE.sub("[otstraneto]", prashanje)
    return prashanje, oznaceno

def _iscisteno(vrednost, * , max_chars: int, pole: str):
    if isinstance(vrednost, str):
        if pole.lower() in _TAJNI_POLINJA:
            tekst = _CONTROL_RE.sub("", vrednost)[:max_chars]
            return tekst, False
        return sanitize_question(vrednost, max_chars=max_chars)
    if isinstance(vrednost, list):
        oznaka = False
        novi = []
        for el in vrednost:
            cist, f = _iscisteno(el, max_chars=max_chars, pole=pole)
            oznaka = oznaka or f
            novi.append(cist)
        return novi, oznaka
    if isinstance(vrednost, dict):
        oznaka = False
        nov = {}
        for k, v in vrednost.items():
            cist, f = _iscisteno(v, max_chars=max_chars, pole=str(k))
            oznaka = oznaka or f
            nov[k] = cist
        return nov, oznaka
    return vrednost, False

def iscisteni_json(raw: bytes, *, ai: bool) -> tuple[bytes, bool]:
    if not raw:
        return raw, False
    try:
        podatoci = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw, False
    max_chars = MAX_QUESTION_CHARS if ai else MAX_TEXT_CHARS
    cisti, oznaka = _iscisteno(podatoci, max_chars=max_chars, pole="")
    return json.dumps(cisti, ensure_ascii=False).encode("utf-8"), oznaka