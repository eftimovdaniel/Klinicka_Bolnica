import json
import os
import re
from urllib import error, request


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "25"))


def _extract_first_json_block(text: str):
    s = str(text or "").strip()
    if not s:
        return None

    # First try direct JSON parse.
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Fallback: find first {...} block.
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def parse_prompt_with_llama(prompt_text: str):
    """
    Returns dict with keys:
      intent: availability|book|''
      doctor_name: str
      date: YYYY-MM-DD or ''
      time: HH:MM or ''
      note: str
    Returns None if parsing failed/unavailable.
    """
    instruction = (
        "You extract appointment intent for a hospital assistant.\n"
        "Return ONLY valid JSON object with keys: intent, doctor_name, date, time, note.\n"
        "Rules:\n"
        "- intent must be 'availability' or 'book' or ''.\n"
        "- date format strictly YYYY-MM-DD or ''.\n"
        "- time format strictly HH:MM (24h) or ''.\n"
        "- doctor_name should be full name if present, else ''.\n"
        "- note should be text after note/napomena if present, else ''.\n"
    )
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{instruction}\nUser prompt:\n{prompt_text}\n",
        "stream": False,
        "options": {"temperature": 0},
    }
    req = request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            outer = json.loads(raw)
            content = outer.get("response", "")
            parsed = _extract_first_json_block(content)
            if not parsed:
                return None
            return {
                "intent": str(parsed.get("intent", "")).strip(),
                "doctor_name": str(parsed.get("doctor_name", "")).strip(),
                "date": str(parsed.get("date", "")).strip(),
                "time": str(parsed.get("time", "")).strip(),
                "note": str(parsed.get("note", "")).strip(),
            }
    except (error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
