import os
import re
from html import unescape
from urllib import error, request

DEFAULT_MAX_BYTES = int(os.getenv("AI_FETCH_MAX_BYTES", "400000"))


def _strip_html(html: str) -> str:
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:50000]


def fetch_url_text(url: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; KB-Stip-AI/1.0; +https://kbstip.mk)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=20) as resp:
        chunk = resp.read(max_bytes + 1)
    if len(chunk) > max_bytes:
        chunk = chunk[:max_bytes]
    text = chunk.decode("utf-8", errors="replace")
    if "<" in text and ">" in text:
        return _strip_html(text)
    return text.strip()[:50000]
